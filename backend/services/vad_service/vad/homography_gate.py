from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .config import VadConfig
from .frame_types import SampledPerson
from .homography_features import (
    FEATURE_NAMES,
    MacroSample,
    TrackGroundState,
    compute_homography_macro_features,
    estimate_groundpoint_from_keypoints,
    load_homography_matrix,
)
from .online_gate_state import GateUpdate, OnlineGateState

log = logging.getLogger("vad.homography_gate")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not read JSON %s: %s", path, e)
    return {}


def _find_first_joblib(folder: Path, include: list[str], exclude: list[str] | None = None) -> Path | None:
    exclude = exclude or []
    if not folder.exists():
        return None
    hits = []
    for p in folder.rglob("*.joblib"):
        name = p.name.lower()
        if all(k.lower() in name for k in include) and not any(k.lower() in name for k in exclude):
            hits.append(p)
    return sorted(hits, key=lambda x: len(str(x)))[0] if hits else None


def _resolve_recommended_path(gate_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    p = Path(str(value))
    if p.exists():
        return p
    # If training stored a Windows absolute path, keep only basename and search under mounted gate dir.
    for cand in gate_dir.rglob(p.name):
        return cand
    return None


@dataclass
class HomographyGateOutput:
    raw_score: float
    smoothed_score: float
    threshold_value: float
    above_threshold: bool
    persistence_hits: int
    persistent: bool
    feature_values: dict[str, Any]
    metadata: dict[str, Any]
    gate_update: GateUpdate


class HomographyMacroGate:
    """Stage-3 homography/macro gate using pose-assisted ankle ground points."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.scaler = None
        self.pca = None
        self.gmm = None
        self.H: np.ndarray | None = None
        self.loaded = False
        self.load_error: str | None = None
        self.threshold_value = float(cfg.homography_macro_threshold_value)
        self.states: dict[int, OnlineGateState] = {}
        self.ground_states: dict[int, TrackGroundState] = {}
        self.pose_model: Any = None
        self.active_persistent: dict[int, bool] = {}
        self.scaler_path = ""
        self.pca_path = ""
        self.gmm_path = ""
        self.homography_macro_gmm_components: int = int(getattr(cfg, "homography_macro_gmm_components", 8))
        self.homography_path = ""

    def load(self) -> None:
        if self.loaded:
            return
        try:
            gate_dir = self.cfg.homography_macro_artifact_dir
            rec_path = gate_dir / "09_recommended_macro_gate.json"
            rec = _read_json(rec_path)
            artifacts = rec.get("artifacts", {}) if isinstance(rec, dict) else {}
            scaler_path = _resolve_recommended_path(gate_dir, artifacts.get("scaler")) or _find_first_joblib(gate_dir, ["scaler"]) or _find_first_joblib(gate_dir, ["robust"])
            pca_path = _resolve_recommended_path(gate_dir, artifacts.get("pca"))
            macro_components = int(getattr(self.cfg, "homography_macro_gmm_components", 8))

            # Deployment must choose the GMM component count explicitly.
            # Do not let 09_recommended_macro_gate.json or primary_components
            # silently select a different model than the configured threshold.
            gmm_path = _find_first_joblib(gate_dir, [f"components_{macro_components}"])

            if gmm_path is None:
                gmm_path = _resolve_recommended_path(gate_dir, artifacts.get("gmm"))

            if gmm_path is None:
                primary_k = rec.get("primary_components") or (rec.get("training", {}) if isinstance(rec.get("training"), dict) else {}).get("primary_components") if isinstance(rec, dict) else None
                if primary_k:
                    gmm_path = _find_first_joblib(gate_dir, [f"components_{int(primary_k)}"])

            gmm_path = gmm_path or _find_first_joblib(gate_dir, ["gmm"])
            if scaler_path is None or not scaler_path.exists():
                raise FileNotFoundError(f"Could not find macro RobustScaler joblib under {gate_dir}")
            if gmm_path is None or not gmm_path.exists():
                raise FileNotFoundError(f"Could not find macro GMM joblib under {gate_dir}")
            self.scaler = joblib.load(scaler_path)
            self.pca = joblib.load(pca_path) if pca_path and pca_path.exists() else None
            self.gmm = joblib.load(gmm_path)
            if rec.get("threshold") is not None:
                self.threshold_value = float(rec["threshold"])
            elif rec.get("primary_threshold") is not None:
                self.threshold_value = float(rec["primary_threshold"])
            # Artifact threshold wins by default. Only an explicitly provided
            # VAD_HOMOGRAPHY_MACRO_THRESHOLD_VALUE env var may override it.
            # This prevents the old config default from silently overriding
            # the newly deployed p99_7 09_recommended_macro_gate.json.
            if "VAD_HOMOGRAPHY_MACRO_THRESHOLD_VALUE" in os.environ:
                self.threshold_value = float(self.cfg.homography_macro_threshold_value)
            H_path = self.cfg.homography_matrix_path if self.cfg.homography_matrix_path else gate_dir
            self.H, self.homography_path = load_homography_matrix(H_path)
            if str(self.cfg.homography_groundpoint_mode).lower().strip() == "pose_ankle":
                from ultralytics import YOLO
                self.pose_model = YOLO(self.cfg.homography_pose_model)
            else:
                self.pose_model = None
            self.scaler_path = str(scaler_path); self.pca_path = str(pca_path or ""); self.gmm_path = str(gmm_path)
            self.homography_macro_gmm_components = macro_components
            self.loaded = True
            self.load_error = None
            log.info("Loaded homography macro gate scaler=%s gmm=%s components=%s H=%s threshold=%.6f", self.scaler_path, self.gmm_path, self.homography_macro_gmm_components, self.homography_path, self.threshold_value)
        except Exception as e:
            self.loaded = False
            self.load_error = str(e)
            raise

    def _state_for(self, tracker_track_id: int) -> OnlineGateState:
        st = self.states.get(tracker_track_id)
        if st is None:
            st = OnlineGateState(
                threshold=self.threshold_value,
                sigma=self.cfg.homography_macro_smoothing_sigma,
                persistence_required_hits=self.cfg.homography_macro_persistence_required_hits,
                persistence_window=self.cfg.homography_macro_persistence_window,
            )
            self.states[tracker_track_id] = st
        return st

    def make_macro_sample(self, sample: SampledPerson) -> MacroSample:
        gs = self.ground_states.get(sample.tracker_track_id)
        if gs is None:
            gs = TrackGroundState()
            self.ground_states[sample.tracker_track_id] = gs
        ground_xy, meta = estimate_groundpoint_from_keypoints(
            sample,
            gs,
            ankle_conf_threshold=self.cfg.homography_ankle_conf_threshold,
            fallback_mode=self.cfg.homography_fallback_mode,
            max_freeze_samples=self.cfg.homography_max_freeze_samples,
            groundpoint_mode=self.cfg.homography_groundpoint_mode,
            pose_model=self.pose_model,
            pose_imgsz=self.cfg.homography_pose_imgsz,
            pose_conf=self.cfg.homography_pose_conf,
            pose_crop_pad_ratio=self.cfg.homography_pose_crop_pad_ratio,
            pose_min_crop_size=self.cfg.homography_pose_min_crop_size,
            device=self.cfg.detector_device,
        )
        # Macro route is 2.5 fps, so use macro-route sample index time, matching calibration.
        t_sample = (sample.sample_index // 2) / max(float(self.cfg.homography_macro_route_fps), 1e-6)
        return MacroSample(
            sample=sample,
            t_sample=float(t_sample),
            ground_xy=ground_xy,
            ground_source=str(meta.get("ground_source", "unknown")),
            ground_conf=float(meta.get("ground_conf", 0.0)),
            ground_frozen=bool(meta.get("ground_frozen", False)),
            ground_meta=meta,
        )

    def score_tubelet(self, tracker_track_id: int, tubelet: list[MacroSample]) -> HomographyGateOutput:
        self.load()
        assert self.scaler is not None and self.gmm is not None and self.H is not None
        X, meta = compute_homography_macro_features(
            tubelet,
            self.H,
            stationary_speed_threshold=self.cfg.homography_stationary_speed_threshold,
            trajectory_smoothing=self.cfg.homography_trajectory_smoothing,
            smoothing_window=self.cfg.homography_trajectory_smoothing_window,
            smoothing_polyorder=self.cfg.homography_trajectory_smoothing_polyorder,
            reject_nonphysical_steps=self.cfg.homography_reject_nonphysical_steps,
            max_plausible_speed=self.cfg.homography_max_plausible_speed,
            max_plausible_accel=self.cfg.homography_max_plausible_accel,
        )
        if self.cfg.homography_min_valid_groundpoint_ratio > 0 and meta.get("valid_groundpoint_ratio", 0.0) < self.cfg.homography_min_valid_groundpoint_ratio:
            X = np.zeros((1, len(FEATURE_NAMES)), dtype=np.float32)
            X[0, 6] = 1.0
            meta["neutralized_due_to_low_valid_groundpoint_ratio"] = True
        else:
            meta["neutralized_due_to_low_valid_groundpoint_ratio"] = False
        Xs = self.scaler.transform(X)
        if self.pca is not None:
            Xs = self.pca.transform(Xs)
        raw_score = float(-self.gmm.score_samples(Xs)[0])
        upd = self._state_for(tracker_track_id).update(raw_score)
        feature_values = {name: float(X[0, i]) for i, name in enumerate(FEATURE_NAMES)}
        previous = bool(self.active_persistent.get(tracker_track_id, False))
        rising_edge = bool(upd.persistent and not previous)
        self.active_persistent[tracker_track_id] = bool(upd.persistent)
        metadata = {
            "gate": "homography_macro",
            "model": "robust_scaler_gmm_stage3_pose_groundpoint",
            "scaler_path": self.scaler_path,
            "pca_path": self.pca_path,
            "gmm_path": self.gmm_path,
            "homography_macro_gmm_components": int(self.homography_macro_gmm_components),
            "homography_path": self.homography_path,
            "feature_names": FEATURE_NAMES,
            "persistent_rising_edge": rising_edge,
            **meta,
        }
        return HomographyGateOutput(
            raw_score=raw_score,
            smoothed_score=upd.smoothed_score,
            threshold_value=self.threshold_value,
            above_threshold=upd.above_threshold,
            persistence_hits=upd.persistence_hits,
            persistent=upd.persistent,
            feature_values=feature_values,
            metadata=metadata,
            gate_update=upd,
        )
