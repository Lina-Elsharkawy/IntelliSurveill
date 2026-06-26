#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
04a2_add_pose_groundpoints_to_motion_tubelets_STAGE3.py

Surgical bridge script for the Stage-3 homography/macro-motion gate.

Why this exists
---------------
The correct long-term fix is to integrate this logic directly into the original
04a tubelet extractor, so motion_tubelet_tracks.jsonl is born with stable
pose-assisted ground points. If the original 04a file is not available, this
script safely enriches an existing motion_tubelet_tracks.jsonl in-place by
writing a new JSONL with the required fields:

  ground_points_xy
  groundpoint_sources
  groundpoint_confs
  groundpoint_left_ankle_confs
  groundpoint_right_ankle_confs
  groundpoint_valid_pose_ratio
  groundpoint_frozen_ratio
  groundpoint_bbox_fallback_ratio
  groundpoint_source_counts

Ground-point policy
-------------------
- both ankles reliable -> ankle midpoint
- one ankle reliable   -> that ankle
- no reliable ankle    -> freeze last valid ground point if recent enough
- no recent valid point -> bbox bottom-center

Recommended command
-------------------
python .\04a2_add_pose_groundpoints_to_motion_tubelets_STAGE3.py `
  --input_jsonl "D:\Embeddings_Distribution\normality_models\motion_tubelets_v1_2_fast\motion_tubelet_tracks.jsonl" `
  --output_jsonl "D:\Embeddings_Distribution\normality_models\motion_tubelets_v1_2_fast_stage3_pose\motion_tubelet_tracks_stage3_pose.jsonl" `
  --pose_model yolov8s-pose.pt --pose_imgsz 256 --pose_conf 0.25 `
  --ankle_conf_threshold 0.35 --fallback_mode freeze_last_valid --max_freeze_samples 12 `
  --device cuda --overwrite
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

LEFT_ANKLE = 15
RIGHT_ANKLE = 16


@dataclass
class TrackGroundState:
    last_xy: Optional[List[float]] = None
    last_sample_index: int = -10**9


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            obj["_jsonl_line_no"] = line_no
            yield obj


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def clamp_box_xyxy(box, w: int, h: int) -> List[float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    x1 = max(0.0, min(x1, w - 1.0))
    y1 = max(0.0, min(y1, h - 1.0))
    x2 = max(0.0, min(x2, w - 1.0))
    y2 = max(0.0, min(y2, h - 1.0))
    if x2 <= x1:
        x2 = min(w - 1.0, x1 + 1.0)
    if y2 <= y1:
        y2 = min(h - 1.0, y1 + 1.0)
    return [x1, y1, x2, y2]


def bbox_bottom_center(box: List[float]) -> List[float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    return [0.5 * (x1 + x2), y2]


def pad_box_xyxy(box, w: int, h: int, pad_ratio: float = 0.25, min_crop_size: int = 192) -> List[int]:
    x1, y1, x2, y2 = clamp_box_xyxy(box, w, h)
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    cx = 0.5 * (x1 + x2)
    cy = 0.5 * (y1 + y2)
    new_w = max(bw * (1.0 + 2.0 * pad_ratio), float(min_crop_size))
    new_h = max(bh * (1.0 + 2.0 * pad_ratio), float(min_crop_size))
    px1 = max(0.0, min(cx - new_w / 2.0, w - 1.0))
    py1 = max(0.0, min(cy - new_h / 2.0, h - 1.0))
    px2 = max(0.0, min(cx + new_w / 2.0, w - 1.0))
    py2 = max(0.0, min(cy + new_h / 2.0, h - 1.0))
    if px2 <= px1:
        px2 = min(w - 1.0, px1 + 1.0)
    if py2 <= py1:
        py2 = min(h - 1.0, py1 + 1.0)
    return [int(round(px1)), int(round(py1)), int(round(px2)), int(round(py2))]


def choose_best_pose_result(result):
    if result is None or getattr(result, "keypoints", None) is None:
        return None, None
    kpts = result.keypoints
    xy = getattr(kpts, "xy", None)
    conf = getattr(kpts, "conf", None)
    if xy is None:
        return None, None
    try:
        xy_np = xy.detach().cpu().numpy()
    except Exception:
        xy_np = np.asarray(xy)
    if conf is not None:
        try:
            conf_np = conf.detach().cpu().numpy()
        except Exception:
            conf_np = np.asarray(conf)
    else:
        conf_np = np.ones((xy_np.shape[0], xy_np.shape[1]), dtype=np.float32)
    if xy_np.ndim != 3 or xy_np.shape[0] == 0:
        return None, None
    scores = np.nanmean(conf_np, axis=1)
    best_idx = int(np.nanargmax(scores))
    best_xy = xy_np[best_idx].astype(np.float32)
    best_conf = conf_np[best_idx].astype(np.float32)
    if best_xy.shape[0] < 17:
        return None, None
    return best_xy[:17], best_conf[:17]


def estimate_groundpoint_pose_assisted(
    pose_model: YOLO,
    frame: np.ndarray,
    bbox_xyxy: List[float],
    track_state: TrackGroundState,
    sample_index: int,
    device: str,
    pose_imgsz: int,
    pose_conf: float,
    ankle_conf_threshold: float,
    pose_crop_pad_ratio: float,
    pose_min_crop_size: int,
    fallback_mode: str,
    max_freeze_samples: int,
) -> Tuple[List[float], Dict[str, Any]]:
    h, w = frame.shape[:2]
    bbox = clamp_box_xyxy(bbox_xyxy, w, h)
    bbox_ground = bbox_bottom_center(bbox)
    meta = {
        "ground_source": "bbox_bottom",
        "ground_conf": 0.0,
        "ground_frozen": False,
        "left_ankle_conf": 0.0,
        "right_ankle_conf": 0.0,
        "pose_used": False,
    }

    try:
        crop_box = pad_box_xyxy(bbox, w=w, h=h, pad_ratio=pose_crop_pad_ratio, min_crop_size=pose_min_crop_size)
        x1, y1, x2, y2 = crop_box
        crop = frame[y1:y2, x1:x2]
        if crop is not None and crop.size:
            results = pose_model.predict(source=[crop], imgsz=pose_imgsz, conf=pose_conf, device=device, verbose=False)
            xy_crop, kconf = choose_best_pose_result(results[0] if results else None)
            if xy_crop is not None and kconf is not None:
                xy_orig = xy_crop.copy()
                xy_orig[:, 0] += float(x1)
                xy_orig[:, 1] += float(y1)
                la_conf = float(kconf[LEFT_ANKLE])
                ra_conf = float(kconf[RIGHT_ANKLE])
                meta["left_ankle_conf"] = la_conf
                meta["right_ankle_conf"] = ra_conf
                valid_points = []
                confs = []
                if la_conf >= ankle_conf_threshold and np.isfinite(xy_orig[LEFT_ANKLE]).all():
                    valid_points.append(xy_orig[LEFT_ANKLE]); confs.append(la_conf)
                if ra_conf >= ankle_conf_threshold and np.isfinite(xy_orig[RIGHT_ANKLE]).all():
                    valid_points.append(xy_orig[RIGHT_ANKLE]); confs.append(ra_conf)
                if len(valid_points) >= 2:
                    gp = np.mean(np.vstack(valid_points), axis=0)
                    xy = [float(gp[0]), float(gp[1])]
                    track_state.last_xy = xy
                    track_state.last_sample_index = int(sample_index)
                    meta.update({"ground_source": "ankle_midpoint", "ground_conf": float(np.mean(confs)), "pose_used": True})
                    return xy, meta
                if len(valid_points) == 1:
                    gp = valid_points[0]
                    xy = [float(gp[0]), float(gp[1])]
                    track_state.last_xy = xy
                    track_state.last_sample_index = int(sample_index)
                    meta.update({"ground_source": "single_ankle", "ground_conf": float(confs[0]), "pose_used": True})
                    return xy, meta
    except Exception as e:
        meta["pose_error"] = str(e)[:200]

    if fallback_mode == "freeze_last_valid" and track_state.last_xy is not None:
        age = int(sample_index - track_state.last_sample_index)
        if age <= int(max_freeze_samples):
            meta.update({"ground_source": "freeze_last_valid", "ground_conf": 0.0, "ground_frozen": True, "freeze_age_samples": age})
            return list(track_state.last_xy), meta

    track_state.last_xy = bbox_ground
    track_state.last_sample_index = int(sample_index)
    return bbox_ground, meta


def first_existing(record: Dict[str, Any], names: List[str]) -> Optional[Any]:
    for name in names:
        if name in record:
            return record[name]
    return None


def choose_bboxes(record: Dict[str, Any]) -> List[List[float]]:
    bboxes = first_existing(record, [
        "bboxes_xyxy_clipped", "bboxes_xyxy", "boxes_xyxy_clipped", "boxes_xyxy",
        "bbox_xyxy_clipped", "bbox_xyxy", "sampled_bboxes_xyxy", "track_bboxes_xyxy",
    ])
    if bboxes is None:
        raise ValueError("No bbox list field found. Expected bboxes_xyxy/bboxes_xyxy_clipped/boxes_xyxy/etc.")
    arr = np.asarray(bboxes, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 4:
        raise ValueError(f"bbox field must be [N,4], got {arr.shape}")
    return arr.astype(float).tolist()


def choose_frame_indices(record: Dict[str, Any]) -> List[int]:
    frames = first_existing(record, ["source_frame_indices", "frame_indices", "sampled_frame_indices", "frames"])
    if frames is None:
        raise ValueError("No source_frame_indices/frame_indices field found")
    arr = np.asarray(frames, dtype=np.int64)
    if arr.ndim != 1:
        raise ValueError(f"frame indices must be 1D, got {arr.shape}")
    return [int(x) for x in arr.tolist()]


def record_key(record: Dict[str, Any]) -> Tuple[str, str]:
    return (str(record.get("video_id", record.get("video_path", ""))), str(record.get("track_id", "")))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Add Stage-3 pose-assisted ground points to motion_tubelet_tracks.jsonl")
    p.add_argument("--input_jsonl", required=True)
    p.add_argument("--output_jsonl", required=True)
    p.add_argument("--pose_model", default="yolov8s-pose.pt")
    p.add_argument("--device", default="cuda")
    p.add_argument("--pose_imgsz", type=int, default=256)
    p.add_argument("--pose_conf", type=float, default=0.25)
    p.add_argument("--ankle_conf_threshold", type=float, default=0.35)
    p.add_argument("--pose_crop_pad_ratio", type=float, default=0.25)
    p.add_argument("--pose_min_crop_size", type=int, default=192)
    p.add_argument("--fallback_mode", choices=["freeze_last_valid", "bbox_bottom"], default="freeze_last_valid")
    p.add_argument("--max_freeze_samples", type=int, default=12)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    inp = Path(args.input_jsonl)
    out = Path(args.output_jsonl)
    if not inp.exists():
        raise FileNotFoundError(inp)
    if out.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists. Use --overwrite: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    print(f"Loading pose model: {args.pose_model}")
    pose_model = YOLO(args.pose_model)

    caps: Dict[str, cv2.VideoCapture] = {}
    states: Dict[Tuple[str, str], TrackGroundState] = defaultdict(TrackGroundState)
    processed = 0
    failed = 0

    try:
        for record in read_jsonl(inp):
            if args.limit is not None and processed >= int(args.limit):
                break
            processed += 1
            clean = dict(record)
            clean.pop("_jsonl_line_no", None)
            try:
                video_path = str(record.get("video_path", ""))
                if not video_path:
                    raise ValueError("record missing video_path")
                if video_path not in caps:
                    cap = cv2.VideoCapture(video_path)
                    if not cap.isOpened():
                        raise RuntimeError(f"Could not open video_path: {video_path}")
                    caps[video_path] = cap
                cap = caps[video_path]

                frame_indices = choose_frame_indices(record)
                bboxes = choose_bboxes(record)
                if len(frame_indices) != len(bboxes):
                    raise ValueError(f"frame/bbox length mismatch: {len(frame_indices)} vs {len(bboxes)}")

                key = record_key(record)
                state = states[key]
                ground_points = []
                sources = []
                confs = []
                la_confs = []
                ra_confs = []
                frozen_flags = []

                for frame_idx, bbox in zip(frame_indices, bboxes):
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        # Keep a deterministic fallback if a single frame cannot be read.
                        gp = bbox_bottom_center(bbox)
                        meta = {"ground_source": "bbox_bottom_frame_read_failed", "ground_conf": 0.0, "ground_frozen": False, "left_ankle_conf": 0.0, "right_ankle_conf": 0.0}
                    else:
                        gp, meta = estimate_groundpoint_pose_assisted(
                            pose_model=pose_model,
                            frame=frame,
                            bbox_xyxy=bbox,
                            track_state=state,
                            sample_index=int(frame_idx),
                            device=str(args.device),
                            pose_imgsz=int(args.pose_imgsz),
                            pose_conf=float(args.pose_conf),
                            ankle_conf_threshold=float(args.ankle_conf_threshold),
                            pose_crop_pad_ratio=float(args.pose_crop_pad_ratio),
                            pose_min_crop_size=int(args.pose_min_crop_size),
                            fallback_mode=str(args.fallback_mode),
                            max_freeze_samples=int(args.max_freeze_samples),
                        )
                    ground_points.append([float(gp[0]), float(gp[1])])
                    sources.append(str(meta.get("ground_source", "unknown")))
                    confs.append(float(meta.get("ground_conf", 0.0)))
                    la_confs.append(float(meta.get("left_ankle_conf", 0.0)))
                    ra_confs.append(float(meta.get("right_ankle_conf", 0.0)))
                    frozen_flags.append(bool(meta.get("ground_frozen", False)))

                counts = Counter(sources)
                valid_pose = [s in {"ankle_midpoint", "single_ankle"} for s in sources]
                frozen = [s == "freeze_last_valid" for s in sources]
                bbox = [s.startswith("bbox") for s in sources]

                clean["ground_points_xy"] = ground_points
                clean["groundpoint_sources"] = sources
                clean["groundpoint_confs"] = confs
                clean["groundpoint_left_ankle_confs"] = la_confs
                clean["groundpoint_right_ankle_confs"] = ra_confs
                clean["groundpoint_valid_pose_ratio"] = float(np.mean(valid_pose)) if sources else 0.0
                clean["groundpoint_frozen_ratio"] = float(np.mean(frozen)) if sources else 0.0
                clean["groundpoint_bbox_fallback_ratio"] = float(np.mean(bbox)) if sources else 0.0
                clean["groundpoint_source_counts"] = dict(counts)
                clean["groundpoint_policy"] = {
                    "pose_model": str(args.pose_model),
                    "pose_imgsz": int(args.pose_imgsz),
                    "pose_conf": float(args.pose_conf),
                    "ankle_conf_threshold": float(args.ankle_conf_threshold),
                    "fallback_mode": str(args.fallback_mode),
                    "max_freeze_samples": int(args.max_freeze_samples),
                }
                write_jsonl(out, clean)
            except Exception as e:
                failed += 1
                clean["groundpoint_error"] = f"{type(e).__name__}: {e}"
                write_jsonl(out, clean)
                print(f"WARNING line {record.get('_jsonl_line_no')}: {clean['groundpoint_error']}")

            if processed % 100 == 0:
                print(f"Processed {processed} tubelets | failed={failed}")
    finally:
        for cap in caps.values():
            cap.release()

    print(f"Done. processed={processed} failed={failed} output={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
