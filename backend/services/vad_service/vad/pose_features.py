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
            dist_norm = None
            iou = 0.0
        else:
            denom = float(exp_diag) if math.isfinite(float(exp_diag)) and float(exp_diag) > 0.0 else 0.0
            if denom <= 0.0:
                dist_norm = None
            else:
                candidate_dist = float(np.linalg.norm(_box_center(pbox) - exp_center) / denom)
                dist_norm = candidate_dist if math.isfinite(candidate_dist) else None
            iou = _box_iou(pbox, exp)
            finite_dist_for_score = float(dist_norm) if dist_norm is not None else 1e6
            score = (3.0 * iou) - (2.0 * finite_dist_for_score) + (0.5 * cmean) + (0.25 * valid_ratio)
        if score > best_score:
            best_score = float(score)
            best_idx = int(i)
            best_diag = {
                "selected_pose_score": float(score),
                "selected_pose_center_distance_norm": float(dist_norm) if dist_norm is not None else None,
                "selected_pose_iou_with_tracker_box": float(iou),
                "selected_pose_mean_conf": float(cmean),
                "selected_pose_keypoint_valid_ratio_loose": float(valid_ratio),
            }

    if best_idx is None:
        return None, None, meta

    best_iou = float(best_diag.get("selected_pose_iou_with_tracker_box", 0.0))
    best_conf = float(best_diag.get("selected_pose_mean_conf", 0.0))
    best_valid_ratio = float(best_diag.get("selected_pose_keypoint_valid_ratio_loose", 0.0))

    if best_iou < 0.20:
        meta.update({"pose_rejected_due_to_low_iou": best_iou, **best_diag})
        return None, None, meta

    # Guard against candidate flicker inside a tracked crop.
    # In live RTSP, a stable tracker box can still contain multiple YOLO-pose candidates.
    # If the selected candidate has weak overlap/confidence/validity, accepting it can
    # make keypoints jump between candidates across frames and explode speed/acceleration.
    if n > 1 and (best_iou < 0.45 or best_conf < 0.55 or best_valid_ratio < 0.85):
        meta.update({
            "pose_rejected_due_to_ambiguity": True,
            "ambiguous_candidate_count": int(n),
            **best_diag,
        })
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




def _persist_keypoints_to_sample(
    sample: SampledPerson,
    xy: np.ndarray,
    conf: np.ndarray,
    *,
    kpt_conf: float = 0.30,
    min_valid_keypoints: int = 5,
) -> bool:
    """Persist full-frame COCO17 keypoints onto the SampledPerson when valid.

    The live Pose gate may re-infer keypoints from the saved person crop for
    scoring.  Those inferred keypoints are full-frame pixel coordinates after
    the crop offset is restored.  Persisting them here lets event_metadata.json
    carry keypoints for the reasoning worker, so Pose keyframe selection can use
    metadata_keypoints instead of re-running YOLO-pose on the saved JPEGs.

    This helper is intentionally metadata-only: it does not change the pose
    feature values, gate score, thresholds, smoothing, or persistence state.
    """
    try:
        arr_xy = np.asarray(xy, dtype=np.float64)
        arr_conf = np.asarray(conf, dtype=np.float64).reshape(-1)
    except Exception:
        return False

    if arr_xy.ndim != 2 or arr_xy.shape[0] < 17 or arr_xy.shape[1] < 2:
        return False
    if arr_conf.ndim != 1 or arr_conf.shape[0] < 17:
        return False

    arr_xy = arr_xy[:17, :2].astype(np.float64, copy=True)
    arr_conf = arr_conf[:17].astype(np.float64, copy=True)

    finite_xy = np.isfinite(arr_xy).all(axis=1)
    finite_conf = np.isfinite(arr_conf)
    valid = finite_xy & finite_conf & (arr_conf >= float(kpt_conf))
    if int(np.count_nonzero(valid)) < int(min_valid_keypoints):
        return False

    # Keep JSON safe and selector-safe.  Invalid/hidden points are retained as
    # coordinate 0 with confidence 0, so downstream code ignores them via conf.
    safe_xy = np.where(finite_xy[:, None], arr_xy, 0.0)
    safe_conf = np.where(finite_conf, arr_conf, 0.0)
    safe_conf = np.clip(safe_conf, 0.0, 1.0)

    sample.keypoints_xy = [[float(x), float(y)] for x, y in safe_xy.tolist()]
    sample.keypoints_conf = [float(c) for c in safe_conf.tolist()]
    return True

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
    return math.atan2(math.sin(delta), math.cos(delta))


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
    persisted_keypoint_frames = 0

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
        persisted = _persist_keypoints_to_sample(s, xy, conf, kpt_conf=kpt_conf)
        src_meta["persisted_to_sample"] = bool(persisted)
        if persisted:
            persisted_keypoint_frames += 1
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
        "pose_persisted_keypoint_frames": int(persisted_keypoint_frames),
        "pose_persisted_keypoint_ratio": float(persisted_keypoint_frames / max(n, 1)),
        "pose_source_meta": pose_source_meta,
    }
    return feature, meta