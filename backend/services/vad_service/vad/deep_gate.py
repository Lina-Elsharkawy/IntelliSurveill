from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import joblib
import numpy as np

from .config import VadConfig
from .frame_types import SampledPerson
from .online_gate_state import GateUpdate, OnlineGateState

log = logging.getLogger("vad.deep_gate")


def _clip_bbox_xyxy(bbox: Sequence[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(x) for x in bbox]
    x1 = max(0, min(width - 1, int(round(x1))))
    y1 = max(0, min(height - 1, int(round(y1))))
    x2 = max(0, min(width - 1, int(round(x2))))
    y2 = max(0, min(height - 1, int(round(y2))))
    if x2 <= x1:
        x2 = min(width - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(height - 1, y1 + 1)
    return x1, y1, x2, y2


def _pad_box_xyxy(bbox: Sequence[float], width: int, height: int, pad_ratio: float = 0.30) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(x) for x in bbox]
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    return _clip_bbox_xyxy((x1 - bw * pad_ratio, y1 - bh * pad_ratio, x2 + bw * pad_ratio, y2 + bh * pad_ratio), width, height)


def _union_box_xyxy(bboxes: Sequence[Sequence[float]], width: int, height: int) -> tuple[int, int, int, int]:
    if not bboxes:
        return _clip_bbox_xyxy((0, 0, 1, 1), width, height)
    return _clip_bbox_xyxy(
        (
            min(float(b[0]) for b in bboxes),
            min(float(b[1]) for b in bboxes),
            max(float(b[2]) for b in bboxes),
            max(float(b[3]) for b in bboxes),
        ),
        width,
        height,
    )


def _load_threshold(thresholds_path: Path, key: str, k: int) -> float:
    data = json.loads(thresholds_path.read_text(encoding="utf-8"))
    candidates: list[Any] = []
    if isinstance(data, dict):
        candidates.append(data)
        for nested_key in ("thresholds", "deep_thresholds", "knn_thresholds", "scores"):
            if isinstance(data.get(nested_key), dict):
                candidates.append(data[nested_key])
    for d in candidates:
        if not isinstance(d, dict):
            continue
        for k_name in (f"k{k}", str(k), f"deep_k_{k}"):
            kd = d.get(k_name)
            if isinstance(kd, dict) and key in kd:
                return float(kd[key])
    for d in candidates:
        if isinstance(d, dict) and key in d:
            return float(d[key])
    raise KeyError(f"Deep threshold {key!r} for k={k} was not found in {thresholds_path}")


def _extract_knn_object(artifact: Any) -> Any:
    if hasattr(artifact, "kneighbors"):
        return artifact
    if isinstance(artifact, dict):
        for key in ("knn", "knn_index", "index", "nearest_neighbors", "nn", "model", "estimator"):
            obj = artifact.get(key)
            if hasattr(obj, "kneighbors"):
                return obj
    raise TypeError("Could not find sklearn-like kNN object with .kneighbors() in deep artifact")


@dataclass
class DeepGateOutput:
    raw_score: float
    smoothed_score: float
    threshold_value: float
    above_threshold: bool
    persistence_hits: int
    persistent: bool
    feature_values: dict[str, Any]
    metadata: dict[str, Any]
    gate_update: GateUpdate
    embedding_l2: np.ndarray


class DeepGate:
    """VideoMAE+kNN deep gate using the UNION crop parity fix from the live script."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.knn = None
        self.processor = None
        self.model = None
        self.device = None
        self.loaded = False
        self.load_error: str | None = None
        self.threshold_value = float(cfg.deep_threshold_value)
        self.states: dict[int, OnlineGateState] = {}
        self.knn_path = cfg.deep_artifact_dir / "models" / "03_knn_index.joblib"
        self.thresholds_path = cfg.deep_artifact_dir / "04_thresholds.json"

    def load(self) -> None:
        if self.loaded:
            return
        try:
            import torch
            from transformers import VideoMAEImageProcessor, VideoMAEModel

            if not self.knn_path.exists():
                raise FileNotFoundError(f"Deep kNN artifact not found: {self.knn_path}")
            artifact = joblib.load(self.knn_path)
            self.knn = _extract_knn_object(artifact)
            if self.thresholds_path.exists():
                self.threshold_value = _load_threshold(self.thresholds_path, self.cfg.deep_threshold_key, self.cfg.deep_k)

            self.device = torch.device(self.cfg.deep_device if (self.cfg.deep_device == "cpu" or torch.cuda.is_available()) else "cpu")
            try:
                self.processor = VideoMAEImageProcessor.from_pretrained(self.cfg.deep_videomae_model, use_fast=self.cfg.deep_use_fast_processor)
            except TypeError:
                self.processor = VideoMAEImageProcessor.from_pretrained(self.cfg.deep_videomae_model)
            self.model = VideoMAEModel.from_pretrained(self.cfg.deep_videomae_model)
            self.model.eval().to(self.device)
            if self.cfg.deep_fp16 and self.device.type == "cuda":
                self.model.half()

            self.loaded = True
            self.load_error = None
            log.info("Loaded deep gate: knn=%s threshold=%s device=%s", self.knn_path, self.threshold_value, self.device)
        except Exception as e:
            self.loaded = False
            self.load_error = str(e)
            raise

    def _state_for(self, tracker_track_id: int) -> OnlineGateState:
        st = self.states.get(tracker_track_id)
        if st is None:
            st = OnlineGateState(
                threshold=self.threshold_value,
                sigma=self.cfg.deep_smoothing_sigma,
                persistence_required_hits=self.cfg.deep_persistence_required_hits,
                persistence_window=self.cfg.deep_persistence_window,
            )
            self.states[tracker_track_id] = st
        return st

    def _crop_union_rgb(self, tubelet: list[SampledPerson]) -> tuple[list[np.ndarray], dict[str, Any]]:
        if not tubelet:
            return [], {}
        h, w = tubelet[0].frame_bgr.shape[:2]
        raw_union = _union_box_xyxy([s.bbox_xyxy for s in tubelet], w, h)
        crop_box = _pad_box_xyxy(raw_union, w, h, pad_ratio=self.cfg.deep_bbox_pad_ratio)
        x1, y1, x2, y2 = crop_box
        crops_rgb: list[np.ndarray] = []
        areas: list[float] = []
        means: list[float] = []
        stds: list[float] = []
        for s in tubelet:
            frame_rgb = cv2.cvtColor(s.frame_bgr, cv2.COLOR_BGR2RGB)
            crop = frame_rgb[y1:y2, x1:x2].copy()
            if crop.size == 0:
                crop = np.zeros((self.cfg.deep_crop_size, self.cfg.deep_crop_size, 3), dtype=np.uint8)
            else:
                crop = cv2.resize(crop, (self.cfg.deep_crop_size, self.cfg.deep_crop_size), interpolation=cv2.INTER_LINEAR)
            crops_rgb.append(crop)
            areas.append(float(max(1, x2 - x1) * max(1, y2 - y1)))
            means.append(float(np.mean(crop)))
            stds.append(float(np.std(crop)))
        return crops_rgb, {
            "crop_mode": "union",
            "crop_pad_ratio": float(self.cfg.deep_bbox_pad_ratio),
            "crop_out_size": int(self.cfg.deep_crop_size),
            "crop_union_x1": int(x1), "crop_union_y1": int(y1), "crop_union_x2": int(x2), "crop_union_y2": int(y2),
            "crop_mean_area_px": float(np.mean(areas)) if areas else 0.0,
            "crop_mean_rgb": float(np.mean(means)) if means else 0.0,
            "crop_std_rgb": float(np.mean(stds)) if stds else 0.0,
        }

    def _embed(self, crops_rgb: list[np.ndarray]) -> np.ndarray:
        self.load()
        import torch
        assert self.processor is not None and self.model is not None and self.device is not None
        try:
            inputs = self.processor(list(crops_rgb), return_tensors="pt", do_flip_channel_order=False)
        except TypeError:
            inputs = self.processor(list(crops_rgb), return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        if self.cfg.deep_fp16 and self.device.type == "cuda":
            inputs = {k: (v.half() if torch.is_floating_point(v) else v) for k, v in inputs.items()}
        with torch.inference_mode():
            with torch.autocast(device_type=self.device.type, dtype=torch.float16, enabled=(self.cfg.deep_fp16 and self.device.type == "cuda")):
                outputs = self.model(**inputs)
        emb = outputs.last_hidden_state.mean(dim=1).squeeze(0).float().cpu().numpy().astype(np.float32)
        norm_before = float(np.linalg.norm(emb))
        emb_l2 = emb / max(norm_before, 1e-12)
        return emb_l2.astype(np.float32)

    def score_tubelet(self, tracker_track_id: int, tubelet: list[SampledPerson]) -> DeepGateOutput:
        self.load()
        assert self.knn is not None
        crops_rgb, crop_meta = self._crop_union_rgb(tubelet)
        emb_l2 = self._embed(crops_rgb)
        distances, indices = self.knn.kneighbors(emb_l2.reshape(1, -1), n_neighbors=int(self.cfg.deep_k), return_distance=True)
        distances = np.asarray(distances).reshape(-1).astype(np.float32)
        indices = np.asarray(indices).reshape(-1)
        raw_score = float(np.mean(distances[: self.cfg.deep_k]))
        st = self._state_for(tracker_track_id)
        upd = st.update(raw_score)
        feature_values = {
            "deep_score": raw_score,
            "nearest_neighbor_distance": float(distances[0]) if len(distances) else math.nan,
            "nearest_neighbor_index": int(indices[0]) if len(indices) else -1,
            "embedding_l2_norm": float(np.linalg.norm(emb_l2)),
            **{f"knn_distance_{i+1}": float(v) for i, v in enumerate(distances[: self.cfg.deep_k])},
            **crop_meta,
        }
        metadata = {
            "gate": "deep",
            "model": "videomae_knn_union_crop",
            "knn_path": str(self.knn_path),
            "thresholds_path": str(self.thresholds_path),
            "deep_k": int(self.cfg.deep_k),
            "threshold_key": self.cfg.deep_threshold_key,
            "tubelet_sample_count": len(tubelet),
        }
        return DeepGateOutput(
            raw_score=raw_score,
            smoothed_score=upd.smoothed_score,
            threshold_value=self.threshold_value,
            above_threshold=upd.above_threshold,
            persistence_hits=upd.persistence_hits,
            persistent=upd.persistent,
            feature_values=feature_values,
            metadata=metadata,
            gate_update=upd,
            embedding_l2=emb_l2,
        )
