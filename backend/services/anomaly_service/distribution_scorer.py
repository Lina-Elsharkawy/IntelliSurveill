from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import torch
from transformers import VideoMAEImageProcessor, VideoMAEModel

from config import (
    VIDEO_ENCODER_MODEL,
    VIDEO_ENCODER_DEVICE,
    VIDEO_ENCODER_USE_FP16,
    TUBELET_FRAMES,
    PERSON_SCALER_PATH,
    PERSON_PCA_PATH,
    PERSON_COV_PATH,
    CONTEXT_SCALER_PATH,
    CONTEXT_PCA_PATH,
    CONTEXT_COV_PATH,
    THRESHOLDS_JSON_PATH,
    FUSION_CONFIG_JSON_PATH,
    DISTRIBUTION_THRESHOLD_NAME,
)
from evidence_io import sample_frames

log = logging.getLogger("distribution_scorer")


@dataclass
class ScoreResult:
    person_score: float
    context_score: float
    person_score_norm: float
    context_score_norm: float
    final_score: float
    threshold_name: str
    threshold_value: float
    distribution_gate: bool


class DistributionScorer:
    def __init__(self) -> None:
        self.person_scaler = None
        self.person_pca = None
        self.person_cov = None
        self.context_scaler = None
        self.context_pca = None
        self.context_cov = None
        self.thresholds: dict[str, Any] = {}
        self.fusion_config: dict[str, Any] = {}
        self.processor: VideoMAEImageProcessor | None = None
        self.encoder: VideoMAEModel | None = None
        self.device: torch.device | None = None
        self.artifacts_loaded = False
        self.encoder_loaded = False
        self.artifact_error: str | None = None
        self.encoder_error: str | None = None

    def load_distribution_artifacts(self) -> None:
        if self.artifacts_loaded:
            return
        try:
            required = [
                PERSON_SCALER_PATH, PERSON_PCA_PATH, PERSON_COV_PATH,
                CONTEXT_SCALER_PATH, CONTEXT_PCA_PATH, CONTEXT_COV_PATH,
                THRESHOLDS_JSON_PATH, FUSION_CONFIG_JSON_PATH,
            ]
            missing = [str(p) for p in required if not Path(p).exists()]
            if missing:
                raise FileNotFoundError("Missing distribution artifacts: " + ", ".join(missing))

            self.person_scaler = joblib.load(PERSON_SCALER_PATH)
            self.person_pca = joblib.load(PERSON_PCA_PATH)
            self.person_cov = joblib.load(PERSON_COV_PATH)
            self.context_scaler = joblib.load(CONTEXT_SCALER_PATH)
            self.context_pca = joblib.load(CONTEXT_PCA_PATH)
            self.context_cov = joblib.load(CONTEXT_COV_PATH)
            self.thresholds = json.loads(Path(THRESHOLDS_JSON_PATH).read_text(encoding="utf-8"))
            self.fusion_config = json.loads(Path(FUSION_CONFIG_JSON_PATH).read_text(encoding="utf-8"))
            # Validate normalization stats immediately. The final thresholds in
            # thresholds.json are normalized thresholds, so silently falling back
            # to median=0 / iqr=1 would make scores explode.
            p_median, p_iqr = self._stats_for("person")
            c_median, c_iqr = self._stats_for("context")
            log.info(
                "Distribution normalization stats: person median=%.6f iqr=%.6f | context median=%.6f iqr=%.6f",
                p_median, p_iqr, c_median, c_iqr,
            )
            self.artifacts_loaded = True
            self.artifact_error = None
            log.info("Loaded distribution artifacts from %s", THRESHOLDS_JSON_PATH.parent)
        except Exception as e:
            self.artifact_error = str(e)
            self.artifacts_loaded = False
            raise

    def load_video_encoder(self) -> None:
        if self.encoder_loaded:
            return
        try:
            self.device = torch.device(
                VIDEO_ENCODER_DEVICE
                if (VIDEO_ENCODER_DEVICE != "cuda" or torch.cuda.is_available())
                else "cpu"
            )
            self.processor = VideoMAEImageProcessor.from_pretrained(VIDEO_ENCODER_MODEL)
            self.encoder = VideoMAEModel.from_pretrained(
                VIDEO_ENCODER_MODEL,
                attn_implementation="sdpa" if self.device.type == "cuda" else "eager",
            )
            self.encoder.eval().to(self.device)
            self.encoder_loaded = True
            self.encoder_error = None
            log.info("Loaded VideoMAE encoder %s on %s", VIDEO_ENCODER_MODEL, self.device)
        except Exception as e:
            self.encoder_error = str(e)
            self.encoder_loaded = False
            raise

    @staticmethod
    def validate_embedding(embedding: list[float] | np.ndarray, *, name: str) -> np.ndarray:
        arr = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if arr.shape[0] != 768:
            raise ValueError(f"{name} must be 768-dimensional, got {arr.shape[0]}")
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"{name} contains NaN or infinite values")
        return arr

    @staticmethod
    def _as_rgb_frame(frame: np.ndarray) -> np.ndarray:
        """Return an RGB uint8 frame, matching the offline RTSP test script.

        Frames fetched through OpenCV/evidence_io are normally BGR.  The
        original offline distribution test converted BGR -> RGB before calling
        the Hugging Face VideoMAE processor, so the backend must do the same.
        """
        arr = np.asarray(frame)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise ValueError(f"Expected HxWx3 frame, got shape={arr.shape}")
        arr = arr[:, :, :3]
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        # OpenCV-decoded frames are BGR. Convert to RGB without adding a cv2 dependency here.
        return arr[:, :, ::-1].copy()

    @torch.inference_mode()
    def extract_videomae_embedding(self, frames: list[np.ndarray]) -> np.ndarray:
        self.load_video_encoder()
        if not frames:
            raise ValueError("Cannot extract VideoMAE embedding from empty frame list")
        assert self.processor is not None and self.encoder is not None and self.device is not None

        sampled = sample_frames(frames, TUBELET_FRAMES)
        sampled_rgb = [self._as_rgb_frame(fr) for fr in sampled]

        # Keep this call aligned with the offline script that produced the
        # distribution artifacts: processor(frames_rgb, return_tensors="pt").
        # Do not wrap the frame list as images=[sampled], because that can change
        # the perceived batch/video structure depending on transformers version.
        inputs = self.processor(sampled_rgb, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        if VIDEO_ENCODER_USE_FP16 and self.device.type == "cuda":
            inputs = {
                k: (v.half() if torch.is_floating_point(v) else v)
                for k, v in inputs.items()
            }

        with torch.autocast(
            device_type=self.device.type,
            dtype=torch.float16 if self.device.type == "cuda" else torch.float32,
            enabled=(VIDEO_ENCODER_USE_FP16 and self.device.type == "cuda"),
        ):
            outputs = self.encoder(**inputs)
        embedding = outputs.last_hidden_state.mean(dim=1).squeeze(0).float().cpu().numpy()
        return self.validate_embedding(embedding, name="VideoMAE embedding")

    @staticmethod
    def score_embedding(embedding: np.ndarray, scaler: Any, pca: Any, covariance_model: Any) -> float:
        x = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
        z = scaler.transform(x)
        z = pca.transform(z)
        if hasattr(covariance_model, "mahalanobis"):
            score = float(covariance_model.mahalanobis(z)[0])
        else:
            center = getattr(covariance_model, "location_", np.zeros(z.shape[1]))
            precision = getattr(covariance_model, "precision_", None)
            if precision is None:
                covariance = getattr(covariance_model, "covariance_", None)
                if covariance is None:
                    raise ValueError("Covariance artifact has neither mahalanobis(), precision_, nor covariance_")
                precision = np.linalg.pinv(covariance)
            diff = z - center.reshape(1, -1)
            score = float(np.einsum("ij,jk,ik->i", diff, precision, diff)[0])
        return max(score, 0.0)

    def _stats_for(self, stream: str) -> tuple[float, float]:
        """Resolve robust-IQR normalisation stats for a stream.

        The offline artifact file uses keys like:
            person_normalization_stats: {median, iqr, ...}
            context_normalization_stats: {median, iqr, ...}

        The previous backend scorer did not look for those keys, so it silently
        fell back to median=0 and iqr=1. That made the final score look like a
        raw Mahalanobis score (for example 200-350) while comparing it against
        normalized thresholds around 2-4.
        """
        cfg = self.fusion_config or {}

        nested_norm = None
        if isinstance(cfg.get("normalization"), dict):
            nested_norm = cfg["normalization"].get(stream)

        candidates = [
            cfg.get(f"{stream}_normalization_stats"),
            cfg.get(f"initial_{stream}_normalization_stats"),
            cfg.get(stream),
            cfg.get(f"{stream}_score"),
            nested_norm,
            cfg,
        ]

        for item in candidates:
            if not isinstance(item, dict):
                continue
            median = item.get("median", item.get(f"{stream}_median"))
            iqr = item.get("iqr", item.get(f"{stream}_iqr"))
            if median is not None and iqr is not None:
                return float(median), max(float(iqr), 1e-6)

        raise KeyError(
            f"Missing robust-IQR normalization stats for stream={stream!r}. "
            f"Expected {stream}_normalization_stats with median and iqr in "
            f"{FUSION_CONFIG_JSON_PATH}."
        )

    def robust_normalize(self, score: float, stream: str) -> float:
        median, iqr = self._stats_for(stream)
        return float((float(score) - median) / iqr)

    def get_threshold(self, threshold_name: str | None = None) -> tuple[str, float]:
        raw_name = threshold_name or DISTRIBUTION_THRESHOLD_NAME
        name = raw_name.replace("final.", "")
        aliases = [raw_name, name, f"final.{name}", f"final_{name}"]
        for key in aliases:
            if key in self.thresholds:
                return name, float(self.thresholds[key])
        final = self.thresholds.get("final")
        if isinstance(final, dict) and name in final:
            return name, float(final[name])
        raise KeyError(f"Threshold {raw_name!r} not found in thresholds.json")

    def percentile(self, name: str) -> float | None:
        try:
            _, value = self.get_threshold(name)
            return value
        except Exception:
            return None

    def score_person_context(
        self,
        person_embedding: list[float] | np.ndarray,
        context_embedding: list[float] | np.ndarray,
        *,
        threshold_name: str | None = None,
    ) -> ScoreResult:
        self.load_distribution_artifacts()
        person = self.validate_embedding(person_embedding, name="person_embedding")
        context = self.validate_embedding(context_embedding, name="context_embedding")

        person_score = self.score_embedding(person, self.person_scaler, self.person_pca, self.person_cov)
        context_score = self.score_embedding(context, self.context_scaler, self.context_pca, self.context_cov)
        person_score_norm = self.robust_normalize(person_score, "person")
        context_score_norm = self.robust_normalize(context_score, "context")

        person_weight = float(self.fusion_config.get("person_weight", 0.65))
        context_weight = float(self.fusion_config.get("context_weight", 0.35))
        total_weight = max(person_weight + context_weight, 1e-9)
        final_score = float((person_weight * person_score_norm + context_weight * context_score_norm) / total_weight)

        th_name, th_value = self.get_threshold(threshold_name)
        return ScoreResult(
            person_score=person_score,
            context_score=context_score,
            person_score_norm=person_score_norm,
            context_score_norm=context_score_norm,
            final_score=final_score,
            threshold_name=th_name,
            threshold_value=th_value,
            distribution_gate=final_score > th_value,
        )
