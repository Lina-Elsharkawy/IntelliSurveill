#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
04_live_homography_gate_rtsp_test.py

Standalone live RTSP tester for the HOMOGRAPHY / MACRO-MOTION gate only.

- YOLO tracking runs on every camera frame.
- Tubelets are sampled at 2.5 fps, 16 frames, stride 8.
- Bbox bottom-center points are projected with a 3x3 homography.
- 7-D macro-motion features are scored with RobustScaler + GMM.
- No score fusion and no other gates.

Important: homography speed units are floor units/sec unless your homography calibration
is true metric. Do not treat them as real m/s unless explicitly calibrated that way.
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


def project_points_homography(points_xy: np.ndarray, H: np.ndarray) -> np.ndarray:
    pts = np.asarray(points_xy, dtype=np.float64)
    ones = np.ones((pts.shape[0], 1), dtype=np.float64)
    homo = np.hstack([pts, ones])
    proj = homo @ H.T
    denom = proj[:, 2:3]
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    return (proj[:, :2] / denom).astype(np.float64)


def angle_wrap(delta: float) -> float:
    return (delta + math.pi) % (2 * math.pi) - math.pi


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

    h, w = tubelet[0].frame.shape[:2]
    img_points = []
    times = []
    boxes = []
    for s in tubelet:
        box = clamp_box_xyxy(s.bbox_xyxy, w=w, h=h)
        boxes.append(box)
        img_points.append(bbox_bottom_center(box))
        times.append(float(s.t_sample))

    img_points = np.asarray(img_points, dtype=np.float64)
    floor_points_raw = project_points_homography(img_points, H)
    floor_points = smooth_floor_trajectory(
        floor_points_raw,
        method=trajectory_smoothing,
        window=smoothing_window,
        polyorder=smoothing_polyorder,
    )
    times = np.asarray(times, dtype=np.float64)

    raw_step_dists = np.linalg.norm(np.diff(floor_points_raw, axis=0), axis=1) if len(floor_points_raw) >= 2 else np.array([], dtype=np.float64)
    smoothed_step_dists_all = np.linalg.norm(np.diff(floor_points, axis=0), axis=1) if len(floor_points) >= 2 else np.array([], dtype=np.float64)

    step_vecs = np.diff(floor_points, axis=0)
    dt = np.diff(times)
    valid_dt = dt > 1e-6
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

    # If all steps are rejected, do NOT feed impossible motion to the GMM.
    # Treat the tubelet as unreliable/stationary for the macro gate instead.
    if len(speeds_all) == 0 or not np.any(valid_step_mask):
        speeds = np.zeros(1, dtype=np.float64)
        step_dists_used = np.zeros(1, dtype=np.float64)
        dt_used = np.ones(1, dtype=np.float64) / 2.5
    else:
        speeds = speeds_all[valid_step_mask]
        step_dists_used = step_dists[valid_step_mask]
        dt_used = dt[valid_step_mask]

    # Optional final cap. Kept separate from outlier rejection.
    if max_step_speed is not None and max_step_speed > 0:
        speeds = np.minimum(speeds, float(max_step_speed))

    # Acceleration from adjacent speeds. Then reject impossible acceleration spikes.
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

    meta = {
        "image_points": img_points.tolist(),
        "floor_points_raw": floor_points_raw.tolist(),
        "floor_points_smoothed": floor_points.tolist(),
        "step_speeds_used": speeds.astype(float).tolist(),
        "step_speeds_all_after_smoothing": speeds_all.astype(float).tolist(),
        "step_accels_used": accels.astype(float).tolist(),
        "total_path_floor_units": total_path,
        "displacement_floor_units": displacement,
        "raw_path_floor_units": float(np.sum(raw_step_dists)) if len(raw_step_dists) else 0.0,
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
        "macro_feature_names": FEATURE_NAMES,
        "macro_feature_values": {name: float(feature[i]) for i, name in enumerate(FEATURE_NAMES)},
    }
    return feature.reshape(1, -1), meta


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
    return sorted(scored, key=lambda x: len(str(x)))[0] if scored else None


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


def make_montage(frames: List[np.ndarray], cols: int = 4, width: int = 320) -> Optional[np.ndarray]:
    if not frames:
        return None
    small = []
    for f in frames:
        h, w = f.shape[:2]
        scale = width / max(1, w)
        small.append(cv2.resize(f, (width, max(1, int(round(h * scale))))))
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
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;10000000|max_delay;500000"
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
    ap.add_argument("--homography_gate_dir", default=r"D:\Embeddings_Distribution\normality_models\homography_macro_gmm_gate_v1_cap3")
    ap.add_argument("--scaler_path", default="")
    ap.add_argument("--gmm_path", default="")
    ap.add_argument("--homography_threshold", type=float, default=10.928259)
    ap.add_argument("--stationary_speed_threshold", type=float, default=0.05)
    ap.add_argument("--max_step_speed", type=float, default=0.0, help="0 disables speed capping. Only use if offline calibration used capping.")
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

    csv_out = CsvAppender(out_dir / "tubelets.csv", [
        "wall_time", "track_id", "tubelet_index", "sample_start_i", "sample_end_i",
        "tubelet_start_time", "tubelet_end_time", "tubelet_duration_sec",
        "macro_score", "macro_threshold", "macro_score_smooth",
        "macro_hit_raw", "macro_hit_smooth", "macro_persistent_hit",
        *FEATURE_NAMES, "anomaly", "reasons", "evidence_frame", "evidence_montage",
    ])

    print("=" * 100)
    print("LIVE HOMOGRAPHY / MACRO-MOTION GATE TEST")
    print("No fusion. Final anomaly = homography persistent hit only.")
    print("Reminder: homography speed units are floor units/sec, not guaranteed true m/s.")
    print(f"output_dir={out_dir}")
    print("=" * 100)

    H = np.load(args.homography_npy).astype(np.float64)
    if H.shape != (3, 3):
        raise ValueError(f"Expected 3x3 homography, got {H.shape}")
    scaler, gmm, scaler_path, gmm_path = load_gate_artifacts(args)
    det = YOLO(args.det_model)
    cap = open_rtsp(args.rtsp_url)
    if not cap.isOpened():
        raise RuntimeError("Could not open RTSP stream.")

    buffers: Dict[int, TrackTubeletBuffer] = defaultdict(lambda: TrackTubeletBuffer(args.tubelet_frames, args.stride))
    states: Dict[int, OnlineGateState] = defaultdict(lambda: OnlineGateState(args.homography_threshold, args.smoothing_sigma, args.persistence_hits, args.persistence_window))
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

            results = det.track(source=frame, persist=True, classes=[0], conf=args.det_conf, imgsz=args.det_imgsz, tracker=args.tracker, device=args.device, verbose=False)
            annotated = frame.copy()
            if not results or results[0].boxes is None or results[0].boxes.xyxy is None:
                if args.display:
                    cv2.imshow("live_homography_gate", resize_for_display(annotated, args.window_width))
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
                    latest_label.pop(tid, None)
                    print(f"[TRACK_RESET] track={tid} gap_samples={sample_i - prev}; buffer/state reset")
                last_seen_sample[tid] = sample_i
                t_sample = sample_i / float(args.sample_fps)
                tub = buffers[tid].add(TubeletSample(frame=frame.copy(), t_sample=t_sample, sample_index=sample_i, bbox_xyxy=b, det_conf=float(det_conf)))
                if tub is None:
                    continue

                tubelet_count += 1
                reasons = []
                evidence_frame = ""
                evidence_montage = ""
                try:
                    X, meta = compute_homography_macro_features(tub, H=H, stationary_speed_threshold=args.stationary_speed_threshold, max_step_speed=args.max_step_speed if args.max_step_speed > 0 else None)
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
                    ]
                    draw_label(annotated, b, latest_label[tid], anomaly=anomaly)

                    if args.save_evidence and (anomaly or args.save_all_tubelets):
                        efp = evidence_dir / f"tubelet_{tubelet_count:06d}_track_{tid}_frame.jpg"
                        emp = evidence_dir / f"tubelet_{tubelet_count:06d}_track_{tid}_montage.jpg"
                        f = tub[-1].frame.copy()
                        draw_label(f, tub[-1].bbox_xyxy, latest_label[tid], anomaly=anomaly)
                        cv2.imwrite(str(efp), f)
                        evidence_frame = str(efp)
                        ims = []
                        for s in tub:
                            im = s.frame.copy()
                            draw_label(im, s.bbox_xyxy, latest_label[tid], anomaly=anomaly)
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
                        "evidence_frame": evidence_frame,
                        "evidence_montage": evidence_montage,
                    }
                    row.update(feat_values)
                    write_jsonl(tubelets_jsonl, row)
                    csv_out.write({**{k: row.get(k, "") for k in csv_out.fieldnames}, "reasons": "|".join(reasons)})
                    if anomaly:
                        event_count += 1
                        event = dict(row)
                        event["event_id"] = f"homography_event_{event_count:06d}"
                        write_jsonl(events_jsonl, event)
                        print(f"[ANOMALY] {event['event_id']} track={tid} score={score:.3f} smooth={gr['score_smooth']:.3f} reasons={reasons}")
                    elif args.print_every_tubelet:
                        print(f"[TUBELET] #{tubelet_count} track={tid} score={score:.3f}/{args.homography_threshold:.3f} smooth={gr['score_smooth']:.3f} raw={gr['hit_raw']} smooth_hit={gr['hit_smooth']} persist={gr['persistent_hit']} features={feat_values}")
                except Exception as e:
                    latest_label[tid] = [f"ID {tid}", f"HOMO_ERROR {str(e)[:50]}"]
                    print(f"[HOMO_ERROR] tubelet={tubelet_count} track={tid}: {e}")
            if args.display:
                cv2.imshow("live_homography_gate", resize_for_display(annotated, args.window_width))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\n[STOP] Ctrl+C")
    finally:
        cap.release()
        if args.display:
            cv2.destroyAllWindows()

    summary = {
        "script": "04_live_homography_gate_rtsp_test_STAGE2.py",
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
        "note": "Standalone homography macro-motion gate with Stage-2 trajectory smoothing + nonphysical-step rejection. Units are homography floor units, not guaranteed meters.",
    }
    (out_dir / "live_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
