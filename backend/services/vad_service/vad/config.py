from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def _float(name: str, default: str) -> float:
    raw = os.getenv(name, default)
    try:
        return float(str(raw).strip())
    except Exception:
        raise ValueError(f"Environment variable {name} must be a float, got {raw!r}")


def _int(name: str, default: str) -> int:
    raw = os.getenv(name, default)
    try:
        return int(str(raw).strip())
    except Exception:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}")


@dataclass(frozen=True)
class VadConfig:
    backend_direct_enabled: bool
    autostart: bool

    db_dsn: str

    rtsp_url_env_var: str
    rtsp_url: str

    stream_key: str
    camera_key: str
    camera_id: int | None

    target_sample_fps: float
    rolling_buffer_sec: float

    debug_save_dir: Path
    debug_save_every_n_frames: int

    pose_route_fps: float
    deep_route_fps: float
    homography_macro_route_fps: float

    deep_artifact_dir: Path
    pose_artifact_dir: Path
    homography_macro_artifact_dir: Path

    reconnect_sleep_sec: float
    open_timeout_sec: float
    read_fail_reconnect_after: int
    db_insert_every_n_frames: int
    jpeg_quality: int

    # Shared YOLO tracking backbone
    tracking_enabled: bool
    detector_model: Path | str
    detector_device: str
    detector_conf: float
    detector_imgsz: int
    tracker_config: str
    track_buffer_max_age_samples: int

    # Pose gate slice
    pose_gate_enabled: bool
    pose_tubelet_frames: int
    pose_stride: int
    pose_kpt_conf: float
    pose_model: Path | str
    pose_imgsz: int
    pose_conf: float
    pose_crop_pad_ratio: float
    pose_min_crop_size: int
    pose_reinfer_enabled: bool
    pose_time_mode: str
    pose_threshold_key: str
    pose_threshold_value: float
    pose_smoothing_sigma: float
    pose_persistence_window: int
    pose_persistence_required_hits: int
    pose_min_event_gap_sec: float

    # Deep gate slice
    deep_gate_enabled: bool
    deep_k: int
    deep_threshold_key: str
    deep_threshold_value: float
    deep_tubelet_frames: int
    deep_stride: int
    deep_bbox_pad_ratio: float
    deep_crop_size: int
    deep_smoothing_sigma: float
    deep_persistence_window: int
    deep_persistence_required_hits: int
    deep_min_event_gap_sec: float
    deep_device: str
    deep_fp16: bool
    deep_videomae_model: str
    deep_use_fast_processor: bool

    # Deep gate VLM/LLM reasoning slice
    deep_reasoning_enabled: bool
    deep_reasoning_require_evidence: bool
    deep_reasoning_min_ratio: float
    deep_reasoning_prompt_version: str
    deep_reasoning_priority: str
    deep_reasoning_max_attempts: int

    # VAD reasoning worker / provider slice
    reasoning_worker_enabled: bool
    reasoning_poll_interval_sec: float
    reasoning_batch_size: int
    reasoning_provider: str
    reasoning_use_llm_normalizer: bool
    reasoning_max_images: int
    reasoning_image_roles: str
    ollama_base_url: str
    ollama_vlm_model: str
    ollama_llm_model: str
    ollama_timeout_sec: float

    # Homography / macro gate slice
    homography_macro_gate_enabled: bool
    homography_macro_tubelet_frames: int
    homography_macro_stride: int
    homography_macro_threshold_key: str
    homography_macro_threshold_value: float
    homography_macro_smoothing_sigma: float
    homography_macro_persistence_window: int
    homography_macro_persistence_required_hits: int
    homography_macro_min_event_gap_sec: float
    homography_matrix_path: Path | None
    homography_groundpoint_mode: str
    homography_pose_model: Path | str
    homography_pose_imgsz: int
    homography_pose_conf: float
    homography_pose_crop_pad_ratio: float
    homography_pose_min_crop_size: int
    homography_ankle_conf_threshold: float
    homography_fallback_mode: str
    homography_max_freeze_samples: int
    homography_stationary_speed_threshold: float
    homography_trajectory_smoothing: str
    homography_trajectory_smoothing_window: int
    homography_trajectory_smoothing_polyorder: int
    homography_reject_nonphysical_steps: bool
    homography_max_plausible_speed: float
    homography_max_plausible_accel: float
    homography_min_valid_groundpoint_ratio: float

    # Event + MinIO evidence slice
    evidence_enabled: bool
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_public_endpoint: str
    minio_public_secure: bool
    minio_bucket: str
    evidence_prefix: str
    save_evidence_on_gate_event: bool
    save_evidence_on_persistent_hit: bool

    @property
    def rolling_buffer_max_frames(self) -> int:
        return max(1, int(round(self.target_sample_fps * self.rolling_buffer_sec)))

    @property
    def route_fps_json(self) -> dict[str, float]:
        return {
            "pose": self.pose_route_fps,
            "deep": self.deep_route_fps,
            "homography_macro": self.homography_macro_route_fps,
        }

    def public_dict(self) -> dict[str, object]:
        """Safe config view that never returns the RTSP URL/password."""
        return {
            "backend_direct_enabled": self.backend_direct_enabled,
            "autostart": self.autostart,
            "rtsp_url_env_var": self.rtsp_url_env_var,
            "rtsp_url_configured": bool(self.rtsp_url),
            "stream_key": self.stream_key,
            "camera_key": self.camera_key,
            "camera_id": self.camera_id,
            "target_sample_fps": self.target_sample_fps,
            "rolling_buffer_sec": self.rolling_buffer_sec,
            "rolling_buffer_max_frames": self.rolling_buffer_max_frames,
            "debug_save_dir": str(self.debug_save_dir),
            "debug_save_every_n_frames": self.debug_save_every_n_frames,
            "route_fps_json": self.route_fps_json,
            "deep_artifact_dir": str(self.deep_artifact_dir),
            "pose_artifact_dir": str(self.pose_artifact_dir),
            "homography_macro_artifact_dir": str(self.homography_macro_artifact_dir),
            "db_insert_every_n_frames": self.db_insert_every_n_frames,
            "tracking_enabled": self.tracking_enabled,
            "detector_model": str(self.detector_model),
            "detector_device": self.detector_device,
            "detector_conf": self.detector_conf,
            "detector_imgsz": self.detector_imgsz,
            "tracker_config": self.tracker_config,
            "track_buffer_max_age_samples": self.track_buffer_max_age_samples,
            "pose_gate_enabled": self.pose_gate_enabled,
            "pose_tubelet_frames": self.pose_tubelet_frames,
            "pose_stride": self.pose_stride,
            "pose_kpt_conf": self.pose_kpt_conf,
            "pose_model": str(self.pose_model),
            "pose_imgsz": self.pose_imgsz,
            "pose_conf": self.pose_conf,
            "pose_crop_pad_ratio": self.pose_crop_pad_ratio,
            "pose_min_crop_size": self.pose_min_crop_size,
            "pose_reinfer_enabled": self.pose_reinfer_enabled,
            "pose_time_mode": self.pose_time_mode,
            "pose_threshold_key": self.pose_threshold_key,
            "pose_threshold_value": self.pose_threshold_value,
            "pose_smoothing_sigma": self.pose_smoothing_sigma,
            "pose_persistence_window": self.pose_persistence_window,
            "pose_persistence_required_hits": self.pose_persistence_required_hits,
            "pose_min_event_gap_sec": self.pose_min_event_gap_sec,
            "deep_gate_enabled": self.deep_gate_enabled,
            "deep_k": self.deep_k,
            "deep_threshold_key": self.deep_threshold_key,
            "deep_threshold_value": self.deep_threshold_value,
            "deep_tubelet_frames": self.deep_tubelet_frames,
            "deep_stride": self.deep_stride,
            "deep_bbox_pad_ratio": self.deep_bbox_pad_ratio,
            "deep_crop_size": self.deep_crop_size,
            "deep_smoothing_sigma": self.deep_smoothing_sigma,
            "deep_persistence_window": self.deep_persistence_window,
            "deep_persistence_required_hits": self.deep_persistence_required_hits,
            "deep_min_event_gap_sec": self.deep_min_event_gap_sec,
            "deep_device": self.deep_device,
            "deep_fp16": self.deep_fp16,
            "deep_videomae_model": self.deep_videomae_model,
            "deep_reasoning_enabled": self.deep_reasoning_enabled,
            "deep_reasoning_require_evidence": self.deep_reasoning_require_evidence,
            "deep_reasoning_min_ratio": self.deep_reasoning_min_ratio,
            "deep_reasoning_prompt_version": self.deep_reasoning_prompt_version,
            "deep_reasoning_priority": self.deep_reasoning_priority,
            "deep_reasoning_max_attempts": self.deep_reasoning_max_attempts,
            "reasoning_worker_enabled": self.reasoning_worker_enabled,
            "reasoning_poll_interval_sec": self.reasoning_poll_interval_sec,
            "reasoning_batch_size": self.reasoning_batch_size,
            "reasoning_provider": self.reasoning_provider,
            "reasoning_use_llm_normalizer": self.reasoning_use_llm_normalizer,
            "reasoning_max_images": self.reasoning_max_images,
            "reasoning_image_roles": self.reasoning_image_roles,
            "ollama_base_url": self.ollama_base_url,
            "ollama_vlm_model": self.ollama_vlm_model,
            "ollama_llm_model": self.ollama_llm_model,
            "ollama_timeout_sec": self.ollama_timeout_sec,
            "homography_macro_gate_enabled": self.homography_macro_gate_enabled,
            "homography_macro_tubelet_frames": self.homography_macro_tubelet_frames,
            "homography_macro_stride": self.homography_macro_stride,
            "homography_macro_threshold_key": self.homography_macro_threshold_key,
            "homography_macro_threshold_value": self.homography_macro_threshold_value,
            "homography_macro_smoothing_sigma": self.homography_macro_smoothing_sigma,
            "homography_macro_persistence_window": self.homography_macro_persistence_window,
            "homography_macro_persistence_required_hits": self.homography_macro_persistence_required_hits,
            "homography_macro_min_event_gap_sec": self.homography_macro_min_event_gap_sec,
            "homography_matrix_path": str(self.homography_matrix_path) if self.homography_matrix_path else "",
            "homography_groundpoint_mode": self.homography_groundpoint_mode,
            "homography_pose_model": str(self.homography_pose_model),
            "homography_pose_imgsz": self.homography_pose_imgsz,
            "homography_pose_conf": self.homography_pose_conf,
            "homography_pose_crop_pad_ratio": self.homography_pose_crop_pad_ratio,
            "homography_pose_min_crop_size": self.homography_pose_min_crop_size,
            "homography_ankle_conf_threshold": self.homography_ankle_conf_threshold,
            "homography_fallback_mode": self.homography_fallback_mode,
            "homography_max_freeze_samples": self.homography_max_freeze_samples,
            "homography_stationary_speed_threshold": self.homography_stationary_speed_threshold,
            "homography_trajectory_smoothing": self.homography_trajectory_smoothing,
            "homography_trajectory_smoothing_window": self.homography_trajectory_smoothing_window,
            "homography_trajectory_smoothing_polyorder": self.homography_trajectory_smoothing_polyorder,
            "homography_reject_nonphysical_steps": self.homography_reject_nonphysical_steps,
            "homography_max_plausible_speed": self.homography_max_plausible_speed,
            "homography_max_plausible_accel": self.homography_max_plausible_accel,
            "homography_min_valid_groundpoint_ratio": self.homography_min_valid_groundpoint_ratio,
            "evidence_enabled": self.evidence_enabled,
            "minio_endpoint": self.minio_endpoint,
            "minio_bucket": self.minio_bucket,
            "evidence_prefix": self.evidence_prefix,
            "save_evidence_on_gate_event": self.save_evidence_on_gate_event,
            "save_evidence_on_persistent_hit": self.save_evidence_on_persistent_hit,
        }


def load_vad_config() -> VadConfig:
    rtsp_url_env_var = os.getenv("VAD_RTSP_URL_ENV_VAR", "VAD_RTSP_URL_LAB_CAM_02").strip()
    rtsp_url = os.getenv(rtsp_url_env_var, "").strip()

    camera_id_raw = os.getenv("VAD_CAMERA_ID", "").strip()
    camera_id = int(camera_id_raw) if camera_id_raw else None

    detector_model_raw = os.getenv("VAD_DETECTOR_MODEL", "/models/vad/yolo/yolov8s-pose.pt").strip()
    detector_model: Path | str = Path(detector_model_raw) if detector_model_raw.startswith(('/', './', '../')) or ':' in detector_model_raw else detector_model_raw
    pose_model_raw = os.getenv("VAD_POSE_MODEL", detector_model_raw).strip()
    pose_model: Path | str = Path(pose_model_raw) if pose_model_raw.startswith(('/', './', '../')) or ':' in pose_model_raw else pose_model_raw
    homography_pose_model_raw = os.getenv("VAD_HOMOGRAPHY_POSE_MODEL", pose_model_raw).strip()
    homography_pose_model: Path | str = Path(homography_pose_model_raw) if homography_pose_model_raw.startswith(('/', './', '../')) or ':' in homography_pose_model_raw else homography_pose_model_raw
    homography_matrix_raw = os.getenv("VAD_HOMOGRAPHY_MATRIX_PATH", "").strip()
    homography_matrix_path = Path(homography_matrix_raw) if homography_matrix_raw else None

    cfg = VadConfig(
        backend_direct_enabled=_bool("VAD_BACKEND_DIRECT_ENABLED", "1"),
        autostart=_bool("VAD_AUTOSTART", "0"),
        db_dsn=os.getenv("DB_DSN") or os.getenv("DATABASE_URL") or "postgresql://lina:123@postgres-db:5432/lina",
        rtsp_url_env_var=rtsp_url_env_var,
        rtsp_url=rtsp_url,
        stream_key=os.getenv("VAD_STREAM_KEY", "lab_cam_02").strip(),
        camera_key=os.getenv("VAD_CAMERA_KEY", "lab_cam_02").strip(),
        camera_id=camera_id,
        target_sample_fps=_float("VAD_TARGET_SAMPLE_FPS", "5.0"),
        rolling_buffer_sec=_float("VAD_ROLLING_BUFFER_SEC", "30.0"),
        debug_save_dir=Path(os.getenv("VAD_DEBUG_SAVE_DIR", "/app/debug_vad")),
        debug_save_every_n_frames=_int("VAD_DEBUG_SAVE_EVERY_N_FRAMES", "0"),
        pose_route_fps=_float("VAD_POSE_ROUTE_FPS", "5.0"),
        deep_route_fps=_float("VAD_DEEP_ROUTE_FPS", "2.5"),
        homography_macro_route_fps=_float("VAD_HOMOGRAPHY_MACRO_ROUTE_FPS", "2.5"),
        deep_artifact_dir=Path(os.getenv("VAD_DEEP_ARTIFACT_DIR", "/models/vad/deep")),
        pose_artifact_dir=Path(os.getenv("VAD_POSE_ARTIFACT_DIR", "/models/vad/pose")),
        homography_macro_artifact_dir=Path(os.getenv("VAD_HOMOGRAPHY_MACRO_ARTIFACT_DIR", "/models/vad/homography_macro")),
        reconnect_sleep_sec=_float("VAD_RECONNECT_SLEEP_SEC", "2.0"),
        open_timeout_sec=_float("VAD_OPEN_TIMEOUT_SEC", "10.0"),
        read_fail_reconnect_after=_int("VAD_READ_FAIL_RECONNECT_AFTER", "30"),
        db_insert_every_n_frames=_int("VAD_DB_INSERT_EVERY_N_FRAMES", "1"),
        jpeg_quality=max(1, min(100, _int("VAD_JPEG_QUALITY", "85"))),
        tracking_enabled=_bool("VAD_TRACKING_ENABLED", "1"),
        detector_model=detector_model,
        detector_device=os.getenv("VAD_DETECTOR_DEVICE", "cuda").strip(),
        detector_conf=_float("VAD_DETECTOR_CONF", "0.25"),
        detector_imgsz=_int("VAD_DETECTOR_IMGSZ", "640"),
        tracker_config=os.getenv("VAD_TRACKER_CONFIG", "bytetrack.yaml").strip(),
        track_buffer_max_age_samples=_int("VAD_TRACK_BUFFER_MAX_AGE_SAMPLES", "75"),
        pose_gate_enabled=_bool("VAD_POSE_GATE_ENABLED", "1"),
        pose_tubelet_frames=_int("VAD_POSE_TUBELET_FRAMES", "24"),
        pose_stride=_int("VAD_POSE_STRIDE", "6"),
        pose_kpt_conf=_float("VAD_POSE_KPT_CONF", "0.30"),
        pose_model=pose_model,
        pose_imgsz=_int("VAD_POSE_IMGSZ", "256"),
        pose_conf=_float("VAD_POSE_CONF", "0.25"),
        pose_crop_pad_ratio=_float("VAD_POSE_CROP_PAD_RATIO", "0.25"),
        pose_min_crop_size=_int("VAD_POSE_MIN_CROP_SIZE", "192"),
        pose_reinfer_enabled=_bool("VAD_POSE_REINFER_ENABLED", "1"),
        pose_time_mode=os.getenv("VAD_POSE_TIME_MODE", "sample").strip().lower(),
        pose_threshold_key=os.getenv("VAD_POSE_THRESHOLD_KEY", "components_5_p99_5").strip(),
        pose_threshold_value=_float("VAD_POSE_THRESHOLD_VALUE", "70.18459395136654"),
        pose_smoothing_sigma=_float("VAD_POSE_SMOOTHING_SIGMA", "2.0"),
        pose_persistence_window=_int("VAD_POSE_PERSISTENCE_WINDOW", "5"),
        pose_persistence_required_hits=_int("VAD_POSE_PERSISTENCE_REQUIRED_HITS", "3"),
        pose_min_event_gap_sec=_float("VAD_POSE_MIN_EVENT_GAP_SEC", "5.0"),
        deep_gate_enabled=_bool("VAD_DEEP_GATE_ENABLED", "1"),
        deep_k=_int("VAD_DEEP_K", "5"),
        deep_threshold_key=os.getenv("VAD_DEEP_THRESHOLD_KEY", "p99_5").strip(),
        deep_threshold_value=_float("VAD_DEEP_THRESHOLD_VALUE", "0.16680973768234253"),
        deep_tubelet_frames=_int("VAD_DEEP_TUBELET_FRAMES", "16"),
        deep_stride=_int("VAD_DEEP_STRIDE", "5"),
        deep_bbox_pad_ratio=_float("VAD_DEEP_BBOX_PAD_RATIO", "0.30"),
        deep_crop_size=_int("VAD_DEEP_CROP_SIZE", "224"),
        deep_smoothing_sigma=_float("VAD_DEEP_SMOOTHING_SIGMA", "2.0"),
        deep_persistence_window=_int("VAD_DEEP_PERSISTENCE_WINDOW", "5"),
        deep_persistence_required_hits=_int("VAD_DEEP_PERSISTENCE_REQUIRED_HITS", "3"),
        deep_min_event_gap_sec=_float("VAD_DEEP_MIN_EVENT_GAP_SEC", "5.0"),
        deep_device=os.getenv("VAD_DEEP_DEVICE", os.getenv("VAD_DETECTOR_DEVICE", "cuda")).strip(),
        deep_fp16=_bool("VAD_DEEP_FP16", "1"),
        deep_videomae_model=os.getenv("VAD_DEEP_VIDEOMAE_MODEL", "MCG-NJU/videomae-base").strip(),
        deep_use_fast_processor=_bool("VAD_DEEP_USE_FAST_PROCESSOR", "0"),
        deep_reasoning_enabled=_bool("VAD_DEEP_REASONING_ENABLED", "1"),
        deep_reasoning_require_evidence=_bool("VAD_DEEP_REASONING_REQUIRE_EVIDENCE", "1"),
        deep_reasoning_min_ratio=_float("VAD_DEEP_REASONING_MIN_RATIO", "1.0"),
        deep_reasoning_prompt_version=os.getenv("VAD_DEEP_REASONING_PROMPT_VERSION", "deep_vlm_reasoning_v1").strip(),
        deep_reasoning_priority=os.getenv("VAD_DEEP_REASONING_PRIORITY", "normal").strip().lower(),
        deep_reasoning_max_attempts=_int("VAD_DEEP_REASONING_MAX_ATTEMPTS", "3"),
        reasoning_worker_enabled=_bool("VAD_REASONING_WORKER_ENABLED", "1"),
        reasoning_poll_interval_sec=_float("VAD_REASONING_POLL_INTERVAL_SEC", "3.0"),
        reasoning_batch_size=_int("VAD_REASONING_BATCH_SIZE", "1"),
        reasoning_provider=os.getenv("VAD_REASONING_PROVIDER", "ollama").strip().lower(),
        reasoning_use_llm_normalizer=_bool("VAD_REASONING_USE_LLM_NORMALIZER", "1"),
        reasoning_max_images=_int("VAD_REASONING_MAX_IMAGES", "6"),
        reasoning_image_roles=os.getenv("VAD_REASONING_IMAGE_ROLES", "annotated_frame,tubelet_montage,tubelet_frame").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").strip().rstrip("/"),
        ollama_vlm_model=os.getenv("VLM_MODEL", os.getenv("OLLAMA_VLM_MODEL", "llava:7b")).strip(),
        ollama_llm_model=os.getenv("LLM_MODEL", os.getenv("OLLAMA_LLM_MODEL", "qwen3:8b")).strip(),
        ollama_timeout_sec=_float("VAD_OLLAMA_TIMEOUT_SEC", "120.0"),
        homography_macro_gate_enabled=_bool("VAD_HOMOGRAPHY_MACRO_GATE_ENABLED", "1"),
        homography_macro_tubelet_frames=_int("VAD_HOMOGRAPHY_MACRO_TUBELET_FRAMES", "16"),
        homography_macro_stride=_int("VAD_HOMOGRAPHY_MACRO_STRIDE", "8"),
        homography_macro_threshold_key=os.getenv("VAD_HOMOGRAPHY_MACRO_THRESHOLD_KEY", "p99_5").strip(),
        homography_macro_threshold_value=_float("VAD_HOMOGRAPHY_MACRO_THRESHOLD_VALUE", "12.774831137922204"),
        homography_macro_smoothing_sigma=_float("VAD_HOMOGRAPHY_MACRO_SMOOTHING_SIGMA", "2.0"),
        homography_macro_persistence_window=_int("VAD_HOMOGRAPHY_MACRO_PERSISTENCE_WINDOW", "5"),
        homography_macro_persistence_required_hits=_int("VAD_HOMOGRAPHY_MACRO_PERSISTENCE_REQUIRED_HITS", "3"),
        homography_macro_min_event_gap_sec=_float("VAD_HOMOGRAPHY_MACRO_MIN_EVENT_GAP_SEC", "5.0"),
        homography_matrix_path=homography_matrix_path,
        homography_groundpoint_mode=os.getenv("VAD_HOMOGRAPHY_GROUNDPOINT_MODE", "pose_ankle").strip(),
        homography_pose_model=homography_pose_model,
        homography_pose_imgsz=_int("VAD_HOMOGRAPHY_POSE_IMGSZ", "256"),
        homography_pose_conf=_float("VAD_HOMOGRAPHY_POSE_CONF", "0.25"),
        homography_pose_crop_pad_ratio=_float("VAD_HOMOGRAPHY_POSE_CROP_PAD_RATIO", "0.25"),
        homography_pose_min_crop_size=_int("VAD_HOMOGRAPHY_POSE_MIN_CROP_SIZE", "192"),
        homography_ankle_conf_threshold=_float("VAD_HOMOGRAPHY_ANKLE_CONF_THRESHOLD", "0.35"),
        homography_fallback_mode=os.getenv("VAD_HOMOGRAPHY_FALLBACK_MODE", "freeze_last_valid").strip(),
        homography_max_freeze_samples=_int("VAD_HOMOGRAPHY_MAX_FREEZE_SAMPLES", "12"),
        homography_stationary_speed_threshold=_float("VAD_HOMOGRAPHY_STATIONARY_SPEED_THRESHOLD", "0.05"),
        homography_trajectory_smoothing=os.getenv("VAD_HOMOGRAPHY_TRAJECTORY_SMOOTHING", "median_savgol").strip(),
        homography_trajectory_smoothing_window=_int("VAD_HOMOGRAPHY_TRAJECTORY_SMOOTHING_WINDOW", "5"),
        homography_trajectory_smoothing_polyorder=_int("VAD_HOMOGRAPHY_TRAJECTORY_SMOOTHING_POLYORDER", "2"),
        homography_reject_nonphysical_steps=_bool("VAD_HOMOGRAPHY_REJECT_NONPHYSICAL_STEPS", "1"),
        homography_max_plausible_speed=_float("VAD_HOMOGRAPHY_MAX_PLAUSIBLE_SPEED", "3.0"),
        homography_max_plausible_accel=_float("VAD_HOMOGRAPHY_MAX_PLAUSIBLE_ACCEL", "6.0"),
        homography_min_valid_groundpoint_ratio=_float("VAD_HOMOGRAPHY_MIN_VALID_GROUNDPOINT_RATIO", "0.0"),
        evidence_enabled=_bool("VAD_EVIDENCE_ENABLED", "1"),
        minio_endpoint=os.getenv("VAD_MINIO_ENDPOINT", "minio:9000").strip(),
        minio_access_key=os.getenv("VAD_MINIO_ACCESS_KEY", "minioadmin").strip(),
        minio_secret_key=os.getenv("VAD_MINIO_SECRET_KEY", "minioadmin123").strip(),
        minio_secure=_bool("VAD_MINIO_SECURE", "0"),
        minio_public_endpoint=os.getenv("MINIO_PUBLIC_ENDPOINT", "localhost:9000").strip(),
        minio_public_secure=_bool("MINIO_PUBLIC_SECURE", "0"),
        minio_bucket=os.getenv("VAD_MINIO_BUCKET", "vad-evidence").strip(),
        evidence_prefix=os.getenv("VAD_EVIDENCE_PREFIX", "vad").strip().strip("/"),
        save_evidence_on_gate_event=_bool("VAD_SAVE_EVIDENCE_ON_GATE_EVENT", "1"),
        save_evidence_on_persistent_hit=_bool("VAD_SAVE_EVIDENCE_ON_PERSISTENT_HIT", "0"),
    )

    if cfg.target_sample_fps <= 0:
        raise ValueError("VAD_TARGET_SAMPLE_FPS must be > 0")
    if cfg.rolling_buffer_sec <= 0:
        raise ValueError("VAD_ROLLING_BUFFER_SEC must be > 0")
    if cfg.backend_direct_enabled and not cfg.rtsp_url:
        raise ValueError(
            f"{cfg.rtsp_url_env_var} is empty or missing. "
            f"Set {cfg.rtsp_url_env_var}=rtsp://USER:PASSWORD@HOST:PORT/path in backend/.env"
        )
    if cfg.detector_conf <= 0 or cfg.detector_conf >= 1:
        raise ValueError("VAD_DETECTOR_CONF must be between 0 and 1")
    if cfg.pose_tubelet_frames <= 1:
        raise ValueError("VAD_POSE_TUBELET_FRAMES must be > 1")
    if cfg.pose_stride <= 0:
        raise ValueError("VAD_POSE_STRIDE must be > 0")
    if cfg.pose_persistence_window <= 0 or cfg.pose_persistence_required_hits <= 0:
        raise ValueError("Pose persistence settings must be > 0")
    if cfg.deep_tubelet_frames <= 1 or cfg.deep_stride <= 0:
        raise ValueError("Deep tubelet settings must be valid")
    if cfg.deep_reasoning_min_ratio <= 0:
        raise ValueError("VAD_DEEP_REASONING_MIN_RATIO must be > 0")
    if cfg.deep_reasoning_priority not in {"low", "normal", "high", "urgent"}:
        raise ValueError("VAD_DEEP_REASONING_PRIORITY must be one of: low, normal, high, urgent")
    if cfg.deep_reasoning_max_attempts <= 0:
        raise ValueError("VAD_DEEP_REASONING_MAX_ATTEMPTS must be > 0")
    if cfg.reasoning_poll_interval_sec <= 0:
        raise ValueError("VAD_REASONING_POLL_INTERVAL_SEC must be > 0")
    if cfg.reasoning_batch_size <= 0:
        raise ValueError("VAD_REASONING_BATCH_SIZE must be > 0")
    if cfg.reasoning_provider not in {"ollama"}:
        raise ValueError("VAD_REASONING_PROVIDER currently supports only: ollama")
    if cfg.reasoning_max_images <= 0:
        raise ValueError("VAD_REASONING_MAX_IMAGES must be > 0")
    if not cfg.ollama_base_url:
        raise ValueError("OLLAMA_BASE_URL must not be empty when reasoning worker is enabled")
    if not cfg.ollama_vlm_model:
        raise ValueError("VLM_MODEL/OLLAMA_VLM_MODEL must not be empty when reasoning worker is enabled")
    if cfg.homography_macro_tubelet_frames <= 1 or cfg.homography_macro_stride <= 0:
        raise ValueError("Homography/macro tubelet settings must be valid")

    cfg.debug_save_dir.mkdir(parents=True, exist_ok=True)
    return cfg
