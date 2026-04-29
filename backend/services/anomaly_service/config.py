import os

# Database
DB_DSN = os.getenv("DB_DSN", "postgresql://lina:123@127.0.0.1:5432/lina")

# ---------------------------------------------------------------------------
# VideoMAE teacher model
# Runs on the backend to produce teacher embeddings for anomaly scoring.
# ---------------------------------------------------------------------------
TEACHER_MODEL      = os.getenv("TEACHER_MODEL",      "MCG-NJU/videomae-base")
TEACHER_DEVICE     = os.getenv("TEACHER_DEVICE",      "cuda")
TEACHER_USE_AMP    = os.getenv("TEACHER_USE_AMP",     "1").strip() in ("1", "true", "yes")
TEACHER_NUM_FRAMES = int(os.getenv("TEACHER_NUM_FRAMES", "16"))
 
# Layers to extract from VideoMAE (must match training: 4,8,12 -> 2304-d)
TEACHER_EXTRACT_LAYERS = [
    int(x.strip())
    for x in os.getenv("TEACHER_EXTRACT_LAYERS", "4,8,12").split(",")
]
 
# ---------------------------------------------------------------------------
# MinIO — for fetching frames uploaded by the edge
# ---------------------------------------------------------------------------
MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "http://minio:9000").strip()
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
S3_BUCKET        = os.getenv("S3_BUCKET",        "evidence")
 
_secure_env = os.getenv("MINIO_SECURE", "").lower().strip()
if _secure_env in ("true", "1", "yes"):
    MINIO_SECURE = True
elif _secure_env in ("false", "0", "no"):
    MINIO_SECURE = False
else:
    MINIO_SECURE = MINIO_ENDPOINT.startswith("https://")
 
# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
OLLAMA_HOST = (
    os.getenv("OLLAMA_HOST")
    or os.getenv("OLLAMA_BASE_URL")
    or "http://localhost:11435"
).rstrip("/")
 
VLM_MODEL            = os.getenv("VLM_MODEL") or os.getenv("OLLAMA_VLM_MODEL") or "moondream:latest"
LLM_MODEL            = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL")     or "llama3.2:1b"
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", LLM_MODEL)
 
# ---------------------------------------------------------------------------
# Service behavior
# ---------------------------------------------------------------------------
ALLOW_SERVICE_BOOT_WITHOUT_MODEL = os.getenv(
    "ALLOW_SERVICE_BOOT_WITHOUT_MODEL",
    os.getenv("ALLOW_START_WITHOUT_MODEL", "1"),
).strip() in ("1", "true", "yes", "y")

# Backward-compatible alias
ALLOW_START_WITHOUT_MODEL = ALLOW_SERVICE_BOOT_WITHOUT_MODEL

MIN_REQUIRED_FRAME_RATIO = float(
    os.getenv("MIN_REQUIRED_FRAME_RATIO", "0.75").strip() or "0.75"
)
 
RETRAIN_FALSE_POSITIVE_THRESHOLD = int(
    os.getenv("RETRAIN_FALSE_POSITIVE_THRESHOLD", "20").strip() or "20"
)