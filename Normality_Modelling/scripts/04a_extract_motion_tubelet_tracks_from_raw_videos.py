#!/usr/bin/env python3
r"""
04a_extract_motion_tubelet_tracks_from_raw_videos_v2_pose_5fps_24f_s6.py

Purpose
-------
Run raw surveillance videos through YOLO person tracking and save reusable
motion tubelet track metadata, WITHOUT loading VideoMAE and WITHOUT extracting
deep embeddings.

This is the "do once" foundation for:
  - RAFT optical-flow velocity features
  - pose keypoints / pose kinematics
  - homography-based floor/world speed
  - future motion or interaction attributes

Example PowerShell usage
------------------------
Test on 3 videos first:

python .\04a_extract_motion_tubelet_tracks_from_raw_videos_v1_2_fast.py `
  --input_dir "D:\Embeddings_Distribution\raw_videos" `
  --output_dir "D:\Embeddings_Distribution\normality_models\motion_tubelets_v2_5fps_24f_s6" `
  --yolo_model "D:\Embeddings_Distribution\yolov8n.pt" `
  --limit_videos 3

Full run:

python .\04a_extract_motion_tubelet_tracks_from_raw_videos_v1_2_fast.py `
  --input_dir "D:\Embeddings_Distribution\raw_videos" `
  --output_dir "D:\Embeddings_Distribution\normality_models\motion_tubelets_v2_5fps_24f_s6" `
  --yolo_model "D:\Embeddings_Distribution\yolov8n.pt"

Overwrite an existing output folder:

python .\04a_extract_motion_tubelet_tracks_from_raw_videos_v1_2_fast.py `
  --input_dir "D:\Embeddings_Distribution\raw_videos" `
  --output_dir "D:\Embeddings_Distribution\normality_models\motion_tubelets_v2_5fps_24f_s6" `
  --yolo_model "D:\Embeddings_Distribution\yolov8n.pt" `
  --overwrite

Dependencies
------------
pip install ultralytics opencv-python numpy pandas tqdm

Notes
-----
- This pose-focused version samples videos at 5 FPS by default.
- Each accepted tubelet has exactly 24 sampled detections and 24 bboxes.
- Tubelet stride is 6 detections by default.
- By default, tubelets must use contiguous sampled detections so pose speeds/accelerations stay comparable to the 5 FPS calibration setting.
- The JSONL output is intentionally rich so later scripts do not need to redo
  tracking just to get bboxes, centers, bottom centers, or timing metadata.
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
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from tqdm import tqdm

try:
    import torch
except ImportError:
    torch = None

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise SystemExit(
        "ERROR: ultralytics is not installed. Install it with:\n"
        "  pip install ultralytics\n"
    ) from exc


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv", ".mpg", ".mpeg", ".webm"
}


@dataclass
class TrackItem:
    sample_index: int
    frame_index: int
    time_sec: float
    bbox_xywh: Tuple[float, float, float, float]
    conf: float
    frame_width: int
    frame_height: int


@dataclass
class TrackBuffer:
    track_id: int
    maxlen: int
    max_track_gap: int
    items: Deque[TrackItem] = field(default_factory=deque)
    last_sample_index: Optional[int] = None
    emitted_start_positions: set = field(default_factory=set)

    def append(self, item: TrackItem) -> None:
        if self.last_sample_index is not None:
            gap = item.sample_index - self.last_sample_index
            if gap > self.max_track_gap + 1:
                self.items.clear()
                self.emitted_start_positions.clear()

        self.items.append(item)
        self.last_sample_index = item.sample_index

        # Keep a little extra history so stride windows can be emitted safely.
        while len(self.items) > self.maxlen:
            self.items.popleft()

    def candidate_windows(self, tubelet_frames: int, stride: int) -> Iterable[List[TrackItem]]:
        if len(self.items) < tubelet_frames:
            return

        items_list = list(self.items)
        max_start = len(items_list) - tubelet_frames

        for start_pos in range(0, max_start + 1):
            start_sample_index = items_list[start_pos].sample_index
            if start_sample_index in self.emitted_start_positions:
                continue

            # Only emit windows aligned to the requested stride.
            # This uses sample indices, so occasional missed detections do not break
            # reproducibility, but the actual source_frame_indices are still saved.
            if (start_sample_index % stride) != 0:
                continue

            window = items_list[start_pos:start_pos + tubelet_frames]
            self.emitted_start_positions.add(start_sample_index)
            yield window


def setup_logging(output_dir: Path) -> None:
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "motion_tubelet_tracks.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract reusable YOLO motion tubelet tracks from raw videos."
    )

    parser.add_argument("--input_dir", required=True, type=Path)
    parser.add_argument("--output_dir", required=True, type=Path)
    parser.add_argument("--yolo_model", required=True, type=Path)

    parser.add_argument("--tracker", default="bytetrack.yaml")
    parser.add_argument("--device", default=None, help="Examples: cuda, cuda:0, cpu. Default lets Ultralytics decide.")
    parser.add_argument("--half", action="store_true", help="Use FP16 inference for YOLO on CUDA. Faster on RTX GPUs; ignored on CPU.")
    parser.add_argument("--compile_model", action="store_true", help="Experimental: ask Ultralytics/PyTorch to compile the YOLO model where supported.")
    parser.add_argument("--no_progress", action="store_true", help="Disable per-video tqdm progress bar for a tiny speedup and cleaner logs.")

    # Pose micro-kinematic gate defaults.
    # 5 FPS gives a 200 ms sampling interval; 24 frames gives ~4.8 s context;
    # stride 6 gives a new tubelet roughly every 1.2 s.
    parser.add_argument("--sample_fps", type=float, default=5.0)
    parser.add_argument("--tubelet_frames", type=int, default=24)
    parser.add_argument("--stride", type=int, default=6)

    parser.add_argument("--min_conf", type=float, default=0.45)
    parser.add_argument("--min_bbox_width", type=float, default=50.0)
    parser.add_argument("--min_bbox_height", type=float, default=50.0)
    parser.add_argument("--min_mean_iou", type=float, default=0.30)
    parser.add_argument("--max_center_jump_ratio", type=float, default=1.50)
    parser.add_argument("--max_track_gap", type=int, default=2)
    parser.add_argument(
        "--allow_sample_gaps",
        action="store_true",
        help=(
            "Allow tubelets with missed sampled detections inside the 24-frame window. "
            "Default is strict/clean: reject non-contiguous sample indices for pose calibration."
        ),
    )

    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--iou", type=float, default=0.7)

    parser.add_argument("--limit_videos", type=int, default=None)
    parser.add_argument("--max_tubelets_per_video", type=int, default=None)

    parser.add_argument("--save_debug_previews", action="store_true")
    parser.add_argument("--debug_preview_limit", type=int, default=20)

    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--video_id_from", choices=["stem", "relative_path"], default="stem")

    return parser.parse_args()


def safe_prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        important_outputs = [
            output_dir / "motion_tubelet_tracks.jsonl",
            output_dir / "motion_tubelet_tracks_summary.json",
            output_dir / "motion_tubelet_tracks_failed.csv",
            output_dir / "motion_tubelet_tracks_rejected.csv",
        ]
        has_existing_outputs = any(path.exists() for path in important_outputs)

        if has_existing_outputs and not overwrite:
            raise SystemExit(
                f"ERROR: output_dir already contains extraction outputs:\n"
                f"  {output_dir}\n\n"
                f"Use a new --output_dir or pass --overwrite if you intentionally want to replace them."
            )

        if overwrite:
            for path in important_outputs:
                if path.exists():
                    path.unlink()
            previews_dir = output_dir / "debug_previews"
            if previews_dir.exists():
                shutil.rmtree(previews_dir)

    output_dir.mkdir(parents=True, exist_ok=True)


def find_videos(input_dir: Path, recursive: bool) -> List[Path]:
    if not input_dir.exists():
        raise SystemExit(f"ERROR: input_dir does not exist: {input_dir}")

    pattern_iter = input_dir.rglob("*") if recursive else input_dir.glob("*")
    videos = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    videos.sort(key=lambda p: str(p).lower())
    return videos


def make_video_id(video_path: Path, input_dir: Path, mode: str) -> str:
    if mode == "relative_path":
        rel = video_path.relative_to(input_dir)
        return rel.as_posix().replace("/", "__")
    return video_path.stem


def xywh_to_xyxy(bbox: Sequence[float]) -> Tuple[float, float, float, float]:
    x, y, w, h = bbox
    return x, y, x + w, y + h


def bbox_iou_xywh(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = xywh_to_xyxy(a)
    bx1, by1, bx2, by2 = xywh_to_xyxy(b)

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter_area

    if union <= 0:
        return 0.0
    return float(inter_area / union)


def center_xy(bbox: Sequence[float]) -> Tuple[float, float]:
    x, y, w, h = bbox
    return x + w / 2.0, y + h / 2.0


def bottom_center_xy(bbox: Sequence[float]) -> Tuple[float, float]:
    x, y, w, h = bbox
    return x + w / 2.0, y + h


def compute_quality(window: Sequence[TrackItem]) -> Dict[str, float]:
    bboxes = [item.bbox_xywh for item in window]
    confs = [item.conf for item in window]

    ious = [
        bbox_iou_xywh(bboxes[i - 1], bboxes[i])
        for i in range(1, len(bboxes))
    ]

    jumps = []
    for i in range(1, len(bboxes)):
        c0 = np.array(center_xy(bboxes[i - 1]), dtype=np.float32)
        c1 = np.array(center_xy(bboxes[i]), dtype=np.float32)
        dist = float(np.linalg.norm(c1 - c0))

        _, _, w0, h0 = bboxes[i - 1]
        _, _, w1, h1 = bboxes[i]
        denom = max(float(w0), float(h0), float(w1), float(h1), 1.0)
        jumps.append(dist / denom)

    frame_w = max(1, int(window[0].frame_width))
    frame_h = max(1, int(window[0].frame_height))
    area_ratios = [
        max(0.0, float(b[2])) * max(0.0, float(b[3])) / float(frame_w * frame_h)
        for b in bboxes
    ]

    widths = [float(b[2]) for b in bboxes]
    heights = [float(b[3]) for b in bboxes]

    return {
        "mean_conf": float(np.mean(confs)) if confs else 0.0,
        "min_conf": float(np.min(confs)) if confs else 0.0,
        "mean_iou": float(np.mean(ious)) if ious else 0.0,
        "max_center_jump_ratio": float(np.max(jumps)) if jumps else 0.0,
        "mean_bbox_area_ratio": float(np.mean(area_ratios)) if area_ratios else 0.0,
        "min_bbox_width": float(np.min(widths)) if widths else 0.0,
        "min_bbox_height": float(np.min(heights)) if heights else 0.0,
    }


def reject_reasons(
    window: Sequence[TrackItem],
    quality: Dict[str, float],
    args: argparse.Namespace,
) -> List[str]:
    reasons = []

    if len(window) != args.tubelet_frames:
        reasons.append("wrong_tubelet_length")

    if quality["min_conf"] < args.min_conf:
        reasons.append("min_conf_too_low")

    if quality["min_bbox_width"] < args.min_bbox_width:
        reasons.append("bbox_width_too_small")

    if quality["min_bbox_height"] < args.min_bbox_height:
        reasons.append("bbox_height_too_small")

    if quality["mean_iou"] < args.min_mean_iou:
        reasons.append("mean_iou_too_low")

    if quality["max_center_jump_ratio"] > args.max_center_jump_ratio:
        reasons.append("center_jump_too_large")

    frame_indices = [item.frame_index for item in window]
    if any(frame_indices[i] <= frame_indices[i - 1] for i in range(1, len(frame_indices))):
        reasons.append("non_increasing_frame_indices")

    sample_indices = [item.sample_index for item in window]
    if not getattr(args, "allow_sample_gaps", False):
        if any((sample_indices[i] - sample_indices[i - 1]) != 1 for i in range(1, len(sample_indices))):
            reasons.append("non_contiguous_sample_indices")

    bboxes = [item.bbox_xywh for item in window]
    for bbox in bboxes:
        x, y, w, h = bbox
        if not all(math.isfinite(float(v)) for v in bbox):
            reasons.append("non_finite_bbox")
            break
        if w <= 0 or h <= 0:
            reasons.append("invalid_bbox_size")
            break

    return reasons


def write_jsonl_record(jsonl_file, record: Dict[str, Any]) -> None:
    jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_debug_preview(
    video_path: Path,
    output_dir: Path,
    tubelet_id: str,
    window: Sequence[TrackItem],
    max_side: int = 960,
) -> None:
    previews_dir = output_dir / "debug_previews"
    previews_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return

    first = window[0]
    cap.set(cv2.CAP_PROP_POS_FRAMES, first.frame_index)
    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        return

    x, y, w, h = [int(round(v)) for v in first.bbox_xywh]
    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    cv2.putText(
        frame,
        tubelet_id,
        (max(0, x), max(25, y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    height, width = frame.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        frame = cv2.resize(frame, (int(width * scale), int(height * scale)))

    out_path = previews_dir / f"{tubelet_id}.jpg"
    cv2.imwrite(str(out_path), frame)


def extract_detections_from_result(result: Any) -> List[Tuple[int, float, Tuple[float, float, float, float]]]:
    """
    Return a list of:
      (track_id, confidence, bbox_xywh_topleft)

    Ultralytics boxes.xywh is center-based xywh.
    This script converts it to top-left xywh because that is easier and safer
    for cropping in RAFT and pose scripts later.
    """
    detections = []

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return detections

    if boxes.id is None:
        return detections

    ids = boxes.id.detach().cpu().numpy().astype(int)
    confs = boxes.conf.detach().cpu().numpy().astype(float)
    classes = boxes.cls.detach().cpu().numpy().astype(int)
    xywh_center = boxes.xywh.detach().cpu().numpy().astype(float)

    for track_id, conf, cls_id, box in zip(ids, confs, classes, xywh_center):
        if cls_id != 0:
            continue

        cx, cy, w, h = [float(v) for v in box]
        x = cx - w / 2.0
        y = cy - h / 2.0
        detections.append((int(track_id), float(conf), (x, y, w, h)))

    return detections



def reset_yolo_tracker_state(model: YOLO) -> None:
    """
    Best-effort reset for Ultralytics tracker state between separate video files.

    Why this matters:
    We call model.track() on sampled frames with persist=True so IDs remain stable
    within one video. However, for a dataset of independent files, we do not want
    internal tracker state from the previous video to leak into the next one.
    Different Ultralytics versions expose tracker internals slightly differently,
    so this function is deliberately defensive.
    """
    predictor = getattr(model, "predictor", None)
    if predictor is None:
        return

    trackers = getattr(predictor, "trackers", None)
    if trackers is not None:
        for tracker in trackers:
            reset = getattr(tracker, "reset", None)
            if callable(reset):
                reset()

    # Some Ultralytics versions keep video-path bookkeeping here.
    if hasattr(predictor, "vid_path"):
        try:
            predictor.vid_path = [None] * len(predictor.vid_path)
        except Exception:
            predictor.vid_path = None


def clip_xywh_to_frame(
    bbox: Sequence[float],
    frame_width: int,
    frame_height: int,
) -> Tuple[float, float, float, float]:
    """Return top-left xywh clipped to valid image coordinates."""
    x, y, w, h = [float(v) for v in bbox]
    x1 = min(max(x, 0.0), float(frame_width - 1))
    y1 = min(max(y, 0.0), float(frame_height - 1))
    x2 = min(max(x + w, 0.0), float(frame_width))
    y2 = min(max(y + h, 0.0), float(frame_height))
    return x1, y1, max(0.0, x2 - x1), max(0.0, y2 - y1)


def xywh_to_list_xyxy(bbox: Sequence[float]) -> List[float]:
    x1, y1, x2, y2 = xywh_to_xyxy(bbox)
    return [float(x1), float(y1), float(x2), float(y2)]

def process_video(
    video_path: Path,
    input_dir: Path,
    model: YOLO,
    jsonl_file,
    rejected_writer: csv.DictWriter,
    failed_writer: csv.DictWriter,
    args: argparse.Namespace,
    global_state: Dict[str, int],
) -> Dict[str, Any]:
    started = time.time()
    video_id = make_video_id(video_path, input_dir, args.video_id_from)

    # Critical for dataset processing: keep tracking persistent within the video,
    # but start every independent video with clean tracker memory.
    reset_yolo_tracker_state(model)

    stats: Dict[str, Any] = {
        "video_path": str(video_path),
        "video_id": video_id,
        "status": "ok",
        "source_fps": None,
        "frame_count": None,
        "duration_sec": None,
        "frame_step": None,
        "effective_sample_fps": None,
        "target_window_duration_sec": None,
        "sampled_frames": 0,
        "accepted_tubelets": 0,
        "rejected_tubelets": 0,
        "unique_track_ids": 0,
        "elapsed_sec": None,
        "error": None,
    }

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        stats["status"] = "failed"
        stats["error"] = "could_not_open_video"
        failed_writer.writerow(stats)
        return stats

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if source_fps <= 0:
        source_fps = args.sample_fps
        logging.warning("FPS unavailable for %s; falling back to sample_fps=%.3f", video_path, source_fps)

    frame_step = max(1, int(round(source_fps / args.sample_fps)))
    effective_sample_fps = source_fps / frame_step
    duration_sec = frame_count / source_fps if source_fps > 0 else None
    target_window_duration_sec = float(args.tubelet_frames / args.sample_fps) if args.sample_fps > 0 else None

    if abs(effective_sample_fps - args.sample_fps) > 0.05:
        logging.warning(
            "Requested sample_fps=%.3f but effective_sample_fps=%.3f for %s because source_fps=%.3f and frame_step=%d",
            args.sample_fps, effective_sample_fps, video_path.name, source_fps, frame_step
        )

    stats.update({
        "source_fps": source_fps,
        "frame_count": frame_count,
        "duration_sec": duration_sec,
        "frame_step": frame_step,
        "effective_sample_fps": effective_sample_fps,
        "target_window_duration_sec": target_window_duration_sec,
    })

    # Keep enough history to emit stride windows without memory bloat.
    buffer_len = args.tubelet_frames + args.stride + args.max_track_gap + 4
    buffers: Dict[int, TrackBuffer] = defaultdict(
        lambda: TrackBuffer(
            track_id=-1,
            maxlen=buffer_len,
            max_track_gap=args.max_track_gap,
        )
    )

    seen_track_ids = set()
    frame_index = 0
    sample_index = -1
    debug_saved_for_video = 0

    try:
        pbar_total = frame_count if frame_count > 0 else None
        pbar_context = tqdm(total=pbar_total, desc=f"Tracking {video_path.name}", unit="frame", disable=args.no_progress)
        with pbar_context as pbar:
            while frame_count <= 0 or frame_index < frame_count:
                # Fast sampled reading: grab skipped frames without fully decoding them,
                # then retrieve only the sampled frame. This preserves exact frame indices
                # but is usually much faster than cap.read() for every source frame.
                ok = cap.grab()
                if not ok:
                    break

                if pbar_total:
                    pbar.update(1)

                if frame_index % frame_step != 0:
                    frame_index += 1
                    continue

                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    frame_index += 1
                    continue

                sample_index += 1
                stats["sampled_frames"] += 1
                current_frame_index = frame_index
                frame_h, frame_w = frame.shape[:2]
                time_sec = current_frame_index / source_fps if source_fps > 0 else sample_index / args.sample_fps

                results = model.track(
                    frame,
                    persist=True,
                    tracker=args.tracker,
                    conf=args.min_conf,
                    iou=args.iou,
                    imgsz=args.imgsz,
                    classes=[0],
                    device=args.device,
                    half=bool(args.half),
                    compile=bool(args.compile_model),
                    verbose=False,
                )

                if not results:
                    frame_index += 1
                    continue

                detections = extract_detections_from_result(results[0])
                for track_id, conf, bbox in detections:
                    seen_track_ids.add(track_id)

                    if track_id not in buffers or buffers[track_id].track_id == -1:
                        buffers[track_id] = TrackBuffer(
                            track_id=track_id,
                            maxlen=buffer_len,
                            max_track_gap=args.max_track_gap,
                        )

                    item = TrackItem(
                        sample_index=sample_index,
                        frame_index=current_frame_index,
                        time_sec=time_sec,
                        bbox_xywh=bbox,
                        conf=conf,
                        frame_width=frame_w,
                        frame_height=frame_h,
                    )
                    buffers[track_id].append(item)

                    for window in buffers[track_id].candidate_windows(args.tubelet_frames, args.stride):
                        quality = compute_quality(window)
                        reasons = reject_reasons(window, quality, args)

                        if reasons:
                            stats["rejected_tubelets"] += 1
                            rejected_writer.writerow({
                                "video_path": str(video_path),
                                "video_id": video_id,
                                "track_id": track_id,
                                "start_frame": window[0].frame_index if window else "",
                                "end_frame": window[-1].frame_index if window else "",
                                "start_time_sec": window[0].time_sec if window else "",
                                "end_time_sec": window[-1].time_sec if window else "",
                                "reasons": "|".join(sorted(set(reasons))),
                                **quality,
                            })
                            continue

                        if (
                            args.max_tubelets_per_video is not None
                            and stats["accepted_tubelets"] >= args.max_tubelets_per_video
                        ):
                            continue

                        local_index = stats["accepted_tubelets"]
                        global_index = global_state["next_tubelet_index"]
                        global_state["next_tubelet_index"] += 1

                        tubelet_id = f"{video_id}__track{track_id}__t{window[0].frame_index}_{window[-1].frame_index}__{global_index:08d}"

                        source_frame_indices = [int(item.frame_index) for item in window]
                        sample_indices = [int(item.sample_index) for item in window]
                        source_times_sec = [float(item.time_sec) for item in window]
                        frame_gaps = [
                            int(source_frame_indices[i] - source_frame_indices[i - 1])
                            for i in range(1, len(source_frame_indices))
                        ]
                        sample_gaps = [
                            int(sample_indices[i] - sample_indices[i - 1])
                            for i in range(1, len(sample_indices))
                        ]

                        bboxes_xywh = [[float(v) for v in item.bbox_xywh] for item in window]
                        bboxes_xyxy = [xywh_to_list_xyxy(item.bbox_xywh) for item in window]
                        bboxes_xywh_clipped = [
                            [float(v) for v in clip_xywh_to_frame(item.bbox_xywh, item.frame_width, item.frame_height)]
                            for item in window
                        ]
                        bboxes_xyxy_clipped = [xywh_to_list_xyxy(b) for b in bboxes_xywh_clipped]

                        bbox_centers_xy = [[float(v) for v in center_xy(item.bbox_xywh)] for item in window]
                        bbox_bottom_centers_xy = [[float(v) for v in bottom_center_xy(item.bbox_xywh)] for item in window]
                        bbox_bottom_centers_xy_clipped = [[float(v) for v in bottom_center_xy(b)] for b in bboxes_xywh_clipped]
                        bbox_widths = [float(item.bbox_xywh[2]) for item in window]
                        bbox_heights = [float(item.bbox_xywh[3]) for item in window]
                        confs = [float(item.conf) for item in window]

                        record = {
                            "schema_version": "motion_tubelet_tracks_v1.2_fast",
                            "tubelet_id": tubelet_id,
                            "video_path": str(video_path),
                            "video_id": video_id,
                            "track_id": int(track_id),

                            "source_fps": float(source_fps),
                            "sample_fps": float(args.sample_fps),
                            "effective_sample_fps": float(effective_sample_fps),
                            "frame_step": int(frame_step),
                            "tubelet_frames": int(args.tubelet_frames),
                            "stride": int(args.stride),

                            "start_frame": int(window[0].frame_index),
                            "end_frame": int(window[-1].frame_index),
                            "start_time_sec": float(window[0].time_sec),
                            "end_time_sec": float(window[-1].time_sec),
                            "tubelet_duration_sec": float(window[-1].time_sec - window[0].time_sec),
                            "target_window_duration_sec": float(args.tubelet_frames / args.sample_fps) if args.sample_fps > 0 else None,

                            "source_frame_indices": source_frame_indices,
                            "sample_indices": sample_indices,
                            "source_times_sec": source_times_sec,
                            "frame_gaps": frame_gaps,
                            "sample_gaps": sample_gaps,

                            "bboxes_xywh": bboxes_xywh,
                            "bboxes_xyxy": bboxes_xyxy,
                            "bboxes_xywh_clipped": bboxes_xywh_clipped,
                            "bboxes_xyxy_clipped": bboxes_xyxy_clipped,
                            "bbox_centers_xy": bbox_centers_xy,
                            "bbox_bottom_centers_xy": bbox_bottom_centers_xy,
                            "bbox_bottom_centers_xy_clipped": bbox_bottom_centers_xy_clipped,
                            "bbox_widths": bbox_widths,
                            "bbox_heights": bbox_heights,
                            "confs": confs,

                            "mean_conf": quality["mean_conf"],
                            "min_conf": quality["min_conf"],
                            "mean_iou": quality["mean_iou"],
                            "max_center_jump_ratio": quality["max_center_jump_ratio"],
                            "mean_bbox_area_ratio": quality["mean_bbox_area_ratio"],

                            "frame_width": int(window[0].frame_width),
                            "frame_height": int(window[0].frame_height),

                            "local_tubelet_index": int(local_index),
                            "global_tubelet_index": int(global_index),
                        }

                        write_jsonl_record(jsonl_file, record)
                        stats["accepted_tubelets"] += 1

                        if args.save_debug_previews and debug_saved_for_video < args.debug_preview_limit:
                            save_debug_preview(video_path, args.output_dir, tubelet_id, window)
                            debug_saved_for_video += 1

                frame_index += 1

        stats["unique_track_ids"] = len(seen_track_ids)

    except Exception as exc:
        logging.exception("Failed while processing video: %s", video_path)
        stats["status"] = "failed"
        stats["error"] = repr(exc)
        failed_writer.writerow(stats)

    finally:
        cap.release()

    stats["elapsed_sec"] = time.time() - started
    return stats


def main() -> None:
    args = parse_args()

    safe_prepare_output_dir(args.output_dir, args.overwrite)
    setup_logging(args.output_dir)

    logging.info("Starting motion tubelet extraction")
    logging.info("Input dir: %s", args.input_dir)
    logging.info("Output dir: %s", args.output_dir)
    logging.info("YOLO model: %s", args.yolo_model)
    logging.info("Temporal config: sample_fps=%.3f | tubelet_frames=%d | stride=%d | window≈%.3fs | allow_sample_gaps=%s", args.sample_fps, args.tubelet_frames, args.stride, (args.tubelet_frames / args.sample_fps if args.sample_fps > 0 else -1), bool(args.allow_sample_gaps))

    if not args.yolo_model.exists():
        raise SystemExit(f"ERROR: yolo_model does not exist: {args.yolo_model}")

    videos = find_videos(args.input_dir, recursive=args.recursive)
    if args.limit_videos is not None:
        videos = videos[:args.limit_videos]

    if not videos:
        raise SystemExit(f"ERROR: no videos found in: {args.input_dir}")

    logging.info("Videos to process: %d", len(videos))

    if torch is not None and torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        logging.info("CUDA available: %s", torch.cuda.get_device_name(0))
        if args.device is None:
            args.device = "cuda"
            logging.info("No --device provided; using cuda automatically.")
    elif args.device and str(args.device).startswith("cuda"):
        logging.warning("--device cuda was requested, but torch.cuda.is_available() is false.")

    model = YOLO(str(args.yolo_model))

    jsonl_path = args.output_dir / "motion_tubelet_tracks.jsonl"
    summary_path = args.output_dir / "motion_tubelet_tracks_summary.json"
    failed_path = args.output_dir / "motion_tubelet_tracks_failed.csv"
    rejected_path = args.output_dir / "motion_tubelet_tracks_rejected.csv"

    failed_fields = [
        "video_path", "video_id", "status", "source_fps", "frame_count",
        "duration_sec", "frame_step", "effective_sample_fps", "target_window_duration_sec", "sampled_frames",
        "accepted_tubelets", "rejected_tubelets", "unique_track_ids",
        "elapsed_sec", "error",
    ]

    rejected_fields = [
        "video_path", "video_id", "track_id", "start_frame", "end_frame",
        "start_time_sec", "end_time_sec", "reasons", "mean_conf", "min_conf",
        "mean_iou", "max_center_jump_ratio", "mean_bbox_area_ratio",
        "min_bbox_width", "min_bbox_height",
    ]

    all_video_stats: List[Dict[str, Any]] = []
    global_state = {"next_tubelet_index": 0}
    started_all = time.time()

    with (
        jsonl_path.open("w", encoding="utf-8", newline="\n") as jsonl_file,
        failed_path.open("w", encoding="utf-8", newline="") as failed_file,
        rejected_path.open("w", encoding="utf-8", newline="") as rejected_file,
    ):
        failed_writer = csv.DictWriter(failed_file, fieldnames=failed_fields)
        rejected_writer = csv.DictWriter(rejected_file, fieldnames=rejected_fields)
        failed_writer.writeheader()
        rejected_writer.writeheader()

        for video_path in videos:
            stats = process_video(
                video_path=video_path,
                input_dir=args.input_dir,
                model=model,
                jsonl_file=jsonl_file,
                rejected_writer=rejected_writer,
                failed_writer=failed_writer,
                args=args,
                global_state=global_state,
            )
            all_video_stats.append(stats)

            logging.info(
                "Video done | %s | status=%s | accepted=%s | rejected=%s | sampled=%s",
                video_path.name,
                stats["status"],
                stats["accepted_tubelets"],
                stats["rejected_tubelets"],
                stats["sampled_frames"],
            )

    total_accepted = int(sum(int(s.get("accepted_tubelets") or 0) for s in all_video_stats))
    total_rejected = int(sum(int(s.get("rejected_tubelets") or 0) for s in all_video_stats))
    total_sampled_frames = int(sum(int(s.get("sampled_frames") or 0) for s in all_video_stats))
    failed_videos = [s for s in all_video_stats if s.get("status") != "ok"]

    summary = {
        "script": Path(__file__).name,
        "schema_version": "motion_tubelet_tracks_v1.2_fast",
        "created_at_unix": time.time(),
        "elapsed_sec": time.time() - started_all,

        "input_dir": str(args.input_dir),
        "output_dir": str(args.output_dir),
        "yolo_model": str(args.yolo_model),
        "tracker": args.tracker,
        "device": args.device,

        "settings": {
            "sample_fps": args.sample_fps,
            "tubelet_frames": args.tubelet_frames,
            "stride": args.stride,
            "min_conf": args.min_conf,
            "min_bbox_width": args.min_bbox_width,
            "min_bbox_height": args.min_bbox_height,
            "min_mean_iou": args.min_mean_iou,
            "max_center_jump_ratio": args.max_center_jump_ratio,
            "max_track_gap": args.max_track_gap,
            "allow_sample_gaps": bool(args.allow_sample_gaps),
            "target_window_duration_sec": float(args.tubelet_frames / args.sample_fps) if args.sample_fps > 0 else None,
            "imgsz": args.imgsz,
            "iou": args.iou,
            "half": bool(args.half),
            "compile_model": bool(args.compile_model),
            "no_progress": bool(args.no_progress),
            "limit_videos": args.limit_videos,
            "max_tubelets_per_video": args.max_tubelets_per_video,
            "recursive": args.recursive,
            "video_id_from": args.video_id_from,
        },

        "totals": {
            "videos_requested": len(videos),
            "videos_ok": len(videos) - len(failed_videos),
            "videos_failed": len(failed_videos),
            "sampled_frames": total_sampled_frames,
            "accepted_tubelets": total_accepted,
            "rejected_tubelets": total_rejected,
        },

        "outputs": {
            "motion_tubelet_tracks_jsonl": str(jsonl_path),
            "summary_json": str(summary_path),
            "failed_csv": str(failed_path),
            "rejected_csv": str(rejected_path),
            "log_file": str(args.output_dir / "logs" / "motion_tubelet_tracks.log"),
        },

        "pose_gate_note": (
            "This run is intended for the 5 FPS / 24-frame / stride-6 pose micro-kinematic gate. "
            "Use the same temporal configuration for pose feature extraction, GMM calibration, and live/backend inference."
        ),

        "video_stats": all_video_stats,
    }

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logging.info("Extraction complete")
    logging.info("Accepted tubelets: %d", total_accepted)
    logging.info("Rejected tubelets: %d", total_rejected)
    logging.info("Summary: %s", summary_path)
    logging.info("JSONL: %s", jsonl_path)


if __name__ == "__main__":
    main()
