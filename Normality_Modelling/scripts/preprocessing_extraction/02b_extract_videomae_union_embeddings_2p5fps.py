#!/usr/bin/env python3
r"""
Direct VideoMAE UNION-CROP embedding extraction from raw surveillance videos.

FIXED VERSION for rebuilding the normal distribution dataset:
  - uses a STATIC padded union crop per 16-frame tubelet instead of frame-by-frame
    moving person crops
  - defaults to 2.5 FPS so 16 VideoMAE frames cover about 6.4 seconds
  - defaults to a NEW output folder, not processed_dataset_direct_8fps
  - accepts fractional --sample_fps values
  - refuses to accidentally write into the old 8fps output folder
  - refuses to mix a fresh run with old embeddings unless --resume is used
  - records actual temporal span and union-crop metadata for every tubelet
  - PERSON-CONTEXT MODE: saves one VideoMAE embedding per tracked person tubelet

This script is designed for large, long MP4 surveillance videos where saving every
person tubelet as an MP4 would be too slow and too large.

Pipeline:
  raw video -> sequential frame read -> YOLO tracking -> rolling track buffers
  -> keep sampled raw frames + bboxes -> quality-filter window
  -> calculate one spatial union bbox across the 16-frame window
  -> pad union bbox -> crop the same region from all 16 frames
  -> VideoMAE embeddings -> .npy + CSV

Outputs:
  processed_dir/
    embeddings/
      person_embeddings.npy
      union_embedding_metadata.csv
    metadata/
      union_rejected_tubelets.csv
      union_invalid_embeddings.csv
    logs/
      union_embeddings.log
    debug_tubelets/              optional, only if --debug_save_mp4_limit > 0
      union/*.mp4

Run from the project root, for example:
  python scripts\02b_extract_videomae_union_embeddings_2p5fps.py ^
    --input_dir "D:\Embeddings_Distribution\raw_videos" ^
    --processed_dir "D:\Embeddings_Distribution\processed_dataset_videomae_union_2p5fps_6sec" ^
    --sample_fps 2.5 --tubelet_frames 16 --stride 5 ^
    --person_padding 0.30 ^
    --yolo_device 0 --half --embedding_device cuda --fp16
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from tqdm import tqdm

try:
    import torch
except Exception as exc:  # pragma: no cover
    torch = None

try:
    from ultralytics import YOLO
except Exception as exc:  # pragma: no cover
    YOLO = None

try:
    from transformers import AutoImageProcessor, AutoModel
except Exception as exc:  # pragma: no cover
    AutoImageProcessor = None
    AutoModel = None


VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".m4v"}

DEFAULT_PROCESSED_DIR = Path(r"D:\Embeddings_Distribution\processed_dataset_videomae_union_2p5fps_6sec")
OLD_8FPS_OUTPUT_NAME = "processed_dataset_direct_8fps"


# ---------------------------------------------------------------------------
# Basic utilities
# ---------------------------------------------------------------------------

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logger(log_path: Path) -> logging.Logger:
    ensure_dir(log_path.parent)
    logger = logging.getLogger("union_embeddings")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


def append_csv(path: Path, row: Dict[str, Any], fieldnames: Optional[List[str]] = None) -> None:
    ensure_dir(path.parent)
    write_header = not path.exists()
    keys = fieldnames or list(row.keys())
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in keys})


def read_existing_metadata_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tubelet_id = row.get("tubelet_id")
            if tubelet_id:
                ids.add(tubelet_id)
    return ids


def find_videos(input_dir: Path) -> List[Path]:
    return sorted([p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS])


def safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_").replace(".", "_").replace("-", "_")


def save_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Bounding box / quality helpers
# ---------------------------------------------------------------------------

def xyxy_to_xywh(xyxy: np.ndarray) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(round(float(v))) for v in xyxy]
    return x1, y1, max(0, x2 - x1), max(0, y2 - y1)


def clamp_xywh(box: Tuple[int, int, int, int], frame_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    x, y, w, h = box
    H, W = frame_shape[:2]
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = max(1, min(w, W - x))
    h = max(1, min(h, H - y))
    return x, y, w, h


def pad_bbox(box: Tuple[int, int, int, int], padding: float, frame_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    x, y, w, h = box
    px = int(round(w * padding))
    py = int(round(h * padding))
    return clamp_xywh((x - px, y - py, w + 2 * px, h + 2 * py), frame_shape)


def union_bbox(bboxes: List[Tuple[int, int, int, int]]) -> Tuple[int, int, int, int]:
    """Return one bbox covering all bboxes in a tubelet window."""
    if not bboxes:
        raise ValueError("cannot calculate union bbox for empty bbox list")
    x1 = min(x for x, y, w, h in bboxes)
    y1 = min(y for x, y, w, h in bboxes)
    x2 = max(x + w for x, y, w, h in bboxes)
    y2 = max(y + h for x, y, w, h in bboxes)
    return int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))


def context_bbox(box: Tuple[int, int, int, int], scale: float, frame_shape: Tuple[int, int, int]) -> Tuple[int, int, int, int]:
    x, y, w, h = box
    cx = x + w / 2.0
    cy = y + h / 2.0
    nw = int(round(w * scale))
    nh = int(round(h * scale))
    nx = int(round(cx - nw / 2.0))
    ny = int(round(cy - nh / 2.0))
    return clamp_xywh((nx, ny, nw, nh), frame_shape)


def crop_resize(frame: np.ndarray, box: Tuple[int, int, int, int], out_size: int) -> np.ndarray:
    x, y, w, h = clamp_xywh(box, frame.shape)
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        raise ValueError("empty crop")
    return cv2.resize(crop, (out_size, out_size), interpolation=cv2.INTER_LINEAR)


def bbox_iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def center_jump_ratio(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    acx, acy = ax + aw / 2.0, ay + ah / 2.0
    bcx, bcy = bx + bw / 2.0, by + bh / 2.0
    dist = math.hypot(bcx - acx, bcy - acy)
    diag = math.hypot(aw, ah)
    return float(dist / diag) if diag > 0 else 0.0


def quality_check(
    bboxes: List[Tuple[int, int, int, int]],
    confs: List[float],
    frame_shape: Tuple[int, int, int],
    min_conf: float,
    min_bbox_width: int,
    min_bbox_height: int,
    min_mean_iou: float,
    max_center_jump_ratio: float,
) -> Tuple[bool, Dict[str, Any]]:
    if not bboxes or not confs:
        return False, {"reason": "empty_window"}
    widths = [b[2] for b in bboxes]
    heights = [b[3] for b in bboxes]
    mean_conf = float(np.mean(confs))
    min_conf_val = float(np.min(confs))
    ious = [bbox_iou(bboxes[i - 1], bboxes[i]) for i in range(1, len(bboxes))]
    jumps = [center_jump_ratio(bboxes[i - 1], bboxes[i]) for i in range(1, len(bboxes))]
    H, W = frame_shape[:2]
    areas = [(b[2] * b[3]) / max(1, W * H) for b in bboxes]
    metrics = {
        "mean_conf": round(mean_conf, 6),
        "min_conf": round(min_conf_val, 6),
        "mean_bbox_area_ratio": round(float(np.mean(areas)), 8),
        "mean_iou": round(float(np.mean(ious)) if ious else 1.0, 6),
        "max_center_jump_ratio": round(float(max(jumps)) if jumps else 0.0, 6),
    }
    if mean_conf < min_conf:
        return False, {**metrics, "reason": "low_mean_conf"}
    if any(w < min_bbox_width or h < min_bbox_height for w, h in zip(widths, heights)):
        return False, {**metrics, "reason": "bbox_too_small"}
    if metrics["mean_iou"] < min_mean_iou:
        return False, {**metrics, "reason": "low_mean_iou"}
    if metrics["max_center_jump_ratio"] > max_center_jump_ratio:
        return False, {**metrics, "reason": "center_jump_too_high"}
    return True, {**metrics, "reason": "accepted"}


def embedding_valid(x: np.ndarray) -> Tuple[bool, Dict[str, Any]]:
    if x is None:
        return False, {"reason": "none"}
    if not np.isfinite(x).all():
        return False, {"reason": "nan_inf"}
    norm = float(np.linalg.norm(x))
    std = float(np.std(x))
    if norm < 1e-4 or norm > 1e6:
        return False, {"reason": "bad_norm", "norm": norm, "std": std}
    if std < 1e-8:
        return False, {"reason": "near_zero_std", "norm": norm, "std": std}
    return True, {"reason": "accepted", "norm": norm, "std": std}


# ---------------------------------------------------------------------------
# Rolling track buffers
# ---------------------------------------------------------------------------

@dataclass
class TrackBuffer:
    track_id: int
    sample_indices: List[int] = field(default_factory=list)
    source_frame_indices: List[int] = field(default_factory=list)
    raw_frames: List[np.ndarray] = field(default_factory=list)
    bboxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    confs: List[float] = field(default_factory=list)
    last_sample_index: int = -1
    last_emit_sample_index: int = -10**9

    def reset(self) -> None:
        self.sample_indices.clear()
        self.source_frame_indices.clear()
        self.raw_frames.clear()
        self.bboxes.clear()
        self.confs.clear()

    def append(
        self,
        sample_index: int,
        source_frame_index: int,
        raw_frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        conf: float,
        max_gap: int,
        max_buffer: int,
    ) -> None:
        if self.last_sample_index >= 0 and sample_index - self.last_sample_index > max_gap:
            self.reset()
        self.sample_indices.append(sample_index)
        self.source_frame_indices.append(source_frame_index)
        self.raw_frames.append(raw_frame)
        self.bboxes.append(bbox)
        self.confs.append(conf)
        self.last_sample_index = sample_index
        # keep only latest max_buffer entries
        if len(self.sample_indices) > max_buffer:
            extra = len(self.sample_indices) - max_buffer
            del self.sample_indices[:extra]
            del self.source_frame_indices[:extra]
            del self.raw_frames[:extra]
            del self.bboxes[:extra]
            del self.confs[:extra]

    def can_emit(self, tubelet_frames: int, stride: int, sample_index: int) -> bool:
        if len(self.sample_indices) < tubelet_frames:
            return False
        if sample_index - self.last_emit_sample_index < stride:
            return False
        return True

    def latest_window(self, tubelet_frames: int) -> Dict[str, Any]:
        return {
            "sample_indices": self.sample_indices[-tubelet_frames:],
            "source_frame_indices": self.source_frame_indices[-tubelet_frames:],
            "raw_frames": self.raw_frames[-tubelet_frames:],
            "bboxes": self.bboxes[-tubelet_frames:],
            "confs": self.confs[-tubelet_frames:],
        }


# ---------------------------------------------------------------------------
# VideoMAE model and embedding batcher
# ---------------------------------------------------------------------------

def load_embedding_model(model_name: str, device: str, fp16: bool, logger: logging.Logger):
    if torch is None:
        raise RuntimeError("torch is not installed")
    if AutoModel is None or AutoImageProcessor is None:
        raise RuntimeError("transformers is not installed")
    logger.info(f"Loading embedding model: {model_name} | device={device} | fp16={fp16}")
    processor = AutoImageProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval().to(device)
    if fp16 and device.startswith("cuda"):
        model.half()
    return model, processor


def extract_video_batch_embeddings(
    videos_bgr: List[List[np.ndarray]],
    model,
    processor,
    device: str,
    fp16: bool,
) -> np.ndarray:
    """Extract embeddings for a batch of videos.

    Each video is a list of BGR frames. Frames are converted to RGB before processing.
    A robust fallback is included if the processor rejects batched nested input.
    """
    if not videos_bgr:
        return np.empty((0, 0), dtype=np.float32)

    def _run(video_batch_rgb: Any) -> np.ndarray:
        inputs = processor(video_batch_rgb, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        if fp16 and device.startswith("cuda"):
            for k, v in list(inputs.items()):
                if torch.is_floating_point(v):
                    inputs[k] = v.half()
        with torch.no_grad():
            with torch.cuda.amp.autocast(enabled=fp16 and device.startswith("cuda")):
                outputs = model(**inputs)
                pooled = outputs.last_hidden_state.mean(dim=1)
        return pooled.detach().float().cpu().numpy()

    videos_rgb = [[cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames] for frames in videos_bgr]
    try:
        return _run(videos_rgb)
    except Exception:
        # Fallback: process one tubelet at a time.
        out: List[np.ndarray] = []
        for vid in videos_rgb:
            emb = _run(vid)
            out.append(emb[0])
        return np.stack(out, axis=0)


def write_mp4(frames: List[np.ndarray], path: Path, fps: float) -> None:
    ensure_dir(path.parent)
    h, w = frames[0].shape[:2]
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, max(1, int(round(float(fps)))), (w, h))
    for f in frames:
        writer.write(f)
    writer.release()


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

class DirectExtractor:
    def __init__(self, args: argparse.Namespace, logger: logging.Logger) -> None:
        self.args = args
        self.logger = logger
        self.processed_dir: Path = args.processed_dir
        self.emb_dir = ensure_dir(self.processed_dir / "embeddings")
        self.meta_dir = ensure_dir(self.processed_dir / "metadata")
        self.debug_dir = ensure_dir(self.processed_dir / "debug_tubelets")
        self.log_dir = ensure_dir(self.processed_dir / "logs")

        self.metadata_csv = self.emb_dir / "union_embedding_metadata.csv"
        self.rejected_csv = self.meta_dir / "union_rejected_tubelets.csv"
        self.invalid_csv = self.meta_dir / "union_invalid_embeddings.csv"
        self.person_npy = self.emb_dir / "person_embeddings.npy"

        self.processed_ids = read_existing_metadata_ids(self.metadata_csv) if args.resume else set()
        self.person_embeddings: List[np.ndarray] = []
        if args.resume and self.person_npy.exists():
            self.logger.info("Loading existing person .npy embeddings for resume mode...")
            self.person_embeddings = list(np.load(self.person_npy, mmap_mode=None))
            self.logger.info(f"Loaded existing person embeddings: {len(self.person_embeddings)}")

        self.batch_person: List[List[np.ndarray]] = []
        self.batch_meta: List[Dict[str, Any]] = []
        self.debug_saved = 0

        self.yolo_model = self._load_yolo()
        self.embed_model, self.processor = load_embedding_model(
            args.model_name, args.embedding_device, args.fp16, logger
        )

    def _load_yolo(self):
        if YOLO is None:
            raise RuntimeError("ultralytics is not installed. Install requirements first.")
        self.logger.info(f"Loading YOLO model: {self.args.yolo_model} | device={self.args.yolo_device} | half={self.args.half}")
        return YOLO(self.args.yolo_model)

    def save_checkpoint(self) -> None:
        if self.person_embeddings:
            np.save(self.person_npy, np.stack(self.person_embeddings, axis=0))
            self.logger.info(f"Checkpoint saved: {len(self.person_embeddings)} embeddings")

    def flush_batch(self) -> None:
        if not self.batch_meta:
            return
        try:
            person_embs = extract_video_batch_embeddings(
                self.batch_person, self.embed_model, self.processor, self.args.embedding_device, self.args.fp16
            )
        except Exception as exc:
            self.logger.error(f"Batch embedding failed: {exc}")
            for m in self.batch_meta:
                append_csv(self.invalid_csv, {"tubelet_id": m.get("tubelet_id"), "reason": "batch_embedding_error", "error": str(exc)})
            self.batch_person.clear()
            self.batch_meta.clear()
            return

        meta_fields = [
            "tubelet_id", "video_path", "video_id", "track_id", "start_frame", "end_frame",
            "start_time_sec", "end_time_sec", "clip_span_sec", "clip_duration_sec",
            "source_fps", "frame_step", "effective_sample_fps", "sample_fps", "tubelet_frames",
            "person_embedding_index", "person_valid", "person_norm",
            "mean_conf", "min_conf", "mean_bbox_area_ratio", "mean_iou", "max_center_jump_ratio",
            "union_x", "union_y", "union_w", "union_h",
            "padded_union_x", "padded_union_y", "padded_union_w", "padded_union_h",
            "person_padding", "crop_mode",
        ]
        for i, meta in enumerate(self.batch_meta):
            p = person_embs[i]
            p_valid, p_metrics = embedding_valid(p)
            if not p_valid:
                append_csv(self.invalid_csv, {
                    "tubelet_id": meta["tubelet_id"],
                    "reason": "invalid_person_embedding",
                    "person_reason": p_metrics.get("reason"),
                })
                continue
            p_idx = len(self.person_embeddings)
            self.person_embeddings.append(p)
            row = {
                **meta,
                "person_embedding_index": p_idx,
                "person_valid": True,
                "person_norm": p_metrics.get("norm"),
            }
            append_csv(self.metadata_csv, row, fieldnames=meta_fields)

        self.batch_person.clear()
        self.batch_meta.clear()

        if len(self.person_embeddings) % self.args.checkpoint_every < self.args.batch_size:
            self.save_checkpoint()

    def enqueue_tubelet(self, meta: Dict[str, Any], person_frames: List[np.ndarray]) -> None:
        tubelet_id = meta["tubelet_id"]
        if tubelet_id in self.processed_ids:
            return
        self.batch_meta.append(meta)
        self.batch_person.append(person_frames)
        if self.args.debug_save_mp4_limit > 0 and self.debug_saved < self.args.debug_save_mp4_limit:
            write_mp4(person_frames, self.debug_dir / "union" / f"{tubelet_id}.mp4", self.args.sample_fps)
            self.debug_saved += 1
        if len(self.batch_meta) >= self.args.batch_size:
            self.flush_batch()

    def process_video(self, video_path: Path, video_number: int, total_videos: int) -> Tuple[int, int]:
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            self.logger.warning(f"Unreadable video skipped: {video_path}")
            return 0, 0

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.args.max_minutes_per_video > 0:
            max_frames = min(total_frames, int(self.args.max_minutes_per_video * 60 * fps))
        else:
            max_frames = total_frames
        frame_step = max(1, int(round(fps / self.args.sample_fps)))
        effective_sample_fps = float(fps / frame_step)
        clip_duration_sec = float(self.args.tubelet_frames / effective_sample_fps)
        video_id = safe_stem(video_path)
        track_buffers: Dict[int, TrackBuffer] = {}
        accepted = 0
        rejected = 0
        sampled_count = int(math.ceil(max_frames / frame_step))
        max_buffer = max(self.args.tubelet_frames + self.args.stride + 4, self.args.tubelet_frames * 3)

        self.logger.info(
            f"[{video_number}/{total_videos}] {video_path.name} | fps={fps:.2f} | frames={total_frames} | "
            f"processing_frames={max_frames} | sample_every={frame_step} | "
            f"requested_sample_fps={self.args.sample_fps:.3f} | effective_sample_fps={effective_sample_fps:.3f} | "
            f"clip_duration≈{clip_duration_sec:.3f}s"
        )

        pbar = tqdm(total=sampled_count, desc=f"Video {video_number}/{total_videos}: {video_path.name}", leave=True)
        frame_idx = -1
        sample_idx = -1
        while True:
            ret, frame = cap.read()
            frame_idx += 1
            if not ret or frame_idx >= max_frames:
                break
            if frame_idx % frame_step != 0:
                continue
            sample_idx += 1
            pbar.update(1)

            # YOLO tracking. persist=True is critical for stable track IDs across sequential frames.
            try:
                results = self.yolo_model.track(
                    frame,
                    persist=True,
                    classes=[0],
                    conf=self.args.min_conf,
                    device=self.args.yolo_device,
                    half=self.args.half,
                    verbose=False,
                    tracker=self.args.tracker,
                )
            except Exception as exc:
                self.logger.error(f"YOLO track failed at frame {frame_idx} in {video_path.name}: {exc}")
                continue

            if not results:
                continue
            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                continue
            # Extract detections with track IDs.
            xyxy = boxes.xyxy.detach().cpu().numpy() if boxes.xyxy is not None else np.empty((0, 4))
            confs = boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.ones((len(xyxy),), dtype=np.float32)
            ids_tensor = boxes.id
            if ids_tensor is None:
                # If tracker failed to assign IDs, skip this frame rather than mixing people.
                continue
            ids = ids_tensor.detach().cpu().numpy().astype(int)

            for det_i, tid in enumerate(ids):
                bbox = clamp_xywh(xyxy_to_xywh(xyxy[det_i]), frame.shape)
                conf = float(confs[det_i])
                if bbox[2] < self.args.min_bbox_width or bbox[3] < self.args.min_bbox_height:
                    continue
                # Store the sampled raw frame first. Cropping is intentionally deferred
                # until we have a complete tubelet window, so all 16 frames use the
                # same static union crop instead of a moving frame-by-frame crop.
                buf = track_buffers.setdefault(int(tid), TrackBuffer(track_id=int(tid)))
                buf.append(
                    sample_index=sample_idx,
                    source_frame_index=frame_idx,
                    raw_frame=frame.copy(),
                    bbox=bbox,
                    conf=conf,
                    max_gap=self.args.max_track_gap,
                    max_buffer=max_buffer,
                )
                if buf.can_emit(self.args.tubelet_frames, self.args.stride, sample_idx):
                    win = buf.latest_window(self.args.tubelet_frames)
                    ok, metrics = quality_check(
                        win["bboxes"],
                        win["confs"],
                        frame.shape,
                        self.args.min_conf,
                        self.args.min_bbox_width,
                        self.args.min_bbox_height,
                        self.args.min_mean_iou,
                        self.args.max_center_jump_ratio,
                    )
                    start_frame = int(win["source_frame_indices"][0])
                    end_frame = int(win["source_frame_indices"][-1])
                    tubelet_id = f"{video_id}_track{int(tid):04d}_start{start_frame:08d}"
                    if ok:
                        try:
                            ubox = union_bbox(win["bboxes"])
                            pubox = pad_bbox(ubox, self.args.person_padding, frame.shape)
                            tubelet_frames = [
                                crop_resize(raw_frame, pubox, self.args.person_size)
                                for raw_frame in win["raw_frames"]
                            ]
                        except Exception as exc:
                            append_csv(self.rejected_csv, {
                                "video_path": str(video_path),
                                "video_id": video_id,
                                "track_id": int(tid),
                                "start_frame": start_frame,
                                "reason": "union_crop_failed",
                                "details": str(exc),
                            })
                            rejected += 1
                            buf.last_emit_sample_index = sample_idx
                            continue

                        meta = {
                            "tubelet_id": tubelet_id,
                            "video_path": str(video_path),
                            "video_id": video_id,
                            "track_id": int(tid),
                            "start_frame": start_frame,
                            "end_frame": end_frame,
                            "start_time_sec": round(start_frame / fps, 3),
                            "end_time_sec": round(end_frame / fps, 3),
                            "clip_span_sec": round((end_frame - start_frame) / fps, 3),
                            "clip_duration_sec": round(clip_duration_sec, 3),
                            "source_fps": round(float(fps), 6),
                            "frame_step": int(frame_step),
                            "effective_sample_fps": round(effective_sample_fps, 6),
                            "sample_fps": self.args.sample_fps,
                            "tubelet_frames": self.args.tubelet_frames,
                            "mean_conf": metrics.get("mean_conf"),
                            "min_conf": metrics.get("min_conf"),
                            "mean_bbox_area_ratio": metrics.get("mean_bbox_area_ratio"),
                            "mean_iou": metrics.get("mean_iou"),
                            "max_center_jump_ratio": metrics.get("max_center_jump_ratio"),
                            "union_x": ubox[0],
                            "union_y": ubox[1],
                            "union_w": ubox[2],
                            "union_h": ubox[3],
                            "padded_union_x": pubox[0],
                            "padded_union_y": pubox[1],
                            "padded_union_w": pubox[2],
                            "padded_union_h": pubox[3],
                            "person_padding": self.args.person_padding,
                            "crop_mode": "static_padded_union",
                        }
                        self.enqueue_tubelet(meta, tubelet_frames)
                        buf.last_emit_sample_index = sample_idx
                        accepted += 1
                        if self.args.max_tubelets_per_video > 0 and accepted >= self.args.max_tubelets_per_video:
                            pbar.close()
                            cap.release()
                            self.flush_batch()
                            return accepted, rejected
                    else:
                        append_csv(self.rejected_csv, {
                            "video_path": str(video_path),
                            "video_id": video_id,
                            "track_id": int(tid),
                            "start_frame": start_frame,
                            "reason": metrics.get("reason"),
                            "details": json.dumps(metrics),
                        })
                        rejected += 1
                        buf.last_emit_sample_index = sample_idx

        pbar.close()
        cap.release()
        self.flush_batch()
        return accepted, rejected

    def run(self) -> None:
        videos = find_videos(self.args.input_dir)
        if self.args.limit_videos > 0:
            videos = videos[: self.args.limit_videos]
        if not videos:
            self.logger.warning(f"No videos found under {self.args.input_dir}")
            return
        self.logger.info(f"Found {len(videos)} video(s). Starting static union-crop embedding extraction.")
        total_acc = 0
        total_rej = 0
        for idx, video in enumerate(videos, 1):
            try:
                acc, rej = self.process_video(video, idx, len(videos))
                total_acc += acc
                total_rej += rej
                self.logger.info(f"Finished {video.name}: accepted={acc}, rejected={rej}, total_embeddings={len(self.person_embeddings)}")
            except KeyboardInterrupt:
                self.logger.warning("Interrupted by user. Saving checkpoint...")
                self.flush_batch()
                self.save_checkpoint()
                raise
            except Exception as exc:
                self.logger.exception(f"Video failed and was skipped: {video} | {exc}")
                continue
        self.flush_batch()
        self.save_checkpoint()
        save_json(self.emb_dir / "union_extraction_summary.json", {
            "total_videos_processed": len(videos),
            "total_accepted_tubelets": total_acc,
            "total_rejected_tubelets": total_rej,
            "total_saved_embeddings": len(self.person_embeddings),
            "requested_sample_fps": self.args.sample_fps,
            "tubelet_frames": self.args.tubelet_frames,
            "stride": self.args.stride,
            "crop_mode": "static_padded_union",
            "person_padding": self.args.person_padding,
            "model_name": self.args.model_name,
            "yolo_model": self.args.yolo_model,
        })
        self.logger.info(f"DONE. Total accepted={total_acc}, rejected={total_rej}, saved embeddings={len(self.person_embeddings)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Direct VideoMAE static union-crop embedding extraction from raw videos")
    parser.add_argument("--input_dir", type=Path, required=True, help="Folder containing raw videos")
    parser.add_argument("--processed_dir", type=Path, default=DEFAULT_PROCESSED_DIR, help=f"Output processed dataset folder. Default: {DEFAULT_PROCESSED_DIR}")
    parser.add_argument("--limit_videos", type=int, default=0, help="Process only first N videos; 0 means all")
    parser.add_argument("--max_minutes_per_video", type=float, default=0.0, help="Limit minutes per video; 0 means full video")
    parser.add_argument("--max_tubelets_per_video", type=int, default=0, help="Limit accepted tubelets per video; 0 means unlimited")

    parser.add_argument("--yolo_model", type=str, default="yolov8n.pt", help="Ultralytics YOLO model")
    parser.add_argument("--tracker", type=str, default="bytetrack.yaml", help="Ultralytics tracker config")
    parser.add_argument("--yolo_device", type=str, default="0", help="YOLO device, e.g. 0 or cpu")
    parser.add_argument("--half", action="store_true", help="Use FP16 for YOLO if supported")

    parser.add_argument("--model_name", type=str, default="MCG-NJU/videomae-base", help="VideoMAE/HF model name")
    parser.add_argument("--embedding_device", type=str, default="cuda", help="Embedding device: cuda or cpu")
    parser.add_argument("--fp16", action="store_true", help="Use FP16 for embedding model if on CUDA")
    parser.add_argument("--batch_size", type=int, default=8, help="Embedding batch size")

    parser.add_argument("--sample_fps", type=float, default=2.5, help="Sampled FPS from source videos. Use 2.5 with 16 frames for ~6.4 seconds of context.")
    parser.add_argument("--tubelet_frames", type=int, default=16, help="Frames per tubelet")
    parser.add_argument("--stride", type=int, default=5, help="Stride in sampled frames between emitted tubelets per track. Default 5 at 2.5 FPS emits about every 2 seconds.")
    parser.add_argument("--person_size", type=int, default=224, help="Person crop output size")
    parser.add_argument("--person_padding", type=float, default=0.30, help="Padding applied to the tubelet-level union bbox. Start with 0.30 or 0.35.")

    parser.add_argument("--min_conf", type=float, default=0.45, help="Minimum detection confidence")
    parser.add_argument("--min_bbox_width", type=int, default=50, help="Minimum bbox width")
    parser.add_argument("--min_bbox_height", type=int, default=50, help="Minimum bbox height")
    parser.add_argument("--min_mean_iou", type=float, default=0.30, help="Minimum mean IoU across tubelet boxes")
    parser.add_argument("--max_center_jump_ratio", type=float, default=1.50, help="Maximum center jump ratio")
    parser.add_argument("--max_track_gap", type=int, default=2, help="Max missed sampled-frame gap before resetting track buffer")

    parser.add_argument("--resume", action="store_true", help="Resume from existing embeddings/metadata if present")
    parser.add_argument("--allow_existing_output", action="store_true", help="Allow a fresh non-resume run to write into a folder that already contains embedding outputs")
    parser.add_argument("--allow_old_8fps_output", action="store_true", help="Allow writing into processed_dataset_direct_8fps. Dangerous; off by default.")
    parser.add_argument("--checkpoint_every", type=int, default=256, help="Save .npy checkpoint every N embeddings")
    parser.add_argument("--debug_save_mp4_limit", type=int, default=40, help="Save first N accepted tubelets as debug MP4; 0 disables")
    return parser.parse_args()



def validate_output_destination(args: argparse.Namespace) -> None:
    """Prevent accidental overwrite/mixing of the old 8fps extraction outputs."""
    processed_dir = args.processed_dir
    if processed_dir.name.lower() == OLD_8FPS_OUTPUT_NAME.lower() and not args.allow_old_8fps_output:
        raise SystemExit(
            f"Refusing to write into the old 8fps output folder: {processed_dir}\n"
            f"Use a new folder such as: {DEFAULT_PROCESSED_DIR}\n"
            "If you truly intend to write there, pass --allow_old_8fps_output."
        )

    emb_dir = processed_dir / "embeddings"
    existing_outputs = [
        emb_dir / "person_embeddings.npy",
        emb_dir / "union_embedding_metadata.csv",
    ]
    if not args.resume and not args.allow_existing_output and any(p.exists() for p in existing_outputs):
        existing = "\n".join(str(p) for p in existing_outputs if p.exists())
        raise SystemExit(
            "Refusing to mix a fresh extraction with existing embedding outputs.\n"
            f"Existing files found:\n{existing}\n\n"
            "Use --resume to continue, choose a new --processed_dir, or pass --allow_existing_output if you know exactly what you are doing."
        )

def main() -> None:
    args = parse_args()
    validate_output_destination(args)
    if not args.input_dir.exists():
        raise SystemExit(f"Input folder does not exist: {args.input_dir}")
    ensure_dir(args.processed_dir)
    logger = setup_logger(args.processed_dir / "logs" / "union_embeddings.log")
    if torch is not None:
        logger.info(f"torch={torch.__version__} | cuda_available={torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"GPU 0: {torch.cuda.get_device_name(0)}")
    logger.info(f"Arguments: {vars(args)}")
    logger.info("UNION-CROP MODE: one static padded union crop is extracted per person tubelet; only person_embeddings.npy will be saved.")
    extractor = DirectExtractor(args, logger)
    extractor.run()


if __name__ == "__main__":
    main()
