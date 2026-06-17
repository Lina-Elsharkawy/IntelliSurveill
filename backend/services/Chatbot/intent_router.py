"""
intent_router.py — Pure LLM Understanding Layer

One LLM call. Constrained JSON schema. No regex. No keyword matching.

Intent names are IDENTICAL to the keys in tools.py TOOL_MAP so the
router never has to translate between the two.

Flow:
  User question
       ↓
  route()  ← single LLM call with constrained JSON schema
       ↓
  { intent, entities, route }
       ↓
  LangGraph router
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from model import OllamaLLM
from config import CHATBOT_TIMEZONE

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Which intents go to a tool vs SQL fallback
# Must match TOOL_MAP keys in tools.py exactly.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_INTENTS = {
    # Face / Person tracking
    "person_last_seen",
    "person_first_seen",
    "person_timeline",
    "people_seen_on_date",
    "known_people",
    # Detection counts
    "count_unknown_detections",
    "count_known_detections",
    "count_all_detections",
    # Unknown face pipeline
    "unknown_face_events",
    "unknown_face_details",
    "similar_unknown_faces",
    "possible_identity_match",
    "investigate_unknown_face",
    # VAD anomaly pipeline
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
    # System / admin
    "cameras",
    "edge_devices",
    "anomaly_rules",
    "reasoning_rules",
    "rule_conflicts",
    "schedules",
    "audit_logs",
    # Meta
    "table_counts",
    "daily_summary",
    "camera_activity",
}

# Vector tools need pgvector — separate execution node
_VECTOR_INTENTS = {
    "similar_unknown_faces",
    "possible_identity_match",
    "investigate_unknown_face",
}

# ─────────────────────────────────────────────────────────────────────────────
# System prompt — tight and focused for 7B models
# ─────────────────────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are the understanding layer for a surveillance security chatbot.
Today is {today}. Yesterday was {yesterday}.

Your ONLY job: read the user question and output the correct intent and entities as JSON.
Do NOT answer the question. Do NOT explain. Output JSON only.

DATABASE TABLES:
- entry_logs + detected_people + employees + visitors → person detections / tracking
- unknown_face_events → unidentified faces (status: pending/assigned/discarded)
- face_embeddings → face vectors for similarity search
- cameras, edge_devices → hardware registry
- anomaly_rules → trigger/suppress/normal/anomalous rules
- vad_anomaly_cases → anomaly cases (status: open/confirmed/dismissed/needs_review/archived)
- vad_gate_events → low-level anomaly gate triggers (severity: low/medium/high/critical)
- vad_reasoning_jobs → LLM reasoning queue (status: queued/running/succeeded/failed)
- vad_reasoning_results → LLM decisions (alert_decision: YES/NO/UNCERTAIN)
- vad_case_reviews → human review decisions (decision: confirmed/dismissed/uncertain)
- vad_case_gate_events, vad_case_evidence, vad_gate_scores → case evidence, linked gates, score/threshold/ratio data
- vad_streams, vad_stream_sessions → live camera streams
- vad_reasoning_rules → rules guiding VAD reasoning (rule_type: trigger/suppress)
- rule_conflicts → conflicts between rules
- schedules → access schedules
- audit_logs → system logs and user/admin activity logs

INTENT → RULE MAPPING:
"where was X" / "last seen X" / "find X" → person_last_seen (extract name)
"first seen X" / "when did X first appear" → person_first_seen (extract name)
"timeline" / "movements" / "path of X" → person_timeline (extract name)
"who was seen today/yesterday/on date" → people_seen_on_date (extract target_date)
"list employees" / "list visitors" / "known people" → known_people
"how many unknown detections" → count_unknown_detections
"how many known detections" → count_known_detections
"how many detections total" / "total detections" → count_all_detections
"unknown face events" / "show unknowns" / "strangers" → unknown_face_events
"details for event N" / "event #N" → unknown_face_details (extract event_id)
"similar to event N" → similar_unknown_faces (extract event_id)
"who could event N be" / "match event N" → possible_identity_match (extract event_id)
"investigate event N" / "full investigation" → investigate_unknown_face (extract event_id)
"anomaly case" / "vad case" / "open cases" / "security incidents" → vad_cases
"case #N" / "case details N" → vad_case_details (extract case_id)
"gate events" / "gate triggers" → vad_gate_events
"reasoning job" / "llm job" / "reasoning queue" → vad_reasoning_jobs
"reasoning result" / "llm decision" / "alert decision" → vad_reasoning_results (extract alert_decision as YES/NO/UNCERTAIN if mentioned; extract severity if mentioned)
"case review" / "human review" → vad_case_reviews (extract decision if confirmed/dismissed/uncertain/needs_more_evidence/calibration_feedback is mentioned)
"case gate events" / "gates for case N" → vad_case_gate_events (extract case_id)
"evidence for case N" / "media for case N" / "reasoning evidence" → vad_case_evidence (extract case_id)
"gate scores" / "score ratio" / "threshold scores" → vad_gate_scores (extract case_id if mentioned; extract gate_name if pose/deep/homography mentioned)
"camera stream" / "active streams" / "stream status" → vad_streams
"stream session" / "session status" → vad_stream_sessions
"cameras" / "list cameras" → cameras
"edge device" / "devices" / "hardware" → edge_devices
"anomaly rule" / "trigger rule" / "suppress rule" → anomaly_rules
"reasoning rule" / "vad rule" → reasoning_rules
"rule conflict" / "conflicting rules" → rule_conflicts
"schedule" / "access schedule" → schedules
"activity log" / "user actions" / "audit log" / "system audit" → audit_logs
"how many tables" / "record count" / "table sizes" → table_counts
"today summary" / "daily report" / "security summary" → daily_summary (extract target_date if today/yesterday/explicit date is mentioned)
"camera activity" / "detections per camera" → camera_activity
"hello" / "hi" / "help" / "what can you do" → small_talk
anything else → sql_fallback

DATE RULES:
- "today" → {today}
- "yesterday" → {yesterday}
- Always output dates as YYYY-MM-DD strings
- If no date mentioned for people_seen_on_date → use {today}
- If no date mentioned for detection counts → use {today}
- If no date mentioned for person tracking → leave target_date null

EXAMPLES:
Q: "Where was Maged yesterday?"
A: {{"intent":"person_last_seen","entities":{{"name":"Maged","target_date":"{yesterday}"}}}}

Q: "Show me open anomaly cases"
A: {{"intent":"vad_cases","entities":{{"status":"open"}}}}

Q: "Any failed reasoning jobs?"
A: {{"intent":"vad_reasoning_jobs","entities":{{"status":"failed"}}}}

Q: "Investigate unknown face event 42"
A: {{"intent":"investigate_unknown_face","entities":{{"event_id":42}}}}

Q: "How many unknown faces today?"
A: {{"intent":"count_unknown_detections","entities":{{"target_date":"{today}"}}}}

Q: "Show me critical gate events"
A: {{"intent":"vad_gate_events","entities":{{"severity":"critical"}}}}

Q: "Show reasoning results where the alert decision was YES"
A: {{"intent":"vad_reasoning_results","entities":{{"alert_decision":"YES"}}}}

Q: "Show evidence for case 12"
A: {{"intent":"vad_case_evidence","entities":{{"case_id":12}}}}

Q: "Show gate scores for case 12"
A: {{"intent":"vad_gate_scores","entities":{{"case_id":12}}}}

Q: "Who was seen today?"
A: {{"intent":"people_seen_on_date","entities":{{"target_date":"{today}"}}}}

Q: "Hello"
A: {{"intent":"small_talk","entities":{{}}}}

Q: "List all cameras"
A: {{"intent":"cameras","entities":{{}}}}
"""


def route(question: str, history: list | None = None) -> dict[str, Any]:
    """
    Single entry point called by LangGraph.
    Returns { intent, entities, route }
    where route ∈ { "tool", "vector", "sql", "small_talk" }
    """
    today_date = datetime.now(ZoneInfo(CHATBOT_TIMEZONE)).date()
    today = today_date.isoformat()
    yesterday = (today_date - timedelta(days=1)).isoformat()

    system = _SYSTEM_PROMPT.format(today=today, yesterday=yesterday)

    # Include last 2 conversation turns for context
    history_str = ""
    if history:
        last_turns = history[-4:]
        history_str = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in last_turns
        )

    user_message = question.strip()
    if history_str:
        user_message = f"RECENT CONVERSATION:\n{history_str}\n\nCURRENT QUESTION: {user_message}"

    llm = OllamaLLM()
    result = llm.understand_query(system, user_message)

    intent = result.get("intent", "sql_fallback")
    entities = result.get("entities", {})

    # Determine route
    if intent == "small_talk":
        route_name = "small_talk"
    elif intent in _VECTOR_INTENTS:
        route_name = "vector"
    elif intent in _TOOL_INTENTS:
        route_name = "tool"
    elif intent == "sql_fallback":
        route_name = "sql"
    else:
        # Unknown intent → SQL fallback
        route_name = "sql"

    logger.info("Routed %r → intent=%s route=%s entities=%s", question, intent, route_name, entities)

    return {
        "intent":   intent,
        "entities": entities,
        "route":    route_name,
    }