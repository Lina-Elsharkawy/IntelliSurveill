from __future__ import annotations

import math
from typing import Any, Sequence

import cv2
import numpy as np

from .frame_types import SampledPerson

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


def _choose_best_pose_result(result: Any) -> tuple[np.ndarray | None, np.ndarray | None]:
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
    if xy_np.ndim != 3 or xy_np.shape[0] == 0 or xy_np.shape[1] < 17:
        return None, None
    scores = np.nanmean(conf_np, axis=1)
    best_idx = int(np.nanargmax(scores))
    return xy_np[best_idx, :17, :2].astype(np.float64), conf_np[best_idx, :17].astype(np.float64)


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
    """Return COCO17 keypoints in original full-frame coordinates.

    The old offline/live pose extractor then normalizes these coordinates relative
    to the tracked bbox before calculating speed/shape features. That normalization
    is done in make_pose_feature_from_tubelet(), not here.
    """
    if pose_model is None:
        xy, conf = _as_pose_arrays_from_sample(sample)
        return xy, conf, {"pose_source": "tracker_keypoints"}

    h, w = sample.frame_bgr.shape[:2]
    x1, y1, x2, y2 = _pad_box_xyxy(sample.bbox_xyxy, w, h, pose_crop_pad_ratio, pose_min_crop_size)
    crop = sample.frame_bgr[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        xy, conf = _as_pose_arrays_from_sample(sample)
        return xy, conf, {"pose_source": "tracker_keypoints_empty_crop", "pose_crop_box": [x1, y1, x2, y2]}
    try:
        results = pose_model.predict(source=[crop], imgsz=int(pose_imgsz), conf=float(pose_conf), device=device, verbose=False)
        xy_crop, conf = _choose_best_pose_result(results[0] if results else None)
        if xy_crop is None or conf is None:
            xy, conf0 = _as_pose_arrays_from_sample(sample)
            return xy, conf0, {"pose_source": "tracker_keypoints_pose_empty", "pose_crop_box": [x1, y1, x2, y2]}
        xy = xy_crop.copy()
        xy[:, 0] += float(x1)
        xy[:, 1] += float(y1)
        return xy, conf, {"pose_source": "crop_pose_model", "pose_crop_box": [x1, y1, x2, y2]}
    except Exception as e:
        xy, conf = _as_pose_arrays_from_sample(sample)
        return xy, conf, {"pose_source": "tracker_keypoints_pose_error", "pose_error": str(e)[:200], "pose_crop_box": [x1, y1, x2, y2]}


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
    """Compute the 30-D pose micro feature vector.

    Parity-critical details from the old pose extractor/live tester:
    - keypoints are re-inferred on padded person crops when a pose_model is provided;
    - keypoints are converted back to full-frame coordinates;
    - then every keypoint is normalized relative to that frame's tracked bbox;
    - all speed/acceleration/shape-change features are computed on normalized coords.

    The previous backend version used full-frame pixel coordinates directly. On
    1920x1080 RTSP this inflated speeds by hundreds/thousands and produced GMM
    scores in the millions. The trained pose scaler/GMM expects bbox-normalized
    features.
    """
    n = len(tubelet)
    if n == 0:
        return np.zeros((30,), dtype=np.float32), {"error": "empty_tubelet"}

    kpts_norm = np.full((n, 17, 2), np.nan, dtype=np.float32)
    conf_arr = np.zeros((n, 17), dtype=np.float32)
    times: list[float] = []
    pose_sources: list[str] = []

    use_sample_time = str(time_mode or "sample").lower().strip() == "sample"
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
        kpts_norm[i] = _normalize_keypoints_to_bbox(xy, s.bbox_xyxy, (h, w))
        conf_arr[i] = np.asarray(conf[:17], dtype=np.float32) if len(conf) >= 17 else np.zeros((17,), dtype=np.float32)
        times.append(float(i) / max(float(fps), 1e-6) if use_sample_time else float(s.captured_at.timestamp()))
        pose_sources.append(str(src_meta.get("pose_source", "unknown")))

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
        "pose_sources": pose_sources,
        "pose_source_counts": {src: int(pose_sources.count(src)) for src in sorted(set(pose_sources))},
    }
    return feature, meta
