"""
model.py — Ollama LLM wrapper + Pydantic models

Architecture: Pure LLM Understanding Layer
  - understand_query() extracts intent + entities via constrained JSON schema
  - generate() handles SQL generation and response formatting
  - No regex, no normalization — the LLM does all understanding

Intent names here match tools.py TOOL_MAP keys exactly.
"""
import json
import ollama
from config import OLLAMA_HOST, LLM_MODEL
from pydantic import BaseModel
from typing import List, Any, Dict, Optional, TypedDict

_KEEP_ALIVE = -1  # never evict from GPU

# ─────────────────────────────────────────────────────────────────────────────
# Constrained JSON schema for intent + entity extraction.
# The LLM physically cannot output wrong field names or wrong types.
# Intent names are IDENTICAL to TOOL_MAP keys in tools.py.
# ─────────────────────────────────────────────────────────────────────────────
_UNDERSTANDING_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                # ── Face / Person tracking ────────────────────────────────
                "person_last_seen",
                "person_first_seen",
                "person_timeline",
                "people_seen_on_date",
                "known_people",

                # ── Detection counts ──────────────────────────────────────
                "count_unknown_detections",
                "count_known_detections",
                "count_all_detections",

                # ── Unknown face pipeline ─────────────────────────────────
                "unknown_face_events",
                "unknown_face_details",
                "similar_unknown_faces",
                "possible_identity_match",
                "investigate_unknown_face",

                # ── VAD anomaly pipeline ──────────────────────────────────
                "vad_cases",
                "vad_case_details",
                "vad_gate_events",
                "vad_reasoning_jobs",
                "vad_reasoning_results",
                "vad_case_reviews",
                "vad_case_gate_events",
                "vad_case_evidence",
                "vad_gate_scores",
                "vad_streams",
                "vad_stream_sessions",

                # ── System / admin ────────────────────────────────────────
                "cameras",
                "edge_devices",
                "anomaly_rules",
                "reasoning_rules",
                "rule_conflicts",
                "schedules",
                "audit_logs",

                # ── Meta ──────────────────────────────────────────────────
                "table_counts",
                "daily_summary",
                "camera_activity",

                # ── Fallback ──────────────────────────────────────────────
                "sql_fallback",
                "small_talk",
            ],
        },
        "entities": {
            "type": "object",
            "properties": {
                "name":        {"type": ["string", "null"]},
                "target_date": {"type": ["string", "null"]},
                "event_id":    {"type": ["integer", "null"]},
                "case_id":     {"type": ["integer", "null"]},
                "camera_id":   {"type": ["integer", "null"]},
                "status":      {"type": ["string", "null"]},
                "severity":    {"type": ["string", "null"]},
                "alert_decision": {"type": ["string", "null"]},
                "decision":    {"type": ["string", "null"]},
                "limit":       {"type": ["integer", "null"]},
                "days_back":   {"type": ["integer", "null"]},
                "hour":        {"type": ["integer", "null"]},
                "rule_type":   {"type": ["string", "null"]},
                "gate_name":   {"type": ["string", "null"]},
                "is_active":   {"type": ["boolean", "null"]},
            },
            "additionalProperties": False,
        },
    },
    "required": ["intent", "entities"],
    "additionalProperties": False,
}


class OllamaLLM:
    def __init__(self, model: str = LLM_MODEL, host: str = OLLAMA_HOST, timeout: float = 180.0):
        self.model = model
        self.host = host
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> ollama.Client:
        return ollama.Client(host=self.host, timeout=timeout or self.timeout)

    def understand_query(self, system_prompt: str, user_question: str) -> dict:
        """
        Core Understanding Layer.
        Uses constrained JSON schema — model cannot deviate from the schema.
        Returns {"intent": "...", "entities": {...}}
        """
        try:
            response = self._client().chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_question},
                ],
                format=_UNDERSTANDING_SCHEMA,
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": 0.0, "num_predict": 200, "num_ctx": 8192},
            )
            raw = response.get("message", {}).get("content", "").strip()
            parsed = json.loads(raw)
            # Scrub null/empty entities
            parsed["entities"] = {
                k: v for k, v in parsed.get("entities", {}).items()
                if v is not None and v != "" and v != "null"
            }
            return parsed
        except Exception as e:
            logger_msg = f"understand_query failed: {e}"
            return {"intent": "sql_fallback", "entities": {}}

    def generate(self, prompt: str, temperature: float = 0.0, num_predict: int = 400) -> str:
        """General-purpose completion — SQL generation and result formatting."""
        try:
            response = self._client(timeout=300.0).chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                keep_alive=_KEEP_ALIVE,
                options={"temperature": temperature, "num_predict": num_predict, "num_ctx": 8192},
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}")

    def test_connection(self) -> bool:
        try:
            self._client().list()
            return True
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# State + API models
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    question:      str
    history:       list
    intent:        str          # raw intent string from router
    entities:      dict         # extracted entities
    route:         str          # "tool" | "vector" | "sql" | "small_talk"
    tool_result:   dict
    schema:        str
    sql:           str
    sql_valid:     bool
    sql_safe:      bool
    safety_reason: str
    retry_count:   int
    error_message: str
    results:       list
    final_answer:  str
    original_question: str

# Alias so langgraph_workflow.py can import either name
SQLState = AgentState


class ChatMessage(BaseModel):
    role:    str
    content: str
    sql:     Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    history:  Optional[List[ChatMessage]] = []


class QueryResponse(BaseModel):
    success:  bool
    question: str
    sql:      str
    results:  List[Dict[str, Any]]
    answer:   str
    error:    str | None = None