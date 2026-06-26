#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
04_live_homography_gate_rtsp_test_STAGE3_POSE.py

Standalone live RTSP tester for the HOMOGRAPHY / MACRO-MOTION gate with multiple real fixes:

Stage 2 fixes:
- Smooth projected floor trajectory before computing speed/acceleration.
- Reject non-physical step speeds.
- Reject non-physical acceleration spikes.

Stage 3 fix:
- Use YOLOv8s-pose ankles as the preferred ground-contact point.
- Fall back to last valid ground point when ankles are not reliable.
- Use bbox bottom-center only as a last fallback.
- Log groundpoint source/confidence for debugging.

Purpose:
- Test the homography macro-motion gate without merely raising the threshold.
- Reduce false alarms from bbox bottom-center jitter when a person is sitting/standing.

IMPORTANT:
- This script is HOMOGRAPHY GATE ONLY.
- No deep gate, no RAFT gate, no pose anomaly gate, no score fusion.
- Pose is used only to estimate a better ground-contact point.
- Homography units are floor units/sec unless your homography was metric-calibrated.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import joblib
import numpy as np
from ultralytics import YOLO


FEATURE_NAMES = [
    "macro_speed_mean_mps",
    "macro_speed_median_mps",
    "macro_speed_p95_mps",
    "macro_accel_p95_mps2",
    "macro_straightness_ratio",
    "macro_direction_change_mean_rad",
    "macro_stationary_step_ratio",
]

LEFT_ANKLE = 15
RIGHT_ANKLE = 16


# ============================================================
# Generic helpers
# ============================================================

def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_jsonl(path: Path, row: Dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


class CsvAppender:
    def __init__(self, path: Path, fieldnames: List[str]):
        self.path = path
        self.fieldnames = fieldnames
        self._header_written = path.exists() and path.stat().st_size > 0

    def write(self, row: Dict[str, Any]) -> None:
        clean = {k: row.get(k, "") for k in self.fieldnames}
        with open(self.path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            if not self._header_written:
                writer.writeheader()
                self._header_written = True
            writer.writerow(clean)


@dataclass
class TubeletSample:
    frame: np.ndarray
    t_sample: float
    sample_index: int
    bbox_xyxy: List[float]
    det_conf: float
    ground_xy: Optional[List[float]] = None
    ground_source: str = "unknown"
    ground_conf: float = 0.0
    ground_frozen: bool = False


class TrackTubeletBuffer:
    def __init__(self, tubelet_frames: int = 16, stride: int = 8, max_samples: int = 64):
        self.tubelet_frames = int(tubelet_frames)
        self.stride = int(stride)
        self.samples: deque[TubeletSample] = deque(maxlen=max_samples)
        self.last_emit_sample_index: Optional[int] = None

    def add(self, sample: TubeletSample) -> Optional[List[TubeletSample]]:
        self.samples.append(sample)

        if len(self.samples) < self.tubelet_frames:
            return None

        latest_idx = self.samples[-1].sample_index
        if self.last_emit_sample_index is not None:
            if latest_idx - self.last_emit_sample_index < self.stride:
                return None

        tubelet = list(self.samples)[-self.tubelet_frames:]
        self.last_emit_sample_index = latest_idx
        return tubelet


class OnlineGateState:
    def __init__(self, threshold: float, sigma: float = 2.0, persistence_hits: int = 3, persistence_window: int = 5):
        self.threshold = float(threshold)
        self.sigma = float(sigma)
        self.persistence_hits = int(persistence_hits)
        self.persistence_window = int(persistence_window)
        self.scores: deque[float] = deque(maxlen=max(10, int(round(6 * sigma + persistence_window + 4))))
        self.smooth_hits: deque[bool] = deque(maxlen=persistence_window)

    def _causal_smooth(self) -> float:
        vals = np.asarray(list(self.scores), dtype=np.float64)
        if len(vals) == 0:
            return 0.0
        if self.sigma <= 0 or len(vals) == 1:
            return float(vals[-1])

        radius = int(max(1, round(3 * self.sigma)))
        recent = vals[-(radius + 1):]
        d = np.arange(len(recent) - 1, -1, -1, dtype=np.float64)
        weights = np.exp(-(d ** 2) / (2 * self.sigma ** 2))
        weights /= weights.sum()
        return float(np.sum(recent * weights))

    def update(self, score: float) -> Dict[str, Any]:
        score = float(score) if math.isfinite(float(score)) else 0.0
        self.scores.append(score)

        smooth = self._causal_smooth()
        hit_raw = score > self.threshold
        hit_smooth = smooth > self.threshold
        self.smooth_hits.append(hit_smooth)
        persistent = int(sum(self.smooth_hits)) >= self.persistence_hits

        return {
            "score": float(score),
            "score_smooth": float(smooth),
            "threshold": float(self.threshold),
            "hit_raw": bool(hit_raw),
            "hit_smooth": bool(hit_smooth),
            "persistent_hit": bool(persistent),
            "recent_smooth_hits": int(sum(self.smooth_hits)),
        }


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


def bbox_bottom_center(box: List[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    return (0.5 * (x1 + x2), y2)


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


def crop_frame(frame: np.ndarray, crop_box: List[int]) -> Optional[np.ndarray]:
    x1, y1, x2, y2 = crop_box
    crop = frame[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return None
    return crop


def project_points_homography(points_xy: np.ndarray, H: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_xy, dtype=np.float64)
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    homo = np.hstack([pts, ones])
    proj = homo @ H.T
    denom = proj[:, 2:3]
    denom = np.where(np.abs(denom) < 1e-12, np.sign(denom) * 1e-12 + 1e-12, denom)
    out = proj[:, :2] / denom
    return out.astype(np.float64)


def angle_wrap(delta: float) -> float:
    return (delta + math.pi) % (2 * math.pi) - math.pi


# ============================================================
# Stage-2 smoothing / outlier rejection
# ============================================================

def _median_smooth_1d(x: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if window <= 1 or len(x) < 3:
        return x.copy()
    window = int(window)
    if window % 2 == 0:
        window += 1
    window = min(window, len(x) if len(x) % 2 == 1 else len(x) - 1)
    if window < 3:
        return x.copy()
    r = window // 2
    out = np.zeros_like(x, dtype=np.float64)
    for i in range(len(x)):
        lo = max(0, i - r)
        hi = min(len(x), i + r + 1)
        out[i] = np.median(x[lo:hi])
    return out


def _savgol_smooth_1d(x: np.ndarray, window: int, polyorder: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if window <= 1 or n < 3:
        return x.copy()

    window = int(window)
    if window % 2 == 0:
        window += 1
    window = min(window, n if n % 2 == 1 else n - 1)
    if window < 3:
        return x.copy()

    polyorder = int(max(1, min(polyorder, window - 1)))
    r = window // 2
    out = np.zeros_like(x, dtype=np.float64)

    for i in range(n):
        lo = max(0, i - r)
        hi = min(n, i + r + 1)

        if hi - lo < window:
            if lo == 0:
                hi = min(n, window)
            elif hi == n:
                lo = max(0, n - window)

        idx = np.arange(lo, hi, dtype=np.float64)
        y = x[lo:hi]
        t = idx - float(i)

        deg = min(polyorder, len(y) - 1)
        if deg < 1:
            out[i] = x[i]
            continue

        try:
            coeff = np.polyfit(t, y, deg)
            out[i] = np.polyval(coeff, 0.0)
        except Exception:
            out[i] = x[i]

    return out


def smooth_floor_trajectory(points: np.ndarray, method: str = "median_savgol", window: int = 5, polyorder: int = 2) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
        return points.copy()

    method = (method or "none").lower().strip()
    if method == "none":
        return points.copy()

    if method == "median":
        out = np.zeros_like(points, dtype=np.float64)
        out[:, 0] = _median_smooth_1d(points[:, 0], window)
        out[:, 1] = _median_smooth_1d(points[:, 1], window)
        return out

    if method == "savgol":
        out = np.zeros_like(points, dtype=np.float64)
        out[:, 0] = _savgol_smooth_1d(points[:, 0], window, polyorder)
        out[:, 1] = _savgol_smooth_1d(points[:, 1], window, polyorder)
        return out

    if method == "median_savgol":
        tmp = np.zeros_like(points, dtype=np.float64)
        tmp[:, 0] = _median_smooth_1d(points[:, 0], window)
        tmp[:, 1] = _median_smooth_1d(points[:, 1], window)
        out = np.zeros_like(points, dtype=np.float64)
        out[:, 0] = _savgol_smooth_1d(tmp[:, 0], window, polyorder)
        out[:, 1] = _savgol_smooth_1d(tmp[:, 1], window, polyorder)
        return out

    raise ValueError(f"Unknown trajectory_smoothing method: {method}")


# ============================================================
# Stage-3 pose-assisted ground point
# ============================================================

@dataclass
class TrackGroundState:
    last_xy: Optional[List[float]] = None
    last_sample_index: int = -10**9


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
    pose_model,
    frame: np.ndarray,
    bbox_xyxy: List[float],
    track_state: TrackGroundState,
    sample_index: int,
    device: str = "cuda",
    pose_imgsz: int = 256,
    pose_conf: float = 0.25,
    ankle_conf_threshold: float = 0.35,
    pose_crop_pad_ratio: float = 0.25,
    pose_min_crop_size: int = 192,
    fallback_mode: str = "freeze_last_valid",
    max_freeze_samples: int = 12,
) -> Tuple[List[float], Dict[str, Any]]:
    """
    Returns image-space ground point [x, y] and debug metadata.
    Preferred:
      both ankles reliable -> midpoint
      one ankle reliable -> that ankle
    Fallback:
      freeze last valid groundpoint if recent enough
      otherwise bbox bottom-center
    """
    h, w = frame.shape[:2]
    bbox = clamp_box_xyxy(bbox_xyxy, w, h)
    bbox_ground = list(bbox_bottom_center(bbox))

    meta = {
        "ground_source": "bbox_bottom",
        "ground_conf": 0.0,
        "ground_frozen": False,
        "left_ankle_conf": 0.0,
        "right_ankle_conf": 0.0,
        "pose_used": False,
        "bbox_ground_x": float(bbox_ground[0]),
        "bbox_ground_y": float(bbox_ground[1]),
    }

    if pose_model is not None:
        try:
            crop_box = pad_box_xyxy(bbox, w=w, h=h, pad_ratio=pose_crop_pad_ratio, min_crop_size=pose_min_crop_size)
            crop = crop_frame(frame, crop_box)

            if crop is not None:
                results = pose_model.predict(source=[crop], imgsz=pose_imgsz, conf=pose_conf, device=device, verbose=False)
                xy_crop, kconf = choose_best_pose_result(results[0] if results else None)

                if xy_crop is not None and kconf is not None:
                    cx1, cy1, _, _ = crop_box

                    xy_orig = xy_crop.copy()
                    xy_orig[:, 0] += float(cx1)
                    xy_orig[:, 1] += float(cy1)

                    la_conf = float(kconf[LEFT_ANKLE])
                    ra_conf = float(kconf[RIGHT_ANKLE])
                    meta["left_ankle_conf"] = la_conf
                    meta["right_ankle_conf"] = ra_conf

                    valid_points = []
                    confs = []

                    if la_conf >= ankle_conf_threshold and np.isfinite(xy_orig[LEFT_ANKLE]).all():
                        valid_points.append(xy_orig[LEFT_ANKLE])
                        confs.append(la_conf)

                    if ra_conf >= ankle_conf_threshold and np.isfinite(xy_orig[RIGHT_ANKLE]).all():
                        valid_points.append(xy_orig[RIGHT_ANKLE])
                        confs.append(ra_conf)

                    if len(valid_points) >= 2:
                        gp = np.mean(np.vstack(valid_points), axis=0)
                        xy = [float(gp[0]), float(gp[1])]
                        conf = float(np.mean(confs))
                        track_state.last_xy = xy
                        track_state.last_sample_index = int(sample_index)
                        meta.update({
                            "ground_source": "ankle_midpoint",
                            "ground_conf": conf,
                            "pose_used": True,
                        })
                        return xy, meta

                    if len(valid_points) == 1:
                        gp = valid_points[0]
                        xy = [float(gp[0]), float(gp[1])]
                        conf = float(confs[0])
                        track_state.last_xy = xy
                        track_state.last_sample_index = int(sample_index)
                        meta.update({
                            "ground_source": "single_ankle",
                            "ground_conf": conf,
                            "pose_used": True,
                        })
                        return xy, meta

        except Exception as e:
            meta["pose_error"] = str(e)[:200]

    # Fallback: freeze last valid ankle/pose point if available and recent.
    if fallback_mode == "freeze_last_valid" and track_state.last_xy is not None:
        age = int(sample_index - track_state.last_sample_index)
        if age <= int(max_freeze_samples):
            meta.update({
                "ground_source": "freeze_last_valid",
                "ground_conf": 0.0,
                "ground_frozen": True,
                "freeze_age_samples": age,
            })
            return list(track_state.last_xy), meta

    # Final fallback: bbox bottom-center.
    track_state.last_xy = bbox_ground
    track_state.last_sample_index = int(sample_index)
    meta.update({
        "ground_source": "bbox_bottom",
        "ground_conf": 0.0,
        "ground_frozen": False,
    })
    return bbox_ground, meta


# ============================================================
# Macro feature extraction
# ============================================================

def compute_homography_macro_features(
    tubelet: List[TubeletSample],
    H: np.ndarray,
    stationary_speed_threshold: float = 0.05,
    max_step_speed: Optional[float] = None,
    trajectory_smoothing: str = "median_savgol",
    smoothing_window: int = 5,
    smoothing_polyorder: int = 2,
    reject_nonphysical_steps: bool = True,
    max_plausible_speed: float = 3.0,
    max_plausible_accel: float = 6.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    if len(tubelet) < 2:
        raise ValueError("Need at least 2 samples for macro features")

    img_points = []
    bbox_points = []
    times = []
    ground_sources = []
    ground_confs = []
    ground_frozen = []

    h, w = tubelet[0].frame.shape[:2]

    for s in tubelet:
        box = clamp_box_xyxy(s.bbox_xyxy, w=w, h=h)
        bbox_points.append(bbox_bottom_center(box))

        if s.ground_xy is None:
            img_points.append(bbox_bottom_center(box))
            ground_sources.append("bbox_bottom_missing")
            ground_confs.append(0.0)
            ground_frozen.append(False)
        else:
            img_points.append(s.ground_xy)
            ground_sources.append(str(s.ground_source))
            ground_confs.append(float(s.ground_conf))
            ground_frozen.append(bool(s.ground_frozen))

        times.append(float(s.t_sample))

    img_points = np.asarray(img_points, dtype=np.float64)
    bbox_points = np.asarray(bbox_points, dtype=np.float64)
    floor_points_raw = project_points_homography(img_points, H)
    bbox_floor_points_raw = project_points_homography(bbox_points, H)

    floor_points = smooth_floor_trajectory(
        floor_points_raw,
        method=trajectory_smoothing,
        window=smoothing_window,
        polyorder=smoothing_polyorder,
    )

    times = np.asarray(times, dtype=np.float64)

    raw_step_dists = np.linalg.norm(np.diff(floor_points_raw, axis=0), axis=1) if len(floor_points_raw) >= 2 else np.array([], dtype=np.float64)
    bbox_raw_step_dists = np.linalg.norm(np.diff(bbox_floor_points_raw, axis=0), axis=1) if len(bbox_floor_points_raw) >= 2 else np.array([], dtype=np.float64)
    smoothed_step_dists_all = np.linalg.norm(np.diff(floor_points, axis=0), axis=1) if len(floor_points) >= 2 else np.array([], dtype=np.float64)

    step_vecs = np.diff(floor_points, axis=0)
    dt = np.diff(times)
    valid_dt = dt > 1e-6

    if not np.all(valid_dt):
        step_vecs = step_vecs[valid_dt]
        dt = dt[valid_dt]

    if len(dt) == 0:
        raise ValueError("No valid time deltas in tubelet")

    step_dists = np.linalg.norm(step_vecs, axis=1)
    speeds_all = step_dists / np.maximum(dt, 1e-6)

    valid_step_mask = np.ones(len(speeds_all), dtype=bool)
    if reject_nonphysical_steps and len(speeds_all):
        valid_step_mask &= np.isfinite(speeds_all)
        valid_step_mask &= speeds_all <= float(max_plausible_speed)

    if len(speeds_all) == 0 or not np.any(valid_step_mask):
        speeds = np.zeros(1, dtype=np.float64)
        step_dists_used = np.zeros(1, dtype=np.float64)
        dt_used = np.ones(1, dtype=np.float64) / 2.5
    else:
        speeds = speeds_all[valid_step_mask]
        step_dists_used = step_dists[valid_step_mask]
        dt_used = dt[valid_step_mask]

    if max_step_speed is not None and max_step_speed > 0:
        speeds = np.minimum(speeds, float(max_step_speed))

    if len(speeds) >= 2:
        mid_dt = 0.5 * (dt_used[1:] + dt_used[:-1])
        accels_all = np.abs(np.diff(speeds)) / np.maximum(mid_dt, 1e-6)

        if reject_nonphysical_steps:
            accel_mask = np.isfinite(accels_all) & (accels_all <= float(max_plausible_accel))
            accels = accels_all[accel_mask]
            if len(accels) == 0:
                accels = np.array([0.0], dtype=np.float64)
        else:
            accels = accels_all
    else:
        accels = np.array([0.0], dtype=np.float64)

    total_path = float(np.sum(step_dists_used))
    displacement = float(np.linalg.norm(floor_points[-1] - floor_points[0]))
    straightness = displacement / max(total_path, 1e-6)

    angles = np.arctan2(step_vecs[:, 1], step_vecs[:, 0])
    if len(angles) >= 2:
        deltas = np.array([abs(angle_wrap(float(angles[i] - angles[i - 1]))) for i in range(1, len(angles))], dtype=np.float64)
        direction_change_mean = float(np.mean(deltas)) if len(deltas) else 0.0
    else:
        direction_change_mean = 0.0

    stationary_ratio = float(np.mean(speeds < float(stationary_speed_threshold))) if len(speeds) else 1.0

    feature = np.array([
        float(np.mean(speeds)) if len(speeds) else 0.0,
        float(np.median(speeds)) if len(speeds) else 0.0,
        float(np.percentile(speeds, 95)) if len(speeds) else 0.0,
        float(np.percentile(accels, 95)) if len(accels) else 0.0,
        float(straightness),
        float(direction_change_mean),
        float(stationary_ratio),
    ], dtype=np.float32)

    if not np.isfinite(feature).all():
        raise ValueError(f"Non-finite macro feature produced: {feature}")

    valid_pose_sources = {"ankle_midpoint", "single_ankle"}
    valid_gp = [s in valid_pose_sources for s in ground_sources]
    frozen_gp = [s == "freeze_last_valid" for s in ground_sources]
    bbox_gp = [s.startswith("bbox") for s in ground_sources]

    meta = {
        "image_points_used": img_points.tolist(),
        "bbox_bottom_points": bbox_points.tolist(),
        "floor_points_raw": floor_points_raw.tolist(),
        "bbox_floor_points_raw": bbox_floor_points_raw.tolist(),
        "floor_points_smoothed": floor_points.tolist(),
        "step_speeds_used": speeds.astype(float).tolist(),
        "step_speeds_all_after_smoothing": speeds_all.astype(float).tolist(),
        "step_accels_used": accels.astype(float).tolist(),
        "total_path_floor_units": total_path,
        "displacement_floor_units": displacement,
        "raw_path_floor_units": float(np.sum(raw_step_dists)) if len(raw_step_dists) else 0.0,
        "bbox_raw_path_floor_units": float(np.sum(bbox_raw_step_dists)) if len(bbox_raw_step_dists) else 0.0,
        "smoothed_path_floor_units_all_steps": float(np.sum(smoothed_step_dists_all)) if len(smoothed_step_dists_all) else 0.0,
        "trajectory_smoothing": trajectory_smoothing,
        "smoothing_window": int(smoothing_window),
        "smoothing_polyorder": int(smoothing_polyorder),
        "reject_nonphysical_steps": bool(reject_nonphysical_steps),
        "max_plausible_speed": float(max_plausible_speed),
        "max_plausible_accel": float(max_plausible_accel),
        "num_steps_total": int(len(speeds_all)),
        "num_steps_used": int(len(speeds)),
        "num_steps_rejected": int(len(speeds_all) - int(np.sum(valid_step_mask)) if len(speeds_all) else 0),
        "stationary_speed_threshold": float(stationary_speed_threshold),
        "ground_sources": ground_sources,
        "ground_conf_mean": float(np.mean(ground_confs)) if ground_confs else 0.0,
        "valid_groundpoint_ratio": float(np.mean(valid_gp)) if ground_sources else 0.0,
        "frozen_groundpoint_ratio": float(np.mean(frozen_gp)) if ground_sources else 0.0,
        "bbox_groundpoint_ratio": float(np.mean(bbox_gp)) if ground_sources else 0.0,
        "num_ankle_points_used": int(sum(valid_gp)),
        "num_frozen_points": int(sum(frozen_gp)),
        "num_bbox_points": int(sum(bbox_gp)),
        "macro_feature_names": FEATURE_NAMES,
        "macro_feature_values": {name: float(feature[i]) for i, name in enumerate(FEATURE_NAMES)},
    }
    return feature.reshape(1, -1), meta


# ============================================================
# Model/artifact helpers
# ============================================================

def find_first_joblib(folder: Path, include_keywords: List[str], exclude_keywords: List[str] = None) -> Optional[Path]:
    exclude_keywords = exclude_keywords or []
    if not folder.exists():
        return None
    candidates = list(folder.rglob("*.joblib"))
    scored = []
    for p in candidates:
        name = p.name.lower()
        if all(k.lower() in name for k in include_keywords) and not any(k.lower() in name for k in exclude_keywords):
            scored.append(p)
    if scored:
        return sorted(scored, key=lambda x: len(str(x)))[0]
    return None


def load_gate_artifacts(args):
    gate_dir = Path(args.homography_gate_dir)

    scaler_path = Path(args.scaler_path) if args.scaler_path else None
    gmm_path = Path(args.gmm_path) if args.gmm_path else None

    if scaler_path is None:
        scaler_path = find_first_joblib(gate_dir, ["scaler"]) or find_first_joblib(gate_dir, ["robust"])
    if gmm_path is None:
        gmm_path = find_first_joblib(gate_dir, ["components_5"]) or find_first_joblib(gate_dir, ["gmm"])

    if scaler_path is None or not scaler_path.exists():
        raise FileNotFoundError("Could not find macro RobustScaler joblib. Pass --scaler_path explicitly.")
    if gmm_path is None or not gmm_path.exists():
        raise FileNotFoundError("Could not find macro GMM joblib. Pass --gmm_path explicitly.")

    print(f"[LOAD] scaler={scaler_path}")
    print(f"[LOAD] gmm={gmm_path}")

    return joblib.load(scaler_path), joblib.load(gmm_path), str(scaler_path), str(gmm_path)


# ============================================================
# Display / evidence
# ============================================================

def draw_label(frame: np.ndarray, box, lines: List[str], anomaly: bool = False):
    color = (0, 0, 255) if anomaly else (0, 180, 0)
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.52
    thickness = 1
    pad = 5
    line_h = 20
    lines = [str(x) for x in lines if str(x).strip()]
    if not lines:
        return

    widths = [cv2.getTextSize(line, font, font_scale, thickness)[0][0] for line in lines]
    box_w = max(widths) + 2 * pad
    box_h = len(lines) * line_h + 2 * pad

    h, w = frame.shape[:2]
    lx = max(0, min(x1, w - box_w - 1))
    ly = max(box_h + 1, y1 - 6)

    cv2.rectangle(frame, (lx, ly - box_h), (lx + box_w, ly), color, -1)
    ty = ly - box_h + pad + 14
    for line in lines:
        cv2.putText(frame, line, (lx + pad, ty), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        ty += line_h


def draw_ground_point(frame: np.ndarray, xy: Optional[List[float]], source: str):
    if xy is None:
        return
    x, y = int(round(xy[0])), int(round(xy[1]))
    color = (255, 0, 255)
    if source == "ankle_midpoint":
        color = (0, 255, 255)
    elif source == "single_ankle":
        color = (0, 200, 255)
    elif source == "freeze_last_valid":
        color = (255, 180, 0)
    elif source.startswith("bbox"):
        color = (255, 0, 255)
    cv2.circle(frame, (x, y), 5, color, -1)
    cv2.putText(frame, source[:14], (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def make_montage(frames: List[np.ndarray], cols: int = 4, width: int = 320) -> Optional[np.ndarray]:
    if not frames:
        return None

    small = []
    for f in frames:
        if f is None:
            continue
        h, w = f.shape[:2]
        scale = width / max(1, w)
        nh = max(1, int(round(h * scale)))
        small.append(cv2.resize(f, (width, nh)))

    if not small:
        return None

    max_h = max(im.shape[0] for im in small)
    padded = []
    for im in small:
        if im.shape[0] < max_h:
            im = np.vstack([im, np.zeros((max_h - im.shape[0], im.shape[1], 3), dtype=im.dtype)])
        padded.append(im)

    rows = []
    for i in range(0, len(padded), cols):
        row = padded[i:i + cols]
        while len(row) < cols:
            row.append(np.zeros_like(padded[0]))
        rows.append(np.hstack(row))
    return np.vstack(rows)


def open_rtsp(url: str):
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        "rtsp_transport;tcp|"
        "stimeout;10000000|"
        "max_delay;500000"
    )
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def resize_for_display(frame: np.ndarray, width: int) -> np.ndarray:
    if width <= 0:
        return frame
    h, w = frame.shape[:2]
    if w <= width:
        return frame
    scale = width / float(w)
    return cv2.resize(frame, (width, int(round(h * scale))), interpolation=cv2.INTER_AREA)


# ============================================================
# Args / main
# ============================================================

def parse_args():
    ap = argparse.ArgumentParser()

    ap.add_argument("--rtsp_url", required=True)
    ap.add_argument("--output_dir", required=True)

    ap.add_argument("--device", default="cuda")
    ap.add_argument("--det_model", default=r"D:\Embeddings_Distribution\yolov8n.pt")
    ap.add_argument("--det_conf", type=float, default=0.25)
    ap.add_argument("--det_imgsz", type=int, default=640)
    ap.add_argument("--tracker", default="bytetrack.yaml")

    ap.add_argument("--sample_fps", type=float, default=2.5)
    ap.add_argument("--tubelet_frames", type=int, default=16)
    ap.add_argument("--stride", type=int, default=8)
    ap.add_argument("--max_track_gap_samples", type=int, default=8)

    ap.add_argument("--homography_npy", default=r"D:\Embeddings_Distribution\calibration\camera_001_homography.npy")
    ap.add_argument("--homography_gate_dir", default=r"D:\Embeddings_Distribution\normality_models\homography_macro_gmm_gate_v1")
    ap.add_argument("--scaler_path", default="")
    ap.add_argument("--gmm_path", default="")

    ap.add_argument("--homography_threshold", type=float, default=10.928259)
    ap.add_argument("--stationary_speed_threshold", type=float, default=0.05)
    ap.add_argument("--max_step_speed", type=float, default=0.0)

    # Stage-2 fixes
    ap.add_argument("--trajectory_smoothing", default="median_savgol", choices=["none", "median", "savgol", "median_savgol"])
    ap.add_argument("--trajectory_smoothing_window", type=int, default=5)
    ap.add_argument("--trajectory_smoothing_polyorder", type=int, default=2)
    ap.add_argument("--reject_nonphysical_steps", action="store_true", default=True)
    ap.add_argument("--no_reject_nonphysical_steps", dest="reject_nonphysical_steps", action="store_false")
    ap.add_argument("--max_plausible_speed", type=float, default=3.0)
    ap.add_argument("--max_plausible_accel", type=float, default=6.0)

    # Stage-3 pose-assisted ground point
    ap.add_argument("--pose_model", default="yolov8s-pose.pt")
    ap.add_argument("--pose_imgsz", type=int, default=256)
    ap.add_argument("--pose_conf", type=float, default=0.25)
    ap.add_argument("--ankle_conf_threshold", type=float, default=0.35)
    ap.add_argument("--pose_crop_pad_ratio", type=float, default=0.25)
    ap.add_argument("--pose_min_crop_size", type=int, default=192)
    ap.add_argument("--groundpoint_mode", default="pose_ankle", choices=["bbox_bottom", "pose_ankle"])
    ap.add_argument("--fallback_mode", default="freeze_last_valid", choices=["freeze_last_valid", "bbox_bottom"])
    ap.add_argument("--max_freeze_samples", type=int, default=12)
    ap.add_argument("--min_valid_groundpoint_ratio", type=float, default=0.0, help="0 disables drop/neutralization. Later can try 0.4-0.5.")

    ap.add_argument("--smoothing_sigma", type=float, default=2.0)
    ap.add_argument("--persistence_hits", type=int, default=3)
    ap.add_argument("--persistence_window", type=int, default=5)

    ap.add_argument("--display", action="store_true")
    ap.add_argument("--window_width", type=int, default=1280)
    ap.add_argument("--save_evidence", action="store_true")
    ap.add_argument("--save_all_tubelets", action="store_true")
    ap.add_argument("--print_every_tubelet", action="store_true")
    ap.add_argument("--max_runtime_sec", type=float, default=0.0)

    return ap.parse_args()


def main():
    args = parse_args()

    out_dir = ensure_dir(Path(args.output_dir))
    evidence_dir = ensure_dir(out_dir / "evidence")
    tubelets_jsonl = out_dir / "tubelets.jsonl"
    events_jsonl = out_dir / "events.jsonl"

    csv = CsvAppender(out_dir / "tubelets.csv", [
        "wall_time", "track_id", "tubelet_index",
        "sample_start_i", "sample_end_i",
        "tubelet_start_time", "tubelet_end_time", "tubelet_duration_sec",
        "macro_score", "macro_threshold", "macro_score_smooth",
        "macro_hit_raw", "macro_hit_smooth", "macro_persistent_hit",
        *FEATURE_NAMES,
        "raw_path_floor_units", "bbox_raw_path_floor_units", "smoothed_path_floor_units_all_steps",
        "num_steps_total", "num_steps_used", "num_steps_rejected",
        "trajectory_smoothing", "max_plausible_speed", "max_plausible_accel",
        "valid_groundpoint_ratio", "frozen_groundpoint_ratio", "bbox_groundpoint_ratio",
        "num_ankle_points_used", "num_frozen_points", "num_bbox_points", "ground_conf_mean",
        "anomaly", "reasons", "evidence_frame", "evidence_montage",
    ])

    print("=" * 100)
    print("LIVE HOMOGRAPHY GATE - STAGE 3 POSE-ASSISTED GROUND POINT")
    print("No fusion. Pose is used only to stabilize homography ground point.")
    print(f"output_dir={out_dir}")
    print("=" * 100)

    H = np.load(args.homography_npy).astype(np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"Expected 3x3 homography, got {H.shape}")

    scaler, gmm, scaler_path, gmm_path = load_gate_artifacts(args)

    det = YOLO(args.det_model)

    pose_model = None
    if args.groundpoint_mode == "pose_ankle":
        print(f"[LOAD] pose groundpoint model={args.pose_model}")
        pose_model = YOLO(args.pose_model)

    cap = open_rtsp(args.rtsp_url)
    if not cap.isOpened():
        raise RuntimeError("Could not open RTSP stream.")

    buffers: Dict[int, TrackTubeletBuffer] = defaultdict(lambda: TrackTubeletBuffer(args.tubelet_frames, args.stride))
    states: Dict[int, OnlineGateState] = defaultdict(
        lambda: OnlineGateState(args.homography_threshold, args.smoothing_sigma, args.persistence_hits, args.persistence_window)
    )
    ground_states: Dict[int, TrackGroundState] = defaultdict(TrackGroundState)

    latest_label: Dict[int, List[str]] = {}
    last_seen_sample: Dict[int, int] = {}

    period = 1.0 / float(args.sample_fps)
    last_sample_t = 0.0
    sample_i = 0
    tubelet_count = 0
    event_count = 0
    start_t = time.time()

    try:
        while True:
            if args.max_runtime_sec and (time.time() - start_t) >= args.max_runtime_sec:
                print("[DONE] max_runtime_sec reached.")
                break

            ok, frame = cap.read()
            if not ok or frame is None:
                print("[WARN] failed frame")
                time.sleep(0.1)
                continue

            now = time.time()
            sample_due = (now - last_sample_t) >= period
            if sample_due:
                last_sample_t = now
                sample_i += 1

            results = det.track(
                source=frame,
                persist=True,
                classes=[0],
                conf=args.det_conf,
                imgsz=args.det_imgsz,
                tracker=args.tracker,
                device=args.device,
                verbose=False,
            )

            annotated = frame.copy()

            if not results or results[0].boxes is None or results[0].boxes.xyxy is None:
                if args.display:
                    cv2.imshow("live_homography_stage3", resize_for_display(annotated, args.window_width))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                continue

            boxes = results[0].boxes
            xyxy = boxes.xyxy.detach().cpu().numpy()
            confs = boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.ones(len(xyxy), dtype=np.float32)
            ids = boxes.id.detach().cpu().numpy().astype(int) if boxes.id is not None else np.arange(len(xyxy), dtype=int)

            for box, det_conf, tid in zip(xyxy, confs, ids):
                tid = int(tid)
                b = [float(v) for v in box.tolist()]
                lines = latest_label.get(tid, [f"ID {tid}", f"buffer {len(buffers[tid].samples)}/{args.tubelet_frames}"])
                draw_label(annotated, b, lines, anomaly=False)

                if not sample_due:
                    continue

                prev = last_seen_sample.get(tid)
                if prev is not None and (sample_i - prev) > (args.max_track_gap_samples + 1):
                    buffers[tid] = TrackTubeletBuffer(args.tubelet_frames, args.stride)
                    states[tid] = OnlineGateState(args.homography_threshold, args.smoothing_sigma, args.persistence_hits, args.persistence_window)
                    ground_states[tid] = TrackGroundState()
                    latest_label.pop(tid, None)
                    print(f"[TRACK_RESET] track={tid} gap_samples={sample_i - prev}; buffer/state reset")

                last_seen_sample[tid] = sample_i

                if args.groundpoint_mode == "pose_ankle":
                    ground_xy, gp_meta = estimate_groundpoint_pose_assisted(
                        pose_model=pose_model,
                        frame=frame,
                        bbox_xyxy=b,
                        track_state=ground_states[tid],
                        sample_index=sample_i,
                        device=args.device,
                        pose_imgsz=args.pose_imgsz,
                        pose_conf=args.pose_conf,
                        ankle_conf_threshold=args.ankle_conf_threshold,
                        pose_crop_pad_ratio=args.pose_crop_pad_ratio,
                        pose_min_crop_size=args.pose_min_crop_size,
                        fallback_mode=args.fallback_mode,
                        max_freeze_samples=args.max_freeze_samples,
                    )
                else:
                    ground_xy = list(bbox_bottom_center(b))
                    gp_meta = {
                        "ground_source": "bbox_bottom",
                        "ground_conf": 0.0,
                        "ground_frozen": False,
                    }

                draw_ground_point(annotated, ground_xy, gp_meta.get("ground_source", "unknown"))

                t_sample = sample_i / float(args.sample_fps)
                tub = buffers[tid].add(
                    TubeletSample(
                        frame=frame.copy(),
                        t_sample=t_sample,
                        sample_index=sample_i,
                        bbox_xyxy=b,
                        det_conf=float(det_conf),
                        ground_xy=ground_xy,
                        ground_source=gp_meta.get("ground_source", "unknown"),
                        ground_conf=float(gp_meta.get("ground_conf", 0.0)),
                        ground_frozen=bool(gp_meta.get("ground_frozen", False)),
                    )
                )

                if tub is None:
                    continue

                tubelet_count += 1
                reasons = []
                evidence_frame = ""
                evidence_montage = ""

                try:
                    X, meta = compute_homography_macro_features(
                        tub,
                        H=H,
                        stationary_speed_threshold=args.stationary_speed_threshold,
                        max_step_speed=args.max_step_speed if args.max_step_speed > 0 else None,
                        trajectory_smoothing=args.trajectory_smoothing,
                        smoothing_window=args.trajectory_smoothing_window,
                        smoothing_polyorder=args.trajectory_smoothing_polyorder,
                        reject_nonphysical_steps=args.reject_nonphysical_steps,
                        max_plausible_speed=args.max_plausible_speed,
                        max_plausible_accel=args.max_plausible_accel,
                    )

                    if args.min_valid_groundpoint_ratio > 0 and meta.get("valid_groundpoint_ratio", 0.0) < args.min_valid_groundpoint_ratio:
                        # Neutralize unreliable tubelets rather than let bbox fallback cause fake alerts.
                        X = np.zeros((1, len(FEATURE_NAMES)), dtype=np.float32)
                        X[0, 6] = 1.0  # stationary ratio
                        meta["neutralized_due_to_low_valid_groundpoint_ratio"] = True
                    else:
                        meta["neutralized_due_to_low_valid_groundpoint_ratio"] = False

                    Xs = scaler.transform(X)
                    score = float(-gmm.score_samples(Xs)[0])
                    gr = states[tid].update(score)

                    if gr["persistent_hit"]:
                        reasons.append("rare_macro_floor_motion")

                    anomaly = bool(reasons)
                    feat_values = {name: float(X[0, i]) for i, name in enumerate(FEATURE_NAMES)}

                    latest_label[tid] = [
                        f"ID {tid} | {'ANOMALY' if anomaly else 'NORMAL'}",
                        f"HOMO {score:.2f}/{args.homography_threshold:.2f} S={gr['score_smooth']:.2f}",
                        f"R={int(gr['hit_raw'])} SH={int(gr['hit_smooth'])} P={int(gr['persistent_hit'])}",
                        f"GP valid={meta.get('valid_groundpoint_ratio', 0):.2f} freeze={meta.get('frozen_groundpoint_ratio', 0):.2f}",
                    ]

                    draw_label(annotated, b, latest_label[tid], anomaly=anomaly)
                    draw_ground_point(annotated, ground_xy, gp_meta.get("ground_source", "unknown"))

                    if args.save_evidence and (anomaly or args.save_all_tubelets):
                        efp = evidence_dir / f"tubelet_{tubelet_count:06d}_track_{tid}_frame.jpg"
                        emp = evidence_dir / f"tubelet_{tubelet_count:06d}_track_{tid}_montage.jpg"

                        f = tub[-1].frame.copy()
                        draw_label(f, tub[-1].bbox_xyxy, latest_label[tid], anomaly=anomaly)
                        draw_ground_point(f, tub[-1].ground_xy, tub[-1].ground_source)
                        cv2.imwrite(str(efp), f)
                        evidence_frame = str(efp)

                        ims = []
                        for s in tub:
                            im = s.frame.copy()
                            draw_label(im, s.bbox_xyxy, [f"id={tid}", f"gp={s.ground_source}"], anomaly=anomaly)
                            draw_ground_point(im, s.ground_xy, s.ground_source)
                            ims.append(im)
                        montage = make_montage(ims)
                        if montage is not None:
                            cv2.imwrite(str(emp), montage)
                            evidence_montage = str(emp)

                    row = {
                        "wall_time": now,
                        "track_id": tid,
                        "tubelet_index": tubelet_count,
                        "sample_start_i": tub[0].sample_index,
                        "sample_end_i": tub[-1].sample_index,
                        "tubelet_start_time": tub[0].t_sample,
                        "tubelet_end_time": tub[-1].t_sample,
                        "tubelet_duration_sec": float(tub[-1].t_sample - tub[0].t_sample),
                        "macro_score": score,
                        "macro_threshold": float(args.homography_threshold),
                        "macro_score_smooth": gr["score_smooth"],
                        "macro_hit_raw": gr["hit_raw"],
                        "macro_hit_smooth": gr["hit_smooth"],
                        "macro_persistent_hit": gr["persistent_hit"],
                        "anomaly": anomaly,
                        "reasons": reasons,
                        "bbox_xyxy": tub[-1].bbox_xyxy,
                        "macro_meta": meta,
                        "last_ground_meta": gp_meta,
                        "evidence_frame": evidence_frame,
                        "evidence_montage": evidence_montage,
                    }
                    row.update(feat_values)
                    write_jsonl(tubelets_jsonl, row)

                    csv.write({
                        "wall_time": now,
                        "track_id": tid,
                        "tubelet_index": tubelet_count,
                        "sample_start_i": tub[0].sample_index,
                        "sample_end_i": tub[-1].sample_index,
                        "tubelet_start_time": tub[0].t_sample,
                        "tubelet_end_time": tub[-1].t_sample,
                        "tubelet_duration_sec": float(tub[-1].t_sample - tub[0].t_sample),
                        "macro_score": score,
                        "macro_threshold": float(args.homography_threshold),
                        "macro_score_smooth": gr["score_smooth"],
                        "macro_hit_raw": gr["hit_raw"],
                        "macro_hit_smooth": gr["hit_smooth"],
                        "macro_persistent_hit": gr["persistent_hit"],
                        **feat_values,
                        "raw_path_floor_units": meta.get("raw_path_floor_units", ""),
                        "bbox_raw_path_floor_units": meta.get("bbox_raw_path_floor_units", ""),
                        "smoothed_path_floor_units_all_steps": meta.get("smoothed_path_floor_units_all_steps", ""),
                        "num_steps_total": meta.get("num_steps_total", ""),
                        "num_steps_used": meta.get("num_steps_used", ""),
                        "num_steps_rejected": meta.get("num_steps_rejected", ""),
                        "trajectory_smoothing": meta.get("trajectory_smoothing", ""),
                        "max_plausible_speed": meta.get("max_plausible_speed", ""),
                        "max_plausible_accel": meta.get("max_plausible_accel", ""),
                        "valid_groundpoint_ratio": meta.get("valid_groundpoint_ratio", ""),
                        "frozen_groundpoint_ratio": meta.get("frozen_groundpoint_ratio", ""),
                        "bbox_groundpoint_ratio": meta.get("bbox_groundpoint_ratio", ""),
                        "num_ankle_points_used": meta.get("num_ankle_points_used", ""),
                        "num_frozen_points": meta.get("num_frozen_points", ""),
                        "num_bbox_points": meta.get("num_bbox_points", ""),
                        "ground_conf_mean": meta.get("ground_conf_mean", ""),
                        "anomaly": anomaly,
                        "reasons": "|".join(reasons),
                        "evidence_frame": evidence_frame,
                        "evidence_montage": evidence_montage,
                    })

                    if anomaly:
                        event_count += 1
                        event = dict(row)
                        event["event_id"] = f"homography_event_{event_count:06d}"
                        write_jsonl(events_jsonl, event)
                        print(f"[ANOMALY] {event['event_id']} track={tid} score={score:.3f} smooth={gr['score_smooth']:.3f} gp_valid={meta.get('valid_groundpoint_ratio', 0):.2f} reasons={reasons}")
                    elif args.print_every_tubelet:
                        print(
                            f"[TUBELET] #{tubelet_count} track={tid} "
                            f"score={score:.3f}/{args.homography_threshold:.3f} "
                            f"smooth={gr['score_smooth']:.3f} "
                            f"raw={gr['hit_raw']} smooth_hit={gr['hit_smooth']} persist={gr['persistent_hit']} "
                            f"gp_valid={meta.get('valid_groundpoint_ratio', 0):.2f} "
                            f"frozen={meta.get('frozen_groundpoint_ratio', 0):.2f} "
                            f"bbox_gp={meta.get('bbox_groundpoint_ratio', 0):.2f} "
                            f"rejected={meta.get('num_steps_rejected', 0)}/{meta.get('num_steps_total', 0)} "
                            f"features={feat_values}"
                        )

                except Exception as e:
                    latest_label[tid] = [f"ID {tid}", f"HOMO_ERROR {str(e)[:50]}"]
                    print(f"[HOMO_ERROR] tubelet={tubelet_count} track={tid}: {e}")

            if args.display:
                cv2.imshow("live_homography_stage3", resize_for_display(annotated, args.window_width))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")
    finally:
        cap.release()
        if args.display:
            cv2.destroyAllWindows()

    summary = {
        "script": "04_live_homography_gate_rtsp_test_STAGE3_POSE.py",
        "tubelets_processed": int(tubelet_count),
        "events": int(event_count),
        "sample_fps": float(args.sample_fps),
        "tubelet_frames": int(args.tubelet_frames),
        "stride": int(args.stride),
        "max_track_gap_samples": int(args.max_track_gap_samples),
        "homography_npy": str(args.homography_npy),
        "homography_gate_dir": str(args.homography_gate_dir),
        "scaler_path": scaler_path,
        "gmm_path": gmm_path,
        "homography_threshold": float(args.homography_threshold),
        "groundpoint_mode": str(args.groundpoint_mode),
        "pose_model": str(args.pose_model),
        "ankle_conf_threshold": float(args.ankle_conf_threshold),
        "fallback_mode": str(args.fallback_mode),
        "max_freeze_samples": int(args.max_freeze_samples),
        "min_valid_groundpoint_ratio": float(args.min_valid_groundpoint_ratio),
        "trajectory_smoothing": str(args.trajectory_smoothing),
        "trajectory_smoothing_window": int(args.trajectory_smoothing_window),
        "trajectory_smoothing_polyorder": int(args.trajectory_smoothing_polyorder),
        "reject_nonphysical_steps": bool(args.reject_nonphysical_steps),
        "max_plausible_speed": float(args.max_plausible_speed),
        "max_plausible_accel": float(args.max_plausible_accel),
        "smoothing_sigma": float(args.smoothing_sigma),
        "persistence_hits": int(args.persistence_hits),
        "persistence_window": int(args.persistence_window),
        "feature_names": FEATURE_NAMES,
        "output_dir": str(out_dir),
        "note": "Stage-3 homography gate: pose-assisted ankle groundpoint + freeze fallback + Stage-2 smoothing/outlier rejection. Units are floor units, not guaranteed meters.",
    }
    (out_dir / "live_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
