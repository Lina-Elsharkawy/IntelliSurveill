"""
Gate-aware evidence frame selection for VAD reasoning.

This module intentionally lives on the reasoning-worker side.  It does not
change the live VAD gates, their thresholds, persistence, scoring, sampling, or
evidence-writing path.  It only chooses which already-saved event frames should
be sent to the VLM.

Selectors:
- deep: 16-frame temporal-change selector, optionally backed by VideoMAE/kNN
  when the reasoning worker has GPU/model/artifact access.
- pose: 24-frame body-motion selector, using saved keypoints when present,
  otherwise optional YOLO-pose reinference on saved evidence frames, then bbox
  and image-motion fallbacks.
- homography_macro: trajectory-change selector when trajectory metadata exists,
  otherwise even spacing.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from .evidence_keys import (
    frame_index_from_key as _frame_index_from_key,
    sort_frame_keys as _sorted_frame_keys,
)

log = logging.getLogger("vad.keyframe_selector")


@dataclass(frozen=True)
class FrameSelectionResult:
    frame_keys: list[str]
    selected_indices: list[int]
    selector: str
    reason: str = ""
    debug: dict[str, Any] = field(default_factory=dict)


# _frame_index_from_key and _sorted_frame_keys are imported from evidence_keys (see above).


def _even_indices(n: int, limit: int) -> list[int]:
    if n <= 0 or limit <= 0:
        return []
    if n <= limit:
        return list(range(n))
    if limit == 1:
        return [0]
    last = n - 1
    return sorted({round(i * last / (limit - 1)) for i in range(limit)})[:limit]


def _fill_even(selected: set[int], n: int, limit: int) -> list[int]:
    for i in _even_indices(n, limit):
        selected.add(i)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for i in range(n):
            selected.add(i)
            if len(selected) >= limit:
                break
    return sorted(i for i in selected if 0 <= i < n)[:limit]



def _round_scores(scores: np.ndarray | list[float], *, digits: int = 6, limit: int = 64) -> list[float]:
    """Small JSON-safe score preview for verification/debug storage."""
    arr = np.asarray(scores, dtype=np.float64).reshape(-1)
    out: list[float] = []
    for v in arr[:limit]:
        if np.isfinite(v):
            out.append(round(float(v), digits))
        else:
            out.append(0.0)
    return out


def _peak_frames_from_scores(scores: np.ndarray | list[float], *, top_k: int = 5) -> list[int]:
    """Return transition peak frame indices, where score index 0 means frame 1."""
    arr = np.asarray(scores, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return []
    arr = np.where(np.isfinite(arr), arr, -np.inf)
    ranked = list(np.argsort(arr)[::-1])
    peaks: list[int] = []
    for raw_idx in ranked:
        if arr[raw_idx] == -np.inf or arr[raw_idx] <= 0:
            continue
        frame_idx = int(raw_idx) + 1
        if any(abs(frame_idx - p) <= 1 for p in peaks):
            continue
        peaks.append(frame_idx)
        if len(peaks) >= top_k:
            break
    return peaks


def _select_around_peaks(n: int, transition_scores: np.ndarray, limit: int, *, anchors: bool = True) -> list[int]:
    """Select frame indices around high transition scores.

    transition_scores[t] describes change from frame t-1 to frame t, with t in
    [1, n-1].  The function adds before/during/after frames around peaks.
    """
    selected: set[int] = set()
    if anchors and n > 0:
        selected.add(0)
        if n > 1:
            selected.add(n - 1)

    if n <= limit:
        return list(range(n))

    scores = np.asarray(transition_scores, dtype=np.float64).reshape(-1)
    if scores.size:
        # Ignore non-finite values and prefer temporally separated peaks.
        scores = np.where(np.isfinite(scores), scores, -np.inf)
        ranked = list(np.argsort(scores)[::-1])
        used_peaks: list[int] = []
        for raw_idx in ranked:
            if len(selected) >= limit:
                break
            if scores[raw_idx] == -np.inf or scores[raw_idx] <= 0:
                continue
            t = int(raw_idx) + 1  # score index 0 means transition 0 -> 1
            if any(abs(t - p) <= 1 for p in used_peaks):
                continue
            used_peaks.append(t)
            for j in (t - 1, t, t + 1):
                if 0 <= j < n:
                    selected.add(j)
                if len(selected) >= limit:
                    break

    return _fill_even(selected, n, limit)


def _decode_rgb(image_bytes: bytes) -> np.ndarray | None:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return np.asarray(img)
    except Exception:
        return None


def _decode_pil(image_bytes: bytes) -> Image.Image | None:
    try:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None


def _samples(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    value = (metadata or {}).get("samples")
    return value if isinstance(value, list) else []


def _bbox_from_sample(sample: dict[str, Any]) -> list[float] | None:
    box = sample.get("bbox_xyxy") or sample.get("bbox") or sample.get("box")
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return None
    try:
        return [float(box[0]), float(box[1]), float(box[2]), float(box[3])]
    except Exception:
        return None


def _bboxes(metadata: dict[str, Any], n: int) -> list[list[float] | None]:
    out: list[list[float] | None] = []
    for s in _samples(metadata)[:n]:
        out.append(_bbox_from_sample(s) if isinstance(s, dict) else None)
    while len(out) < n:
        out.append(None)
    return out


def _crop_from_bbox(img: np.ndarray, bbox: list[float] | None, *, pad: float = 0.15, out_size: int = 224) -> np.ndarray:
    h, w = img.shape[:2]
    if bbox is None:
        crop = img
    else:
        x1, y1, x2, y2 = bbox
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        x1 = int(max(0, math.floor(x1 - bw * pad)))
        y1 = int(max(0, math.floor(y1 - bh * pad)))
        x2 = int(min(w, math.ceil(x2 + bw * pad)))
        y2 = int(min(h, math.ceil(y2 + bh * pad)))
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            crop = img
    pil = Image.fromarray(crop).resize((out_size, out_size))
    return np.asarray(pil, dtype=np.float32) / 255.0


def _image_transition_scores(frame_keys: list[str], image_bytes_map: dict[str, bytes], metadata: dict[str, Any] | None = None) -> np.ndarray:
    n = len(frame_keys)
    if n <= 1:
        return np.zeros(0, dtype=np.float64)
    boxes = _bboxes(metadata or {}, n)
    prev: np.ndarray | None = None
    scores: list[float] = []
    for i, key in enumerate(frame_keys):
        arr = _decode_rgb(image_bytes_map.get(key, b""))
        if arr is None:
            cur = None
        else:
            cur = _crop_from_bbox(arr, boxes[i], pad=0.15, out_size=160)
        if i > 0:
            if cur is None or prev is None:
                scores.append(0.0)
            else:
                scores.append(float(np.mean(np.abs(cur - prev))))
        if cur is not None:
            prev = cur
    return np.asarray(scores, dtype=np.float64)


class _VideoMAEHelper:
    """Lazy VideoMAE loader for the reasoning worker.

    This is optional.  If anything is missing, selectors fall back instead of
    crashing the worker.
    """

    def __init__(self, cfg: Any | None) -> None:
        self.cfg = cfg
        self.model_name = str(getattr(cfg, "deep_videomae_model", None) or os.getenv("VAD_DEEP_VIDEOMAE_MODEL", "MCG-NJU/videomae-base"))
        self.device_name = str(os.getenv("VAD_REASONING_DEEP_DEVICE", getattr(cfg, "deep_device", "cuda")))
        self.fp16 = str(os.getenv("VAD_REASONING_DEEP_FP16", "1")).lower() in {"1", "true", "yes"}
        self.cache_dir = os.getenv("VAD_REASONING_VIDEOMAE_CACHE", "/models/vad/deep_videomae")
        self.artifact_dir = Path(str(os.getenv("VAD_DEEP_ARTIFACT_DIR", getattr(cfg, "deep_artifact_dir", "/models/vad/deep"))))
        self.knn_path = self.artifact_dir / "models" / "03_knn_index.joblib"
        self._loaded = False
        self._load_error: str | None = None
        self._torch = None
        self._processor = None
        self._model = None
        self._device = None
        self._knn = None

    def load(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            import torch
            from transformers import VideoMAEImageProcessor, VideoMAEModel

            if self.device_name == "cuda" and not torch.cuda.is_available():
                device_name = "cpu"
            else:
                device_name = self.device_name
            self._device = torch.device(device_name)
            self._torch = torch
            try:
                self._processor = VideoMAEImageProcessor.from_pretrained(self.model_name, cache_dir=self.cache_dir, use_fast=False)
            except TypeError:
                self._processor = VideoMAEImageProcessor.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self._model = VideoMAEModel.from_pretrained(self.model_name, cache_dir=self.cache_dir)
            self._model.eval().to(self._device)
            if self.fp16 and self._device.type == "cuda":
                self._model.half()

            if self.knn_path.exists():
                try:
                    import joblib
                    artifact = joblib.load(self.knn_path)
                    self._knn = artifact.get("knn") if isinstance(artifact, dict) and "knn" in artifact else artifact
                except Exception as e:
                    log.warning("VideoMAE selector could not load kNN artifact %s: %s", self.knn_path, e)

            self._loaded = True
            log.info("VideoMAE selector loaded model=%s device=%s knn=%s", self.model_name, self._device, bool(self._knn))
            return True
        except Exception as e:
            self._load_error = str(e)
            log.warning("VideoMAE selector load failed: %s", e)
            return False

    def embed_pil_sequence(self, images: list[Image.Image]) -> np.ndarray | None:
        if not images or not self.load():
            return None
        try:
            torch = self._torch
            assert torch is not None and self._processor is not None and self._model is not None and self._device is not None
            try:
                inputs = self._processor(images, return_tensors="pt", do_flip_channel_order=False)
            except TypeError:
                inputs = self._processor(images, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            if self.fp16 and self._device.type == "cuda":
                inputs = {k: (v.half() if torch.is_floating_point(v) else v) for k, v in inputs.items()}
            with torch.inference_mode():
                with torch.autocast(device_type=self._device.type, dtype=torch.float16, enabled=(self.fp16 and self._device.type == "cuda")):
                    outputs = self._model(**inputs)
            emb = outputs.last_hidden_state.mean(dim=1).squeeze(0).float().cpu().numpy().astype(np.float32)
            emb = emb / max(float(np.linalg.norm(emb)), 1e-12)
            return emb.astype(np.float32)
        except Exception as e:
            log.warning("VideoMAE selector embedding failed: %s", e)
            return None

    def knn_distance(self, emb: np.ndarray | None, k: int = 5) -> float | None:
        if emb is None or self._knn is None:
            return None
        try:
            distances, _ = self._knn.kneighbors(emb.reshape(1, -1), n_neighbors=int(k), return_distance=True)
            d = np.asarray(distances).reshape(-1)
            return float(np.mean(d[:k])) if d.size else None
        except Exception as e:
            log.warning("VideoMAE selector kNN distance failed: %s", e)
            return None


_videomae_helper: _VideoMAEHelper | None = None


def _get_videomae_helper(cfg: Any | None) -> _VideoMAEHelper:
    global _videomae_helper
    if _videomae_helper is None:
        _videomae_helper = _VideoMAEHelper(cfg)
    return _videomae_helper


class _YoloPoseHelper:
    def __init__(self, cfg: Any | None) -> None:
        self.cfg = cfg
        self.model_path = str(os.getenv("VAD_REASONING_POSE_MODEL", getattr(cfg, "pose_model", "/models/vad/yolo/yolov8s-pose.pt")))
        self.device = str(os.getenv("VAD_REASONING_POSE_DEVICE", getattr(cfg, "deep_device", "cuda")))
        self.imgsz = int(os.getenv("VAD_REASONING_POSE_IMGSZ", "640"))
        self.conf = float(os.getenv("VAD_REASONING_POSE_CONF", "0.25"))
        self._model = None
        self._loaded = False
        self._load_error: str | None = None

    def load(self) -> bool:
        if self._loaded:
            return True
        if self._load_error:
            return False
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.model_path)
            self._loaded = True
            log.info("YOLO pose selector loaded model=%s device=%s", self.model_path, self.device)
            return True
        except Exception as e:
            self._load_error = str(e)
            log.warning("YOLO pose selector load failed: %s", e)
            return False

    @staticmethod
    def _iou(a: list[float] | None, b: list[float] | None) -> float:
        if a is None or b is None:
            return 0.0
        ax1, ay1, ax2, ay2 = a[:4]
        bx1, by1, bx2, by2 = b[:4]
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        inter = iw * ih
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        return float(inter / max(area_a + area_b - inter, 1e-9))

    def infer_keypoints(self, frame_keys: list[str], image_bytes_map: dict[str, bytes], metadata: dict[str, Any]) -> tuple[list[np.ndarray | None], list[np.ndarray | None]]:
        n = len(frame_keys)
        out_xy: list[np.ndarray | None] = [None] * n
        out_conf: list[np.ndarray | None] = [None] * n
        if not self.load():
            return out_xy, out_conf
        boxes_meta = _bboxes(metadata, n)
        try:
            assert self._model is not None
            for i, key in enumerate(frame_keys):
                arr = _decode_rgb(image_bytes_map.get(key, b""))
                if arr is None:
                    continue
                results = self._model.predict(arr, imgsz=self.imgsz, conf=self.conf, device=self.device, verbose=False)
                if not results:
                    continue
                r = results[0]
                if getattr(r, "keypoints", None) is None or r.keypoints is None:
                    continue
                kxy = r.keypoints.xy.cpu().numpy() if getattr(r.keypoints, "xy", None) is not None else None
                kcf = r.keypoints.conf.cpu().numpy() if getattr(r.keypoints, "conf", None) is not None else None
                if kxy is None or len(kxy) == 0:
                    continue
                det_boxes = None
                if getattr(r, "boxes", None) is not None and getattr(r.boxes, "xyxy", None) is not None:
                    det_boxes = r.boxes.xyxy.cpu().numpy().tolist()
                if det_boxes:
                    best = max(range(len(det_boxes)), key=lambda j: self._iou(boxes_meta[i], det_boxes[j]))
                else:
                    best = 0
                out_xy[i] = np.asarray(kxy[best], dtype=np.float64)
                out_conf[i] = np.asarray(kcf[best], dtype=np.float64) if kcf is not None else np.ones((out_xy[i].shape[0],), dtype=np.float64)
        except Exception as e:
            log.warning("YOLO pose selector inference failed: %s", e)
        return out_xy, out_conf


_yolo_pose_helper: _YoloPoseHelper | None = None


def _get_yolo_pose_helper(cfg: Any | None) -> _YoloPoseHelper:
    global _yolo_pose_helper
    if _yolo_pose_helper is None:
        _yolo_pose_helper = _YoloPoseHelper(cfg)
    return _yolo_pose_helper


def _deep_select(frame_keys: list[str], image_bytes_map: dict[str, bytes], metadata: dict[str, Any], max_images: int, cfg: Any | None) -> FrameSelectionResult:
    n = len(frame_keys)
    if n == 0:
        return FrameSelectionResult([], [], "even_spacing_fallback", "no_frames", {"gate": "deep", "total_frames": 0})
    if n <= max_images:
        return FrameSelectionResult(frame_keys, list(range(n)), "deep_temporal_change_16f", "n_le_budget", {
            "gate": "deep",
            "native_expected_frames": 16,
            "total_frames": n,
            "selection_mode": "all_frames_under_budget",
        })

    # Correct Deep-native assumption: 16 frames are the main temporal unit.
    # We load VideoMAE for alignment/metadata/kNN when available.  For exactly
    # 16 frames, frame indices are still selected from temporal crop changes,
    # because VideoMAE emits one tubelet embedding rather than one clean score
    # per frame.
    videomae_ok = False
    knn_note = ""
    if str(os.getenv("VAD_REASONING_DEEP_USE_VIDEOMAE", "1")).lower() in {"1", "true", "yes"}:
        helper = _get_videomae_helper(cfg)
        pil_images = [_decode_pil(image_bytes_map.get(k, b"")) for k in frame_keys]
        pil_images = [im for im in pil_images if im is not None]
        if len(pil_images) >= min(16, n):
            # Use the native 16-frame Deep unit. If more frames exist, score
            # overlapping 16-frame windows and spread their score to member frames.
            window = int(os.getenv("VAD_DEEP_TUBELET_FRAMES", getattr(cfg, "deep_tubelet_frames", 16) if cfg is not None else 16))
            window = max(1, min(window, len(pil_images)))
            step = max(1, window // 2)
            frame_window_scores = np.zeros(n, dtype=np.float64)
            frame_window_counts = np.zeros(n, dtype=np.float64)
            for start in range(0, max(1, len(pil_images) - window + 1), step):
                seq = pil_images[start:start + window]
                emb = helper.embed_pil_sequence(seq)
                if emb is not None:
                    videomae_ok = True
                    d = helper.knn_distance(emb, k=int(getattr(cfg, "deep_k", 5)))
                    if d is not None:
                        frame_window_scores[start:start + window] += float(d)
                        frame_window_counts[start:start + window] += 1.0
            if np.any(frame_window_counts > 0):
                frame_window_scores = frame_window_scores / np.maximum(frame_window_counts, 1.0)
                # Add weak VideoMAE-window guidance to image temporal changes.
                # For exactly 16 frames this is nearly uniform, which is fine.
                knn_note = "videomae_knn_guided"

    scores = _image_transition_scores(frame_keys, image_bytes_map, metadata)
    idx = _select_around_peaks(n, scores, max_images, anchors=True)
    selector_name = "deep_temporal_change_16f" if n <= 16 else "deep_temporal_change_videomae_windows"
    reason = "videomae_available" if videomae_ok else "videomae_unavailable_image_temporal_change"
    if knn_note:
        reason += f"_{knn_note}"
    return FrameSelectionResult([frame_keys[i] for i in idx], idx, selector_name, reason, {
        "gate": "deep",
        "native_expected_frames": 16,
        "total_frames": n,
        "max_images": max_images,
        "videomae_loaded": bool(videomae_ok),
        "selection_basis": reason,
        "transition_scores": _round_scores(scores),
        "top_transition_peaks": _peak_frames_from_scores(scores, top_k=5),
        "selected_indices": idx,
        "selected_frame_numbers": [_frame_index_from_key(frame_keys[i]) for i in idx],
    })


def _keypoints_from_metadata(metadata: dict[str, Any], n: int) -> tuple[list[np.ndarray | None], list[np.ndarray | None]]:
    xy_list: list[np.ndarray | None] = []
    cf_list: list[np.ndarray | None] = []
    for s in _samples(metadata)[:n]:
        if not isinstance(s, dict):
            xy_list.append(None); cf_list.append(None); continue
        xy = s.get("keypoints_xy") or s.get("kpts_xy") or s.get("keypoints")
        cf = s.get("keypoints_conf") or s.get("kpts_conf") or s.get("keypoint_confidences")
        try:
            arr_xy = np.asarray(xy, dtype=np.float64) if xy is not None else None
            arr_cf = np.asarray(cf, dtype=np.float64) if cf is not None else None
            if arr_xy is not None and arr_xy.ndim == 2 and arr_xy.shape[1] >= 2:
                xy_list.append(arr_xy[:, :2])
                cf_list.append(arr_cf.reshape(-1) if arr_cf is not None else np.ones((arr_xy.shape[0],), dtype=np.float64))
            else:
                xy_list.append(None); cf_list.append(None)
        except Exception:
            xy_list.append(None); cf_list.append(None)
    while len(xy_list) < n:
        xy_list.append(None); cf_list.append(None)
    return xy_list, cf_list


def _bbox_transition_scores(metadata: dict[str, Any], n: int) -> np.ndarray:
    boxes = _bboxes(metadata, n)
    scores: list[float] = []
    prev = boxes[0] if boxes else None
    for i in range(1, n):
        cur = boxes[i]
        if prev is None or cur is None:
            scores.append(0.0)
        else:
            px1, py1, px2, py2 = prev
            cx1, cy1, cx2, cy2 = cur
            pw, ph = max(1.0, px2 - px1), max(1.0, py2 - py1)
            cw, ch = max(1.0, cx2 - cx1), max(1.0, cy2 - cy1)
            pcx, pcy = (px1 + px2) / 2.0, (py1 + py2) / 2.0
            ccx, ccy = (cx1 + cx2) / 2.0, (cy1 + cy2) / 2.0
            diag = max(1.0, math.sqrt(pw * pw + ph * ph))
            center = math.sqrt((ccx - pcx) ** 2 + (ccy - pcy) ** 2) / diag
            size = abs(cw - pw) / pw + abs(ch - ph) / ph
            aspect = abs((cw / max(ch, 1.0)) - (pw / max(ph, 1.0)))
            scores.append(float(center + 0.5 * size + 0.25 * aspect))
        if cur is not None:
            prev = cur
    return np.asarray(scores, dtype=np.float64)


def _pose_energy_from_keypoints(xy_list: list[np.ndarray | None], cf_list: list[np.ndarray | None]) -> np.ndarray:
    n = len(xy_list)
    scores: list[float] = []
    for i in range(1, n):
        prev, cur = xy_list[i - 1], xy_list[i]
        pc, cc = cf_list[i - 1], cf_list[i]
        if prev is None or cur is None or prev.shape != cur.shape:
            scores.append(0.0)
            continue
        conf = np.ones((prev.shape[0],), dtype=np.float64)
        if pc is not None and cc is not None and pc.shape[0] == prev.shape[0] and cc.shape[0] == cur.shape[0]:
            conf = np.minimum(pc, cc)
        valid = conf >= float(os.getenv("VAD_REASONING_POSE_KPT_CONF", "0.30"))
        if not np.any(valid):
            scores.append(0.0)
            continue
        center_prev = np.nanmedian(prev[valid], axis=0)
        centered_prev = prev[valid] - center_prev
        scale = max(float(np.nanpercentile(np.linalg.norm(centered_prev, axis=1), 75)), 1.0)
        disp = np.linalg.norm(cur[valid] - prev[valid], axis=1) / scale
        base = float(np.nanmean(disp))
        # Add posture/torso/arm-ish crude terms when COCO indices exist.
        extra = 0.0
        if prev.shape[0] >= 17:
            def angle(a: np.ndarray, b: np.ndarray) -> float:
                return float(math.atan2(float(b[1] - a[1]), float(b[0] - a[0])))
            # shoulders 5,6; hips 11,12; wrists 9,10; ankles 15,16
            try:
                torso_p = (prev[5] + prev[6] + prev[11] + prev[12]) / 4.0
                torso_c = (cur[5] + cur[6] + cur[11] + cur[12]) / 4.0
                extra += float(np.linalg.norm(torso_c - torso_p) / scale)
                body_ang_p = angle((prev[11] + prev[12]) / 2.0, (prev[5] + prev[6]) / 2.0)
                body_ang_c = angle((cur[11] + cur[12]) / 2.0, (cur[5] + cur[6]) / 2.0)
                extra += abs(math.atan2(math.sin(body_ang_c - body_ang_p), math.cos(body_ang_c - body_ang_p)))
                wrist = np.linalg.norm(cur[[9, 10]] - prev[[9, 10]], axis=1).mean() / scale
                ankle = np.linalg.norm(cur[[15, 16]] - prev[[15, 16]], axis=1).mean() / scale
                extra += float(0.5 * wrist + 0.5 * ankle)
            except Exception:
                pass
        scores.append(float(base + 0.5 * extra))
    return np.asarray(scores, dtype=np.float64)


def _pose_select(frame_keys: list[str], image_bytes_map: dict[str, bytes], metadata: dict[str, Any], max_images: int, cfg: Any | None) -> FrameSelectionResult:
    n = len(frame_keys)
    if n == 0:
        return FrameSelectionResult([], [], "even_spacing_fallback", "no_frames", {"gate": "pose", "total_frames": 0})
    if n <= max_images:
        return FrameSelectionResult(frame_keys, list(range(n)), "pose_motion_energy_24f", "n_le_budget", {
            "gate": "pose",
            "native_expected_frames": 24,
            "total_frames": n,
            "selection_mode": "all_frames_under_budget",
        })

    xy_list, cf_list = _keypoints_from_metadata(metadata, n)
    source = "metadata_keypoints"
    if not any(x is not None for x in xy_list) and str(os.getenv("VAD_REASONING_POSE_REINFER", "1")).lower() in {"1", "true", "yes"}:
        helper = _get_yolo_pose_helper(cfg)
        xy_list, cf_list = helper.infer_keypoints(frame_keys, image_bytes_map, metadata)
        source = "yolo_pose_reinfer"

    if any(x is not None for x in xy_list):
        scores = _pose_energy_from_keypoints(xy_list, cf_list)
        reason = source
    else:
        scores = _bbox_transition_scores(metadata, n)
        reason = "bbox_fallback"
        if not np.any(scores > 0):
            scores = _image_transition_scores(frame_keys, image_bytes_map, metadata)
            reason = "image_motion_fallback"

    if not np.any(np.asarray(scores) > 0):
        idx = _even_indices(n, max_images)
        return FrameSelectionResult([frame_keys[i] for i in idx], idx, "even_spacing_fallback", "pose_no_motion_scores", {
            "gate": "pose",
            "native_expected_frames": 24,
            "total_frames": n,
            "max_images": max_images,
            "selection_basis": "no_positive_pose_motion_scores",
            "transition_scores": _round_scores(scores),
            "selected_indices": idx,
            "selected_frame_numbers": [_frame_index_from_key(frame_keys[i]) for i in idx],
        })

    idx = _select_around_peaks(n, scores, max_images, anchors=True)
    return FrameSelectionResult([frame_keys[i] for i in idx], idx, "pose_motion_energy_24f", reason, {
        "gate": "pose",
        "native_expected_frames": 24,
        "total_frames": n,
        "max_images": max_images,
        "selection_basis": reason,
        "transition_scores": _round_scores(scores),
        "top_transition_peaks": _peak_frames_from_scores(scores, top_k=5),
        "selected_indices": idx,
        "selected_frame_numbers": [_frame_index_from_key(frame_keys[i]) for i in idx],
    })


def _trajectory_points_from_metadata(metadata: dict[str, Any], n: int) -> list[np.ndarray | None]:
    keys = ("ground_xy", "world_xy", "trajectory_xy", "homography_xy", "ground_point")
    out: list[np.ndarray | None] = []
    for s in _samples(metadata)[:n]:
        point = None
        if isinstance(s, dict):
            for k in keys:
                v = s.get(k)
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    try:
                        point = np.asarray([float(v[0]), float(v[1])], dtype=np.float64)
                        break
                    except Exception:
                        pass
        out.append(point)
    while len(out) < n:
        out.append(None)
    return out


def _homography_select(frame_keys: list[str], image_bytes_map: dict[str, bytes], metadata: dict[str, Any], max_images: int, cfg: Any | None) -> FrameSelectionResult:
    n = len(frame_keys)
    pts = _trajectory_points_from_metadata(metadata, n)
    if any(p is not None for p in pts):
        scores = []
        prev = pts[0]
        prev_vel = None
        for i in range(1, n):
            cur = pts[i]
            if cur is None or prev is None:
                scores.append(0.0)
            else:
                vel = cur - prev
                speed = float(np.linalg.norm(vel))
                accel = float(np.linalg.norm(vel - prev_vel)) if prev_vel is not None else 0.0
                turn = 0.0
                if prev_vel is not None and np.linalg.norm(prev_vel) > 1e-9 and np.linalg.norm(vel) > 1e-9:
                    dot = float(np.dot(prev_vel, vel) / max(np.linalg.norm(prev_vel) * np.linalg.norm(vel), 1e-9))
                    turn = float(math.acos(max(-1.0, min(1.0, dot))))
                scores.append(speed + accel + turn)
                prev_vel = vel
            if cur is not None:
                prev = cur
        idx = _select_around_peaks(n, np.asarray(scores), max_images, anchors=True)
        return FrameSelectionResult([frame_keys[i] for i in idx], idx, "trajectory_change", "trajectory_metadata", {
            "gate": "homography_macro",
            "total_frames": n,
            "max_images": max_images,
            "transition_scores": _round_scores(scores),
            "top_transition_peaks": _peak_frames_from_scores(scores, top_k=5),
            "selected_indices": idx,
            "selected_frame_numbers": [_frame_index_from_key(frame_keys[i]) for i in idx],
        })

    idx = _even_indices(n, max_images)
    return FrameSelectionResult([frame_keys[i] for i in idx], idx, "even_spacing_fallback", "no_trajectory_metadata", {
        "gate": "homography_macro",
        "total_frames": n,
        "max_images": max_images,
        "selected_indices": idx,
        "selected_frame_numbers": [_frame_index_from_key(frame_keys[i]) for i in idx],
    })


def select_reasoning_frames(
    gate_name: str,
    frame_keys: list[str],
    image_bytes_map: dict[str, bytes],
    metadata: dict[str, Any] | None = None,
    max_images: int = 8,
    cfg: Any | None = None,
) -> FrameSelectionResult:
    """Gate-aware selector entry point used by vad.reasoning_worker."""
    max_images = max(1, int(max_images or 8))
    ordered = _sorted_frame_keys(frame_keys)
    metadata = metadata or {}
    gate = (gate_name or "").strip().lower()

    try:
        if gate == "deep":
            return _deep_select(ordered, image_bytes_map, metadata, max_images, cfg)
        if gate == "pose":
            return _pose_select(ordered, image_bytes_map, metadata, max_images, cfg)
        if gate in {"homography", "homography_macro", "macro", "homography macro"}:
            return _homography_select(ordered, image_bytes_map, metadata, max_images, cfg)

        idx = _even_indices(len(ordered), max_images)
        return FrameSelectionResult([ordered[i] for i in idx], idx, "even_spacing_fallback", f"unknown_gate={gate_name}", {
            "gate": gate,
            "total_frames": len(ordered),
            "max_images": max_images,
            "selected_indices": idx,
            "selected_frame_numbers": [_frame_index_from_key(ordered[i]) for i in idx],
        })
    except Exception as e:
        log.warning("Gate-aware frame selector failed gate=%s: %s", gate_name, e)
        idx = _even_indices(len(ordered), max_images)
        return FrameSelectionResult([ordered[i] for i in idx], idx, "even_spacing_fallback", "selector_exception", {
            "gate": gate,
            "total_frames": len(ordered),
            "max_images": max_images,
            "error": str(e),
            "selected_indices": idx,
            "selected_frame_numbers": [_frame_index_from_key(ordered[i]) for i in idx],
        })


# Backward-compatible wrapper so old imports do not break immediately.
class CLIPKeyframeSelector:
    def select(self, frame_keys: list[str], image_bytes_map: dict[str, bytes], budget: int = 8) -> list[str]:
        idx = _even_indices(len(frame_keys), budget)
        return [frame_keys[i] for i in idx]


def get_selector() -> CLIPKeyframeSelector:
    return CLIPKeyframeSelector()
