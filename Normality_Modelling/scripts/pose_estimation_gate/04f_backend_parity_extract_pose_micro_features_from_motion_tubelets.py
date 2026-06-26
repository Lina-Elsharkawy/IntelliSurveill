#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
04f_backend_parity_extract_pose_micro_features_from_motion_tubelets.py

Backend-parity offline Pose feature extraction.

Purpose
-------
Use the DEPLOYMENT pose feature logic from backend/vad/pose_features.py
as the source of truth for offline normal-distribution rebuilding and
anomaly-dataset evaluation.

This script reads motion_tubelet_tracks.jsonl produced by the live-parity
04a extractor / dual extractor, reopens exact source frames, reconstructs
backend-like SampledPerson tubelets, and calls the same deployment-style
make_pose_feature_from_tubelet() logic.

Outputs are compatible with:
  04g_build_pose_micro_gmm_gate.py
  evaluate_pose_gate_on_anomaly_dataset.py

Key parity choices
------------------
- Feature names/order: exactly deployment POSE_FEATURE_NAMES, 30 features.
- Pose re-inference: YOLOv8s-pose on tracked person crop.
- Pose candidate selection: expected-box IoU + center distance + confidence.
- BBox normalization: deployment V7 smoothed center/dimensions normalization.
- Default time_mode: sample.
- Default FPS used in features: 5.0, matching deployment pose_route_fps.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np
import pandas as pd
from tqdm import tqdm

try:
    from ultralytics import YOLO
except Exception as e:
    raise RuntimeError(
        "Could not import ultralytics. Install it with:\n"
        "  pip install ultralytics\n"
        f"Original error: {e}"
    )


@dataclass
class SampledPerson:
    """Minimal backend-compatible SampledPerson for offline feature extraction."""
    frame_id: int
    detection_id: int | None
    db_track_id: int | None
    tracker_track_id: int
    sample_index: int
    captured_at: datetime
    frame_bgr: np.ndarray
    bbox_xyxy: list[float]
    confidence: float | None
    keypoints_xy: list[list[float]] = field(default_factory=list)
    keypoints_conf: list[float] = field(default_factory=list)


# -------------------------------------------------------------------------
# Embedded deployment pose_features.py logic
# -------------------------------------------------------------------------

import math
from typing import Any, Sequence

import cv2
import numpy as np


POSE_FEATURE_NAMES = [
    "pose_valid_frame_ratio",
    "pose_mean_keypoint_conf",
    "pose_valid_keypoint_ratio_mean",
    "pose_wrist_speed_mean",
    "pose_wrist_speed_p95",
    "pose_wrist_speed_max",
    "pose_ankle_speed_mean",
    "pose_ankle_speed_p95",
    "pose_ankle_speed_max",
    "pose_limb_speed_mean",
    "pose_limb_speed_p95",
    "pose_limb_speed_max",
    "pose_limb_accel_mean",
    "pose_limb_accel_p95",
    "pose_limb_accel_max",
    "pose_torso_center_speed_mean",
    "pose_torso_center_speed_p95",
    "pose_torso_center_speed_max",
    "pose_body_angle_change_mean",
    "pose_body_angle_change_p95",
    "pose_body_angle_change_max",
    "pose_crouch_change_mean",
    "pose_crouch_change_p95",
    "pose_crouch_change_max",
    "pose_arm_extension_change_mean",
    "pose_arm_extension_change_p95",
    "pose_arm_extension_change_max",
    "pose_asymmetry_motion_mean",
    "pose_asymmetry_motion_p95",
    "pose_asymmetry_motion_max",
]

# COCO17 indices
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_ELBOW, RIGHT_ELBOW = 7, 8
LEFT_WRIST, RIGHT_WRIST = 9, 10
LEFT_HIP, RIGHT_HIP = 11, 12
LEFT_KNEE, RIGHT_KNEE = 13, 14
LEFT_ANKLE, RIGHT_ANKLE = 15, 16

WRISTS = [LEFT_WRIST, RIGHT_WRIST]
ANKLES = [LEFT_ANKLE, RIGHT_ANKLE]
LIMBS = [LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST, LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE]
LEFT_LIMBS = [LEFT_ELBOW, LEFT_WRIST, LEFT_KNEE, LEFT_ANKLE]
RIGHT_LIMBS = [RIGHT_ELBOW, RIGHT_WRIST, RIGHT_KNEE, RIGHT_ANKLE]
TORSO_POINTS = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]


def _safe_stats(values: Sequence[float]) -> tuple[float, float, float]:
    arr = np.asarray([v for v in values if np.isfinite(v)], dtype=np.float64)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    return float(np.mean(arr)), float(np.percentile(arr, 95)), float(np.max(arr))


def _clip_bbox_xyxy(box: Sequence[float], w: int, h: int) -> list[float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    x1 = max(0.0, min(x1, w - 1.0)); y1 = max(0.0, min(y1, h - 1.0))
    x2 = max(0.0, min(x2, w - 1.0)); y2 = max(0.0, min(y2, h - 1.0))
    if x2 <= x1: x2 = min(w - 1.0, x1 + 1.0)
    if y2 <= y1: y2 = min(h - 1.0, y1 + 1.0)
    return [x1, y1, x2, y2]


def _pad_box_xyxy(box: Sequence[float], w: int, h: int, pad_ratio: float = 0.25, min_crop_size: int = 192) -> list[int]:
    x1, y1, x2, y2 = _clip_bbox_xyxy(box, w, h)
    bw = max(1.0, x2 - x1); bh = max(1.0, y2 - y1)
    cx = 0.5 * (x1 + x2); cy = 0.5 * (y1 + y2)
    new_w = max(bw * (1.0 + 2.0 * float(pad_ratio)), float(min_crop_size))
    new_h = max(bh * (1.0 + 2.0 * float(pad_ratio)), float(min_crop_size))
    px1 = max(0.0, min(cx - new_w / 2.0, w - 1.0))
    py1 = max(0.0, min(cy - new_h / 2.0, h - 1.0))
    px2 = max(0.0, min(cx + new_w / 2.0, w - 1.0))
    py2 = max(0.0, min(cy + new_h / 2.0, h - 1.0))
    if px2 <= px1: px2 = min(w - 1.0, px1 + 1.0)
    if py2 <= py1: py2 = min(h - 1.0, py1 + 1.0)
    return [int(round(px1)), int(round(py1)), int(round(px2)), int(round(py2))]


def _invalid_pose_arrays() -> tuple[np.ndarray, np.ndarray]:
    """Return an invalid COCO17 pose."""
    return np.full((17, 2), np.nan, dtype=np.float64), np.zeros((17,), dtype=np.float64)


def _candidate_pose_box(xy: np.ndarray, conf: np.ndarray | None = None, *, conf_thr: float = 0.05) -> tuple[np.ndarray | None, float]:
    """Approximate a detected pose box from finite/confident keypoints."""
    arr = np.asarray(xy, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] < 17 or arr.shape[1] < 2:
        return None, 0.0
    finite = np.isfinite(arr[:, 0]) & np.isfinite(arr[:, 1])
    if conf is not None:
        c = np.asarray(conf, dtype=np.float64)
        if c.ndim == 1 and c.shape[0] >= 17:
            finite = finite & np.isfinite(c[:17]) & (c[:17] >= float(conf_thr))
    pts = arr[:17][finite[:17]]
    if pts.shape[0] < 3:
        return None, float(pts.shape[0]) / 17.0
    x1, y1 = np.nanmin(pts[:, 0]), np.nanmin(pts[:, 1])
    x2, y2 = np.nanmax(pts[:, 0]), np.nanmax(pts[:, 1])
    if not np.all(np.isfinite([x1, y1, x2, y2])) or x2 <= x1 or y2 <= y1:
        return None, float(pts.shape[0]) / 17.0
    return np.asarray([x1, y1, x2, y2], dtype=np.float64), float(pts.shape[0]) / 17.0


def _box_center(box: Sequence[float]) -> np.ndarray:
    x1, y1, x2, y2 = [float(v) for v in box]
    return np.asarray([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float64)


def _box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(1e-6, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1e-6, (bx2 - bx1) * (by2 - by1))
    return float(inter / max(1e-6, area_a + area_b - inter))


def _choose_best_pose_result(
    result: Any,
    expected_box_xyxy: Sequence[float] | None = None,
) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, Any]]:
    """Choose the pose candidate that belongs to the tracked crop."""
    meta: dict[str, Any] = {
        "pose_candidate_count": 0,
        "pose_selection_policy": "expected_box_iou_center_conf" if expected_box_xyxy is not None else "mean_conf",
    }
    if result is None or getattr(result, "keypoints", None) is None:
        return None, None, meta
    kpts = result.keypoints
    xy = getattr(kpts, "xy", None)
    conf = getattr(kpts, "conf", None)
    if xy is None:
        return None, None, meta
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
    if xy_np.ndim != 3 or xy_np.shape[0] == 0 or xy_np.shape[1] < 17:
        return None, None, meta

    n = int(xy_np.shape[0])
    meta["pose_candidate_count"] = n
    mean_conf = np.nanmean(conf_np[:, :17], axis=1)

    if expected_box_xyxy is None:
        best_idx = int(np.nanargmax(mean_conf))
        meta.update({"selected_pose_index": best_idx, "selected_pose_mean_conf": float(mean_conf[best_idx])})
        return xy_np[best_idx, :17, :2].astype(np.float64), conf_np[best_idx, :17].astype(np.float64), meta

    exp = np.asarray(expected_box_xyxy, dtype=np.float64)
    exp_center = _box_center(exp)
    exp_w = max(1.0, float(exp[2] - exp[0]))
    exp_h = max(1.0, float(exp[3] - exp[1]))
    exp_diag = max(1.0, math.sqrt(exp_w * exp_w + exp_h * exp_h))

    best_idx: int | None = None
    best_score = -1e18
    best_diag: dict[str, Any] = {}
    for i in range(n):
        cand_xy = xy_np[i, :17, :2]
        cand_conf = conf_np[i, :17] if conf_np is not None and i < len(conf_np) else None
        pbox, valid_ratio = _candidate_pose_box(cand_xy, cand_conf)
        cmean = float(mean_conf[i]) if np.isfinite(mean_conf[i]) else 0.0
        if pbox is None:
            score = -10.0 + cmean
            dist_norm = float("inf")
            iou = 0.0
        else:
            dist_norm = float(np.linalg.norm(_box_center(pbox) - exp_center) / exp_diag)
            iou = _box_iou(pbox, exp)
            score = (3.0 * iou) - (2.0 * dist_norm) + (0.5 * cmean) + (0.25 * valid_ratio)
        if score > best_score:
            best_score = float(score)
            best_idx = int(i)
            best_diag = {
                "selected_pose_score": float(score),
                "selected_pose_center_distance_norm": float(dist_norm),
                "selected_pose_iou_with_tracker_box": float(iou),
                "selected_pose_mean_conf": float(cmean),
                "selected_pose_keypoint_valid_ratio_loose": float(valid_ratio),
            }

    if best_idx is None:
        return None, None, meta

    best_iou = float(best_diag.get("selected_pose_iou_with_tracker_box", 0.0))
    if best_iou < 0.20:
        meta.update({"pose_rejected_due_to_low_iou": best_iou})
        return None, None, meta
    meta.update({"selected_pose_index": int(best_idx), **best_diag})
    return xy_np[best_idx, :17, :2].astype(np.float64), conf_np[best_idx, :17].astype(np.float64), meta


def _as_pose_arrays_from_sample(sample: SampledPerson) -> tuple[np.ndarray, np.ndarray]:
    xy = np.asarray(sample.keypoints_xy or [], dtype=np.float64)
    conf = np.asarray(sample.keypoints_conf or [], dtype=np.float64)
    if xy.ndim != 2 or xy.shape[0] < 17 or xy.shape[1] < 2:
        xy = np.full((17, 2), np.nan, dtype=np.float64)
    else:
        xy = xy[:17, :2]
    if conf.ndim != 1 or conf.shape[0] < 17:
        conf = np.zeros((17,), dtype=np.float64)
    else:
        conf = conf[:17]
    return xy, conf


def _as_pose_arrays(
    sample: SampledPerson,
    *,
    pose_model: Any | None = None,
    pose_imgsz: int = 256,
    pose_conf: float = 0.25,
    pose_crop_pad_ratio: float = 0.25,
    pose_min_crop_size: int = 192,
    device: str = "cuda",
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if pose_model is None:
        xy, conf = _as_pose_arrays_from_sample(sample)
        return xy, conf, {"pose_source": "tracker_keypoints"}

    h, w = sample.frame_bgr.shape[:2]
    x1, y1, x2, y2 = _pad_box_xyxy(sample.bbox_xyxy, w, h, pose_crop_pad_ratio, pose_min_crop_size)
    crop = sample.frame_bgr[y1:y2, x1:x2]
    pose_crop_box = [x1, y1, x2, y2]

    if crop is None or crop.size == 0:
        xy, conf = _invalid_pose_arrays()
        return xy, conf, {"pose_source": "crop_empty_invalid", "pose_crop_box": pose_crop_box}

    bx1, by1, bx2, by2 = _clip_bbox_xyxy(sample.bbox_xyxy, w, h)
    expected_crop_box = [
        max(0.0, float(bx1) - float(x1)),
        max(0.0, float(by1) - float(y1)),
        max(1.0, float(bx2) - float(x1)),
        max(1.0, float(by2) - float(y1)),
    ]

    try:
        results = pose_model.predict(source=[crop], imgsz=int(pose_imgsz), conf=float(pose_conf), device=device, verbose=False)
        xy_crop, conf, select_meta = _choose_best_pose_result(results[0] if results else None, expected_box_xyxy=expected_crop_box)
        if xy_crop is None or conf is None:
            xy, conf0 = _invalid_pose_arrays()
            return xy, conf0, {
                "pose_source": "crop_pose_empty_invalid",
                "pose_crop_box": pose_crop_box,
                "expected_crop_box": expected_crop_box,
                **select_meta,
            }
        xy = xy_crop.copy()
        xy[:, 0] += float(x1)
        xy[:, 1] += float(y1)
        return xy, conf, {
            "pose_source": "crop_pose_model_spatial",
            "pose_crop_box": pose_crop_box,
            "expected_crop_box": expected_crop_box,
            **select_meta,
        }
    except Exception as e:
        xy, conf = _invalid_pose_arrays()
        return xy, conf, {
            "pose_source": "crop_pose_error_invalid",
            "pose_error": str(e)[:200],
            "pose_crop_box": pose_crop_box,
            "expected_crop_box": expected_crop_box,
        }


def _normalize_keypoints_to_bbox(xy: np.ndarray, bbox_xyxy: Sequence[float], frame_shape: tuple[int, int]) -> np.ndarray:
    h, w = frame_shape
    bx1, by1, bx2, by2 = _clip_bbox_xyxy(bbox_xyxy, w, h)
    bw = max(1.0, bx2 - bx1)
    bh = max(1.0, by2 - by1)
    out = np.full((17, 2), np.nan, dtype=np.float32)
    arr = np.asarray(xy, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[0] >= 17 and arr.shape[1] >= 2:
        out[:, 0] = ((arr[:17, 0] - float(bx1)) / float(bw)).astype(np.float32)
        out[:, 1] = ((arr[:17, 1] - float(by1)) / float(bh)).astype(np.float32)
    return out


def _angle_wrap(delta: float) -> float:
    return (delta + math.pi) % (2 * math.pi) - math.pi


def _center_of(kpts: np.ndarray, valid: np.ndarray, ids: Sequence[int]) -> np.ndarray | None:
    pts = [kpts[i] for i in ids if valid[i]]
    if not pts:
        return None
    return np.mean(np.asarray(pts, dtype=np.float64), axis=0)


def _point_speed_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray, ids: Sequence[int]) -> list[float]:
    speeds: list[float] = []
    for t in range(1, len(times)):
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        for k in ids:
            if valid[t, k] and valid[t - 1, k]:
                d = np.linalg.norm(kpts_norm[t, k] - kpts_norm[t - 1, k])
                if math.isfinite(float(d)):
                    speeds.append(float(d / dt))
    return speeds


def _point_accel_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray, ids: Sequence[int]) -> list[float]:
    accels: list[float] = []
    per_key_speeds: dict[int, list[tuple[int, float]]] = {int(k): [] for k in ids}
    for k in ids:
        for t in range(1, len(times)):
            dt = float(times[t] - times[t - 1])
            if dt <= 1e-6:
                continue
            if valid[t, k] and valid[t - 1, k]:
                d = np.linalg.norm(kpts_norm[t, k] - kpts_norm[t - 1, k])
                if math.isfinite(float(d)):
                    per_key_speeds[int(k)].append((t, float(d / dt)))
    for vals in per_key_speeds.values():
        for i in range(1, len(vals)):
            t_prev, s_prev = vals[i - 1]
            t_cur, s_cur = vals[i]
            dt = float(times[t_cur] - times[t_prev])
            if dt <= 1e-6:
                continue
            a = abs(s_cur - s_prev) / dt
            if math.isfinite(float(a)):
                accels.append(float(a))
    return accels


def _torso_center_speed_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray) -> list[float]:
    centers: list[np.ndarray | None] = []
    for t in range(len(times)):
        shoulder = _center_of(kpts_norm[t], valid[t], [LEFT_SHOULDER, RIGHT_SHOULDER])
        hip = _center_of(kpts_norm[t], valid[t], [LEFT_HIP, RIGHT_HIP])
        centers.append(None if shoulder is None or hip is None else (shoulder + hip) / 2.0)
    speeds: list[float] = []
    for t in range(1, len(times)):
        if centers[t] is None or centers[t - 1] is None:
            continue
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        d = np.linalg.norm(centers[t] - centers[t - 1])
        if math.isfinite(float(d)):
            speeds.append(float(d / dt))
    return speeds


def _body_angle_change_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray) -> list[float]:
    angles: list[float | None] = []
    for t in range(len(times)):
        shoulder = _center_of(kpts_norm[t], valid[t], [LEFT_SHOULDER, RIGHT_SHOULDER])
        hip = _center_of(kpts_norm[t], valid[t], [LEFT_HIP, RIGHT_HIP])
        if shoulder is None or hip is None:
            angles.append(None)
        else:
            vec = shoulder - hip
            angles.append(math.atan2(float(vec[1]), float(vec[0])))
    changes: list[float] = []
    for t in range(1, len(times)):
        if angles[t] is None or angles[t - 1] is None:
            continue
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        changes.append(float(abs(_angle_wrap(float(angles[t]) - float(angles[t - 1]))) / dt))
    return changes


def _crouch_change_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray) -> list[float]:
    values: list[float | None] = []
    for t in range(len(times)):
        shoulder = _center_of(kpts_norm[t], valid[t], [LEFT_SHOULDER, RIGHT_SHOULDER])
        hip = _center_of(kpts_norm[t], valid[t], [LEFT_HIP, RIGHT_HIP])
        values.append(None if shoulder is None or hip is None else abs(float(hip[1] - shoulder[1])))
    changes: list[float] = []
    for t in range(1, len(times)):
        if values[t] is None or values[t - 1] is None:
            continue
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        changes.append(float(abs(float(values[t]) - float(values[t - 1])) / dt))
    return changes


def _arm_extension_change_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray) -> list[float]:
    values: list[float | None] = []
    pairs = [(LEFT_SHOULDER, LEFT_WRIST), (RIGHT_SHOULDER, RIGHT_WRIST)]
    for t in range(len(times)):
        frame_vals: list[float] = []
        for a, b in pairs:
            if valid[t, a] and valid[t, b]:
                d = np.linalg.norm(kpts_norm[t, a] - kpts_norm[t, b])
                if math.isfinite(float(d)):
                    frame_vals.append(float(d))
        values.append(float(np.mean(frame_vals)) if frame_vals else None)
    changes: list[float] = []
    for t in range(1, len(times)):
        if values[t] is None or values[t - 1] is None:
            continue
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        changes.append(float(abs(float(values[t]) - float(values[t - 1])) / dt))
    return changes


def _asymmetry_motion_series(kpts_norm: np.ndarray, valid: np.ndarray, times: np.ndarray) -> list[float]:
    values: list[float] = []
    for t in range(1, len(times)):
        dt = float(times[t] - times[t - 1])
        if dt <= 1e-6:
            continue
        left_speeds: list[float] = []
        right_speeds: list[float] = []
        for k in LEFT_LIMBS:
            if valid[t, k] and valid[t - 1, k]:
                d = np.linalg.norm(kpts_norm[t, k] - kpts_norm[t - 1, k])
                if math.isfinite(float(d)):
                    left_speeds.append(float(d / dt))
        for k in RIGHT_LIMBS:
            if valid[t, k] and valid[t - 1, k]:
                d = np.linalg.norm(kpts_norm[t, k] - kpts_norm[t - 1, k])
                if math.isfinite(float(d)):
                    right_speeds.append(float(d / dt))
        if left_speeds and right_speeds:
            values.append(abs(float(np.mean(left_speeds)) - float(np.mean(right_speeds))))
    return values


def make_pose_feature_from_tubelet(
    tubelet: Sequence[SampledPerson],
    *,
    kpt_conf: float = 0.30,
    fps: float = 5.0,
    time_mode: str = "sample",
    pose_model: Any | None = None,
    pose_imgsz: int = 256,
    pose_conf: float = 0.25,
    pose_crop_pad_ratio: float = 0.25,
    pose_min_crop_size: int = 192,
    device: str = "cuda",
) -> tuple[np.ndarray, dict[str, Any]]:
    n = len(tubelet)
    if n == 0:
        return np.zeros((30,), dtype=np.float32), {"error": "empty_tubelet"}

    kpts_norm = np.full((n, 17, 2), np.nan, dtype=np.float32)
    conf_arr = np.zeros((n, 17), dtype=np.float32)
    times: list[float] = []
    pose_sources: list[str] = []
    pose_source_meta: list[dict[str, Any]] = []

    use_sample_time = str(time_mode or "sample").lower().strip() == "sample"

    tubelet_bws: list[float] = []
    tubelet_bhs: list[float] = []
    raw_centers: list[tuple[float, float]] = []
    areas: list[float] = []
    for s in tubelet:
        h, w = s.frame_bgr.shape[:2]
        bx1, by1, bx2, by2 = _clip_bbox_xyxy(s.bbox_xyxy, w, h)
        bw = max(1.0, float(bx2 - bx1))
        bh = max(1.0, float(by2 - by1))
        cx = float(bx1 + bw / 2.0)
        cy = float(by1 + bh / 2.0)
        tubelet_bws.append(bw)
        tubelet_bhs.append(bh)
        raw_centers.append((cx, cy))
        areas.append(float(bw * bh))

    med_bw = float(np.median(tubelet_bws)) if tubelet_bws else 1.0
    med_bh = float(np.median(tubelet_bhs)) if tubelet_bhs else 1.0
    bw_cv = float(np.std(tubelet_bws) / max(1e-6, float(np.mean(tubelet_bws)))) if tubelet_bws else 0.0
    bh_cv = float(np.std(tubelet_bhs) / max(1e-6, float(np.mean(tubelet_bhs)))) if tubelet_bhs else 0.0

    # --- SURGICAL PATCH V7: Sliding Window for Centers AND Dimensions ---
    smoothed_centers: list[tuple[float, float]] = []
    smoothed_bws: list[float] = []
    smoothed_bhs: list[float] = []
    
    center_smooth_window = 5
    half_w = center_smooth_window // 2
    
    for j in range(n):
        start_idx = max(0, j - half_w)
        end_idx = min(n, j + half_w + 1)
        
        # Smooth the centers
        cx_window = [c[0] for c in raw_centers[start_idx:end_idx]]
        cy_window = [c[1] for c in raw_centers[start_idx:end_idx]]
        smoothed_centers.append((float(np.median(cx_window)), float(np.median(cy_window))))
        
        # Smooth the widths and heights (restores depth invariance)
        bw_window = tubelet_bws[start_idx:end_idx]
        bh_window = tubelet_bhs[start_idx:end_idx]
        smoothed_bws.append(float(np.median(bw_window)))
        smoothed_bhs.append(float(np.median(bh_window)))

    raw_center_jitter: list[float] = []
    smoothed_center_jitter: list[float] = []
    size_jitter_rel: list[float] = []
    
    for j in range(1, n):
        dx_raw = float(raw_centers[j][0] - raw_centers[j - 1][0])
        dy_raw = float(raw_centers[j][1] - raw_centers[j - 1][1])
        raw_center_jitter.append(float(math.sqrt(dx_raw * dx_raw + dy_raw * dy_raw)))

        dx_sm = float(smoothed_centers[j][0] - smoothed_centers[j - 1][0])
        dy_sm = float(smoothed_centers[j][1] - smoothed_centers[j - 1][1])
        smoothed_center_jitter.append(float(math.sqrt(dx_sm * dx_sm + dy_sm * dy_sm)))

        prev_area = max(1e-6, float(areas[j - 1]))
        size_jitter_rel.append(float(abs(float(areas[j]) - float(areas[j - 1])) / prev_area))

    bbox_center_jitter_raw_p95 = float(np.percentile(raw_center_jitter, 95)) if raw_center_jitter else 0.0
    bbox_center_jitter_smoothed_p95 = float(np.percentile(smoothed_center_jitter, 95)) if smoothed_center_jitter else 0.0
    bbox_size_jitter_relative_p95 = float(np.percentile(size_jitter_rel, 95)) if size_jitter_rel else 0.0

    for i, s in enumerate(tubelet):
        xy, conf, src_meta = _as_pose_arrays(
            s,
            pose_model=pose_model,
            pose_imgsz=pose_imgsz,
            pose_conf=pose_conf,
            pose_crop_pad_ratio=pose_crop_pad_ratio,
            pose_min_crop_size=pose_min_crop_size,
            device=device,
        )
        h, w = s.frame_bgr.shape[:2]
        
        # Apply fully smoothed dynamic box
        cx, cy = smoothed_centers[i]
        bw = smoothed_bws[i]
        bh = smoothed_bhs[i]
        
        stable_bbox = [
            cx - bw / 2.0,
            cy - bh / 2.0,
            cx + bw / 2.0,
            cy + bh / 2.0,
        ]
        kpts_norm[i] = _normalize_keypoints_to_bbox(xy, stable_bbox, (h, w))
        
        conf_arr[i] = np.asarray(conf[:17], dtype=np.float32) if len(conf) >= 17 else np.zeros((17,), dtype=np.float32)
        if use_sample_time:
           times.append(float(getattr(s, "sample_index", i)) / max(float(fps), 1e-6))
        else:
           times.append(float(s.captured_at.timestamp()))
        pose_sources.append(str(src_meta.get("pose_source", "unknown")))
        pose_source_meta.append(src_meta)

    times_arr = np.asarray(times, dtype=np.float64)
    finite_xy = np.isfinite(kpts_norm).all(axis=2)
    valid = finite_xy & np.isfinite(conf_arr) & (conf_arr >= float(kpt_conf))

    valid_frame = valid.sum(axis=1) >= 5
    valid_frame_ratio = float(valid_frame.mean()) if n else 0.0
    valid_confs = conf_arr[valid]
    mean_conf = float(np.mean(valid_confs)) if valid_confs.size else 0.0
    valid_kpt_ratio_mean = float(np.mean(valid.mean(axis=1))) if n else 0.0

    wrist_speeds = _point_speed_series(kpts_norm, valid, times_arr, WRISTS)
    ankle_speeds = _point_speed_series(kpts_norm, valid, times_arr, ANKLES)
    limb_speeds = _point_speed_series(kpts_norm, valid, times_arr, LIMBS)
    limb_accels = _point_accel_series(kpts_norm, valid, times_arr, LIMBS)
    torso_speeds = _torso_center_speed_series(kpts_norm, valid, times_arr)
    angle_changes = _body_angle_change_series(kpts_norm, valid, times_arr)
    crouch_changes = _crouch_change_series(kpts_norm, valid, times_arr)
    arm_ext_changes = _arm_extension_change_series(kpts_norm, valid, times_arr)
    asymmetry_values = _asymmetry_motion_series(kpts_norm, valid, times_arr)

    ws_mean, ws_p95, ws_max = _safe_stats(wrist_speeds)
    as_mean, as_p95, as_max = _safe_stats(ankle_speeds)
    ls_mean, ls_p95, ls_max = _safe_stats(limb_speeds)
    la_mean, la_p95, la_max = _safe_stats(limb_accels)
    tc_mean, tc_p95, tc_max = _safe_stats(torso_speeds)
    ba_mean, ba_p95, ba_max = _safe_stats(angle_changes)
    cr_mean, cr_p95, cr_max = _safe_stats(crouch_changes)
    ae_mean, ae_p95, ae_max = _safe_stats(arm_ext_changes)
    sy_mean, sy_p95, sy_max = _safe_stats(asymmetry_values)

    feature = np.asarray([
        valid_frame_ratio, mean_conf, valid_kpt_ratio_mean,
        ws_mean, ws_p95, ws_max,
        as_mean, as_p95, as_max,
        ls_mean, ls_p95, ls_max,
        la_mean, la_p95, la_max,
        tc_mean, tc_p95, tc_max,
        ba_mean, ba_p95, ba_max,
        cr_mean, cr_p95, cr_max,
        ae_mean, ae_p95, ae_max,
        sy_mean, sy_p95, sy_max,
    ], dtype=np.float32)
    feature = np.nan_to_num(feature, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    values = {name: float(feature[i]) for i, name in enumerate(POSE_FEATURE_NAMES)}
    meta = {
        "feature_names": POSE_FEATURE_NAMES,
        "feature_values": values,
        "tubelet_sample_count": n,
        "pose_valid_frames": int(valid_frame.sum()),
        "pose_total_frames": int(n),
        "pose_valid_frame_ratio": float(valid_frame_ratio),
        "pose_mean_keypoint_conf": float(mean_conf),
        "pose_valid_keypoint_ratio_mean": float(valid_kpt_ratio_mean),
        "kpt_conf": float(kpt_conf),
        "fps": float(fps),
        "time_mode": str(time_mode),
        "coordinate_space": "bbox_normalized_xy",
        "normalization_mode": "tubelet_median_wh_smoothed_center_v7_dynamic",
        "median_bbox_width": float(med_bw),
        "median_bbox_height": float(med_bh),
        "bbox_width_cv": float(bw_cv),
        "bbox_height_cv": float(bh_cv),
        "bbox_center_smooth_window": int(center_smooth_window),
        "bbox_center_jitter_raw_p95": float(bbox_center_jitter_raw_p95),
        "bbox_center_jitter_smoothed_p95": float(bbox_center_jitter_smoothed_p95),
        "bbox_center_jitter_p95": float(bbox_center_jitter_smoothed_p95),
        "bbox_size_jitter_relative_p95": float(bbox_size_jitter_relative_p95),
        "pose_sources": pose_sources,
        "pose_source_counts": {src: int(pose_sources.count(src)) for src in sorted(set(pose_sources))},
        "pose_source_meta": pose_source_meta,
    }
    return feature, meta
# -------------------------------------------------------------------------
# Offline extraction wrapper
# -------------------------------------------------------------------------


class FrameCache:
    def __init__(self, max_size: int = 512):
        self.max_size = int(max_size)
        self.cache: OrderedDict[tuple[str, int], np.ndarray] = OrderedDict()

    def get(self, key: tuple[str, int]) -> np.ndarray | None:
        if key not in self.cache:
            return None
        value = self.cache.pop(key)
        self.cache[key] = value
        return value.copy()

    def put(self, key: tuple[str, int], frame: np.ndarray) -> None:
        if key in self.cache:
            self.cache.pop(key)
        self.cache[key] = frame.copy()
        while len(self.cache) > self.max_size:
            self.cache.popitem(last=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backend-parity offline Pose micro-feature extraction from motion tubelets."
    )

    p.add_argument("--tracks_jsonl", required=True, type=Path)
    p.add_argument("--output_dir", required=True, type=Path)

    p.add_argument("--pose_model", default="yolov8s-pose.pt")
    p.add_argument("--device", default="cuda")
    p.add_argument("--imgsz", type=int, default=256)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--kpt_conf", type=float, default=0.30)
    p.add_argument("--crop_pad_ratio", type=float, default=0.25)
    p.add_argument("--min_crop_size", type=int, default=192)
    p.add_argument("--pose_time_mode", default="sample", choices=["sample", "timestamp"])

    # Deployment Pose route config
    p.add_argument("--expected_sample_fps", type=float, default=5.0)
    p.add_argument("--expected_tubelet_frames", type=int, default=24)
    p.add_argument("--expected_stride", type=int, default=6)
    p.add_argument("--fps_tolerance", type=float, default=0.30)
    p.add_argument("--skip_config_validation", action="store_true")

    # For dual extractor outputs, keep only the Pose records.
    p.add_argument("--gate_name", default="pose", help="Filter records by gate_name if present. Use empty string to disable.")

    p.add_argument("--frame_cache_size", type=int, default=512)
    p.add_argument("--limit_tubelets", type=int, default=None)
    p.add_argument("--limit_videos", type=int, default=None)
    p.add_argument("--max_tubelets_per_video", type=int, default=None)
    p.add_argument("--no_progress", action="store_true")
    p.add_argument("--overwrite", action="store_true")

    return p.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def xywh_to_xyxy(box: Sequence[float]) -> list[float]:
    x, y, w, h = [float(v) for v in box]
    return [x, y, x + w, y + h]


def get_bboxes_xyxy(record: dict[str, Any]) -> list[list[float]]:
    if isinstance(record.get("bboxes_xyxy_clipped"), list) and record["bboxes_xyxy_clipped"]:
        return [[float(v) for v in b] for b in record["bboxes_xyxy_clipped"]]
    if isinstance(record.get("bboxes_xyxy"), list) and record["bboxes_xyxy"]:
        return [[float(v) for v in b] for b in record["bboxes_xyxy"]]
    if isinstance(record.get("bboxes_xywh_clipped"), list) and record["bboxes_xywh_clipped"]:
        return [xywh_to_xyxy(b) for b in record["bboxes_xywh_clipped"]]
    if isinstance(record.get("bboxes_xywh"), list) and record["bboxes_xywh"]:
        return [xywh_to_xyxy(b) for b in record["bboxes_xywh"]]
    raise ValueError("Tubelet record has no usable bbox sequence.")


def validate_record(record: dict[str, Any], args: argparse.Namespace) -> list[str]:
    if args.skip_config_validation:
        return []

    problems: list[str] = []

    if int(record.get("tubelet_frames", -1)) != int(args.expected_tubelet_frames):
        problems.append(f"tubelet_frames={record.get('tubelet_frames')} expected={args.expected_tubelet_frames}")

    if int(record.get("stride", -1)) != int(args.expected_stride):
        problems.append(f"stride={record.get('stride')} expected={args.expected_stride}")

    sfps = safe_float(record.get("sample_fps"), default=float("nan"))
    if math.isfinite(sfps) and abs(sfps - float(args.expected_sample_fps)) > 1e-6:
        problems.append(f"sample_fps={sfps} expected={args.expected_sample_fps}")

    eff = safe_float(record.get("effective_sample_fps"), default=float("nan"))
    if math.isfinite(eff) and abs(eff - float(args.expected_sample_fps)) > float(args.fps_tolerance):
        problems.append(
            f"effective_sample_fps={eff:.6f} expected≈{args.expected_sample_fps} tolerance={args.fps_tolerance}"
        )

    sample_indices = record.get("sample_indices") or []
    if len(sample_indices) == int(args.expected_tubelet_frames):
        gaps = [int(sample_indices[i]) - int(sample_indices[i - 1]) for i in range(1, len(sample_indices))]
        if any(g != 1 for g in gaps):
            problems.append("non_contiguous_sample_indices")

    return problems


def read_frame(cap: cv2.VideoCapture, video_path: str, frame_idx: int, cache: FrameCache) -> np.ndarray | None:
    key = (video_path, int(frame_idx))
    cached = cache.get(key)
    if cached is not None:
        return cached

    cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_idx))
    ok, frame = cap.read()
    if not ok or frame is None:
        return None

    cache.put(key, frame)
    return frame.copy()


def make_captured_at(record: dict[str, Any], local_i: int) -> datetime:
    times = record.get("source_times_sec") or []
    if local_i < len(times):
        t = safe_float(times[local_i], default=float(local_i) / max(1e-6, safe_float(record.get("sample_fps"), 5.0)))
    else:
        t = float(local_i) / 5.0
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=float(t))


def build_tubelet_samples(
    record: dict[str, Any],
    cap: cv2.VideoCapture,
    cache: FrameCache,
) -> list[SampledPerson]:
    video_path = str(record["video_path"])
    frame_indices = [int(x) for x in record.get("source_frame_indices", [])]
    sample_indices = [int(x) for x in record.get("sample_indices", [])]
    bboxes = get_bboxes_xyxy(record)
    confs = [safe_float(x, default=0.0) for x in record.get("confs", [])]

    n = int(record.get("tubelet_frames", len(frame_indices)))
    if len(frame_indices) != n or len(bboxes) != n:
        raise ValueError(
            f"Tubelet length mismatch: n={n}, frames={len(frame_indices)}, bboxes={len(bboxes)}"
        )

    samples: list[SampledPerson] = []
    for i in range(n):
        frame = read_frame(cap, video_path, frame_indices[i], cache)
        if frame is None:
            raise ValueError(f"Could not read frame {frame_indices[i]} from {video_path}")

        sample_index = int(sample_indices[i]) if i < len(sample_indices) else i
        samples.append(
            SampledPerson(
                frame_id=int(frame_indices[i]),
                detection_id=None,
                db_track_id=None,
                tracker_track_id=safe_int(record.get("track_id"), 0),
                sample_index=sample_index,
                captured_at=make_captured_at(record, i),
                frame_bgr=frame,
                bbox_xyxy=[float(v) for v in bboxes[i]],
                confidence=confs[i] if i < len(confs) else None,
                keypoints_xy=[],
                keypoints_conf=[],
            )
        )
    return samples


def prepare_records(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    gate_filter = str(args.gate_name or "").strip()
    for r in rows:
        if gate_filter and "gate_name" in r and str(r.get("gate_name")) != gate_filter:
            continue
        out.append(r)

    if args.limit_videos is not None:
        videos = sorted({str(r.get("video_id", r.get("video_path", ""))) for r in out})
        keep = set(videos[: int(args.limit_videos)])
        out = [r for r in out if str(r.get("video_id", r.get("video_path", ""))) in keep]

    if args.max_tubelets_per_video is not None:
        counts: dict[str, int] = defaultdict(int)
        limited: list[dict[str, Any]] = []
        for r in out:
            vid = str(r.get("video_id", r.get("video_path", "")))
            if counts[vid] >= int(args.max_tubelets_per_video):
                continue
            counts[vid] += 1
            limited.append(r)
        out = limited

    if args.limit_tubelets is not None:
        out = out[: int(args.limit_tubelets)]

    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    features_path = args.output_dir / "pose_micro_features.npy"
    metadata_path = args.output_dir / "pose_micro_metadata.csv"
    feature_names_path = args.output_dir / "pose_micro_feature_names.json"
    failed_path = args.output_dir / "pose_micro_failed.csv"
    summary_path = args.output_dir / "pose_micro_extraction_summary.json"

    if features_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {features_path}. Use --overwrite.")

    started = time.time()
    print("=" * 88)
    print("Backend-parity Pose feature extraction")
    print("=" * 88)
    print(f"tracks_jsonl       = {args.tracks_jsonl}")
    print(f"output_dir         = {args.output_dir}")
    print(f"pose_model         = {args.pose_model}")
    print(f"pose imgsz/conf    = {args.imgsz} / {args.conf}")
    print(f"kpt_conf           = {args.kpt_conf}")
    print(f"crop pad/min size  = {args.crop_pad_ratio} / {args.min_crop_size}")
    print(f"pose_time_mode     = {args.pose_time_mode}")
    print("=" * 88)

    if not args.tracks_jsonl.exists():
        raise FileNotFoundError(args.tracks_jsonl)

    rows = prepare_records(read_jsonl(args.tracks_jsonl), args)
    if not rows:
        raise RuntimeError("No tubelet records left after filtering.")

    print(f"Tubelets to process: {len(rows)}")

    pose_model = YOLO(str(args.pose_model))
    cache = FrameCache(max_size=int(args.frame_cache_size))

    features: list[np.ndarray] = []
    meta_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []

    cap_by_video: dict[str, cv2.VideoCapture] = {}

    try:
        iterator = tqdm(rows, desc="Extracting backend-parity pose features", disable=args.no_progress)
        for idx, record in enumerate(iterator):
            tubelet_id = str(record.get("tubelet_id", f"tubelet_{idx}"))
            video_path = str(record.get("video_path", ""))

            try:
                if not video_path:
                    raise ValueError("Missing video_path")

                problems = validate_record(record, args)
                if problems:
                    raise ValueError("config_validation_failed: " + "; ".join(problems))

                cap = cap_by_video.get(video_path)
                if cap is None:
                    cap = cv2.VideoCapture(video_path)
                    if not cap.isOpened():
                        raise ValueError(f"Could not open video: {video_path}")
                    cap_by_video[video_path] = cap

                tubelet = build_tubelet_samples(record, cap, cache)

                feature, fmeta = make_pose_feature_from_tubelet(
                    tubelet,
                    kpt_conf=float(args.kpt_conf),
                    fps=float(args.expected_sample_fps),
                    time_mode=str(args.pose_time_mode),
                    pose_model=pose_model,
                    pose_imgsz=int(args.imgsz),
                    pose_conf=float(args.conf),
                    pose_crop_pad_ratio=float(args.crop_pad_ratio),
                    pose_min_crop_size=int(args.min_crop_size),
                    device=str(args.device),
                )

                if feature.shape[0] != len(POSE_FEATURE_NAMES):
                    raise ValueError(f"Feature length mismatch: got {feature.shape[0]} expected {len(POSE_FEATURE_NAMES)}")

                feature = np.nan_to_num(feature, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
                features.append(feature)

                meta_row: dict[str, Any] = {
                    "tubelet_id": tubelet_id,
                    "video_path": video_path,
                    "video_id": record.get("video_id", Path(video_path).stem),
                    "track_id": safe_int(record.get("track_id"), 0),
                    "gate_name": record.get("gate_name", "pose"),
                    "source_fps": safe_float(record.get("source_fps"), 0.0),
                    "sample_fps": safe_float(record.get("sample_fps"), float(args.expected_sample_fps)),
                    "effective_sample_fps": safe_float(record.get("effective_sample_fps"), 0.0),
                    "frame_step": safe_int(record.get("frame_step"), 0),
                    "tubelet_frames": safe_int(record.get("tubelet_frames"), len(tubelet)),
                    "stride": safe_int(record.get("stride"), int(args.expected_stride)),
                    "start_frame": safe_int(record.get("start_frame"), 0),
                    "end_frame": safe_int(record.get("end_frame"), 0),
                    "start_time_sec": safe_float(record.get("start_time_sec"), 0.0),
                    "end_time_sec": safe_float(record.get("end_time_sec"), 0.0),
                    "tubelet_duration_sec": safe_float(record.get("tubelet_duration_sec"), 0.0),
                    "pose_valid_frame_ratio": float(fmeta.get("pose_valid_frame_ratio", 0.0)),
                    "pose_mean_keypoint_conf": float(fmeta.get("pose_mean_keypoint_conf", 0.0)),
                    "pose_valid_keypoint_ratio_mean": float(fmeta.get("pose_valid_keypoint_ratio_mean", 0.0)),
                    "pose_source_counts_json": json.dumps(fmeta.get("pose_source_counts", {}), ensure_ascii=False),
                    "normalization_mode": str(fmeta.get("normalization_mode", "")),
                    "bbox_center_jitter_p95": float(fmeta.get("bbox_center_jitter_p95", 0.0)),
                    "bbox_size_jitter_relative_p95": float(fmeta.get("bbox_size_jitter_relative_p95", 0.0)),
                }

                values = fmeta.get("feature_values", {})
                for name in POSE_FEATURE_NAMES:
                    meta_row[name] = float(values.get(name, feature[POSE_FEATURE_NAMES.index(name)]))

                meta_rows.append(meta_row)

            except Exception as e:
                failed_rows.append({
                    "tubelet_id": tubelet_id,
                    "video_path": video_path,
                    "video_id": record.get("video_id", ""),
                    "track_id": record.get("track_id", ""),
                    "error": str(e),
                })

    finally:
        for cap in cap_by_video.values():
            try:
                cap.release()
            except Exception:
                pass

    if features:
        X = np.vstack(features).astype(np.float32)
    else:
        X = np.zeros((0, len(POSE_FEATURE_NAMES)), dtype=np.float32)

    np.save(features_path, X)
    pd.DataFrame(meta_rows).to_csv(metadata_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(failed_rows).to_csv(failed_path, index=False, encoding="utf-8-sig")
    feature_names_path.write_text(json.dumps(POSE_FEATURE_NAMES, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "script": Path(__file__).name,
        "purpose": "backend-parity offline pose micro-feature extraction",
        "tracks_jsonl": str(args.tracks_jsonl),
        "output_dir": str(args.output_dir),
        "pose_model": str(args.pose_model),
        "settings": {
            "pose_imgsz": int(args.imgsz),
            "pose_conf": float(args.conf),
            "kpt_conf": float(args.kpt_conf),
            "crop_pad_ratio": float(args.crop_pad_ratio),
            "min_crop_size": int(args.min_crop_size),
            "pose_time_mode": str(args.pose_time_mode),
            "expected_sample_fps": float(args.expected_sample_fps),
            "expected_tubelet_frames": int(args.expected_tubelet_frames),
            "expected_stride": int(args.expected_stride),
            "fps_tolerance": float(args.fps_tolerance),
            "gate_name_filter": str(args.gate_name),
            "skip_config_validation": bool(args.skip_config_validation),
        },
        "feature_shape": list(map(int, X.shape)),
        "feature_names": POSE_FEATURE_NAMES,
        "total_input_records_after_filter": int(len(rows)),
        "successful_tubelets": int(len(meta_rows)),
        "failed_tubelets": int(len(failed_rows)),
        "elapsed_sec": float(time.time() - started),
        "parity_note": (
            "This script embeds the deployment pose_features.py implementation and calls "
            "make_pose_feature_from_tubelet() on offline reconstructed SampledPerson tubelets."
        ),
        "outputs": {
            "pose_micro_features_npy": str(features_path),
            "pose_micro_metadata_csv": str(metadata_path),
            "pose_micro_feature_names_json": str(feature_names_path),
            "pose_micro_failed_csv": str(failed_path),
            "pose_micro_extraction_summary_json": str(summary_path),
        },
    }

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 88)
    print("DONE")
    print("=" * 88)
    print(f"Features shape: {X.shape}")
    print(f"Successful:      {len(meta_rows)}")
    print(f"Failed:          {len(failed_rows)}")
    print(f"Output:          {args.output_dir}")
    print(f"Summary:         {summary_path}")


if __name__ == "__main__":
    main()
