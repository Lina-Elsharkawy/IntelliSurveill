"""
LangGraph workflow for a tool-first Surveillance Investigation Chatbot.

Design:
  - LangGraph stays as the orchestrator.
  - Trusted investigation tools are the main path.
  - Vector/pgvector tools are first-class investigation tools.
  - Generic NL-to-SQL is kept only as a read-only fallback.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import date
from typing import Any

from langgraph.graph import StateGraph, END

from model import OllamaLLM, SQLState
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql, safety_gate, is_write_intent
from prompts import get_sql_generation_prompt, get_error_correction_prompt, get_result_formatting_prompt
from intent_router import route
from capabilities import required_params, tool_type
from tools import (
    get_all_known_people,
    get_person_last_seen,
    get_person_first_seen,
    get_person_timeline,
    get_unknown_faces_today,
    get_unknown_face_events,
    get_unknown_face_event_details,
    get_repeated_unknowns,
    get_anomalies_near_face,
    get_anomalies_near_unknown_event,
    get_people_seen_today,
    get_table_record_counts,
    get_latest_anomalies,
    get_camera_activity_summary,
    get_daily_security_summary,
    get_unknown_detection_count,
    get_known_face_detection_count,
    get_face_detection_count,
    find_similar_unknown_faces,
    find_possible_identity_match,
    investigate_unknown_face_event,
    get_anomaly_candidates,
    get_anomaly_candidate_review,
    get_ollama_jobs,
    get_scene_window_embeddings,
    get_anomaly_rules,
    get_edge_devices,
    get_normal_behavior_models,
    get_rule_conflicts,
)

_llm = None
_workflow = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = OllamaLLM()
    return _llm


TOOL_MAP = {
    # Registry
    "all_known_people": get_all_known_people,

    # New canonical tool names
    "person_last_seen": get_person_last_seen,
    "person_first_seen": get_person_first_seen,
    "person_timeline": get_person_timeline,
    "people_seen_on_date": get_people_seen_today,
    "latest_unknown_face_events": get_unknown_face_events,
    "unknown_detection_count": get_unknown_detection_count,
    "known_face_detection_count": get_known_face_detection_count,
    "face_detection_count": get_face_detection_count,
    "unknown_face_event_details": get_unknown_face_event_details,
    "repeated_unknown_faces": get_repeated_unknowns,
    "latest_anomalies": get_latest_anomalies,
    "anomalies_near_person": get_anomalies_near_face,
    "anomalies_near_unknown_event": get_anomalies_near_unknown_event,
    "camera_activity_summary": get_camera_activity_summary,
    "daily_security_summary": get_daily_security_summary,
    "table_record_counts": get_table_record_counts,
    "anomaly_candidates": get_anomaly_candidates,
    "anomaly_candidate_review": get_anomaly_candidate_review,
    "ollama_jobs": get_ollama_jobs,
    "scene_window_embeddings": get_scene_window_embeddings,
    "anomaly_rules": get_anomaly_rules,
    "edge_devices": get_edge_devices,
    "normal_behavior_models": get_normal_behavior_models,
    "rule_conflicts": get_rule_conflicts,

    # Vector tools
    "similar_unknown_faces": find_similar_unknown_faces,
    "possible_identity_match": find_possible_identity_match,
    "investigate_unknown_face_event": investigate_unknown_face_event,

    # Backward compatibility aliases
    "last_seen": get_person_last_seen,
    "first_seen": get_person_first_seen,
    "timeline": get_person_timeline,
    "unknown_faces": get_unknown_faces_today,
    "unknown_face_events": get_unknown_face_events,
    "repeated_unknowns": get_repeated_unknowns,
    "anomalies_near_face": get_anomalies_near_face,
    "people_seen_today": get_people_seen_today,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compact(value: Any, max_len: int = 220) -> str:
    text = str(value)
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def _coerce_tool_params(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Map canonical params to the actual function signature and drop extras."""
    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return params

    p = dict(params or {})

    # Existing functions still use old names.
    if tool_name in {"person_last_seen", "person_first_seen", "person_timeline", "anomalies_near_person"}:
        if "person_name" in p and "name" not in p:
            p["name"] = p.pop("person_name")
    if tool_name == "anomalies_near_person":
        if "name" in p and "person_name" not in p:
            p["person_name"] = p.pop("name")
    if tool_name in {"people_seen_on_date", "person_timeline", "person_last_seen", "person_first_seen"}:
        if "date" in p and "target_date" not in p:
            p["target_date"] = p.pop("date")
    if tool_name == "latest_unknown_face_events":
        # get_unknown_face_events does not accept target_date. days_back covers recent ranges.
        p.pop("target_date", None)
    if tool_name == "repeated_unknown_faces":
        p.pop("target_date", None)
        p.setdefault("days_back", 7)

    sig = inspect.signature(fn)
    allowed = set(sig.parameters.keys())
    return {k: v for k, v in p.items() if k in allowed and v is not None}


def _flatten_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data", [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _safe_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, indent=2)


def _strip_embeddings(data: Any) -> Any:
    """Recursively strip high-dimensional vectors and binary data from tool results before sending to LLM."""
    _SKIP_COLS = {
        "embedding", "face_embedding", "vector", "encoding",
        "scene_embedding", "image_data", "thumbnail",
        "student_embedding", "teacher_embedding", "student_embeddings", "teacher_embeddings"
    }

    if isinstance(data, dict):
        return {k: _strip_embeddings(v) for k, v in data.items() if k.lower() not in _SKIP_COLS}
    elif isinstance(data, list):
        return [_strip_embeddings(x) for x in data]
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────

def _needs_normalization(q: str) -> bool:
    """
    Return True only when the question is likely to have real typos worth correcting.
    Skip the LLM call for short questions, pure-ASCII well-formed questions, and
    questions that are already handled by Layer 1 (deterministic router).
    This prevents the normalize LLM call from blocking the Ollama thread and
    causing downstream classify() timeouts.
    """
    words = q.split()
    # Very short questions are handled well by regex alone
    if len(words) <= 4:
        return False
    # If every word looks like normal ASCII text with no obvious run-together errors, skip
    import re as _re
    suspicious = sum(1 for w in words if len(w) > 15 or _re.search(r"[^a-zA-Z0-9 '?.,!-]", w))
    return suspicious > 0


def normalize_question(state: SQLState) -> SQLState:
    q = (state.get("question") or "").strip()
    retry = state.get("retry_count", 0)
    
    # Only perform spelling/casing correction on the first try to avoid overhead on retries.
    # Skip entirely when the question looks clean — avoids blocking the Ollama thread,
    # which caused downstream classify() timeouts (Layer 2 timed out at 90s while
    # normalize was still holding the model for 2+ minutes).
    if retry == 0 and _needs_normalization(q):
        prompt = f"""You are a spelling correction assistant for a surveillance system.
Your ONLY job is to fix obvious typos and capitalize person names.
STRICT RULES:
- Do NOT rephrase, restructure, or change the meaning of the question.
- Do NOT change verb tenses (e.g. "inserted" stays "inserted", never change to "insert into").
- Do NOT add or remove words beyond fixing clear spelling errors.
- Keep the question in whatever tense and structure the user wrote it.
- If it is already correct, output it exactly as is.

USER QUESTION: {q}

CORRECTED QUESTION:"""
        try:
            corrected_q = get_llm().generate(prompt, temperature=0.0, num_predict=60).strip()
            # Clean up the response just in case the LLM includes the prefix
            for prefix in ["Corrected Query:", "CORRECTED QUESTION:", "Corrected question:"]:
                if corrected_q.lower().startswith(prefix.lower()):
                    corrected_q = corrected_q[len(prefix):].strip()
            corrected_q = corrected_q.strip('"').strip("'")
            # Safety: if the LLM output triggers write-intent but original didn't, discard correction
            if is_write_intent(corrected_q) and not is_write_intent(q):
                corrected_q = q
            
            # Fix 2: post-normalization guard for intent keywords
            # If the original had "first" and the correction doesn't, restore it.
            if "first" in q.lower() and "first" not in corrected_q.lower():
                # Re-insert "first" before the main verb or at a reasonable spot
                # Simple approach: if it was "first inserted" and became "inserted", fix it.
                # Even simpler: just use original if a critical keyword is lost.
                corrected_q = q 

            q = corrected_q
        except Exception:
            pass  # fallback to original on LLM failure

    return {**state, "question": q, "original_question": state.get("question", ""), "retry_count": retry}


def route_intent(state: SQLState) -> SQLState:
    question = state["question"]
    # Also check the pre-normalization question so a bad LLM correction can't
    # cause a false write-block on a genuine historical read query.
    original = state.get("original_question", question)

    # Block write commands before any routing — catches "drop anomaly rules",
    # "remove table", "delete employee X", etc. even when Layer 1 would match a tool.
    # IMPORTANT: only block if BOTH the normalized AND original question trigger write-intent.
    # This prevents a bad LLM spelling correction from false-blocking historical questions
    # like "when did Lina first inserted in the system?"
    if is_write_intent(question) and is_write_intent(original):
        blocked = {
            "path": "small_talk",
            "intent": "small_talk",
            "tool": None,
            "params": {},
            "confidence": 1.0,
            "needs_clarification": False,
            "clarification_question": None,
            "required_params": [],
            "_write_blocked": True,
        }
        return {**state, "intent": blocked}

    decision = route(question, history=state.get("history", []))
    return {**state, "intent": decision}


def validate_intent_params(state: SQLState) -> SQLState:
    intent = state.get("intent", {})
    intent_name = intent.get("intent") or intent.get("tool") or "sql_fallback"
    params = intent.get("params", {}) or {}

    missing = [p for p in required_params(intent_name) if not params.get(p)]

    if missing and tool_type(intent_name) not in {"sql", "small_talk"}:
        if "name" in missing:
            question = "Which person do you mean? Please provide the name, for example: “Where was Maged last seen?”"
        elif "event_id" in missing:
            question = "Which unknown face event ID should I use? For example: “Investigate unknown face event 274.”"
        elif "target_date" in missing:
            params["target_date"] = date.today().isoformat()
            missing = []
            question = None
        else:
            question = f"I need the missing parameter(s): {', '.join(missing)}."

        if missing:
            return {
                **state,
                "intent": {
                    **intent,
                    "needs_clarification": True,
                    "clarification_question": question,
                    "missing_params": missing,
                },
            }

    return {**state, "intent": {**intent, "params": params, "needs_clarification": False}}


def ask_clarification(state: SQLState) -> SQLState:
    intent = state.get("intent", {})
    answer = intent.get("clarification_question") or "I need one more detail before I can answer that."
    return {**state, "final_answer": answer, "sql": "", "results": []}


def handle_small_talk(state: SQLState) -> SQLState:
    intent = state.get("intent", {})

    # Write-command block — triggered by is_write_intent() in route_intent
    if intent.get("_write_blocked"):
        answer = (
            "⛔ That looks like a write or delete command. "
            "I only support read-only investigation queries. "
            "Please ask me to show, find, count, or investigate instead."
        )
        return {**state, "final_answer": answer, "sql": "", "results": []}

    q = state["question"].lower()
    if any(p in q for p in ["hello", "hi", "hey", "hiya", "howdy"]):
        answer = "👋 Hello! I’m the AI-Edge surveillance investigation assistant. Ask me about detections, unknown faces, anomalies, cameras, or security summaries."
    elif "how are you" in q:
        answer = "I’m operational and ready to investigate the surveillance data. 🟢"
    elif any(p in q for p in ["thank", "thanks"]):
        answer = "You’re welcome!"
    elif any(p in q for p in ["what can you do", "help"]):
        answer = (
            "I can help with surveillance investigations:\n\n"
            "People: 'Where was Maged last seen?', 'Show Ahmed movements yesterday'\n"
            "Unknown faces: 'Show latest unknown events', 'Investigate event 274'\n"
            "Anomaly pipeline: 'Show pending candidates', 'Any failed Ollama jobs?', 'Which scene windows were flagged?'\n"
            "Rules & devices: 'Show active anomaly rules', 'Any rule conflicts?', 'Show edge devices'\n"
            "Models: 'List active behavior models'\n"
            "Summaries: 'Today security summary', 'Camera activity', 'How many cameras?'"
        )
    else:
        answer = "I’m the AI-Edge surveillance investigation assistant. Ask me about people, cameras, unknown faces, anomalies, or summaries."
    return {**state, "final_answer": answer, "sql": "", "results": []}


def run_tool(state: SQLState) -> SQLState:
    intent = state.get("intent", {})
    tool_name = intent.get("tool")
    params = _coerce_tool_params(tool_name, intent.get("params", {}))
    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {**state, "tool_result": {"found": False, "message": f"Unknown tool: {tool_name}"}}
    result = fn(**params)
    return {**state, "tool_result": result, "sql": f"[Tool: {tool_name}]"}


def run_vector_tool(state: SQLState) -> SQLState:
    # Same execution model as normal tools, but separate node makes the graph explicit.
    return run_tool(state)


def load_schema(state: SQLState) -> SQLState:
    return {**state, "schema": get_database_schema()}


def generate_sql(state: SQLState) -> SQLState:
    retry = state.get("retry_count", 0)
    if retry == 0:
        prompt = get_sql_generation_prompt(
            state["question"],
            state.get("schema", ""),
            history=state.get("history", []),
        )
    else:
        prompt = get_error_correction_prompt(
            state["question"],
            state.get("sql", ""),
            state.get("error_message", ""),
            state.get("schema", ""),
        )
    raw_sql = get_llm().generate(prompt, temperature=0.0)
    return {**state, "sql": sanitize_sql(raw_sql)}


def check_sql_safety(state: SQLState) -> SQLState:
    is_safe, reason = safety_gate(state.get("sql", ""))
    return {**state, "sql_safe": is_safe, "safety_reason": reason}


def validate_sql_query(state: SQLState) -> SQLState:
    is_valid, error_msg = validate_sql(state.get("sql", ""))
    if is_valid:
        return {**state, "sql_valid": True, "error_message": ""}
    return {
        **state,
        "sql_valid": False,
        "error_message": error_msg,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def execute_query(state: SQLState) -> SQLState:
    result = execute_sql_safely(state.get("sql", ""))
    if result["success"]:
        return {**state, "results": result["data"], "sql_valid": True}
    return {
        **state,
        "sql_valid": False,
        "error_message": result["error"],
        "retry_count": state.get("retry_count", 0) + 1,
    }


def reject_write_sql(state: SQLState) -> SQLState:
    reason = state.get("safety_reason", "")
    answer = (
        "⛔ I can only run read-only database queries. This request produced SQL that was blocked.\n\n"
        f"Technical reason: {reason}"
    )
    return {**state, "final_answer": answer, "results": []}


def give_up_sql(state: SQLState) -> SQLState:
    answer = (
        "I could not safely answer this through the SQL fallback after retrying.\n\n"
        "This question may need a dedicated investigation tool.\n\n"
        f"Last SQL attempted:\n{state.get('sql', '')}\n\n"
        f"Error:\n{state.get('error_message', 'Unknown error')}"
    )
    return {**state, "final_answer": answer, "results": state.get("results", [])}


def format_sql_response(state: SQLState) -> SQLState:
    results = state.get("results", [])
    if not results:
        return {**state, "final_answer": "I searched the database but found no matching records for your question."}
    prompt = get_result_formatting_prompt(state["question"], state.get("sql", ""), results)
    answer = get_llm().generate(prompt, temperature=0.2)
    return {**state, "final_answer": answer}


# ─────────────────────────────────────────────────────────────────────────────
# Tool result formatting
# ─────────────────────────────────────────────────────────────────────────────

def format_tool_result(state: SQLState) -> SQLState:
    result = state.get("tool_result", {}) or {}
    question = state.get("question", "")
    tool = result.get("tool") or state.get("intent", {}).get("tool") or "tool"

    if not result.get("found"):
        answer = result.get("message") or result.get("error") or "No matching records were found."
        return {**state, "final_answer": answer, "results": []}

    data = result.get("data", [])

    # Deterministic formatters for factual outputs.
    if tool == "all_known_people":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No known people (employees or visitors) found in the registry."
        else:
            employees = [r for r in rows if r.get("person_type") == "employee"]
            visitors = [r for r in rows if r.get("person_type") == "visitor"]
            enrolled = [r for r in rows if r.get("person_type") == "enrolled"]
            lines = []
            if employees:
                lines.append(f"**Employees ({len(employees)}):**")
                for r in employees:
                    dept = f", dept: {r['department']}" if r.get("department") else ""
                    lines.append(f"  - {r['name']}{dept}")
            if visitors:
                lines.append(f"**Visitors ({len(visitors)}):**")
                for r in visitors:
                    visit = f", visit date: {r['visit_date']}" if r.get("visit_date") else ""
                    purpose = f", purpose: {r['purpose']}" if r.get("purpose") else ""
                    lines.append(f"  - {r['name']}{visit}{purpose}")
            if enrolled:
                lines.append(f"**Enrolled Profiles ({len(enrolled)}):**")
                for r in enrolled:
                    lines.append(f"  - {r['name']}, source: {r.get('department', 'Unknown')}")
            answer = f"Known people in the system ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if tool == "table_record_counts":
        rows = data if isinstance(data, list) else []
        empty = [r for r in rows if r.get("record_count") == 0]
        top = rows[0] if rows else None
        q = question.lower()

        # Build a fast lookup: table_name → record_count
        counts = {r["table_name"]: r["record_count"] for r in rows}

        # ── Specific entity count: "how many departments/labs/rules/..." ──────
        # Map question keywords → table name(s) to look up
        _ENTITY_TABLE_MAP = {
            "department": "departments",
            "departments": "departments",
            "lab": "labs",
            "labs": "labs",
            "rule": "anomaly_rules",
            "rules": "anomaly_rules",
            "schedule": "schedules",
            "schedules": "schedules",
            "camera": "cameras",
            "cameras": "cameras",
            "employee": "employees",
            "employees": "employees",
            "visitor": "visitors",
            "visitors": "visitors",
            "entry log": "entry_logs",
            "entry logs": "entry_logs",
            "anomaly log": "anomalies_logs",
            "anomaly logs": "anomalies_logs",
            "unknown face": "unknown_face_events",
            "unknown faces": "unknown_face_events",
        }
        matched_table = None
        for keyword, tname in _ENTITY_TABLE_MAP.items():
            if keyword in q:
                matched_table = tname
                break

        if matched_table:
            count = counts.get(matched_table)
            if count is not None:
                # Friendly singular/plural label
                friendly = matched_table.replace("_", " ").rstrip("s")
                answer = f"There {'is' if count == 1 else 'are'} **{count}** {matched_table.replace('_', ' ')} in the system."
            else:
                answer = f"I couldn't find a table named '{matched_table}' in the database."
        elif "empty" in q:
            answer = "There are no empty tables in the database." if not empty else (
                f"There are {len(empty)} empty tables:\n\n" + "\n".join(f"- {r['table_name']}" for r in empty)
            )
        elif "most records" in q or "largest" in q:
            answer = "I could not find any tables." if not top else (
                f"The table with the most records is **{top['table_name']}**, with {top['record_count']:,} records."
            )
        else:
            answer = "Here are the record counts:\n\n" + "\n".join(
                f"- {r['table_name']}: {r['record_count']:,} records" for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool in {"unknown_detection_count", "known_face_detection_count", "face_detection_count"}:
        d = data if isinstance(data, dict) else {}
        count = d.get("count", 0)
        target_date = d.get("target_date", "today")
        hour = d.get("hour")
        if tool == "unknown_detection_count":
            label = "unknown detection(s)"
        elif tool == "known_face_detection_count":
            label = "known face detection(s)"
        else:
            label = "face/person detection(s)"

        if hour is None:
            answer = f"There were {count} {label} on {target_date}."
        else:
            answer = f"There were {count} {label} on {target_date} between {int(hour):02d}:00 and {int(hour):02d}:59."
        return {**state, "final_answer": answer, "results": [d]}

    if tool == "latest_unknown_face_events":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No unknown face events were found."
        else:
            heading = f"Latest {len(rows)} unknown face event(s)"
            if result.get("days_back"):
                heading += f" from the last {result.get('days_back')} day(s)"
            lines = []
            for r in rows:
                assigned = r.get("assigned_detected_id")
                review = "unreviewed" if assigned is None else f"assigned to detected_id={assigned}"
                lines.append(
                    f"- Event {r.get('id', 'N/A')}: {r.get('created_at') or r.get('timestamp') or 'N/A'}, "
                    f"status={r.get('status', 'N/A')}, {review}, "
                    f"quality={r.get('quality_score', 'N/A')}, best_similarity={r.get('best_similarity_score', 'N/A')}"
                )
            answer = heading + ":\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if tool == "unknown_face_event_details":
        d = data if isinstance(data, dict) else {}
        answer = f"Unknown face event {result.get('event_id')} details:\n\n" + "\n".join(
            f"- {k}: {_compact(v)}" for k, v in d.items()
        )
        return {**state, "final_answer": answer, "results": [d]}

    if tool in {"person_last_seen", "person_first_seen", "last_seen", "first_seen"}:
        d = data if isinstance(data, dict) else {}
        label = "Last seen" if "last" in tool else "First detected"
        answer = (
            f"{label}: {d.get('person_name', 'N/A')} was detected at "
            f"{d.get('camera_name', 'N/A')} ({d.get('camera_location', 'N/A')}) "
            f"at {d.get('timestamp', 'N/A')}."
        )
        if d.get("evidence_url"):
            answer += f"\nEvidence: {d.get('evidence_url')}"
        return {**state, "final_answer": answer, "results": [d]}

    if tool in {"person_timeline", "timeline"}:
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No detections were found for that timeline."
        else:
            answer = f"Timeline for {rows[0].get('person_name', 'person')} on {result.get('date')}:\n\n" + "\n".join(
                f"- {r.get('timestamp')}: {r.get('camera_name')} ({r.get('camera_location')})" for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool in {"people_seen_on_date", "people_seen_today"}:
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = f"No identified people were found on {result.get('date', 'that date')}."
        else:
            answer = f"People seen on {result.get('date')} ({len(rows)}):\n\n" + "\n".join(
                f"- {r.get('person_name')} ({r.get('person_type')}): {r.get('detections')} detections, "
                f"first={r.get('first_seen')}, last={r.get('last_seen')}, cameras={r.get('cameras_seen')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool == "latest_anomalies":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No anomaly logs were found."
        else:
            answer = f"Latest {len(rows)} anomaly log(s):\n\n" + "\n".join(
                f"- {r.get('timestamp')}: {r.get('description', 'N/A')} at {r.get('camera_name', 'N/A')} "
                f"({r.get('camera_location', 'N/A')}), severity={r.get('severity', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool in {"anomalies_near_person", "anomalies_near_face", "anomalies_near_unknown_event"}:
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = f"No anomalies were found within the checked time window."
        else:
            answer = f"Found {len(rows)} nearby anomaly/anomalies:\n\n" + "\n".join(
                f"- {r.get('timestamp') or r.get('detected_at')}: {r.get('description') or r.get('event_type')} "
                f"at {r.get('camera_name', 'N/A')} ({r.get('seconds_apart', 'N/A')}s apart)"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool in {"repeated_unknowns", "repeated_unknown_faces"}:
        rows = data if isinstance(data, list) else []
        if not rows:
            days = result.get('days_back', 7)
            answer = f"No repeated unknown visitors were found in the last {days} day(s)."
        else:
            days = result.get('days_back', 7)
            answer = f"Repeated unknown visitors in the last {days} day(s) ({len(rows)} group(s)):\n\n" + "\n".join(
                f"- {r.get('camera_name', 'N/A')} on {r.get('day', 'N/A')}: "
                f"{r.get('appearances', 'N/A')} appearances, "
                f"first={r.get('first_seen', 'N/A')}, last={r.get('last_seen', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool == "similar_unknown_faces":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = f"No similar unknown faces were found for event {result.get('event_id')} above the threshold {result.get('threshold')}."
        else:
            answer = f"Similar unknown faces for event {result.get('event_id')}:\n\n" + "\n".join(
                f"- Event {r.get('event_id')}: similarity={float(r.get('similarity', 0)):.3f}, time={r.get('created_at')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool == "possible_identity_match":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = f"No possible known identity match was found for event {result.get('event_id')} above the threshold {result.get('threshold')}."
        else:
            answer = f"Possible known identity matches for event {result.get('event_id')}:\n\n" + "\n".join(
                f"- {r.get('person_name')} ({r.get('person_type')}), detected_id={r.get('detected_id')}, similarity={float(r.get('similarity', 0)):.3f}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool == "camera_activity_summary":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No camera activity was found for the selected period."
        else:
            answer = f"Camera activity summary ({len(rows)} camera(s)):\n\n" + "\n".join(
                f"- {r.get('camera_name')}: {r.get('detections')} detections, first={r.get('first_seen')}, last={r.get('last_seen')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    if tool == "daily_security_summary":
        d = data if isinstance(data, dict) else {}
        answer = (
            f"Security summary for {d.get('date', result.get('date'))}:\n\n"
            f"- Entry-log detections: {d.get('entry_log_detections', 'N/A')}\n"
            f"- Unknown face events: {d.get('unknown_face_events', 'N/A')}\n"
            f"- Anomaly logs: {d.get('anomaly_logs', 'N/A')}"
        )
        if d.get("top_cameras"):
            answer += "\n- Top cameras:\n" + "\n".join(
                f"  • {r.get('camera_name')}: {r.get('detections')} detections" for r in d["top_cameras"]
            )
        return {**state, "final_answer": answer, "results": [d]}

    if tool == "investigate_unknown_face_event":
        # Build a structured answer without the LLM when data is sufficient
        # — avoids generate_long timeout on slow/loaded models.
        details_data = data.get("details", {}).get("data", {}) if isinstance(data, dict) else {}
        similar_data = data.get("similar_unknown_faces", {}) if isinstance(data, dict) else {}
        identity_data = data.get("possible_identity_matches", {}) if isinstance(data, dict) else {}
        anomaly_data = data.get("nearby_anomalies", {}) if isinstance(data, dict) else {}

        similar_rows = similar_data.get("data", []) if isinstance(similar_data, dict) else []
        identity_rows = identity_data.get("data", []) if isinstance(identity_data, dict) else []
        anomaly_rows = anomaly_data.get("data", []) if isinstance(anomaly_data, dict) else []

        # Event section
        eid = details_data.get("id", result.get("event_id", "?"))
        cam = details_data.get("camera_name", details_data.get("camera_id", "N/A"))
        loc = details_data.get("camera_location", "")
        ts = details_data.get("event_timestamp", details_data.get("created_at", "N/A"))
        status = details_data.get("status", "N/A")
        img = details_data.get("image_video_ref", "")

        sections = [f"**Investigation Report — Unknown Face Event #{eid}**\n"]
        sections.append(f"**Event:** Detected at {cam}" + (f" ({loc})" if loc else "") + f" on {ts}. Status: {status}.")
        if img:
            sections.append(f"Evidence: {img}")

        # Similar unknown faces
        if similar_rows:
            sections.append(f"\n**Similar Unknown Faces ({len(similar_rows)} match(es)):**")
            for r in similar_rows[:3]:
                sections.append(f"- Event #{r.get('id')} at {r.get('camera_name', 'N/A')} — distance: {r.get('distance', 'N/A'):.4f}")
        else:
            sections.append("\n**Similar Unknown Faces:** No prior sightings found via vector search.")

        # Possible identity matches
        if identity_rows:
            sections.append(f"\n**Possible Identity Matches ({len(identity_rows)} result(s)):**")
            for r in identity_rows[:3]:
                sections.append(f"- {r.get('name', 'Unknown')} (distance: {r.get('distance', 'N/A'):.4f})")
        else:
            sections.append("\n**Possible Identity Matches:** No close match found in known identity registry.")

        # Nearby anomalies
        if anomaly_rows:
            sections.append(f"\n**Nearby Anomalies ({len(anomaly_rows)} found):**")
            for r in anomaly_rows[:3]:
                sections.append(f"- {r.get('reason', r.get('type', 'Anomaly'))} at {r.get('timestamp', 'N/A')}")
        else:
            sections.append("\n**Nearby Anomalies:** No anomaly events recorded near this event.")

        sections.append("\n**Conclusion:** " + (
            "This person has possible matches in the known registry — manual review recommended."
            if identity_rows else
            "This person remains unidentified. No strong matches found in registry or prior events."
        ))

        answer = "\n".join(sections)
        return {**state, "final_answer": answer, "results": [data] if isinstance(data, dict) else _flatten_results(result)}

    # ── NEW: Anomaly candidates ───────────────────────────────────────────────
    if tool == "anomaly_candidates":
        rows = data if isinstance(data, list) else []
        if not rows:
            status_label = f" with status '{result.get('status')}'" if result.get("status") else ""
            answer = f"No anomaly candidates found{status_label}."
        else:
            status_counts: dict[str, int] = {}
            for r in rows:
                s = str(r.get("status", "unknown"))
                status_counts[s] = status_counts.get(s, 0) + 1
            count_str = ", ".join(f"{v} {k}" for k, v in status_counts.items())
            answer = f"Anomaly candidates ({len(rows)} total — {count_str}):\n\n" + "\n".join(
                f"- Candidate {r.get('id')}: status={r.get('status')}, "
                f"severity={r.get('severity', 'N/A')}, "
                f"alert_decision={r.get('alert_decision', 'N/A')}, "
                f"reason={str(r.get('reason', 'N/A'))[:80]}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Anomaly candidate review ─────────────────────────────────────────
    if tool == "anomaly_candidate_review":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No anomaly candidate review decisions found."
        else:
            confirmed = sum(1 for r in rows if r.get("decision") == "confirmed")
            dismissed = sum(1 for r in rows if r.get("decision") == "dismissed")
            uncertain = sum(1 for r in rows if r.get("decision") == "uncertain")
            answer = (
                f"Anomaly candidate review decisions ({len(rows)} total — "
                f"{confirmed} confirmed, {dismissed} dismissed, {uncertain} uncertain):\n\n"
            ) + "\n".join(
                f"- Review {r.get('id')}: candidate_id={r.get('anomaly_candidate_id')}, "
                f"decision={r.get('decision')}, reviewer={r.get('reviewer', 'N/A')}, "
                f"reviewed_at={r.get('reviewed_at', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Ollama jobs ──────────────────────────────────────────────────────
    if tool == "ollama_jobs":
        rows = data if isinstance(data, list) else []
        if not rows:
            status_label = f" with status '{result.get('status')}'" if result.get("status") else ""
            answer = f"No Ollama jobs found{status_label}."
        else:
            status_counts: dict[str, int] = {}
            for r in rows:
                s = str(r.get("status", "unknown"))
                status_counts[s] = status_counts.get(s, 0) + 1
            count_str = ", ".join(f"{v} {k}" for k, v in status_counts.items())
            answer = f"Ollama jobs ({len(rows)} total — {count_str}):\n\n" + "\n".join(
                f"- Job {r.get('id')}: status={r.get('status')}, "
                f"model={r.get('model_name', 'N/A')}, "
                f"candidate_id={r.get('anomaly_candidate_id', 'N/A')}, "
                f"created={r.get('created_at', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Scene window embeddings ──────────────────────────────────────────
    if tool == "scene_window_embeddings":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No scene window embeddings found matching your filter."
        else:
            flagged = sum(1 for r in rows if r.get("is_anomalous"))
            answer = (
                f"Scene window embeddings ({len(rows)} shown, {flagged} anomalous):\n\n"
            ) + "\n".join(
                f"- Window {r.get('id')}: camera_id={r.get('camera_id')}, "
                f"anomalous={r.get('is_anomalous')}, "
                f"l2={r.get('l2_score', 'N/A')}, mse={r.get('mse_score', 'N/A')}, "
                f"cos_flag={r.get('cos_flag', 'N/A')}, "
                f"start={r.get('start_time', r.get('window_start_ts', 'N/A'))}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Anomaly rules ────────────────────────────────────────────────────
    if tool == "anomaly_rules":
        rows = data if isinstance(data, list) else []
        q_lower = question.lower()
        if not rows:
            answer = "No anomaly rules found matching your filter."
        # Count-only: "how many rules", "how many active rules", etc.
        elif re.search(r"\bhow\s+many\b|\bcount\b", q_lower):
            label = "total"
            if "trigger" in q_lower:
                label = "trigger"
            elif "suppress" in q_lower:
                label = "suppress"
            elif "inactive" in q_lower or "not active" in q_lower:
                label = "inactive"
            elif "active" in q_lower:
                label = "active"
            answer = f"There are **{len(rows)}** {label} anomaly rule(s) in the system."
        # Single rule lookup: "show me rule 32", "description of anomaly rule 32"
        elif len(rows) == 1:
            r = rows[0]
            answer = (
                f"Anomaly Rule {r.get('id')} [{r.get('rule_type')}|{r.get('event_type', 'N/A')}|{r.get('source', 'N/A')}]:\n\n"
                f"{r.get('rule_text', 'No rule text available.')}"
            )
        else:
            triggers  = [r for r in rows if r.get("rule_type") == "trigger"]
            suppresses = [r for r in rows if r.get("rule_type") == "suppress"]
            answer = (
                f"Anomaly rules ({len(rows)} total — "
                f"{len(triggers)} trigger, {len(suppresses)} suppress):\n\n"
            ) + "\n".join(
                f"- Rule {r.get('id')} [{r.get('rule_type')}|{r.get('event_type', 'N/A')}|{r.get('source', 'N/A')}]: "
                f"{str(r.get('rule_text', ''))[:100]}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Edge devices ─────────────────────────────────────────────────────
    if tool == "edge_devices":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No edge devices are registered in the system."
        else:
            answer = f"Registered edge devices ({len(rows)}):\n\n" + "\n".join(
                f"- {r.get('name', 'N/A')} (key={r.get('device_key', 'N/A')}): "
                f"location={r.get('location', 'N/A')}, "
                f"registered={r.get('created_at', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Normal behavior models ───────────────────────────────────────────
    if tool == "normal_behavior_models":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No behavior models found in the system."
        else:
            active = [r for r in rows if r.get("is_active")]
            answer = (
                f"Normal behavior models ({len(rows)} total, {len(active)} active):\n\n"
            ) + "\n".join(
                f"- Model {r.get('id')}: {r.get('name', 'N/A')} v{r.get('version', 'N/A')}, "
                f"active={r.get('is_active')}, dim={r.get('embedding_dim', 'N/A')}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── NEW: Rule conflicts ───────────────────────────────────────────────────
    if tool == "rule_conflicts":
        rows = data if isinstance(data, list) else []
        if not rows:
            answer = "No rule conflicts are currently recorded."
        else:
            pending = [r for r in rows if r.get("status") == "pending"]
            answer = (
                f"Rule conflicts ({len(rows)} total, {len(pending)} pending):\n\n"
            ) + "\n".join(
                f"- Conflict {r.get('id')}: rule {r.get('rule_id_1')} vs rule {r.get('rule_id_2')}, "
                f"status={r.get('status', 'N/A')}, reason={str(r.get('conflict_reason', 'N/A'))[:80]}"
                for r in rows
            )
        return {**state, "final_answer": answer, "results": rows}

    # ── Generic LLM fallback — for any tool without a specific formatter ───────
    prompt = f"""You are a surveillance security assistant. Answer naturally and concisely.
Base your answer ONLY on the structured data below. Do not invent facts.

USER QUESTION: {question}
TOOL RESULT:
{_safe_json(_strip_embeddings(result))}

ANSWER:
"""
    answer = get_llm().generate(prompt, temperature=0.2)
    return {**state, "final_answer": answer, "results": _flatten_results(result)}


# ─────────────────────────────────────────────────────────────────────────────
# Routing functions
# ─────────────────────────────────────────────────────────────────────────────

def after_validate_params(state: SQLState) -> str:
    intent = state.get("intent", {})
    if intent.get("needs_clarification"):
        return "clarification"
    path = intent.get("path") or tool_type(intent.get("intent", "sql_fallback"))
    if path == "small_talk":
        return "small_talk"
    if path == "vector":
        return "vector"
    if path == "normal":
        return "tool"
    return "sql"


def after_safety_check(state: SQLState) -> str:
    return "safe" if state.get("sql_safe", False) else "blocked"


def after_validate_sql(state: SQLState) -> str:
    return "execute" if state.get("sql_valid", False) else "retry"


def should_retry(state: SQLState) -> str:
    if state.get("sql_valid", False):
        return "format"
    if state.get("retry_count", 0) < 2:
        return "retry"
    return "give_up"


# ─────────────────────────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────────────────────────

def create_workflow():
    wf = StateGraph(SQLState)

    wf.add_node("normalize_question", normalize_question)
    wf.add_node("route_intent", route_intent)
    wf.add_node("validate_intent_params", validate_intent_params)
    wf.add_node("ask_clarification", ask_clarification)
    wf.add_node("small_talk", handle_small_talk)
    wf.add_node("run_tool", run_tool)
    wf.add_node("run_vector_tool", run_vector_tool)
    wf.add_node("format_tool_result", format_tool_result)
    wf.add_node("load_schema", load_schema)
    wf.add_node("generate", generate_sql)
    wf.add_node("safety_check", check_sql_safety)
    wf.add_node("reject_write", reject_write_sql)
    wf.add_node("validate_sql", validate_sql_query)
    wf.add_node("execute", execute_query)
    wf.add_node("format_sql", format_sql_response)
    wf.add_node("give_up", give_up_sql)

    wf.set_entry_point("normalize_question")
    wf.add_edge("normalize_question", "route_intent")
    wf.add_edge("route_intent", "validate_intent_params")

    wf.add_conditional_edges(
        "validate_intent_params",
        after_validate_params,
        {
            "clarification": "ask_clarification",
            "small_talk": "small_talk",
            "tool": "run_tool",
            "vector": "run_vector_tool",
            "sql": "load_schema",
        },
    )

    wf.add_edge("ask_clarification", END)
    wf.add_edge("small_talk", END)

    wf.add_edge("run_tool", "format_tool_result")
    wf.add_edge("run_vector_tool", "format_tool_result")
    wf.add_edge("format_tool_result", END)

    wf.add_edge("load_schema", "generate")
    wf.add_edge("generate", "safety_check")
    wf.add_conditional_edges("safety_check", after_safety_check, {"safe": "validate_sql", "blocked": "reject_write"})
    wf.add_edge("reject_write", END)
    wf.add_conditional_edges("validate_sql", after_validate_sql, {"execute": "execute", "retry": "generate"})
    wf.add_conditional_edges("execute", should_retry, {"format": "format_sql", "retry": "generate", "give_up": "give_up"})
    wf.add_edge("format_sql", END)
    wf.add_edge("give_up", END)

    return wf.compile()


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = create_workflow()
    return _workflow


def process_question(question: str, history: list | None = None) -> dict:
    initial_state = {
        "question": question,
        "history": history or [],
        "retry_count": 0,
    }
    try:
        final_state = get_workflow().invoke(initial_state, config={"recursion_limit": 20})
        return {
            "success": True,
            "question": question,
            "sql": final_state.get("sql", ""),
            "results": final_state.get("results", []),
            "answer": final_state.get("final_answer", "No answer generated"),
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "question": question,
            "sql": "",
            "results": [],
            "answer": "I could not answer that question because the investigation workflow failed.",
            "error": str(e),
        }