import os

DB_DSN = os.getenv("DB_DSN", "postgresql://lina:123@postgres-db:5432/lina")
OLLAMA_HOST = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:3b")