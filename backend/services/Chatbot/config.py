import os


DB_DSN = os.getenv("DB_DSN", "postgresql://lina:123@postgres-db:5432/lina")
OLLAMA_HOST = os.getenv("OLLAMA_BASE_URL", "http://ollama-chatbot:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
CHATBOT_TIMEZONE = os.getenv("CHATBOT_TIMEZONE", "Africa/Cairo")

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
