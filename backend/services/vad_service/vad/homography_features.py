from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from .frame_types import SampledPerson

log = logging.getLogger("vad.homography_features")

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


@dataclass
class MacroSample:
    sample: SampledPerson
    t_sample: float
    ground_xy: list[float]
    ground_source: str
    ground_conf: float
    ground_frozen: bool
    ground_meta: dict[str, Any]


@dataclass
class TrackGroundState:
    last_xy: list[float] | None = None
    last_sample_index: int = -10**9


def clamp_box_xyxy(box: Sequence[float], w: int, h: int) -> list[float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    x1 = max(0.0, min(x1, w - 1.0)); y1 = max(0.0, min(y1, h - 1.0))
    x2 = max(0.0, min(x2, w - 1.0)); y2 = max(0.0, min(y2, h - 1.0))
    if x2 <= x1: x2 = min(w - 1.0, x1 + 1.0)
    if y2 <= y1: y2 = min(h - 1.0, y1 + 1.0)
    return [x1, y1, x2, y2]


def bbox_bottom_center(box: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = [float(v) for v in box]
    return (0.5 * (x1 + x2), y2)



def _pad_box_xyxy(box: Sequence[float], w: int, h: int, pad_ratio: float = 0.25, min_crop_size: int = 192) -> list[int]:
    x1, y1, x2, y2 = clamp_box_xyxy(box, w, h)
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


def _choose_best_pose_result(result: Any) -> tuple[np.ndarray | None, np.ndarray | None]:
    if result is None or getattr(result, "keypoints", None) is None:
        return None, None
    kpts = result.keypoints
    xy = getattr(kpts, "xy", None); conf = getattr(kpts, "conf", None)
    if xy is None:
        return None, None
    try: xy_np = xy.detach().cpu().numpy()
    except Exception: xy_np = np.asarray(xy)
    if conf is not None:
        try: conf_np = conf.detach().cpu().numpy()
        except Exception: conf_np = np.asarray(conf)
    else:
        conf_np = np.ones((xy_np.shape[0], xy_np.shape[1]), dtype=np.float32)
    if xy_np.ndim != 3 or xy_np.shape[0] == 0 or xy_np.shape[1] < 17:
        return None, None
    best_idx = int(np.nanargmax(np.nanmean(conf_np, axis=1)))
    return xy_np[best_idx, :17, :2].astype(np.float64), conf_np[best_idx, :17].astype(np.float64)


def _pose_arrays_for_groundpoint(
    sample: SampledPerson,
    *,
    pose_model: Any | None = None,
    pose_imgsz: int = 256,
    pose_conf: float = 0.25,
    pose_crop_pad_ratio: float = 0.25,
    pose_min_crop_size: int = 192,
    device: str = "cuda",
) -> tuple[list[list[float]], list[float], dict[str, Any]]:
    if pose_model is None:
        return sample.keypoints_xy or [], sample.keypoints_conf or [], {"ground_pose_source": "tracker_keypoints"}
    h, w = sample.frame_bgr.shape[:2]
    x1, y1, x2, y2 = _pad_box_xyxy(sample.bbox_xyxy, w, h, pose_crop_pad_ratio, pose_min_crop_size)
    crop = sample.frame_bgr[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return sample.keypoints_xy or [], sample.keypoints_conf or [], {"ground_pose_source": "tracker_keypoints_empty_crop"}
    try:
        results = pose_model.predict(source=[crop], imgsz=int(pose_imgsz), conf=float(pose_conf), device=device, verbose=False)
        xy_crop, conf = _choose_best_pose_result(results[0] if results else None)
        if xy_crop is None or conf is None:
            return sample.keypoints_xy or [], sample.keypoints_conf or [], {"ground_pose_source": "tracker_keypoints_pose_empty", "ground_pose_crop_box": [x1, y1, x2, y2]}
        xy = xy_crop.copy(); xy[:, 0] += float(x1); xy[:, 1] += float(y1)
        return xy.tolist(), conf.tolist(), {"ground_pose_source": "crop_pose_model", "ground_pose_crop_box": [x1, y1, x2, y2]}
    except Exception as e:
        return sample.keypoints_xy or [], sample.keypoints_conf or [], {"ground_pose_source": "tracker_keypoints_pose_error", "ground_pose_error": str(e)[:200], "ground_pose_crop_box": [x1, y1, x2, y2]}

def estimate_groundpoint_from_keypoints(
    sample: SampledPerson,
    track_state: TrackGroundState,
    *,
    ankle_conf_threshold: float = 0.35,
    fallback_mode: str = "freeze_last_valid",
    max_freeze_samples: int = 12,
    groundpoint_mode: str = "pose_ankle",
    pose_model: Any | None = None,
    pose_imgsz: int = 256,
    pose_conf: float = 0.25,
    pose_crop_pad_ratio: float = 0.25,
    pose_min_crop_size: int = 192,
    device: str = "cuda",
) -> tuple[list[float], dict[str, Any]]:
    h, w = sample.frame_bgr.shape[:2]
    bbox = clamp_box_xyxy(sample.bbox_xyxy, w, h)
    bbox_ground = list(bbox_bottom_center(bbox))
    meta = {
        "ground_source": "bbox_bottom",
        "ground_conf": 0.0,
        "ground_frozen": False,
        "left_ankle_conf": 0.0,
        "right_ankle_conf": 0.0,
        "bbox_ground_x": float(bbox_ground[0]),
        "bbox_ground_y": float(bbox_ground[1]),
    }
    if str(groundpoint_mode).lower().strip() == "bbox_bottom":
        track_state.last_xy = bbox_ground; track_state.last_sample_index = int(sample.sample_index)
        meta.update({"ground_source": "bbox_bottom_forced", "groundpoint_mode": "bbox_bottom"})
        return bbox_ground, meta
    xy, conf, pose_meta = _pose_arrays_for_groundpoint(
        sample,
        pose_model=pose_model,
        pose_imgsz=pose_imgsz,
        pose_conf=pose_conf,
        pose_crop_pad_ratio=pose_crop_pad_ratio,
        pose_min_crop_size=pose_min_crop_size,
        device=device,
    )
    meta.update(pose_meta)
    meta["groundpoint_mode"] = str(groundpoint_mode)
    valid_points: list[np.ndarray] = []
    valid_confs: list[float] = []
    if len(xy) >= 17 and len(conf) >= 17:
        la_conf = float(conf[LEFT_ANKLE]); ra_conf = float(conf[RIGHT_ANKLE])
        meta["left_ankle_conf"] = la_conf; meta["right_ankle_conf"] = ra_conf
        for idx, c in ((LEFT_ANKLE, la_conf), (RIGHT_ANKLE, ra_conf)):
            p = np.asarray(xy[idx], dtype=np.float64)
            if c >= ankle_conf_threshold and np.isfinite(p).all():
                valid_points.append(p)
                valid_confs.append(c)
    if len(valid_points) >= 2:
        gp = np.mean(np.vstack(valid_points), axis=0)
        out = [float(gp[0]), float(gp[1])]
        track_state.last_xy = out; track_state.last_sample_index = int(sample.sample_index)
        meta.update({"ground_source": "ankle_midpoint", "ground_conf": float(np.mean(valid_confs)), "ground_frozen": False})
        return out, meta
    if len(valid_points) == 1:
        gp = valid_points[0]
        out = [float(gp[0]), float(gp[1])]
        track_state.last_xy = out; track_state.last_sample_index = int(sample.sample_index)
        meta.update({"ground_source": "single_ankle", "ground_conf": float(valid_confs[0]), "ground_frozen": False})
        return out, meta
    if fallback_mode == "freeze_last_valid" and track_state.last_xy is not None:
        age = int(sample.sample_index - track_state.last_sample_index)
        if age <= int(max_freeze_samples):
            meta.update({"ground_source": "freeze_last_valid", "ground_conf": 0.0, "ground_frozen": True, "freeze_age_samples": age})
            return list(track_state.last_xy), meta
    track_state.last_xy = bbox_ground; track_state.last_sample_index = int(sample.sample_index)
    return bbox_ground, meta


def load_homography_matrix(path_or_dir: Path) -> tuple[np.ndarray, str]:
    candidates: list[Path] = []
    p = Path(path_or_dir)
    if p.is_file():
        candidates.append(p)
    elif p.exists():
        for pattern in ("*homography*.json", "*calibration*.json", "*H*.json"):
            candidates.extend(sorted(p.rglob(pattern)))
    for c in candidates:
        try:
            data = json.loads(c.read_text(encoding="utf-8"))
            for key in ("H", "homography", "homography_matrix", "homography_matrix_json", "matrix"):
                val = data.get(key) if isinstance(data, dict) else None
                if val is not None:
                    arr = np.asarray(val, dtype=np.float64)
                    if arr.shape == (3, 3):
                        return arr, str(c)
            if isinstance(data, list):
                arr = np.asarray(data, dtype=np.float64)
                if arr.shape == (3, 3):
                    return arr, str(c)
        except Exception:
            continue
    raise FileNotFoundError(f"Could not find a 3x3 homography matrix JSON under {path_or_dir}")


def project_points_homography(points_xy: np.ndarray, H: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_xy, dtype=np.float64)
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    homo = np.hstack([pts, ones])
    proj = homo @ H.T
    denom = proj[:, 2:3]
    denom = np.where(np.abs(denom) < 1e-12, np.sign(denom) * 1e-12 + 1e-12, denom)
    return (proj[:, :2] / denom).astype(np.float64)


def _median_smooth_1d(x: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if window <= 1 or len(x) < 3:
        return x.copy()
    window = int(window) + (0 if int(window) % 2 else 1)
    window = min(window, len(x) if len(x) % 2 else len(x) - 1)
    if window < 3:
        return x.copy()
    r = window // 2
    out = np.zeros_like(x)
    for i in range(len(x)):
        out[i] = np.median(x[max(0, i - r): min(len(x), i + r + 1)])
    return out


def _savgol_smooth_1d(x: np.ndarray, window: int, polyorder: int) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if window <= 1 or n < 3:
        return x.copy()
    window = int(window) + (0 if int(window) % 2 else 1)
    window = min(window, n if n % 2 else n - 1)
    if window < 3:
        return x.copy()
    polyorder = int(max(1, min(polyorder, window - 1)))
    r = window // 2
    out = np.zeros_like(x)
    for i in range(n):
        lo = max(0, i - r); hi = min(n, i + r + 1)
        if hi - lo < window:
            if lo == 0: hi = min(n, window)
            elif hi == n: lo = max(0, n - window)
        idx = np.arange(lo, hi, dtype=np.float64)
        y = x[lo:hi]
        t = idx - float(i)
        deg = min(polyorder, len(y) - 1)
        try:
            out[i] = np.polyval(np.polyfit(t, y, deg), 0.0) if deg >= 1 else x[i]
        except Exception:
            out[i] = x[i]
    return out


def smooth_floor_trajectory(points: np.ndarray, method: str = "median_savgol", window: int = 5, polyorder: int = 2) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or method == "none":
        return points.copy()
    if method == "median":
        return np.column_stack([_median_smooth_1d(points[:, 0], window), _median_smooth_1d(points[:, 1], window)])
    if method == "savgol":
        return np.column_stack([_savgol_smooth_1d(points[:, 0], window, polyorder), _savgol_smooth_1d(points[:, 1], window, polyorder)])
    if method == "median_savgol":
        tmp = np.column_stack([_median_smooth_1d(points[:, 0], window), _median_smooth_1d(points[:, 1], window)])
        return np.column_stack([_savgol_smooth_1d(tmp[:, 0], window, polyorder), _savgol_smooth_1d(tmp[:, 1], window, polyorder)])
    raise ValueError(f"Unknown trajectory smoothing method: {method}")


def angle_wrap(delta: float) -> float:
    return (delta + math.pi) % (2 * math.pi) - math.pi


def compute_homography_macro_features(
    tubelet: list[MacroSample],
    H: np.ndarray,
    *,
    stationary_speed_threshold: float = 0.05,
    trajectory_smoothing: str = "median_savgol",
    smoothing_window: int = 5,
    smoothing_polyorder: int = 2,
    reject_nonphysical_steps: bool = True,
    max_plausible_speed: float = 3.0,
    max_plausible_accel: float = 6.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    if len(tubelet) < 2:
        raise ValueError("Need at least 2 samples for macro features")
    img_points = np.asarray([s.ground_xy for s in tubelet], dtype=np.float64)
    bbox_points = np.asarray([bbox_bottom_center(s.sample.bbox_xyxy) for s in tubelet], dtype=np.float64)
    times = np.asarray([float(s.t_sample) for s in tubelet], dtype=np.float64)
    ground_sources = [s.ground_source for s in tubelet]
    floor_raw = project_points_homography(img_points, H)
    bbox_floor_raw = project_points_homography(bbox_points, H)
    floor = smooth_floor_trajectory(floor_raw, method=trajectory_smoothing, window=smoothing_window, polyorder=smoothing_polyorder)
    step_vecs = np.diff(floor, axis=0)
    dt = np.diff(times)
    valid_dt = dt > 1e-6
    step_vecs = step_vecs[valid_dt]
    dt = dt[valid_dt]
    if len(dt) == 0:
        raise ValueError("No valid time deltas in macro tubelet")
    step_dists = np.linalg.norm(step_vecs, axis=1)
    speeds_all = step_dists / np.maximum(dt, 1e-6)
    valid = np.isfinite(speeds_all)
    if reject_nonphysical_steps:
        valid &= speeds_all <= float(max_plausible_speed)
    speeds = speeds_all[valid] if np.any(valid) else np.zeros(1, dtype=np.float64)
    step_dists_used = step_dists[valid] if np.any(valid) else np.zeros(1, dtype=np.float64)
    dt_used = dt[valid] if np.any(valid) else np.ones(1, dtype=np.float64) / 2.5
    if len(speeds) >= 2:
        mid_dt = 0.5 * (dt_used[1:] + dt_used[:-1])
        accels_all = np.abs(np.diff(speeds)) / np.maximum(mid_dt, 1e-6)
        accels = accels_all[np.isfinite(accels_all) & (accels_all <= max_plausible_accel)] if reject_nonphysical_steps else accels_all
        if len(accels) == 0:
            accels = np.array([0.0], dtype=np.float64)
    else:
        accels = np.array([0.0], dtype=np.float64)
    total_path = float(np.sum(step_dists_used))
    displacement = float(np.linalg.norm(floor[-1] - floor[0]))
    straightness = displacement / max(total_path, 1e-6)
    angles = np.arctan2(step_vecs[:, 1], step_vecs[:, 0])
    if len(angles) >= 2:
        deltas = np.asarray([abs(angle_wrap(float(angles[i] - angles[i - 1]))) for i in range(1, len(angles))], dtype=np.float64)
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
    raw_step_dists = np.linalg.norm(np.diff(floor_raw, axis=0), axis=1) if len(floor_raw) >= 2 else np.array([], dtype=np.float64)
    bbox_raw_step_dists = np.linalg.norm(np.diff(bbox_floor_raw, axis=0), axis=1) if len(bbox_floor_raw) >= 2 else np.array([], dtype=np.float64)
    meta = {
        "macro_feature_names": FEATURE_NAMES,
        "macro_feature_values": {name: float(feature[i]) for i, name in enumerate(FEATURE_NAMES)},
        "image_points_used": img_points.tolist(),
        "bbox_bottom_points": bbox_points.tolist(),
        "floor_points_raw": floor_raw.tolist(),
        "bbox_floor_points_raw": bbox_floor_raw.tolist(),
        "floor_points_smoothed": floor.tolist(),
        "step_speeds_used": speeds.astype(float).tolist(),
        "step_speeds_all_after_smoothing": speeds_all.astype(float).tolist(),
        "step_accels_used": accels.astype(float).tolist(),
        "valid_groundpoint_ratio": float(np.mean(valid_gp)) if valid_gp else 0.0,
        "frozen_groundpoint_ratio": float(np.mean(frozen_gp)) if frozen_gp else 0.0,
        "bbox_groundpoint_ratio": float(np.mean(bbox_gp)) if bbox_gp else 0.0,
        "num_ankle_points_used": int(sum(valid_gp)),
        "num_frozen_points": int(sum(frozen_gp)),
        "num_bbox_points": int(sum(bbox_gp)),
        "raw_path_floor_units": float(np.sum(raw_step_dists)) if len(raw_step_dists) else 0.0,
        "bbox_raw_path_floor_units": float(np.sum(bbox_raw_step_dists)) if len(bbox_raw_step_dists) else 0.0,
        "total_path_floor_units": total_path,
        "displacement_floor_units": displacement,
    }
    return feature.reshape(1, -1), meta
