import os

# Database
DB_DSN = os.getenv("DB_DSN", "postgresql://lina:123@127.0.0.1:5432/lina")

# Model selection:
# - "isoforest"  -> expects a joblib IsolationForest + meta json
# - "clusters"   -> expects a joblib artifact with centroids+radii (+ optional pca object)
MODEL_TYPE = os.getenv("MODEL_TYPE", "isoforest").strip().lower()

# Default paths (kept compatible with what you already had)
MODEL_PATH = os.getenv("MODEL_PATH", "./models/isoforest_v1.joblib")
MODEL_META_PATH = os.getenv("MODEL_META_PATH", "./models/isoforest_v1_meta.json")

# Allow API to start even if model files don't exist yet
ALLOW_START_WITHOUT_MODEL = os.getenv("ALLOW_START_WITHOUT_MODEL", "1").strip() in ("1", "true", "yes", "y")

# Ollama (support both styles)
OLLAMA_HOST = (os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")

# Model names (support both styles)
VLM_MODEL = os.getenv("VLM_MODEL") or os.getenv("OLLAMA_VLM_MODEL") or "moondream"
LLM_MODEL = os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3.2:1b"

# For legacy behavior in your current service enqueue
DEFAULT_OLLAMA_MODEL = os.getenv("DEFAULT_OLLAMA_MODEL", LLM_MODEL)

RETRAIN_FALSE_POSITIVE_THRESHOLD = int(os.getenv("RETRAIN_FALSE_POSITIVE_THRESHOLD", "20").strip() or "20")
