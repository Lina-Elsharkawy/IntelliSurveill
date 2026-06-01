from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np

from .config import VadConfig
from .frame_types import SampledPerson
from .online_gate_state import OnlineGateState, GateUpdate
from .pose_features import POSE_FEATURE_NAMES, make_pose_feature_from_tubelet

log = logging.getLogger("vad.pose_gate")


@dataclass
class PoseGateOutput:
    raw_score: float
    smoothed_score: float
    threshold_value: float
    above_threshold: bool
    persistent: bool
    persistence_hits: int
    feature_values: dict[str, float]
    metadata: dict[str, Any]
    gate_update: GateUpdate


class PoseGate:
    """Pose micro GMM gate.

    This is the backend version of the pose part of the live multigate tester:
    5 fps route, 24-frame tubelets, stride 6, 30 pose features, RobustScaler +
    GMM score, Gaussian smoothing, and 3/5 persistence.
    """

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.loaded = False
        self.load_error: str | None = None
        self.scaler: Any = None
        self.gmm: Any = None
        self.pose_model: Any = None
        self.model_version_id: int | None = None
        self.threshold_id: int | None = None
        self.threshold_key = cfg.pose_threshold_key
        self.threshold_value = float(cfg.pose_threshold_value)
        self.states: dict[int, OnlineGateState] = {}

    def load(self) -> None:
        if self.loaded:
            return
        try:
            artifact_dir = Path(self.cfg.pose_artifact_dir)
            scaler_path = self._find_existing([
                artifact_dir / "models" / "pose_robust_scaler.joblib",
                artifact_dir / "models" / "pose_scaler.joblib",
                artifact_dir / "models" / "robust_scaler.joblib",
                artifact_dir / "models" / "scaler.joblib",
            ], glob_patterns=["models/*scaler*.joblib", "models/*scaler*.pkl", "*scaler*.joblib", "*scaler*.pkl"])
            gmm_path = self._find_existing([
                artifact_dir / "models" / "pose_gmm_components_5.joblib",
                artifact_dir / "models" / "pose_gmm.joblib",
                artifact_dir / "models" / "gmm.joblib",
            ], glob_patterns=["models/*components_5*.joblib", "models/*gmm*.joblib", "models/*gmm*.pkl", "*gmm*.joblib", "*gmm*.pkl"])
            self.scaler = joblib.load(scaler_path)
            self.gmm = joblib.load(gmm_path)
            if self.cfg.pose_reinfer_enabled:
                from ultralytics import YOLO
                self.pose_model = YOLO(self.cfg.pose_model)
            else:
                self.pose_model = None
            if self.cfg.pose_threshold_value <= 0:
                self.threshold_value = self._load_threshold_from_artifact(artifact_dir, self.cfg.pose_threshold_key)
            self.loaded = True
            self.load_error = None
            log.info("Loaded pose gate scaler=%s gmm=%s threshold=%s", scaler_path, gmm_path, self.threshold_value)
        except Exception as e:
            self.loaded = False
            self.load_error = str(e)
            raise

    @staticmethod
    def _find_existing(candidates: list[Path], *, glob_patterns: list[str]) -> Path:
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        base = candidates[0].parents[1] if len(candidates[0].parents) > 1 else Path(".")
        for pattern in glob_patterns:
            matches = sorted(base.glob(pattern))
            if matches:
                return matches[0]
        raise FileNotFoundError("Could not find pose gate artifact. Tried: " + ", ".join(str(p) for p in candidates))

    @staticmethod
    def _load_threshold_from_artifact(artifact_dir: Path, key: str) -> float:
        candidates = [artifact_dir / "04_pose_thresholds.json", artifact_dir / "pose_thresholds.json"]
        for path in candidates:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            # Common layouts: direct, thresholds, components_5, model rows.
            if isinstance(data, dict):
                for d in [data, data.get("thresholds") if isinstance(data.get("thresholds"), dict) else None]:
                    if isinstance(d, dict):
                        if key in d:
                            return float(d[key])
                        if "components_5" in d and isinstance(d["components_5"], dict) and key in d["components_5"]:
                            return float(d["components_5"][key])
                        if "primary_threshold" in d:
                            return float(d["primary_threshold"])
        raise KeyError(f"Could not load pose threshold key={key!r} from {artifact_dir}")

    def _state_for(self, tracker_track_id: int) -> OnlineGateState:
        state = self.states.get(tracker_track_id)
        if state is None:
            state = OnlineGateState(
                threshold=self.threshold_value,
                sigma=self.cfg.pose_smoothing_sigma,
                persistence_window=self.cfg.pose_persistence_window,
                persistence_required_hits=self.cfg.pose_persistence_required_hits,
            )
            self.states[tracker_track_id] = state
        return state

    def score_tubelet(self, tracker_track_id: int, tubelet: Sequence[SampledPerson]) -> PoseGateOutput:
        self.load()
        assert self.scaler is not None and self.gmm is not None
        feature, feature_meta = make_pose_feature_from_tubelet(
            tubelet,
            kpt_conf=self.cfg.pose_kpt_conf,
            fps=self.cfg.pose_route_fps,
            time_mode=self.cfg.pose_time_mode,
            pose_model=self.pose_model if self.cfg.pose_reinfer_enabled else None,
            pose_imgsz=self.cfg.pose_imgsz,
            pose_conf=self.cfg.pose_conf,
            pose_crop_pad_ratio=self.cfg.pose_crop_pad_ratio,
            pose_min_crop_size=self.cfg.pose_min_crop_size,
            device=self.cfg.detector_device,
        )
        x = feature.reshape(1, -1).astype(np.float32)
        x_scaled = self.scaler.transform(x)
        raw_score = float(-self.gmm.score_samples(x_scaled)[0])
        update = self._state_for(tracker_track_id).update(raw_score)
        feature_values = {name: float(feature[i]) for i, name in enumerate(POSE_FEATURE_NAMES)}
        metadata = {
            "gate": "pose",
            "model": "pose_micro_gmm_gate",
            "score_definition": "negative_gmm_log_likelihood",
            "parity_source": "04_live_multigate_rtsp_test pose branch only",
            "pose_reinfer_enabled": bool(self.cfg.pose_reinfer_enabled),
            "pose_imgsz": int(self.cfg.pose_imgsz),
            "pose_conf": float(self.cfg.pose_conf),
            "pose_crop_pad_ratio": float(self.cfg.pose_crop_pad_ratio),
            "pose_min_crop_size": int(self.cfg.pose_min_crop_size),
            "pose_time_mode": str(self.cfg.pose_time_mode),
            "threshold_key": self.threshold_key,
            "feature_meta": feature_meta,
            "tubelet_start_sample_index": int(tubelet[0].sample_index) if tubelet else None,
            "tubelet_end_sample_index": int(tubelet[-1].sample_index) if tubelet else None,
        }
        return PoseGateOutput(
            raw_score=update.raw_score,
            smoothed_score=update.smoothed_score,
            threshold_value=update.threshold,
            above_threshold=update.hit_smooth,
            persistent=update.persistent,
            persistence_hits=update.persistence_hits,
            feature_values=feature_values,
            metadata=metadata,
            gate_update=update,
        )
