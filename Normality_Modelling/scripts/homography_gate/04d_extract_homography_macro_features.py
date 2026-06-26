#!/usr/bin/env python3
r"""
04d_extract_homography_macro_features.py

Macro-scale kinematic feature extractor for video anomaly detection.

Purpose
-------
Consumes motion_tubelet_tracks.jsonl produced by:
  04a_extract_motion_tubelet_tracks_from_raw_videos_v1_2_fast.py

For each accepted person tubelet, this script:
  1) reads bbox bottom-center points (feet proxy) from the track JSONL,
  2) projects those image points to real-world floor coordinates using a homography,
  3) computes macro movement features such as real-world speed, acceleration,
     path length, displacement, straightness, and direction change,
  4) saves one feature vector per tubelet for a later GMM/density gate.

This is intentionally independent from RAFT and VideoMAE.

Expected homography convention
------------------------------
The 3x3 homography H must map IMAGE PIXEL coordinates to WORLD/FLOOR coordinates:

    [X, Y, W]^T = H @ [x_pixel, y_pixel, 1]^T
    X_world = X / W
    Y_world = Y / W

Ideally X/Y are in meters. If your homography maps to floor-plan pixels or arbitrary
units, use --world_scale_m_per_unit to convert them to meters.

Typical outputs
---------------
  homography_macro_features.npy            shape: [N, D]
  homography_macro_metadata.csv
  homography_macro_feature_names.json
  homography_macro_extraction_summary.json
  homography_macro_failed.csv
  logs/homography_macro_extraction.log

Example PowerShell
------------------
python .\04d_extract_homography_macro_features.py --tracks_jsonl "D:\Embeddings_Distribution\normality_models\motion_tubelets_v1_2_fast\motion_tubelet_tracks.jsonl" --output_dir "D:\Embeddings_Distribution\normality_models\homography_macro_v1" --homography_npy "D:\Embeddings_Distribution\calibration\camera_001_homography.npy" --world_scale_m_per_unit 1.0 --overwrite

If you do not yet have a calibrated homography, create a template:
python .\04d_extract_homography_macro_features.py --write_config_template "D:\Embeddings_Distribution\calibration\homography_config_template.json"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None


SCHEMA_VERSION = "homography_macro_features_v1.0"

FEATURE_NAMES = [
    # Position/displacement/path
    "macro_duration_sec",
    "macro_displacement_m",
    "macro_path_length_m",
    "macro_straightness_ratio",
    # Velocity magnitude
    "macro_speed_mean_mps",
    "macro_speed_median_mps",
    "macro_speed_std_mps",
    "macro_speed_max_mps",
    "macro_speed_p95_mps",
    # Velocity components
    "macro_vx_mean_mps",
    "macro_vy_mean_mps",
    "macro_vx_std_mps",
    "macro_vy_std_mps",
    # Acceleration
    "macro_accel_mean_mps2",
    "macro_accel_median_mps2",
    "macro_accel_max_mps2",
    "macro_accel_p95_mps2",
    # Direction / trajectory shape
    "macro_direction_change_mean_rad",
    "macro_direction_change_max_rad",
    "macro_stationary_step_ratio",
    # Quality / validity
    "macro_valid_point_ratio",
    "macro_valid_step_ratio",
    "macro_mean_dt_sec",
    "macro_max_dt_sec",
    "macro_world_x_min_m",
    "macro_world_x_max_m",
    "macro_world_y_min_m",
    "macro_world_y_max_m",
]


@dataclass
class HomographySpec:
    camera_id: str
    H: np.ndarray
    world_scale_m_per_unit: float = 1.0
    description: str = ""


# ---------------------------------------------------------------------------
# Logging / IO helpers
# ---------------------------------------------------------------------------

def setup_logging(output_dir: Path) -> None:
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "homography_macro_extraction.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def safe_mkdir_output(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    protected = [
        output_dir / "homography_macro_features.npy",
        output_dir / "homography_macro_metadata.csv",
        output_dir / "homography_macro_extraction_summary.json",
    ]
    existing = [p for p in protected if p.exists()]
    if existing and not overwrite:
        joined = "\n".join(str(p) for p in existing)
        raise FileExistsError(
            "Output files already exist. Use --overwrite or choose a new --output_dir:\n" + joined
        )


def read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at line {line_no}: {e}") from e
            obj["_jsonl_line_no"] = line_no
            yield obj


def count_jsonl_rows(path: Path) -> int:
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_failed_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "tubelet_id",
        "video_id",
        "track_id",
        "jsonl_line_no",
        "reason",
        "detail",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


# ---------------------------------------------------------------------------
# Homography loading
# ---------------------------------------------------------------------------

def validate_homography(H: np.ndarray, label: str) -> np.ndarray:
    H = np.asarray(H, dtype=np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"Homography {label} must be 3x3, got shape {H.shape}")
    if not np.all(np.isfinite(H)):
        raise ValueError(f"Homography {label} contains non-finite values")
    det = float(np.linalg.det(H))
    if abs(det) < 1e-12:
        raise ValueError(f"Homography {label} is near-singular; determinant={det}")
    return H


def load_single_homography(args: argparse.Namespace) -> HomographySpec:
    if not args.homography_npy:
        raise ValueError("Provide --homography_npy or --homography_config_json")
    path = Path(args.homography_npy)
    H = validate_homography(np.load(path), str(path))
    return HomographySpec(
        camera_id=args.default_camera_id,
        H=H,
        world_scale_m_per_unit=float(args.world_scale_m_per_unit),
        description=f"single_homography_npy:{path}",
    )


def load_homography_config(path: Path, default_scale: float) -> Dict[str, HomographySpec]:
    """Load a flexible config JSON.

    Supported schema:
    {
      "homographies": {
        "camera_001": {
          "homography_npy": "D:/.../camera_001_homography.npy",
          "world_scale_m_per_unit": 1.0,
          "description": "pixel to meters"
        },
        "camera_002": {
          "H": [[...], [...], [...]],
          "world_scale_m_per_unit": 0.01
        }
      },
      "video_id_to_camera_id": {
        "20260315_093203_tp00034": "camera_001"
      },
      "default_camera_id": "camera_001"
    }

    This function returns only camera_id -> HomographySpec. The video mapping is read
    separately with load_video_camera_mapping().
    """
    with path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    specs: Dict[str, HomographySpec] = {}
    homos = cfg.get("homographies", {})
    if not isinstance(homos, dict) or not homos:
        raise ValueError("homography_config_json must contain non-empty 'homographies' object")

    base_dir = path.parent
    for camera_id, item in homos.items():
        if not isinstance(item, dict):
            raise ValueError(f"Config entry for {camera_id} must be an object")
        if "homography_npy" in item:
            h_path = Path(item["homography_npy"])
            if not h_path.is_absolute():
                h_path = base_dir / h_path
            H = np.load(h_path)
            desc = f"npy:{h_path}"
        elif "H" in item:
            H = np.asarray(item["H"], dtype=np.float64)
            desc = "inline_matrix"
        else:
            raise ValueError(f"Config entry for {camera_id} must contain 'homography_npy' or 'H'")

        specs[str(camera_id)] = HomographySpec(
            camera_id=str(camera_id),
            H=validate_homography(H, str(camera_id)),
            world_scale_m_per_unit=float(item.get("world_scale_m_per_unit", default_scale)),
            description=str(item.get("description", desc)),
        )
    return specs


def load_video_camera_mapping(path: Optional[str]) -> Tuple[Dict[str, str], Optional[str]]:
    if not path:
        return {}, None
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    mapping = cfg.get("video_id_to_camera_id", {}) or {}
    default_camera_id = cfg.get("default_camera_id")
    return {str(k): str(v) for k, v in mapping.items()}, str(default_camera_id) if default_camera_id else None


def make_template_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "description": "Template. Homography must map image pixel coordinates (x,y) to floor/world coordinates. Prefer meters.",
        "default_camera_id": "camera_001",
        "homographies": {
            "camera_001": {
                "homography_npy": "camera_001_homography.npy",
                "world_scale_m_per_unit": 1.0,
                "description": "image pixels -> floor coordinates in meters"
            }
        },
        "video_id_to_camera_id": {
            "20260315_093203_tp00034": "camera_001",
            "20260315_104219_tp00035": "camera_001"
        },
        "calibration_notes": {
            "image_points": "Use floor contact points visible in the video frame, e.g. tile/lab floor corners.",
            "world_points": "Corresponding real floor coordinates in meters on a flat 2D plane.",
            "opencv_hint": "H, mask = cv2.findHomography(image_points_px, world_points_m, method=0)"
        }
    }
    write_json(path, template)


# ---------------------------------------------------------------------------
# Geometry / feature extraction
# ---------------------------------------------------------------------------

def project_points(points_xy: np.ndarray, H: np.ndarray, scale: float) -> np.ndarray:
    """Project image points [N,2] through H into world coordinates."""
    pts = np.asarray(points_xy, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(f"points_xy must be [N,2], got {pts.shape}")
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    ph = np.concatenate([pts, ones], axis=1)  # [N,3]
    wh = ph @ H.T
    denom = wh[:, 2]
    out = np.full((pts.shape[0], 2), np.nan, dtype=np.float64)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-12)
    out[valid, 0] = (wh[valid, 0] / denom[valid]) * scale
    out[valid, 1] = (wh[valid, 1] / denom[valid]) * scale
    return out


def angle_between_vectors_rad(a: np.ndarray, b: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    """Return unsigned angle between paired vectors a,b as radians."""
    dot = np.sum(a * b, axis=1)
    na = np.linalg.norm(a, axis=1)
    nb = np.linalg.norm(b, axis=1)
    denom = np.maximum(na * nb, eps)
    cosv = np.clip(dot / denom, -1.0, 1.0)
    angles = np.arccos(cosv)
    valid = (na > eps) & (nb > eps) & np.isfinite(angles)
    return angles[valid]


def finite_percentile(x: np.ndarray, q: float, default: float = 0.0) -> float:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float(default)
    return float(np.percentile(x, q))


def finite_stat(x: np.ndarray, fn: str, default: float = 0.0) -> float:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return float(default)
    if fn == "mean":
        return float(np.mean(x))
    if fn == "median":
        return float(np.median(x))
    if fn == "std":
        return float(np.std(x))
    if fn == "max":
        return float(np.max(x))
    if fn == "min":
        return float(np.min(x))
    raise ValueError(fn)


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
    """Small dependency-free Savitzky-Golay-style local polynomial smoother."""
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


def smooth_floor_trajectory(points: np.ndarray, method: str, window: int, polyorder: int) -> np.ndarray:
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


def angle_wrap(delta: float) -> float:
    return (delta + math.pi) % (2 * math.pi) - math.pi


def compute_macro_features(
    world_xy: np.ndarray,
    times_sec: np.ndarray,
    stationary_speed_threshold_mps: float,
    max_reasonable_speed_mps: Optional[float],
    trajectory_smoothing: str = "median_savgol",
    smoothing_window: int = 5,
    smoothing_polyorder: int = 2,
    reject_nonphysical_steps: bool = True,
    max_plausible_speed_mps: float = 3.0,
    max_plausible_accel_mps2: float = 6.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Compute macro kinematic features for one tubelet.

    Stage-3 offline/live alignment:
    - points are expected to be pose-assisted ground points when available;
    - the projected floor trajectory is smoothed before derivatives;
    - non-physical speed and acceleration steps are excluded, not clipped.
    """
    pts_raw = np.asarray(world_xy, dtype=np.float64)
    t = np.asarray(times_sec, dtype=np.float64)

    if pts_raw.shape[0] != t.shape[0]:
        raise ValueError(f"points/times length mismatch: {pts_raw.shape[0]} vs {t.shape[0]}")
    if pts_raw.shape[0] < 2:
        raise ValueError("Need at least 2 points")

    point_valid = np.isfinite(pts_raw).all(axis=1) & np.isfinite(t)
    valid_point_ratio = float(np.mean(point_valid))

    pts = pts_raw.copy()
    # Fill isolated invalid points by nearest valid value so smoothing can operate; validity is still reported.
    if not np.all(point_valid):
        valid_idx = np.where(point_valid)[0]
        if valid_idx.size < 2:
            raise ValueError("Fewer than 2 valid points after homography projection")
        for i in range(len(pts)):
            if not point_valid[i]:
                nearest = valid_idx[int(np.argmin(np.abs(valid_idx - i)))]
                pts[i] = pts[nearest]

    pts_smooth = smooth_floor_trajectory(
        pts,
        method=trajectory_smoothing,
        window=int(smoothing_window),
        polyorder=int(smoothing_polyorder),
    )

    p0 = pts_smooth[:-1]
    p1 = pts_smooth[1:]
    dt = t[1:] - t[:-1]
    step_valid = point_valid[:-1] & point_valid[1:] & np.isfinite(dt) & (dt > 1e-6)
    valid_step_ratio_before_physics = float(np.mean(step_valid)) if step_valid.size else 0.0
    if not np.any(step_valid):
        raise ValueError("No valid time/point steps after homography projection")

    dxy_all = p1 - p0
    dxy = dxy_all[step_valid]
    dt_valid = dt[step_valid]
    vel = dxy / np.maximum(dt_valid[:, None], 1e-6)
    speed = np.linalg.norm(vel, axis=1)

    speed_mask = np.isfinite(speed)
    effective_speed_cap = None
    if reject_nonphysical_steps:
        effective_speed_cap = float(max_plausible_speed_mps)
    elif max_reasonable_speed_mps is not None and max_reasonable_speed_mps > 0:
        effective_speed_cap = float(max_reasonable_speed_mps)
    if effective_speed_cap is not None and effective_speed_cap > 0:
        speed_mask &= speed <= effective_speed_cap

    rejected_speed_steps = int(len(speed) - int(np.sum(speed_mask)))
    vel = vel[speed_mask]
    dxy = dxy[speed_mask]
    dt_valid = dt_valid[speed_mask]
    speed = speed[speed_mask]
    if speed.size == 0:
        # Keep the tubelet but make it explicitly stationary after rejecting impossible jumps.
        vel = np.zeros((1, 2), dtype=np.float64)
        dxy = np.zeros((1, 2), dtype=np.float64)
        dt_valid = np.array([1.0 / 2.5], dtype=np.float64)
        speed = np.array([0.0], dtype=np.float64)

    duration = float(np.nanmax(t[point_valid]) - np.nanmin(t[point_valid])) if np.any(point_valid) else 0.0

    # IMPORTANT FEATURE-CONTRACT FIX
    # ------------------------------
    # After speed/physics filtering, `dxy` contains only the accepted physical
    # motion steps. Therefore path length, displacement, and straightness must
    # all be computed from this SAME accepted step set.
    #
    # Do NOT compute displacement as ||last_point - first_point|| here, because
    # rejected "teleport"/tracking-jitter steps can still move the endpoint while
    # being absent from path_length. That mismatch can create impossible
    # straightness ratios (> 1.0) and poison the GMM feature distribution.
    step_vecs_used = dxy if dxy.size else np.zeros((0, 2), dtype=np.float64)
    step_dists_used = np.linalg.norm(step_vecs_used, axis=1) if len(step_vecs_used) else np.zeros(0, dtype=np.float64)
    path_length = float(np.sum(step_dists_used))
    displacement = float(np.linalg.norm(np.sum(step_vecs_used, axis=0))) if len(step_vecs_used) else 0.0
    straightness = float(displacement / path_length) if path_length > 1e-9 else 0.0
    straightness = float(np.clip(straightness, 0.0, 1.0))

    accel_mag_all = np.array([], dtype=np.float64)
    accel_mag = np.array([], dtype=np.float64)
    rejected_accel_steps = 0
    if vel.shape[0] >= 2:
        dt_mid = (dt_valid[1:] + dt_valid[:-1]) / 2.0
        accel_vec = (vel[1:] - vel[:-1]) / np.maximum(dt_mid[:, None], 1e-6)
        accel_mag_all = np.linalg.norm(accel_vec, axis=1)
        if reject_nonphysical_steps:
            accel_mask = np.isfinite(accel_mag_all) & (accel_mag_all <= float(max_plausible_accel_mps2))
            rejected_accel_steps = int(len(accel_mag_all) - int(np.sum(accel_mask)))
            accel_mag = accel_mag_all[accel_mask]
        else:
            accel_mag = accel_mag_all[np.isfinite(accel_mag_all)]
    if accel_mag.size == 0:
        accel_mag = np.array([0.0], dtype=np.float64)

    dir_changes = np.array([], dtype=np.float64)
    if vel.shape[0] >= 2:
        angles = np.arctan2(vel[:, 1], vel[:, 0])
        dir_changes = np.array([abs(angle_wrap(float(angles[i] - angles[i - 1]))) for i in range(1, len(angles))], dtype=np.float64)

    stationary_ratio = float(np.mean(speed <= stationary_speed_threshold_mps)) if speed.size else 0.0
    world_valid = pts_smooth[point_valid]
    x_min = finite_stat(world_valid[:, 0], "min") if world_valid.size else 0.0
    x_max = finite_stat(world_valid[:, 0], "max") if world_valid.size else 0.0
    y_min = finite_stat(world_valid[:, 1], "min") if world_valid.size else 0.0
    y_max = finite_stat(world_valid[:, 1], "max") if world_valid.size else 0.0

    total_possible_steps = max(1, len(t) - 1)
    used_step_ratio = float(len(speed) / total_possible_steps)

    feats = np.array([
        duration,
        displacement,
        path_length,
        straightness,
        finite_stat(speed, "mean"),
        finite_stat(speed, "median"),
        finite_stat(speed, "std"),
        finite_stat(speed, "max"),
        finite_percentile(speed, 95),
        finite_stat(vel[:, 0], "mean") if vel.size else 0.0,
        finite_stat(vel[:, 1], "mean") if vel.size else 0.0,
        finite_stat(vel[:, 0], "std") if vel.size else 0.0,
        finite_stat(vel[:, 1], "std") if vel.size else 0.0,
        finite_stat(accel_mag, "mean"),
        finite_stat(accel_mag, "median"),
        finite_stat(accel_mag, "max"),
        finite_percentile(accel_mag, 95),
        finite_stat(dir_changes, "mean"),
        finite_stat(dir_changes, "max"),
        stationary_ratio,
        valid_point_ratio,
        used_step_ratio,
        finite_stat(dt_valid, "mean"),
        finite_stat(dt_valid, "max"),
        x_min,
        x_max,
        y_min,
        y_max,
    ], dtype=np.float32)

    diagnostics = {
        "valid_points": int(np.sum(point_valid)),
        "valid_steps_before_physics": int(np.sum(step_valid)),
        "valid_steps": int(speed.size),
        "rejected_speed_steps": rejected_speed_steps,
        "rejected_accel_steps": rejected_accel_steps,
        "valid_step_ratio_before_physics": valid_step_ratio_before_physics,
        "valid_step_ratio_after_physics": used_step_ratio,
        "duration_sec": duration,
        "displacement_m": displacement,
        "path_length_m": path_length,
        "straightness_ratio": straightness,
        "speed_mean_mps": float(feats[4]),
        "speed_max_mps": float(feats[7]),
        "trajectory_smoothing": trajectory_smoothing,
        "smoothing_window": int(smoothing_window),
        "smoothing_polyorder": int(smoothing_polyorder),
        "reject_nonphysical_steps": bool(reject_nonphysical_steps),
        "max_plausible_speed_mps": float(max_plausible_speed_mps),
        "max_plausible_accel_mps2": float(max_plausible_accel_mps2),
    }
    return feats, diagnostics


def choose_points(record: Dict[str, Any], point_field: str) -> np.ndarray:
    if point_field not in record:
        # fallback for v1.1/v1.2 04a outputs
        fallback_fields = [
            "bbox_bottom_centers_xy_clipped",
            "bbox_bottom_centers_xy",
            "bbox_centers_xy",
        ]
        for ff in fallback_fields:
            if ff in record:
                point_field = ff
                break
        else:
            raise ValueError(f"Missing point field '{point_field}' and no fallback point fields found")
    pts = np.asarray(record[point_field], dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError(f"{point_field} must be a list of [x,y] points, got shape {pts.shape}")
    return pts


def choose_times(record: Dict[str, Any]) -> np.ndarray:
    if "source_times_sec" in record:
        t = np.asarray(record["source_times_sec"], dtype=np.float64)
    elif "source_frame_indices" in record and "source_fps" in record:
        frames = np.asarray(record["source_frame_indices"], dtype=np.float64)
        fps = float(record["source_fps"])
        if fps <= 0:
            raise ValueError("source_fps must be positive when source_times_sec is absent")
        t = frames / fps
    else:
        raise ValueError("Missing source_times_sec and cannot derive time from source_frame_indices/source_fps")
    if t.ndim != 1:
        raise ValueError(f"source_times_sec must be 1D, got shape {t.shape}")
    return t


def camera_for_record(
    record: Dict[str, Any],
    video_map: Dict[str, str],
    default_camera_id: str,
) -> str:
    # Prefer explicit camera_id if future 04a versions include it.
    if record.get("camera_id"):
        return str(record["camera_id"])
    video_id = str(record.get("video_id", ""))
    if video_id in video_map:
        return video_map[video_id]
    return default_camera_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract homography-based macro real-world speed features from motion tubelets."
    )

    p.add_argument("--tracks_jsonl", type=str, help="Path to motion_tubelet_tracks.jsonl")
    p.add_argument("--output_dir", type=str, help="Output folder")

    h = p.add_mutually_exclusive_group(required=False)
    h.add_argument("--homography_npy", type=str, help="Single 3x3 .npy homography for all videos")
    h.add_argument("--homography_config_json", type=str, help="JSON config for one or more camera homographies")

    p.add_argument("--default_camera_id", type=str, default="camera_001")
    p.add_argument("--world_scale_m_per_unit", type=float, default=1.0,
                   help="Multiply projected world coordinates by this value to convert units to meters")
    p.add_argument("--point_field", type=str, default="ground_points_xy",
                   help="Track field to project. Stage-3 default is pose-assisted ground_points_xy; bbox fields are fallback only.")
    p.add_argument("--stationary_speed_threshold_mps", type=float, default=0.05,
                   help="Steps below this speed are counted as stationary")
    p.add_argument("--max_reasonable_speed_mps", type=float, default=3.0,
                   help="Backward-compatible speed cap. Stage-3 default is 3.0. Use <=0 to disable when --no_reject_nonphysical_steps is set.")
    p.add_argument("--trajectory_smoothing", type=str, default="median_savgol", choices=["none", "median", "savgol", "median_savgol"],
                   help="Smooth projected floor trajectory before derivatives.")
    p.add_argument("--trajectory_smoothing_window", type=int, default=5)
    p.add_argument("--trajectory_smoothing_polyorder", type=int, default=2)
    p.add_argument("--max_plausible_speed_mps", type=float, default=3.0)
    p.add_argument("--max_plausible_accel_mps2", type=float, default=6.0)
    p.add_argument("--no_reject_nonphysical_steps", action="store_true",
                   help="Disable Stage-3 non-physical speed/acceleration rejection.")
    p.add_argument("--min_valid_point_ratio", type=float, default=0.90,
                   help="Reject tubelets with lower valid homography point ratio")
    p.add_argument("--min_valid_step_ratio", type=float, default=0.80,
                   help="Reject tubelets with lower valid motion step ratio")

    p.add_argument("--limit_tubelets", type=int, default=None)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no_progress", action="store_true")

    p.add_argument("--write_config_template", type=str, default=None,
                   help="Write a homography config JSON template and exit")

    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.write_config_template:
        make_template_config(Path(args.write_config_template))
        print(f"Wrote template: {args.write_config_template}")
        return 0

    if not args.tracks_jsonl or not args.output_dir:
        raise SystemExit("--tracks_jsonl and --output_dir are required unless using --write_config_template")

    tracks_jsonl = Path(args.tracks_jsonl)
    output_dir = Path(args.output_dir)
    safe_mkdir_output(output_dir, args.overwrite)
    setup_logging(output_dir)

    if not tracks_jsonl.exists():
        raise FileNotFoundError(tracks_jsonl)

    # Load homographies and video mapping.
    if args.homography_config_json:
        config_path = Path(args.homography_config_json)
        homographies = load_homography_config(config_path, args.world_scale_m_per_unit)
        video_map, cfg_default_camera = load_video_camera_mapping(str(config_path))
        default_camera_id = cfg_default_camera or args.default_camera_id
    else:
        spec = load_single_homography(args)
        homographies = {spec.camera_id: spec}
        video_map = {}
        default_camera_id = spec.camera_id

    if default_camera_id not in homographies:
        raise ValueError(
            f"default_camera_id '{default_camera_id}' has no homography. Available: {sorted(homographies)}"
        )

    max_reasonable_speed = args.max_reasonable_speed_mps
    if max_reasonable_speed is not None and max_reasonable_speed <= 0:
        max_reasonable_speed = None

    total_rows = count_jsonl_rows(tracks_jsonl)
    if args.limit_tubelets is not None:
        total_iter = min(total_rows, int(args.limit_tubelets))
    else:
        total_iter = total_rows

    logging.info("Starting homography macro extraction")
    logging.info("tracks_jsonl=%s", tracks_jsonl)
    logging.info("output_dir=%s", output_dir)
    logging.info("homographies=%s", sorted(homographies.keys()))
    logging.info("default_camera_id=%s", default_camera_id)
    logging.info("total_rows=%d limit=%s", total_rows, args.limit_tubelets)

    features: List[np.ndarray] = []
    metadata_rows: List[Dict[str, Any]] = []
    failed_rows: List[Dict[str, Any]] = []
    camera_counts = defaultdict(int)
    video_counts = defaultdict(int)

    iterator = read_jsonl(tracks_jsonl)
    if tqdm is not None and not args.no_progress:
        iterator = tqdm(iterator, total=total_iter, desc="Homography macro", unit="tubelet")

    start = time.time()
    processed = 0
    accepted = 0

    for record in iterator:
        if args.limit_tubelets is not None and processed >= int(args.limit_tubelets):
            break
        processed += 1

        tubelet_id = record.get("tubelet_id", "")
        video_id = record.get("video_id", "")
        track_id = record.get("track_id", "")
        line_no = record.get("_jsonl_line_no", "")

        try:
            camera_id = camera_for_record(record, video_map, default_camera_id)
            if camera_id not in homographies:
                raise ValueError(f"No homography for camera_id='{camera_id}'")
            spec = homographies[camera_id]

            points_xy = choose_points(record, args.point_field)
            times_sec = choose_times(record)
            if points_xy.shape[0] != times_sec.shape[0]:
                raise ValueError(
                    f"points/time length mismatch: {points_xy.shape[0]} points vs {times_sec.shape[0]} times"
                )

            world_xy = project_points(points_xy, spec.H, spec.world_scale_m_per_unit)
            feat, diag = compute_macro_features(
                world_xy=world_xy,
                times_sec=times_sec,
                stationary_speed_threshold_mps=float(args.stationary_speed_threshold_mps),
                max_reasonable_speed_mps=max_reasonable_speed,
                trajectory_smoothing=str(args.trajectory_smoothing),
                smoothing_window=int(args.trajectory_smoothing_window),
                smoothing_polyorder=int(args.trajectory_smoothing_polyorder),
                reject_nonphysical_steps=not bool(args.no_reject_nonphysical_steps),
                max_plausible_speed_mps=float(args.max_plausible_speed_mps),
                max_plausible_accel_mps2=float(args.max_plausible_accel_mps2),
            )

            valid_point_ratio = float(feat[20])
            valid_step_ratio = float(feat[21])
            if valid_point_ratio < args.min_valid_point_ratio:
                raise ValueError(f"valid_point_ratio too low: {valid_point_ratio:.3f}")
            if valid_step_ratio < args.min_valid_step_ratio:
                raise ValueError(f"valid_step_ratio too low: {valid_step_ratio:.3f}")

            features.append(feat)
            accepted += 1
            camera_counts[camera_id] += 1
            video_counts[str(video_id)] += 1

            metadata_rows.append({
                "tubelet_id": tubelet_id,
                "video_id": video_id,
                "track_id": track_id,
                "camera_id": camera_id,
                "video_path": record.get("video_path", ""),
                "start_frame": record.get("start_frame", ""),
                "end_frame": record.get("end_frame", ""),
                "start_time_sec": record.get("start_time_sec", ""),
                "end_time_sec": record.get("end_time_sec", ""),
                "source_fps": record.get("source_fps", ""),
                "effective_sample_fps": record.get("effective_sample_fps", ""),
                "tubelet_frames": record.get("tubelet_frames", ""),
                "mean_conf": record.get("mean_conf", ""),
                "min_conf": record.get("min_conf", ""),
                "mean_iou": record.get("mean_iou", ""),
                "max_center_jump_ratio": record.get("max_center_jump_ratio", ""),
                "macro_valid_points": diag["valid_points"],
                "macro_valid_steps": diag["valid_steps"],
                "macro_speed_mean_mps": diag["speed_mean_mps"],
                "macro_speed_max_mps": diag["speed_max_mps"],
                "macro_displacement_m": diag.get("displacement_m", ""),
                "macro_path_length_m": diag["path_length_m"],
                "macro_straightness_ratio": diag.get("straightness_ratio", ""),
                "macro_rejected_speed_steps": diag.get("rejected_speed_steps", ""),
                "macro_rejected_accel_steps": diag.get("rejected_accel_steps", ""),
                "trajectory_smoothing": diag.get("trajectory_smoothing", ""),
                "trajectory_smoothing_window": diag.get("smoothing_window", ""),
                "trajectory_smoothing_polyorder": diag.get("smoothing_polyorder", ""),
                "reject_nonphysical_steps": diag.get("reject_nonphysical_steps", ""),
                "max_plausible_speed_mps": diag.get("max_plausible_speed_mps", ""),
                "max_plausible_accel_mps2": diag.get("max_plausible_accel_mps2", ""),
                "groundpoint_valid_pose_ratio": record.get("groundpoint_valid_pose_ratio", ""),
                "groundpoint_frozen_ratio": record.get("groundpoint_frozen_ratio", ""),
                "groundpoint_bbox_fallback_ratio": record.get("groundpoint_bbox_fallback_ratio", ""),
                "groundpoint_source_counts": json.dumps(record.get("groundpoint_source_counts", {}), ensure_ascii=False),
                "groundpoint_policy": json.dumps(record.get("groundpoint_policy", {}), ensure_ascii=False),
                "num_ankle_points_used": int(record.get("groundpoint_source_counts", {}).get("ankle_midpoint", 0)) + int(record.get("groundpoint_source_counts", {}).get("single_ankle", 0)) if isinstance(record.get("groundpoint_source_counts", {}), dict) else "",
                "num_frozen_points": int(record.get("groundpoint_source_counts", {}).get("freeze_last_valid", 0)) if isinstance(record.get("groundpoint_source_counts", {}), dict) else "",
                "num_bbox_points": int(record.get("groundpoint_source_counts", {}).get("bbox_bottom", 0)) if isinstance(record.get("groundpoint_source_counts", {}), dict) else "",
            })

        except Exception as e:
            failed_rows.append({
                "tubelet_id": tubelet_id,
                "video_id": video_id,
                "track_id": track_id,
                "jsonl_line_no": line_no,
                "reason": type(e).__name__,
                "detail": str(e),
            })

    elapsed = time.time() - start

    if features:
        feature_arr = np.stack(features, axis=0).astype(np.float32)
    else:
        feature_arr = np.zeros((0, len(FEATURE_NAMES)), dtype=np.float32)

    np.save(output_dir / "homography_macro_features.npy", feature_arr)
    write_json(output_dir / "homography_macro_feature_names.json", {
        "schema_version": SCHEMA_VERSION,
        "feature_names": FEATURE_NAMES,
        "feature_dim": len(FEATURE_NAMES),
        "units": "meters, seconds, radians where indicated",
    })

    metadata_path = output_dir / "homography_macro_metadata.csv"
    meta_fields = [
        "tubelet_id", "video_id", "track_id", "camera_id", "video_path",
        "start_frame", "end_frame", "start_time_sec", "end_time_sec",
        "source_fps", "effective_sample_fps", "tubelet_frames",
        "mean_conf", "min_conf", "mean_iou", "max_center_jump_ratio",
        "macro_valid_points", "macro_valid_steps",
        "macro_speed_mean_mps", "macro_speed_max_mps",
        "macro_displacement_m", "macro_path_length_m", "macro_straightness_ratio",
        "macro_rejected_speed_steps", "macro_rejected_accel_steps",
        "trajectory_smoothing", "trajectory_smoothing_window", "trajectory_smoothing_polyorder",
        "reject_nonphysical_steps", "max_plausible_speed_mps", "max_plausible_accel_mps2",
        "groundpoint_valid_pose_ratio", "groundpoint_frozen_ratio", "groundpoint_bbox_fallback_ratio",
        "groundpoint_source_counts", "groundpoint_policy",
        "num_ankle_points_used", "num_frozen_points", "num_bbox_points",
    ]
    with metadata_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=meta_fields)
        w.writeheader()
        for row in metadata_rows:
            w.writerow({k: row.get(k, "") for k in meta_fields})

    write_failed_csv(output_dir / "homography_macro_failed.csv", failed_rows)

    summary = {
        "script": Path(__file__).name,
        "schema_version": SCHEMA_VERSION,
        "created_at_unix": time.time(),
        "elapsed_sec": elapsed,
        "tracks_jsonl": str(tracks_jsonl),
        "output_dir": str(output_dir),
        "settings": {
            "point_field": args.point_field,
            "default_camera_id": default_camera_id,
            "world_scale_m_per_unit": args.world_scale_m_per_unit,
            "stationary_speed_threshold_mps": args.stationary_speed_threshold_mps,
            "max_reasonable_speed_mps": args.max_reasonable_speed_mps,
            "min_valid_point_ratio": args.min_valid_point_ratio,
            "min_valid_step_ratio": args.min_valid_step_ratio,
            "limit_tubelets": args.limit_tubelets,
        },
        "homographies": {
            cid: {
                "camera_id": spec.camera_id,
                "world_scale_m_per_unit": spec.world_scale_m_per_unit,
                "description": spec.description,
                "determinant": float(np.linalg.det(spec.H)),
            }
            for cid, spec in homographies.items()
        },
        "totals": {
            "jsonl_rows_total": total_rows,
            "processed_tubelets": processed,
            "accepted_tubelets": int(feature_arr.shape[0]),
            "failed_tubelets": len(failed_rows),
            "feature_dim": int(feature_arr.shape[1]),
        },
        "camera_counts": dict(camera_counts),
        "video_count": len(video_counts),
        "outputs": {
            "features_npy": str(output_dir / "homography_macro_features.npy"),
            "metadata_csv": str(metadata_path),
            "feature_names_json": str(output_dir / "homography_macro_feature_names.json"),
            "failed_csv": str(output_dir / "homography_macro_failed.csv"),
            "summary_json": str(output_dir / "homography_macro_extraction_summary.json"),
        },
    }
    write_json(output_dir / "homography_macro_extraction_summary.json", summary)

    logging.info("Done. accepted=%d failed=%d elapsed=%.2fs", feature_arr.shape[0], len(failed_rows), elapsed)
    logging.info("features shape=%s", feature_arr.shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
