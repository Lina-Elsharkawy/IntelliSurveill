from __future__ import annotations

import os
from pathlib import Path


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_DSN = os.getenv("DB_DSN", "postgresql://lina:123@postgres-db:5432/lina")
DATABASE_URL = os.getenv("DATABASE_URL", DB_DSN)

# ---------------------------------------------------------------------------
# Runtime VideoMAE encoder / tubelet settings
# ---------------------------------------------------------------------------
VIDEO_ENCODER_MODEL = os.getenv("VIDEO_ENCODER_MODEL", "MCG-NJU/videomae-base")
VIDEO_ENCODER_DEVICE = os.getenv("VIDEO_ENCODER_DEVICE", "cuda")
VIDEO_ENCODER_USE_FP16 = _bool("VIDEO_ENCODER_USE_FP16", "1")

TUBELET_FRAMES = int(os.getenv("TUBELET_FRAMES", "16"))
SAMPLE_FPS = int(os.getenv("SAMPLE_FPS", "8"))
STRIDE = int(os.getenv("STRIDE", "16"))
PERSON_SIZE = int(os.getenv("PERSON_SIZE", "224"))
CONTEXT_SIZE = int(os.getenv("CONTEXT_SIZE", "224"))
PERSON_PADDING = float(os.getenv("PERSON_PADDING", "0.20"))
CONTEXT_SCALE = float(os.getenv("CONTEXT_SCALE", "2.5"))

# ---------------------------------------------------------------------------
# Distribution artifacts
# ---------------------------------------------------------------------------
DISTRIBUTION_ARTIFACTS_DIR = Path(
    os.getenv("DISTRIBUTION_ARTIFACTS_DIR", "/models/distribution_artifacts")
)
PERSON_SCALER_PATH = Path(os.getenv("PERSON_SCALER_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "person_scaler.pkl")))
PERSON_PCA_PATH = Path(os.getenv("PERSON_PCA_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "person_pca.pkl")))
PERSON_COV_PATH = Path(os.getenv("PERSON_COV_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "person_ledoitwolf.pkl")))
CONTEXT_SCALER_PATH = Path(os.getenv("CONTEXT_SCALER_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "context_scaler.pkl")))
CONTEXT_PCA_PATH = Path(os.getenv("CONTEXT_PCA_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "context_pca.pkl")))
CONTEXT_COV_PATH = Path(os.getenv("CONTEXT_COV_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "context_ledoitwolf.pkl")))
THRESHOLDS_JSON_PATH = Path(os.getenv("THRESHOLDS_JSON_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "thresholds.json")))
FUSION_CONFIG_JSON_PATH = Path(os.getenv("FUSION_CONFIG_JSON_PATH", str(DISTRIBUTION_ARTIFACTS_DIR / "fusion_config.json")))

# ---------------------------------------------------------------------------
# Gate thresholds
# ---------------------------------------------------------------------------
DISTRIBUTION_THRESHOLD_NAME = os.getenv("DISTRIBUTION_THRESHOLD_NAME", "p97")
HIGH_SPEED_THRESHOLD = float(os.getenv("HIGH_SPEED_THRESHOLD", "0.24"))
ABRUPT_ANGLE_THRESHOLD = float(os.getenv("ABRUPT_ANGLE_THRESHOLD", "120"))
MIN_TURN_SPEED = float(os.getenv("MIN_TURN_SPEED", "0.08"))
MAX_TRACK_GAP = int(os.getenv("MAX_TRACK_GAP", "6"))
CANDIDATE_COOLDOWN_SEC = float(os.getenv("CANDIDATE_COOLDOWN_SEC", "5"))

# ---------------------------------------------------------------------------
# MinIO evidence storage
# ---------------------------------------------------------------------------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").strip()
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")
_secure_env = os.getenv("MINIO_SECURE", "").lower().strip()
if _secure_env in {"true", "1", "yes"}:
    MINIO_SECURE = True
elif _secure_env in {"false", "0", "no"}:
    MINIO_SECURE = False
else:
    MINIO_SECURE = MINIO_ENDPOINT.startswith("https://")

# ---------------------------------------------------------------------------
# Ollama reasoning
# ---------------------------------------------------------------------------
OLLAMA_HOST = (os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://ollama:11434").rstrip("/")
VLM_MODEL = os.getenv("VLM_MODEL", "openbmb/minicpm-v4.5:8b")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b")
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", LLM_MODEL)

# ---------------------------------------------------------------------------
# Service behavior
# ---------------------------------------------------------------------------
ALLOW_SERVICE_BOOT_WITHOUT_MODEL = _bool("ALLOW_SERVICE_BOOT_WITHOUT_MODEL", os.getenv("ALLOW_START_WITHOUT_MODEL", "1"))
ALLOW_START_WITHOUT_MODEL = ALLOW_SERVICE_BOOT_WITHOUT_MODEL
MIN_REQUIRED_FRAME_RATIO = float(os.getenv("MIN_REQUIRED_FRAME_RATIO", "0.75"))
RETRAIN_FALSE_POSITIVE_THRESHOLD = int(os.getenv("RETRAIN_FALSE_POSITIVE_THRESHOLD", "20"))
