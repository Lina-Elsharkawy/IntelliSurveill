"""
Ollama LLM wrapper + Pydantic models
"""
import ollama
from config import OLLAMA_HOST, LLM_MODEL
from pydantic import BaseModel
from typing import List, Any, Dict, Optional, TypedDict

# ── Context window ────────────────────────────────────────────────────────────
# Do NOT set num_ctx here.  Setting it per-request forces Ollama to reallocate
# the KV cache every single call, which is slow and can exhaust VRAM.
# Set it once at the system level (docker-compose env or Modelfile).
#
# ── Keep-alive ────────────────────────────────────────────────────────────────
# Ollama evicts a model from GPU after 5 minutes of idle by default.
# When evicted, the next request waits ~8–15 s for reload before inference
# can even begin.  That cold-start cost eats into the classify() timeout and
# causes spurious Layer 2 failures.
#
# keep_alive=-1 tells Ollama to keep the model loaded indefinitely.
# Combined with the startup warmup in app.py, the model is always hot and
# classify() reliably finishes in 3–8 s.
_KEEP_ALIVE = -1   # seconds; -1 = never evict


class OllamaLLM:
    def __init__(self, model: str = LLM_MODEL, host: str = OLLAMA_HOST, timeout: float = 300.0):
        self.model = model
        self.host = host
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> ollama.Client:
        return ollama.Client(host=self.host, timeout=timeout or self.timeout)

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        """
        General-purpose completion for SQL generation and result formatting.
        Timeout: the caller's default (90 s).
        """
        try:
            response = self._client().chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={
                    "temperature": temperature,
                    "num_predict": 350,
                },
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")

    def classify(self, system_prompt: str, user_question: str, temperature: float = 0.0, response_format: str | dict | None = "json") -> str:
        """
        Intent classification using a system + user turn.

        Timeout: 60 s.
          - Warm model (normal case): finishes in 3–8 s.
          - Cold model (first call after restart): model loads ~8–15 s,
            leaving 45–52 s for inference — comfortably within budget.
          - If Ollama is genuinely stuck > 60 s, error is surfaced immediately
            so Layer 3 keyword routing takes over without making the user wait.

        Falls back to a single user-turn ONLY on model role-format errors,
        never on timeouts or network failures (those are re-raised immediately).
        """
        try:
            response = self._client(timeout=300.0).chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_question},
                ],
                stream=False,
                keep_alive=_KEEP_ALIVE,
                format=response_format,
                options={
                    "temperature": temperature,
                    "num_predict": 256,
                },
            )
            return response.get("message", {}).get("content", "").strip()

        except Exception as exc:
            err = str(exc).lower()

            # Hard failures: surface immediately, let Layer 3 take over.
            if any(kw in err for kw in ("timed out", "timeout", "connect", "refused", "network")):
                raise RuntimeError(f"Ollama classification failed: {exc}") from exc

            # Only retry for role-format rejection (rare with modern models).
            combined = f"{system_prompt}\n\nQuestion: {user_question}"
            try:
                response = self._client(timeout=300.0).chat(
                    model=self.model,
                    messages=[{"role": "user", "content": combined}],
                    stream=False,
                    keep_alive=_KEEP_ALIVE,
                    format=response_format,
                    options={"temperature": temperature, "num_predict": 256},
                )
                return response.get("message", {}).get("content", "").strip()
            except Exception as exc2:
                raise RuntimeError(f"Ollama classification fallback failed: {exc2}") from exc2

    def test_connection(self) -> bool:
        try:
            self._client().list()
            return True
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            return False


class SQLState(TypedDict, total=False):
    question: str
    history: list
    schema: str
    sql: str
    sql_valid: bool
    error_message: str
    results: list
    final_answer: str
    retry_count: int
    intent: dict
    tool_result: dict


class ChatMessage(BaseModel):
    role: str
    content: str
    sql: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    history: Optional[List[ChatMessage]] = []


class QueryResponse(BaseModel):
    success: bool
    question: str
    sql: str
    results: List[Dict[str, Any]]
    answer: str
    error: str | None = None