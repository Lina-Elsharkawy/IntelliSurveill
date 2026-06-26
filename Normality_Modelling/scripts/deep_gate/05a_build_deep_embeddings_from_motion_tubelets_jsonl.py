#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
05a_build_deep_embeddings_from_motion_tubelets_jsonl.py

Build VideoMAE Deep-gate embeddings from existing live-parity motion tubelets.

Purpose
-------
This script reuses motion_tubelet_tracks.jsonl produced by the live-parity
Pose/Homography extractor, instead of running YOLO/ByteTrack again.

Input JSONL records must contain, at minimum:
  - tubelet_id
  - video_path
  - video_id
  - track_id
  - source_frame_indices
  - bboxes_xyxy_clipped
  - source_fps / sample_fps / effective_sample_fps where available

For every tubelet, the script:
  1) Re-opens the source video.
  2) Reads the exact source_frame_indices listed in the JSONL.
  3) Computes one static union bbox across the 16 tracked boxes.
  4) Applies the same pad ratio used by the deployment Deep gate.
  5) Crops/resizes all 16 frames to 224x224 RGB.
  6) Runs MCG-NJU/videomae-base.
  7) Saves person_embeddings.npy and union_embedding_metadata.csv.

Important parity note
---------------------
The JSONL must come from a live-parity tubelet extractor where YOLO.track() was
run on every decoded frame before sampling. This script does NOT repair a bad
sample-first JSONL; it only converts a good live-parity JSONL into Deep features.

Example
-------
python .\scripts\05a_build_deep_embeddings_from_motion_tubelets_jsonl.py `
  --jsonl_path "D:\Embeddings_Distribution\normality_models\motion_tubelets\motion_tubelets_homography_live_parity_2p5fps_16f_s8_50vid\motion_tubelet_tracks.jsonl" `
  --processed_dir "D:\Embeddings_Distribution\processed_dataset_deep_from_motion_tubelets_liveparity_2p5fps_16f_s8_50vid" `
  --model_name "MCG-NJU/videomae-base" `
  --embedding_device cuda `
  --fp16 `
  --batch_size 8 `
  --person_padding 0.30 `
  --person_size 224
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from tqdm import tqdm

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

try:
    from transformers import VideoMAEImageProcessor, VideoMAEModel
except Exception:  # pragma: no cover
    VideoMAEImageProcessor = None
    VideoMAEModel = None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logger(log_path: Path) -> logging.Logger:
    ensure_dir(log_path.parent)
    logger = logging.getLogger("deep_from_motion_tubelets")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def append_csv(path: Path, row: Dict[str, Any], fieldnames: List[str]) -> None:
    ensure_dir(path.parent)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in fieldnames})


def save_json(path: Path, data: Dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_existing_tubelet_ids(metadata_csv: Path) -> set[str]:
    if not metadata_csv.exists():
        return set()
    ids: set[str] = set()
    with metadata_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = row.get("tubelet_id")
            if tid:
                ids.add(tid)
    return ids


# ---------------------------------------------------------------------------
# Geometry / crop helpers matching deployment Deep gate semantics
# ---------------------------------------------------------------------------


def clip_xyxy(box: Tuple[float, float, float, float], width: int, height: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(v) for v in box]
    x1 = max(0, min(width - 1, int(round(x1))))
    y1 = max(0, min(height - 1, int(round(y1))))
    x2 = max(0, min(width - 1, int(round(x2))))
    y2 = max(0, min(height - 1, int(round(y2))))
    if x2 <= x1:
        x2 = min(width - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(height - 1, y1 + 1)
    return x1, y1, x2, y2


def union_xyxy(bboxes_xyxy: List[List[float]], width: int, height: int) -> Tuple[int, int, int, int]:
    if not bboxes_xyxy:
        raise ValueError("empty bboxes_xyxy")
    return clip_xyxy(
        (
            min(float(b[0]) for b in bboxes_xyxy),
            min(float(b[1]) for b in bboxes_xyxy),
            max(float(b[2]) for b in bboxes_xyxy),
            max(float(b[3]) for b in bboxes_xyxy),
        ),
        width,
        height,
    )


def pad_xyxy(box: Tuple[int, int, int, int], width: int, height: int, pad_ratio: float) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    bw = max(1.0, float(x2 - x1))
    bh = max(1.0, float(y2 - y1))
    return clip_xyxy((x1 - bw * pad_ratio, y1 - bh * pad_ratio, x2 + bw * pad_ratio, y2 + bh * pad_ratio), width, height)


def xyxy_to_xywh(box: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))


def crop_tubelet_rgb(
    frames_bgr: List[np.ndarray],
    bboxes_xyxy_clipped: List[List[float]],
    *,
    out_size: int,
    pad_ratio: float,
) -> Tuple[List[np.ndarray], Dict[str, Any]]:
    if not frames_bgr:
        raise ValueError("empty frame list")
    h, w = frames_bgr[0].shape[:2]
    raw_union = union_xyxy(bboxes_xyxy_clipped, w, h)
    crop_box = pad_xyxy(raw_union, w, h, pad_ratio)
    x1, y1, x2, y2 = crop_box

    crops_rgb: List[np.ndarray] = []
    means: List[float] = []
    stds: List[float] = []
    for frame_bgr in frames_bgr:
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        crop = frame_rgb[y1:y2, x1:x2].copy()
        if crop.size == 0:
            crop = np.zeros((out_size, out_size, 3), dtype=np.uint8)
        else:
            crop = cv2.resize(crop, (out_size, out_size), interpolation=cv2.INTER_LINEAR)
        crops_rgb.append(crop)
        means.append(float(np.mean(crop)))
        stds.append(float(np.std(crop)))

    ux, uy, uw, uh = xyxy_to_xywh(raw_union)
    px, py, pw, ph = xyxy_to_xywh(crop_box)
    return crops_rgb, {
        "union_x": ux,
        "union_y": uy,
        "union_w": uw,
        "union_h": uh,
        "padded_union_x": px,
        "padded_union_y": py,
        "padded_union_w": pw,
        "padded_union_h": ph,
        "crop_union_x1": int(x1),
        "crop_union_y1": int(y1),
        "crop_union_x2": int(x2),
        "crop_union_y2": int(y2),
        "crop_mean_rgb": float(np.mean(means)) if means else 0.0,
        "crop_std_rgb": float(np.mean(stds)) if stds else 0.0,
    }


def embedding_valid(x: np.ndarray) -> Tuple[bool, Dict[str, Any]]:
    if x is None:
        return False, {"reason": "none"}
    if not np.isfinite(x).all():
        return False, {"reason": "nan_or_inf"}
    norm = float(np.linalg.norm(x))
    std = float(np.std(x))
    if norm < 1e-8 or norm > 1e8:
        return False, {"reason": "bad_norm", "norm": norm, "std": std}
    if std < 1e-10:
        return False, {"reason": "near_zero_std", "norm": norm, "std": std}
    return True, {"reason": "accepted", "norm": norm, "std": std}


# ---------------------------------------------------------------------------
# VideoMAE helpers
# ---------------------------------------------------------------------------


def load_videomae(model_name: str, device: str, fp16: bool, use_fast_processor: bool, logger: logging.Logger):
    if torch is None:
        raise RuntimeError("torch is not installed")
    if VideoMAEImageProcessor is None or VideoMAEModel is None:
        raise RuntimeError("transformers with VideoMAE support is not installed")

    if device.startswith("cuda") and not torch.cuda.is_available():
        logger.warning("CUDA requested but unavailable; falling back to CPU")
        device = "cpu"

    logger.info("Loading VideoMAE model=%s device=%s fp16=%s", model_name, device, fp16)
    try:
        processor = VideoMAEImageProcessor.from_pretrained(model_name, use_fast=use_fast_processor)
    except TypeError:
        processor = VideoMAEImageProcessor.from_pretrained(model_name)

    model = VideoMAEModel.from_pretrained(model_name)
    model.eval().to(device)
    if fp16 and str(device).startswith("cuda"):
        model.half()
    return model, processor, device


def extract_batch_embeddings_raw(
    videos_rgb: List[List[np.ndarray]],
    model,
    processor,
    device: str,
    fp16: bool,
) -> np.ndarray:
    """Return raw mean-pooled VideoMAE embeddings. Builder will L2-normalize later."""
    if not videos_rgb:
        return np.empty((0, 0), dtype=np.float32)

    def _run(batch: Any) -> np.ndarray:
        try:
            inputs = processor(batch, return_tensors="pt", do_flip_channel_order=False)
        except TypeError:
            inputs = processor(batch, return_tensors="pt")
        inputs = {k: v.to(device) for k, v in inputs.items()}
        if fp16 and str(device).startswith("cuda"):
            inputs = {k: (v.half() if torch.is_floating_point(v) else v) for k, v in inputs.items()}
        with torch.inference_mode():
            # torch.autocast works on modern torch; keep it guarded for older builds.
            try:
                with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=(fp16 and str(device).startswith("cuda"))):
                    outputs = model(**inputs)
            except TypeError:
                outputs = model(**inputs)
        pooled = outputs.last_hidden_state.mean(dim=1)
        return pooled.detach().float().cpu().numpy().astype(np.float32)

    try:
        return _run(videos_rgb)
    except Exception:
        # Robust fallback for processors that dislike nested batching.
        out: List[np.ndarray] = []
        for one in videos_rgb:
            emb = _run(one)
            out.append(emb[0] if emb.ndim == 2 else emb)
        return np.stack(out, axis=0).astype(np.float32)


# ---------------------------------------------------------------------------
# JSONL loading / validation
# ---------------------------------------------------------------------------


def iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec["_line_no"] = line_no
                yield rec
            except Exception as exc:
                yield {"_line_no": line_no, "_invalid_json": str(exc)}


def basic_record_error(rec: Dict[str, Any], expected_tubelet_frames: int) -> Optional[str]:
    if rec.get("_invalid_json"):
        return f"invalid_json:{rec.get('_invalid_json')}"
    required = ["tubelet_id", "video_path", "video_id", "track_id", "source_frame_indices", "bboxes_xyxy_clipped"]
    for k in required:
        if k not in rec:
            return f"missing_{k}"
    frames = rec.get("source_frame_indices")
    boxes = rec.get("bboxes_xyxy_clipped")
    if not isinstance(frames, list) or not isinstance(boxes, list):
        return "source_frame_indices_or_bboxes_not_list"
    if len(frames) != expected_tubelet_frames:
        return f"wrong_frame_count:{len(frames)}"
    if len(boxes) != expected_tubelet_frames:
        return f"wrong_bbox_count:{len(boxes)}"
    for b in boxes:
        if not isinstance(b, list) or len(b) != 4:
            return "bad_bbox_shape"
    return None


# ---------------------------------------------------------------------------
# Main conversion logic
# ---------------------------------------------------------------------------


META_FIELDS = [
    "tubelet_id", "video_path", "video_id", "track_id", "gate_name",
    "start_frame", "end_frame", "start_time_sec", "end_time_sec",
    "clip_span_sec", "clip_duration_sec",
    "source_fps", "frame_step", "effective_sample_fps", "sample_fps", "tubelet_frames", "stride",
    "person_embedding_index", "person_valid", "person_norm", "person_std",
    "mean_conf", "min_conf", "mean_bbox_area_ratio", "mean_iou", "max_center_jump_ratio",
    "union_x", "union_y", "union_w", "union_h",
    "padded_union_x", "padded_union_y", "padded_union_w", "padded_union_h",
    "crop_union_x1", "crop_union_y1", "crop_union_x2", "crop_union_y2",
    "crop_mean_rgb", "crop_std_rgb",
    "person_padding", "crop_mode", "crop_out_size", "model_name",
    "source_frame_indices_json", "sample_indices_json",
    "local_tubelet_index", "global_tubelet_index", "jsonl_line_no",
]

INVALID_FIELDS = ["tubelet_id", "video_path", "video_id", "track_id", "jsonl_line_no", "reason", "error"]


def prepare_output_dirs(processed_dir: Path, resume: bool, overwrite: bool) -> Tuple[Path, Path, Path, Path, Path]:
    emb_dir = processed_dir / "embeddings"
    meta_dir = processed_dir / "metadata"
    logs_dir = processed_dir / "logs"
    debug_dir = processed_dir / "debug_tubelets"
    person_npy = emb_dir / "person_embeddings.npy"
    metadata_csv = emb_dir / "union_embedding_metadata.csv"

    if processed_dir.exists() and not resume:
        important = [person_npy, metadata_csv, meta_dir / "union_invalid_embeddings.csv"]
        has_existing = any(p.exists() for p in important)
        if has_existing and not overwrite:
            raise SystemExit(
                f"ERROR: processed_dir already contains Deep embedding outputs:\n  {processed_dir}\n\n"
                "Use --resume to continue, --overwrite to replace, or choose a new folder."
            )
        if overwrite:
            for p in important:
                if p.exists():
                    p.unlink()
            if debug_dir.exists():
                shutil.rmtree(debug_dir)

    ensure_dir(emb_dir)
    ensure_dir(meta_dir)
    ensure_dir(logs_dir)
    ensure_dir(debug_dir)
    return emb_dir, meta_dir, logs_dir, debug_dir, person_npy


def save_debug_mp4(frames_rgb: List[np.ndarray], path: Path, fps: float) -> None:
    ensure_dir(path.parent)
    if not frames_rgb:
        return
    h, w = frames_rgb[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), max(1, int(round(fps))), (w, h))
    for fr_rgb in frames_rgb:
        writer.write(cv2.cvtColor(fr_rgb, cv2.COLOR_RGB2BGR))
    writer.release()


def flush_embedding_batch(
    *,
    batch_videos_rgb: List[List[np.ndarray]],
    batch_meta: List[Dict[str, Any]],
    embeddings: List[np.ndarray],
    metadata_csv: Path,
    invalid_csv: Path,
    model,
    processor,
    device: str,
    fp16: bool,
    logger: logging.Logger,
) -> Tuple[int, int]:
    if not batch_meta:
        return 0, 0
    try:
        embs = extract_batch_embeddings_raw(batch_videos_rgb, model, processor, device, fp16)
    except Exception as exc:
        logger.exception("VideoMAE batch failed")
        for m in batch_meta:
            append_csv(invalid_csv, {
                "tubelet_id": m.get("tubelet_id", ""),
                "video_path": m.get("video_path", ""),
                "video_id": m.get("video_id", ""),
                "track_id": m.get("track_id", ""),
                "jsonl_line_no": m.get("jsonl_line_no", ""),
                "reason": "videomae_batch_failed",
                "error": repr(exc),
            }, INVALID_FIELDS)
        return 0, len(batch_meta)

    saved = 0
    invalid = 0
    for emb, meta in zip(embs, batch_meta):
        ok, info = embedding_valid(np.asarray(emb))
        if not ok:
            invalid += 1
            append_csv(invalid_csv, {
                "tubelet_id": meta.get("tubelet_id", ""),
                "video_path": meta.get("video_path", ""),
                "video_id": meta.get("video_id", ""),
                "track_id": meta.get("track_id", ""),
                "jsonl_line_no": meta.get("jsonl_line_no", ""),
                "reason": info.get("reason", "invalid_embedding"),
                "error": json.dumps(info, ensure_ascii=False),
            }, INVALID_FIELDS)
            continue

        meta = dict(meta)
        meta["person_embedding_index"] = len(embeddings)
        meta["person_valid"] = True
        meta["person_norm"] = float(info.get("norm", np.linalg.norm(emb)))
        meta["person_std"] = float(info.get("std", np.std(emb)))
        embeddings.append(np.asarray(emb, dtype=np.float32))
        append_csv(metadata_csv, meta, META_FIELDS)
        saved += 1
    return saved, invalid


def process_video_records(
    *,
    video_path: Path,
    records: List[Dict[str, Any]],
    args: argparse.Namespace,
    model,
    processor,
    device: str,
    embeddings: List[np.ndarray],
    metadata_csv: Path,
    invalid_csv: Path,
    person_npy: Path,
    debug_dir: Path,
    logger: logging.Logger,
    stats: Dict[str, Any],
) -> None:
    records = sorted(records, key=lambda r: max(int(x) for x in r["source_frame_indices"]))
    needed_counter: Counter[int] = Counter()
    for r in records:
        needed_counter.update(int(x) for x in r["source_frame_indices"])

    max_needed_frame = max(needed_counter.keys()) if needed_counter else -1
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("Could not open video: %s", video_path)
        for r in records:
            append_csv(invalid_csv, {
                "tubelet_id": r.get("tubelet_id", ""), "video_path": str(video_path),
                "video_id": r.get("video_id", ""), "track_id": r.get("track_id", ""),
                "jsonl_line_no": r.get("_line_no", ""), "reason": "could_not_open_video", "error": "",
            }, INVALID_FIELDS)
        stats["failed_records"] += len(records)
        return

    frame_cache: Dict[int, np.ndarray] = {}
    current_frame_index = -1
    rec_i = 0
    batch_videos_rgb: List[List[np.ndarray]] = []
    batch_meta: List[Dict[str, Any]] = []
    debug_saved_for_video = 0

    pbar = tqdm(total=max_needed_frame + 1 if max_needed_frame >= 0 else None,
                desc=f"Deep crops {video_path.name}", unit="frame", disable=args.no_progress)
    try:
        while current_frame_index < max_needed_frame:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            current_frame_index += 1
            pbar.update(1)

            if current_frame_index in needed_counter:
                frame_cache[current_frame_index] = frame.copy()

            # Process every record whose final frame is now available.
            while rec_i < len(records) and max(int(x) for x in records[rec_i]["source_frame_indices"]) <= current_frame_index:
                rec = records[rec_i]
                rec_i += 1
                tubelet_id = str(rec["tubelet_id"])
                indices = [int(x) for x in rec["source_frame_indices"]]

                try:
                    missing = [idx for idx in indices if idx not in frame_cache]
                    if missing:
                        raise RuntimeError(f"missing_frames:{missing[:5]} count={len(missing)}")
                    frames = [frame_cache[idx] for idx in indices]
                    bboxes = rec["bboxes_xyxy_clipped"]
                    crops_rgb, crop_meta = crop_tubelet_rgb(
                        frames,
                        bboxes,
                        out_size=args.person_size,
                        pad_ratio=args.person_padding,
                    )

                    start_t = rec.get("start_time_sec")
                    end_t = rec.get("end_time_sec")
                    try:
                        clip_span = float(end_t) - float(start_t)
                    except Exception:
                        clip_span = math.nan

                    meta = {
                        "tubelet_id": tubelet_id,
                        "video_path": str(video_path),
                        "video_id": rec.get("video_id", ""),
                        "track_id": rec.get("track_id", ""),
                        "gate_name": rec.get("gate_name", ""),
                        "start_frame": rec.get("start_frame", indices[0]),
                        "end_frame": rec.get("end_frame", indices[-1]),
                        "start_time_sec": start_t,
                        "end_time_sec": end_t,
                        "clip_span_sec": clip_span,
                        "clip_duration_sec": clip_span,
                        "source_fps": rec.get("source_fps", ""),
                        "frame_step": rec.get("frame_step", ""),
                        "effective_sample_fps": rec.get("effective_sample_fps", rec.get("sample_fps", "")),
                        "sample_fps": rec.get("sample_fps", ""),
                        "tubelet_frames": rec.get("tubelet_frames", len(indices)),
                        "stride": rec.get("stride", ""),
                        "mean_conf": rec.get("mean_conf", ""),
                        "min_conf": rec.get("min_conf", ""),
                        "mean_bbox_area_ratio": rec.get("mean_bbox_area_ratio", ""),
                        "mean_iou": rec.get("mean_iou", ""),
                        "max_center_jump_ratio": rec.get("max_center_jump_ratio", ""),
                        "person_padding": args.person_padding,
                        "crop_mode": "static_padded_union_from_live_parity_motion_tubelets",
                        "crop_out_size": args.person_size,
                        "model_name": args.model_name,
                        "source_frame_indices_json": json.dumps(indices),
                        "sample_indices_json": json.dumps(rec.get("sample_indices", [])),
                        "local_tubelet_index": rec.get("local_tubelet_index", ""),
                        "global_tubelet_index": rec.get("global_tubelet_index", ""),
                        "jsonl_line_no": rec.get("_line_no", ""),
                        **crop_meta,
                    }
                    batch_videos_rgb.append(crops_rgb)
                    batch_meta.append(meta)

                    if args.debug_save_mp4_limit > 0 and debug_saved_for_video < args.debug_save_mp4_limit and stats["debug_saved"] < args.debug_save_mp4_limit:
                        safe_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in tubelet_id)[:180]
                        save_debug_mp4(crops_rgb, debug_dir / "union" / f"{safe_id}.mp4", args.debug_fps)
                        debug_saved_for_video += 1
                        stats["debug_saved"] += 1

                    if len(batch_meta) >= args.batch_size:
                        saved, invalid = flush_embedding_batch(
                            batch_videos_rgb=batch_videos_rgb,
                            batch_meta=batch_meta,
                            embeddings=embeddings,
                            metadata_csv=metadata_csv,
                            invalid_csv=invalid_csv,
                            model=model,
                            processor=processor,
                            device=device,
                            fp16=args.fp16,
                            logger=logger,
                        )
                        stats["saved_embeddings"] += saved
                        stats["invalid_embeddings"] += invalid
                        batch_videos_rgb.clear()
                        batch_meta.clear()
                        if embeddings and len(embeddings) % args.checkpoint_every < args.batch_size:
                            np.save(person_npy, np.stack(embeddings, axis=0))

                except Exception as exc:
                    stats["failed_records"] += 1
                    append_csv(invalid_csv, {
                        "tubelet_id": tubelet_id,
                        "video_path": str(video_path),
                        "video_id": rec.get("video_id", ""),
                        "track_id": rec.get("track_id", ""),
                        "jsonl_line_no": rec.get("_line_no", ""),
                        "reason": "crop_or_frame_read_failed",
                        "error": repr(exc),
                    }, INVALID_FIELDS)

                # Decrement frame reference counts and drop frames no longer needed.
                for idx in indices:
                    needed_counter[idx] -= 1
                    if needed_counter[idx] <= 0:
                        needed_counter.pop(idx, None)
                        frame_cache.pop(idx, None)

        # Remaining records were beyond actual video length.
        while rec_i < len(records):
            rec = records[rec_i]
            rec_i += 1
            stats["failed_records"] += 1
            append_csv(invalid_csv, {
                "tubelet_id": rec.get("tubelet_id", ""), "video_path": str(video_path),
                "video_id": rec.get("video_id", ""), "track_id": rec.get("track_id", ""),
                "jsonl_line_no": rec.get("_line_no", ""),
                "reason": "video_ended_before_required_frames",
                "error": f"last_read_frame={current_frame_index}, max_needed={max(rec.get('source_frame_indices', [0]))}",
            }, INVALID_FIELDS)

        saved, invalid = flush_embedding_batch(
            batch_videos_rgb=batch_videos_rgb,
            batch_meta=batch_meta,
            embeddings=embeddings,
            metadata_csv=metadata_csv,
            invalid_csv=invalid_csv,
            model=model,
            processor=processor,
            device=device,
            fp16=args.fp16,
            logger=logger,
        )
        stats["saved_embeddings"] += saved
        stats["invalid_embeddings"] += invalid
        batch_videos_rgb.clear()
        batch_meta.clear()

    finally:
        pbar.close()
        cap.release()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Deep VideoMAE embeddings from live-parity motion_tubelet_tracks.jsonl")
    p.add_argument("--jsonl_path", required=True, type=Path, help="Path to motion_tubelet_tracks.jsonl")
    p.add_argument("--processed_dir", required=True, type=Path, help="Output processed dataset folder")
    p.add_argument("--model_name", default="MCG-NJU/videomae-base")
    p.add_argument("--embedding_device", default="cuda")
    p.add_argument("--fp16", action="store_true")
    p.add_argument("--use_fast_processor", action="store_true")
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--person_padding", type=float, default=0.30)
    p.add_argument("--person_size", type=int, default=224)
    p.add_argument("--expected_tubelet_frames", type=int, default=16)
    p.add_argument("--limit_tubelets", type=int, default=0, help="0 = no limit")
    p.add_argument("--limit_videos", type=int, default=0, help="0 = no limit")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--checkpoint_every", type=int, default=256)
    p.add_argument("--debug_save_mp4_limit", type=int, default=0)
    p.add_argument("--debug_fps", type=float, default=2.5)
    p.add_argument("--no_progress", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    started = time.time()

    if not args.jsonl_path.exists():
        raise SystemExit(f"ERROR: jsonl_path does not exist: {args.jsonl_path}")
    if args.batch_size < 1:
        raise SystemExit("ERROR: --batch_size must be >= 1")

    emb_dir, meta_dir, logs_dir, debug_dir, person_npy = prepare_output_dirs(args.processed_dir, args.resume, args.overwrite)
    metadata_csv = emb_dir / "union_embedding_metadata.csv"
    invalid_csv = meta_dir / "union_invalid_embeddings.csv"
    summary_json = emb_dir / "deep_from_motion_tubelets_summary.json"
    logger = setup_logger(logs_dir / "deep_from_motion_tubelets.log")

    processed_ids = read_existing_tubelet_ids(metadata_csv) if args.resume else set()
    embeddings: List[np.ndarray] = []
    if args.resume and person_npy.exists():
        logger.info("Resume mode: loading existing embeddings from %s", person_npy)
        arr = np.load(person_npy, mmap_mode=None)
        embeddings = [arr[i].astype(np.float32, copy=False) for i in range(arr.shape[0])]
        logger.info("Loaded %d existing embeddings", len(embeddings))

    logger.info("Loading JSONL records: %s", args.jsonl_path)
    by_video: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    invalid_records = 0
    total_records_seen = 0
    for rec in iter_jsonl(args.jsonl_path):
        total_records_seen += 1
        if args.limit_tubelets and (total_records_seen > args.limit_tubelets):
            break
        err = basic_record_error(rec, args.expected_tubelet_frames)
        if err:
            invalid_records += 1
            append_csv(invalid_csv, {
                "tubelet_id": rec.get("tubelet_id", ""),
                "video_path": rec.get("video_path", ""),
                "video_id": rec.get("video_id", ""),
                "track_id": rec.get("track_id", ""),
                "jsonl_line_no": rec.get("_line_no", ""),
                "reason": "invalid_jsonl_record",
                "error": err,
            }, INVALID_FIELDS)
            continue
        if rec["tubelet_id"] in processed_ids:
            continue
        by_video[str(rec["video_path"])].append(rec)

    video_items = list(by_video.items())
    if args.limit_videos:
        video_items = video_items[: args.limit_videos]
    logger.info("Records seen=%d | invalid_records=%d | videos_to_process=%d | tubelets_to_process=%d",
                total_records_seen, invalid_records, len(video_items), sum(len(v) for _, v in video_items))

    model, processor, device = load_videomae(args.model_name, args.embedding_device, args.fp16, args.use_fast_processor, logger)

    stats: Dict[str, Any] = {
        "total_records_seen": int(total_records_seen),
        "invalid_jsonl_records": int(invalid_records),
        "videos_to_process": int(len(video_items)),
        "tubelets_to_process": int(sum(len(v) for _, v in video_items)),
        "saved_embeddings": int(len(embeddings)),
        "invalid_embeddings": 0,
        "failed_records": 0,
        "debug_saved": 0,
    }

    for video_path_str, records in video_items:
        logger.info("Processing video: %s | records=%d", video_path_str, len(records))
        process_video_records(
            video_path=Path(video_path_str),
            records=records,
            args=args,
            model=model,
            processor=processor,
            device=device,
            embeddings=embeddings,
            metadata_csv=metadata_csv,
            invalid_csv=invalid_csv,
            person_npy=person_npy,
            debug_dir=debug_dir,
            logger=logger,
            stats=stats,
        )
        if embeddings:
            np.save(person_npy, np.stack(embeddings, axis=0))
            logger.info("Checkpoint saved: %s | embeddings=%d", person_npy, len(embeddings))

    if embeddings:
        np.save(person_npy, np.stack(embeddings, axis=0))
    else:
        logger.warning("No embeddings were saved; person_embeddings.npy was not written")

    stats["final_saved_embeddings"] = int(len(embeddings))
    stats["elapsed_sec"] = float(time.time() - started)
    stats["settings"] = {
        "jsonl_path": str(args.jsonl_path),
        "processed_dir": str(args.processed_dir),
        "model_name": args.model_name,
        "embedding_device": device,
        "fp16": bool(args.fp16),
        "batch_size": int(args.batch_size),
        "person_padding": float(args.person_padding),
        "person_size": int(args.person_size),
        "expected_tubelet_frames": int(args.expected_tubelet_frames),
        "crop_mode": "static_padded_union_from_live_parity_motion_tubelets",
        "embedding_saved_normalization": "raw_mean_pooled_videomae_builder_will_l2_normalize",
    }
    stats["outputs"] = {
        "person_embeddings_npy": str(person_npy),
        "union_embedding_metadata_csv": str(metadata_csv),
        "invalid_csv": str(invalid_csv),
        "summary_json": str(summary_json),
        "log": str(logs_dir / "deep_from_motion_tubelets.log"),
    }
    save_json(summary_json, stats)
    logger.info("DONE | saved_embeddings=%d | failed_records=%d | invalid_embeddings=%d", len(embeddings), stats["failed_records"], stats["invalid_embeddings"])
    logger.info("Summary: %s", summary_json)


if __name__ == "__main__":
    main()
