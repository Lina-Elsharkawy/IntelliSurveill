"""
Ollama LLM wrapper + Pydantic models

KEY UPGRADE — constrained JSON decoding:
  classify() now passes a strict JSON schema via Ollama's `format` param.
  The 7B model physically cannot produce wrong field names, wrong types,
  or malformed JSON — eliminated entire class of JSON-parse failures.

  Requires Ollama >= 0.3. Falls back gracefully on older versions.
"""
import ollama
from config import OLLAMA_HOST, LLM_MODEL
from pydantic import BaseModel
from typing import List, Any, Dict, Optional, TypedDict

_KEEP_ALIVE = -1  # never evict from GPU

# ─────────────────────────────────────────────────────────────────────────────
# Strict JSON schema — enforced at token level by Ollama constrained decoding.
# Model can ONLY output one of the listed intent names — no more typos.
# ─────────────────────────────────────────────────────────────────────────────
_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "person_last_seen", "person_first_seen", "person_timeline",
                "people_seen_on_date",
                "unknown_detection_count", "known_face_detection_count", "face_detection_count",
                "latest_unknown_face_events", "unknown_face_event_details", "repeated_unknown_faces",
                "similar_unknown_faces", "possible_identity_match", "investigate_unknown_face_event",
                "latest_anomalies", "anomalies_near_person", "anomalies_near_unknown_event",
                "all_known_people", "camera_activity_summary", "daily_security_summary",
                "table_record_counts",
                "anomaly_candidates", "anomaly_candidate_review", "ollama_jobs",
                "scene_window_embeddings", "anomaly_rules", "edge_devices",
                "normal_behavior_models", "rule_conflicts",
                "sql_fallback", "small_talk",
            ],
        },
        "name":            {"type": ["string", "null"]},
        "target_date":     {"type": ["string", "null"]},
        "event_id":        {"type": ["integer", "null"]},
        "limit":           {"type": ["integer", "null"]},
        "days_back":       {"type": ["integer", "null"]},
        "hour":            {"type": ["integer", "null"]},
        "only_unreviewed": {"type": ["boolean", "null"]},
        "person_type":     {"type": ["string", "null"]},
        "status":          {"type": ["string", "null"]},
    },
    "required": ["intent"],
    "additionalProperties": False,
}


class OllamaLLM:
    def __init__(self, model: str = LLM_MODEL, host: str = OLLAMA_HOST, timeout: float = 300.0):
        self.model = model
        self.host = host
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> ollama.Client:
        return ollama.Client(host=self.host, timeout=timeout or self.timeout)

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int = 350) -> str:
        """General-purpose completion — SQL generation and result formatting."""
        try:
            response = self._client(timeout=300.0).chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": temperature, "num_predict": num_predict, "num_ctx": 131072},
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")

    def generate_long(self, prompt: str, temperature: float = 0.0) -> str:
        """Long-form completion — investigation reports, multi-section answers.
        Uses a moderate num_predict budget. Falls back to a shorter generate()
        call if the first attempt times out, so the user always gets an answer.
        """
        try:
            response = self._client(timeout=300.0).chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": temperature, "num_predict": 500, "num_ctx": 131072},
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            err = str(e).lower()
            # On timeout, retry with a tighter budget instead of failing hard
            if any(kw in err for kw in ("timed out", "timeout")):
                try:
                    response = self._client(timeout=150.0).chat(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        stream=False,
                        keep_alive=_KEEP_ALIVE,
                        options={"temperature": temperature, "num_predict": 300, "num_ctx": 131072},
                    )
                    return response.get("message", {}).get("content", "").strip()
                except Exception as e2:
                    raise RuntimeError(f"Ollama long generation failed: {str(e2)}")
            raise RuntimeError(f"Ollama long generation failed: {str(e)}")

    def classify(self, system_prompt: str, user_question: str, temperature: float = 0.0) -> str:
        """
        Intent classification with constrained JSON schema output.

        Attempt 1: Ollama >= 0.3 — full schema constraint, model cannot deviate.
        Attempt 2: Fallback — JSON mode only (older Ollama), regex cleans output.
        Hard failures (network/timeout) are raised immediately so Layer 3 takes over.
        """
        try:
            response = self._client(timeout=180.0).chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_question},
                ],
                format=_INTENT_SCHEMA,
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": temperature, "num_predict": 200, "num_ctx": 131072},
            )
            return response.get("message", {}).get("content", "").strip()

        except Exception as exc:
            err = str(exc).lower()
            if any(kw in err for kw in ("timed out", "timeout", "connect", "refused", "network")):
                raise RuntimeError(f"Ollama unreachable: {exc}") from exc

            # format param rejected (Ollama < 0.3) — retry with basic JSON mode
            try:
                combined = f"{system_prompt}\n\nQuestion: {user_question}"
                response = self._client(timeout=180.0).chat(
                    model=self.model,
                    messages=[{"role": "user", "content": combined}],
                    format="json",
                    stream=False,
                    keep_alive=_KEEP_ALIVE,
                    options={"temperature": temperature, "num_predict": 256, "num_ctx": 131072},
                )
                return response.get("message", {}).get("content", "").strip()
            except Exception as exc2:
                raise RuntimeError(f"Ollama classification failed (both attempts): {exc2}") from exc2

    def test_connection(self) -> bool:
        try:
            self._client().list()
            return True
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic / TypedDict models
# ─────────────────────────────────────────────────────────────────────────────

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