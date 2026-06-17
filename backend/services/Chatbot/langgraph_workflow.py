"""
langgraph_workflow.py — Clean LangGraph orchestration for the Surveillance Chatbot.

Architecture (paper-backed):
  ReAct  (Yao et al. 2022)       → reasoning + acting in each node
  DIN-SQL (Pourreza & Rafiei)    → decomposed in-context SQL generation
  Hybrid LLM+Tools (2410.01066) → deterministic tools first, SQL as fallback

Flow:
  normalize → route → validate_params
                           ↓
               ┌────────────────────────┐
           small_talk   tool   vector   sql
               ↓         ↓       ↓      ↓
              END     format  format  generate→safety→validate→execute→format
                         ↓       ↓
                        END     END
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from langgraph.graph import StateGraph, END

from model import SQLState, OllamaLLM
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql, safety_gate, is_write_intent
from prompts import get_sql_generation_prompt, get_error_correction_prompt, get_result_formatting_prompt
from intent_router import route as _router_route, _TOOL_INTENTS, _VECTOR_INTENTS
from tools import TOOL_MAP

# ─────────────────────────────────────────────────────────────────────────────
# Lazy singletons
# ─────────────────────────────────────────────────────────────────────────────
_llm = None
_workflow = None


def _llm_instance() -> OllamaLLM:
    global _llm
    if _llm is None:
        _llm = OllamaLLM()
    return _llm


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compact(value: Any, max_len: int = 220) -> str:
    text = str(value)
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def _safe_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, indent=2)


def _flatten(result: dict) -> list:
    data = result.get("data", [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


_EMBED_COLS = {
    "embedding", "face_embedding", "vector", "encoding",
    "scene_embedding", "image_data", "thumbnail",
    "student_embedding", "teacher_embedding",
}


def _strip_embeddings(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _strip_embeddings(v) for k, v in data.items() if k.lower() not in _EMBED_COLS}
    if isinstance(data, list):
        return [_strip_embeddings(x) for x in data]
    return data


def _coerce_params(intent: str, entities: dict) -> dict:
    """
    Map entity names to the actual function signature of the tool.
    Drop any keys the function doesn't accept.
    """
    import inspect
    fn = TOOL_MAP.get(intent)
    if not fn:
        return {}

    p = dict(entities or {})

    # Canonical renames
    renames = {
        "person_last_seen":    {"person_name": "name"},
        "person_first_seen":   {"person_name": "name"},
        "person_timeline":     {"person_name": "name", "date": "target_date"},
        "people_seen_on_date": {"date": "target_date"},
    }
    for old, new in renames.get(intent, {}).items():
        if old in p and new not in p:
            p[new] = p.pop(old)

    # Intent-specific aliases / normalisation.
    if intent == "vad_case_reviews" and "status" in p and "decision" not in p:
        p["decision"] = p.pop("status")

    if isinstance(p.get("alert_decision"), str):
        p["alert_decision"] = p["alert_decision"].upper()
    if isinstance(p.get("severity"), str):
        p["severity"] = p["severity"].lower()
    if isinstance(p.get("decision"), str):
        p["decision"] = p["decision"].lower()
    if isinstance(p.get("status"), str):
        p["status"] = p["status"].lower()
    if isinstance(p.get("rule_type"), str):
        p["rule_type"] = p["rule_type"].lower()

    # Keep only params the function actually accepts, drop None values
    sig = inspect.signature(fn)
    allowed = set(sig.parameters.keys())
    return {k: v for k, v in p.items() if k in allowed and v is not None}


# ─────────────────────────────────────────────────────────────────────────────
# NODES
# ─────────────────────────────────────────────────────────────────────────────

def normalize_question(state: SQLState) -> SQLState:
    """Pass-through — LLM understanding handles any phrasing."""
    q = (state.get("question") or "").strip()
    return {**state, "question": q, "original_question": q, "retry_count": state.get("retry_count", 0)}


def route_intent(state: SQLState) -> SQLState:
    question = state["question"]
    original = state.get("original_question", question)

    # Block write commands before routing
    if is_write_intent(question) and is_write_intent(original):
        return {**state, "intent": "small_talk", "entities": {}, "route": "small_talk", "_write_blocked": True}

    decision = _router_route(question, history=state.get("history", []))
    return {
        **state,
        "intent":   decision["intent"],
        "entities": decision["entities"],
        "route":    decision["route"],
    }


def validate_intent_params(state: SQLState) -> SQLState:
    """Check required params; set needs_clarification if missing."""
    intent = state.get("intent", "sql_fallback")
    entities = state.get("entities", {})
    route = state.get("route", "sql")

    # Tools that need an event_id
    needs_event_id = {"similar_unknown_faces", "possible_identity_match",
                      "investigate_unknown_face", "unknown_face_details"}
    # Tools that need a name
    needs_name = {"person_last_seen", "person_first_seen", "person_timeline"}
    # Tools that need a case_id
    needs_case_id = {"vad_case_details"}

    clarification = None

    if route in {"tool", "vector"}:
        if intent in needs_name and not entities.get("name"):
            clarification = "Which person do you mean? Please provide a name, e.g. 'Where was Maged last seen?'"
        elif intent in needs_event_id and not entities.get("event_id"):
            clarification = "Which unknown face event ID? e.g. 'Investigate unknown face event 42.'"
        elif intent in needs_case_id and not entities.get("case_id"):
            clarification = "Which VAD case ID? e.g. 'Show details for case 7.'"

    return {**state, "needs_clarification": bool(clarification), "clarification_question": clarification}


def ask_clarification(state: SQLState) -> SQLState:
    answer = state.get("clarification_question") or "I need one more detail to answer that."
    return {**state, "final_answer": answer, "sql": "", "results": []}


def handle_small_talk(state: SQLState) -> SQLState:
    if state.get("_write_blocked"):
        return {**state,
                "final_answer": (
                    "⛔ That looks like a write or delete command. "
                    "I only support read-only investigation queries. "
                    "Please ask me to show, find, count, or investigate instead."
                ),
                "sql": "", "results": []}

    q = state["question"].lower()
    if any(w in q for w in ["hello", "hi", "hey", "howdy", "hiya"]):
        answer = ("👋 Hello! I'm the AI-Edge surveillance investigation assistant. "
                  "Ask me about detections, unknown faces, anomaly cases, cameras, or security summaries.")
    elif "how are you" in q:
        answer = "I'm operational and ready to investigate. 🟢"
    elif any(w in q for w in ["thank", "thanks"]):
        answer = "You're welcome!"
    elif any(w in q for w in ["what can you do", "help"]):
        answer = (
            "I can help with surveillance investigations:\n\n"
            "**People:** 'Where was Maged last seen?', 'Show Ahmed's movements yesterday'\n"
            "**Unknown faces:** 'Show latest unknown events', 'Investigate event 42'\n"
            "**VAD anomaly pipeline:** 'Show open cases', 'Any failed reasoning jobs?', 'Critical gate events'\n"
            "**Rules & devices:** 'Show active anomaly rules', 'Any rule conflicts?', 'List edge devices'\n"
            "**Summaries:** 'Today's security summary', 'Camera activity', 'Table record counts'"
        )
    else:
        answer = ("I'm the AI-Edge surveillance investigation assistant. "
                  "Ask me about people, cameras, unknown faces, anomalies, or summaries.")
    return {**state, "final_answer": answer, "sql": "", "results": []}


def run_tool(state: SQLState) -> SQLState:
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    fn = TOOL_MAP.get(intent)
    if not fn:
        return {**state, "tool_result": {"found": False, "message": f"No tool registered for intent '{intent}'"}}
    params = _coerce_params(intent, entities)
    try:
        result = fn(**params)
    except Exception as e:
        result = {"found": False, "message": str(e)}
    return {**state, "tool_result": result, "sql": f"[Tool: {intent}]"}


def run_vector_tool(state: SQLState) -> SQLState:
    # Same execution path — separate node makes the graph explicit and allows
    # different error handling / logging in the future.
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
    raw = _llm_instance().generate(prompt, temperature=0.0)
    return {**state, "sql": sanitize_sql(raw)}


def check_sql_safety(state: SQLState) -> SQLState:
    is_safe, reason = safety_gate(state.get("sql", ""))
    return {**state, "sql_safe": is_safe, "safety_reason": reason}


def validate_sql_query(state: SQLState) -> SQLState:
    is_valid, error_msg = validate_sql(state.get("sql", ""))
    if is_valid:
        return {**state, "sql_valid": True, "error_message": ""}
    return {**state, "sql_valid": False, "error_message": error_msg,
            "retry_count": state.get("retry_count", 0) + 1}


def execute_query(state: SQLState) -> SQLState:
    result = execute_sql_safely(state.get("sql", ""))
    if result["success"]:
        return {**state, "results": result["data"], "sql_valid": True}
    return {**state, "sql_valid": False, "error_message": result["error"],
            "retry_count": state.get("retry_count", 0) + 1}


def reject_write_sql(state: SQLState) -> SQLState:
    reason = state.get("safety_reason", "")
    return {**state,
            "final_answer": (
                "⛔ I can only run read-only database queries. "
                f"The generated SQL was blocked.\n\nReason: {reason}"
            ),
            "results": []}


def give_up_sql(state: SQLState) -> SQLState:
    return {**state,
            "final_answer": (
                "I could not safely answer this via the SQL fallback after retrying.\n\n"
                f"Last SQL attempted:\n{state.get('sql', '')}\n\n"
                f"Error:\n{state.get('error_message', 'Unknown error')}"
            ),
            "results": state.get("results", [])}


def format_sql_response(state: SQLState) -> SQLState:
    results = state.get("results", [])
    if not results:
        return {**state, "final_answer": "I searched the database but found no matching records."}
    prompt = get_result_formatting_prompt(state["question"], state.get("sql", ""), results)
    answer = _llm_instance().generate(prompt, temperature=0.2)
    return {**state, "final_answer": answer}


# ─────────────────────────────────────────────────────────────────────────────
# Tool result formatters — deterministic, no LLM needed for most cases
# ─────────────────────────────────────────────────────────────────────────────

def format_tool_result(state: SQLState) -> SQLState:  # noqa: C901
    result = state.get("tool_result", {}) or {}
    question = state.get("question", "")
    intent = state.get("intent", "")

    if not result.get("found"):
        msg = result.get("message") or result.get("error") or "No matching records found."
        return {**state, "final_answer": msg, "results": []}

    data = result.get("data", [])

    # ── Person tracking ──────────────────────────────────────────────────────
    if intent in {"person_last_seen", "person_first_seen"}:
        d = data if isinstance(data, dict) else {}
        label = "Last seen" if intent == "person_last_seen" else "First detected"
        answer = (
            f"{label}: **{d.get('person_name', 'N/A')}** at "
            f"{d.get('camera_name', 'N/A')} ({d.get('camera_location', 'N/A')}) "
            f"on {d.get('timestamp', 'N/A')}."
        )
        if d.get("evidence_url"):
            answer += f"\nEvidence: {d['evidence_url']}"
        return {**state, "final_answer": answer, "results": [d]}

    if intent == "person_timeline":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No detections found for that timeline.", "results": []}
        name = rows[0].get("person_name", "person")
        period = result.get("period", "")
        lines = [f"- {r.get('timestamp')}: {r.get('camera_name')} ({r.get('camera_location')})" for r in rows]
        answer = f"Timeline for **{name}** ({period}, {len(rows)} stop(s)):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "people_seen_on_date":
        rows = data if isinstance(data, list) else []
        dt = result.get("date", "that date")
        if not rows:
            return {**state, "final_answer": f"No identified people found on {dt}.", "results": []}
        lines = [
            f"- **{r.get('person_name')}** ({r.get('person_type')}): "
            f"{r.get('detections')} detection(s), "
            f"first={r.get('first_seen')}, last={r.get('last_seen')}, "
            f"cameras={r.get('cameras_seen')}"
            for r in rows
        ]
        answer = f"People seen on {dt} ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "known_people":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No known people in the registry.", "results": []}
        employees = [r for r in rows if r.get("person_type") == "employee"]
        visitors  = [r for r in rows if r.get("person_type") == "visitor"]
        enrolled  = [r for r in rows if r.get("person_type") == "enrolled"]
        lines = []
        if employees:
            lines.append(f"**Employees ({len(employees)}):**")
            lines += [f"  - {r['name']}" for r in employees]
        if visitors:
            lines.append(f"**Visitors ({len(visitors)}):**")
            lines += [f"  - {r['name']} (visit: {r.get('visit_date','?')}, purpose: {r.get('purpose','?')})" for r in visitors]
        if enrolled:
            lines.append(f"**Enrolled profiles ({len(enrolled)}):**")
            lines += [f"  - {r['name']}" for r in enrolled]
        answer = f"Known people ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    # ── Detection counts ─────────────────────────────────────────────────────
    if intent in {"count_unknown_detections", "count_known_detections", "count_all_detections"}:
        d = data if isinstance(data, dict) else {}
        count = d.get("count", 0)
        period = d.get("period", "today")
        hour = d.get("hour")
        labels = {
            "count_unknown_detections": "unknown face detection(s)",
            "count_known_detections":   "known face detection(s)",
            "count_all_detections":     "total detection(s)",
        }
        label = labels.get(intent, "detection(s)")
        time_str = f" between {int(hour):02d}:00–{int(hour):02d}:59" if hour is not None else ""
        answer = f"There were **{count}** {label} on {period}{time_str}."
        return {**state, "final_answer": answer, "results": [d]}

    # ── Unknown face pipeline ────────────────────────────────────────────────
    if intent == "unknown_face_events":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No unknown face events found.", "results": []}
        lines = [
            f"- Event **#{r.get('id')}**: "
            f"status={r.get('status')}, "
            f"camera={r.get('camera_name','N/A')}, "
            f"time={r.get('event_timestamp') or r.get('created_at','N/A')}, "
            f"quality={r.get('quality_score','N/A')}"
            for r in rows
        ]
        answer = f"Unknown face events ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "unknown_face_details":
        d = data if isinstance(data, dict) else (rows[0] if isinstance(data, list) and data else {})
        eid = result.get("event_id", d.get("id", "?"))
        lines = [f"- {k}: {_compact(v)}" for k, v in d.items()]
        answer = f"Unknown face event **#{eid}** details:\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": [d]}

    if intent == "similar_unknown_faces":
        rows = data if isinstance(data, list) else []
        eid = result.get("event_id", "?")
        thr = result.get("threshold", 0.6)
        if not rows:
            return {**state,
                    "final_answer": f"No similar unknown faces found for event #{eid} (threshold {thr}).",
                    "results": []}
        lines = [
            f"- Event **#{r.get('event_id')}**: similarity={float(r.get('similarity', 0)):.3f}, "
            f"camera={r.get('camera_name','N/A')}, time={r.get('created_at','N/A')}"
            for r in rows
        ]
        answer = f"Similar unknown faces for event #{eid} ({len(rows)} match(es)):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "possible_identity_match":
        rows = data if isinstance(data, list) else []
        eid = result.get("event_id", "?")
        if not rows:
            return {**state,
                    "final_answer": f"No known identity match found for event #{eid}.",
                    "results": []}
        lines = [
            f"- **{r.get('person_name')}** ({r.get('person_type')}): "
            f"similarity={float(r.get('similarity', 0)):.3f}"
            for r in rows
        ]
        answer = f"Possible identity matches for event #{eid}:\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "investigate_unknown_face":
        eid = result.get("event_id", "?")
        d = data if isinstance(data, dict) else {}
        details  = d.get("details", {})
        similar  = d.get("similar", {})
        identity = d.get("identity", {})

        det = details.get("data", {}) if isinstance(details, dict) else {}
        sim_rows = similar.get("data", []) if isinstance(similar, dict) else []
        id_rows  = identity.get("data", []) if isinstance(identity, dict) else []

        cam = det.get("camera_name", "N/A")
        loc = det.get("camera_location", "")
        ts  = det.get("event_timestamp") or det.get("created_at", "N/A")
        status = det.get("status", "N/A")

        sections = [f"**Investigation Report — Unknown Face Event #{eid}**\n"]
        sections.append(f"Detected at **{cam}**" + (f" ({loc})" if loc else "") + f" on {ts}. Status: {status}.")

        if sim_rows:
            sections.append(f"\n**Similar Unknown Faces ({len(sim_rows)} match(es)):**")
            for r in sim_rows[:3]:
                sections.append(f"- Event #{r.get('event_id')} — similarity: {float(r.get('similarity',0)):.3f}")
        else:
            sections.append("\n**Similar Unknown Faces:** None found.")

        if id_rows:
            sections.append(f"\n**Possible Identity Matches ({len(id_rows)}):**")
            for r in id_rows[:3]:
                sections.append(f"- **{r.get('person_name')}** ({r.get('person_type')}) — similarity: {float(r.get('similarity',0)):.3f}")
            sections.append("\n**Conclusion:** Possible match found — manual review recommended.")
        else:
            sections.append("\n**Possible Identity Matches:** No strong match in registry.")
            sections.append("\n**Conclusion:** Person remains unidentified.")

        return {**state, "final_answer": "\n".join(sections), "results": [d]}

    # ── VAD anomaly pipeline ─────────────────────────────────────────────────
    if intent == "vad_cases":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No VAD anomaly cases found.", "results": []}
        lines = [
            f"- Case **#{r.get('id')}** [{r.get('case_key','N/A')}]: "
            f"status={r.get('status')}, severity={r.get('severity')}, "
            f"type={r.get('case_type')}, camera={r.get('camera_name','N/A')}, "
            f"start={r.get('start_ts')}"
            for r in rows
        ]
        answer = f"VAD anomaly cases ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_case_details":
        d = data if isinstance(data, dict) else {}
        cid = result.get("case_id", d.get("id", "?"))
        rr = d.get("reasoning_result")
        lines = [f"- {k}: {_compact(v)}" for k, v in d.items() if k != "reasoning_result"]
        answer = f"VAD Case **#{cid}** details:\n\n" + "\n".join(lines)
        if rr:
            answer += (
                f"\n\n**LLM Reasoning Result:**\n"
                f"- Decision: {rr.get('alert_decision')}\n"
                f"- Severity: {rr.get('severity')}\n"
                f"- Confidence: {rr.get('confidence')}\n"
                f"- Summary: {rr.get('reasoning_summary','N/A')}"
            )
        return {**state, "final_answer": answer, "results": [d]}

    if intent == "vad_gate_events":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No VAD gate events found.", "results": []}
        lines = [
            f"- Event **#{r.get('id')}** [{r.get('gate_name')}]: "
            f"severity={r.get('severity')}, type={r.get('event_type')}, "
            f"camera={r.get('camera_name','N/A')}, start={r.get('start_ts')}, "
            f"peak_score={r.get('peak_score','N/A')}"
            for r in rows
        ]
        answer = f"VAD gate events ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_reasoning_jobs":
        rows = data if isinstance(data, list) else []
        if not rows:
            sf = result.get("status_filter", "")
            label = f" with status '{sf}'" if sf else ""
            return {**state, "final_answer": f"No reasoning jobs found{label}.", "results": []}
        from collections import Counter
        counts = Counter(r.get("status", "unknown") for r in rows)
        count_str = ", ".join(f"{v} {k}" for k, v in counts.items())
        lines = [
            f"- Job **#{r.get('id')}** (case {r.get('case_id')}): "
            f"status={r.get('status')}, "
            f"model={r.get('vlm_model') or r.get('llm_model','N/A')}, "
            f"queued={r.get('queued_at','N/A')}"
            for r in rows
        ]
        answer = f"Reasoning jobs ({len(rows)} total — {count_str}):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_reasoning_results":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No reasoning results found.", "results": []}
        lines = [
            f"- Result **#{r.get('id')}** (case {r.get('case_id')}): "
            f"decision={r.get('alert_decision')}, severity={r.get('severity')}, "
            f"confidence={r.get('confidence')}, type={r.get('event_type','N/A')}"
            for r in rows
        ]
        answer = f"Reasoning results ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_case_reviews":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No case reviews found.", "results": []}
        confirmed = sum(1 for r in rows if r.get("decision") == "confirmed")
        dismissed = sum(1 for r in rows if r.get("decision") == "dismissed")
        uncertain = sum(1 for r in rows if r.get("decision") == "uncertain")
        lines = [
            f"- Review **#{r.get('id')}** (case {r.get('case_id')}): "
            f"decision={r.get('decision')}, reviewer={r.get('reviewer','N/A')}, "
            f"at={r.get('created_at','N/A')}"
            for r in rows
        ]
        answer = (
            f"Case reviews ({len(rows)} total — "
            f"{confirmed} confirmed, {dismissed} dismissed, {uncertain} uncertain):\n\n"
            + "\n".join(lines)
        )
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_case_gate_events":
        rows = data if isinstance(data, list) else []
        cid = result.get("case_id", "?")
        if not rows:
            return {**state, "final_answer": f"No gate events are linked to VAD case #{cid}.", "results": []}
        lines = [
            f"- Gate event **#{r.get('gate_event_id')}** [{r.get('gate_name')}]: "
            f"severity={r.get('severity')}, type={r.get('event_type')}, "
            f"peak_score={r.get('peak_score','N/A')}, threshold={r.get('threshold_value','N/A')}, "
            f"start={r.get('start_ts','N/A')}"
            for r in rows
        ]
        answer = f"Gate events linked to VAD case #{cid} ({len(rows)}):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_case_evidence":
        rows = data if isinstance(data, list) else []
        cid = result.get("case_id", "?")
        if not rows:
            return {**state, "final_answer": f"No evidence items found for VAD case #{cid}.", "results": []}
        lines = [
            f"- Evidence **#{r.get('evidence_item_id')}** [{r.get('evidence_role')} / {r.get('media_type','N/A')}]: "
            f"rank={r.get('evidence_rank')}, included={r.get('included_in_reasoning')}, "
            f"object={r.get('object_key') or r.get('uri') or 'N/A'}"
            for r in rows
        ]
        answer = f"Evidence for VAD case #{cid} ({len(rows)} item(s)):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_gate_scores":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No VAD gate scores found.", "results": []}
        lines = []
        for r in rows[:30]:
            raw = r.get('raw_score')
            thr = r.get('threshold_value')
            ratio = None
            try:
                if raw is not None and thr not in (None, 0):
                    ratio = float(raw) / float(thr)
            except Exception:
                ratio = None
            ratio_text = f", ratio={ratio:.3f}" if ratio is not None else ""
            lines.append(
                f"- Score **#{r.get('score_id')}** [{r.get('gate_name')}]: "
                f"raw={raw}, threshold={thr}{ratio_text}, "
                f"above={r.get('above_threshold')}, persistent={r.get('persistent')}, "
                f"case={r.get('case_id','N/A')}, time={r.get('score_ts','N/A')}"
            )
        answer = f"VAD gate scores ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_streams":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No VAD streams found.", "results": []}
        lines = [
            f"- Stream **{r.get('display_name','N/A')}** (key={r.get('stream_key')}): "
            f"active={r.get('is_active')}, type={r.get('source_type')}, "
            f"fps={r.get('target_sample_fps')}, camera={r.get('camera_name','N/A')}"
            for r in rows
        ]
        answer = f"VAD streams ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "vad_stream_sessions":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No stream sessions found.", "results": []}
        lines = [
            f"- Session **#{r.get('id')}**: "
            f"status={r.get('status')}, camera={r.get('camera_name','N/A')}, "
            f"started={r.get('started_at','N/A')}, "
            f"frames={r.get('sampled_frame_count',0)}"
            for r in rows
        ]
        answer = f"Stream sessions ({len(rows)} shown):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    # ── System / admin ───────────────────────────────────────────────────────
    if intent == "cameras":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No cameras registered.", "results": []}
        lines = [f"- **{r.get('name','N/A')}**: location={r.get('location','N/A')}" for r in rows]
        answer = f"Cameras ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "edge_devices":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No edge devices registered.", "results": []}
        lines = [
            f"- **{r.get('name','N/A')}** (key={r.get('device_key','N/A')}): "
            f"location={r.get('location','N/A')}, registered={r.get('created_at','N/A')}"
            for r in rows
        ]
        answer = f"Edge devices ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "anomaly_rules":
        rows = data if isinstance(data, list) else []
        q_lower = question.lower()
        if not rows:
            return {**state, "final_answer": "No anomaly rules found.", "results": []}
        if re.search(r"\bhow\s+many\b|\bcount\b", q_lower):
            label = "trigger" if "trigger" in q_lower else "suppress" if "suppress" in q_lower else "total"
            return {**state, "final_answer": f"There are **{len(rows)}** {label} anomaly rule(s).", "results": rows}
        if len(rows) == 1:
            r = rows[0]
            answer = (
                f"Anomaly Rule **#{r.get('id')}** [{r.get('rule_type')} | {r.get('event_type','N/A')} | {r.get('source','N/A')}]:\n\n"
                f"{r.get('rule_text','(no text)')}"
            )
            return {**state, "final_answer": answer, "results": rows}
        triggers   = [r for r in rows if r.get("rule_type") == "trigger"]
        suppresses = [r for r in rows if r.get("rule_type") == "suppress"]
        lines = [
            f"- Rule **#{r.get('id')}** [{r.get('rule_type')} | {r.get('event_type','N/A')}]: "
            f"{str(r.get('rule_text',''))[:100]}"
            for r in rows
        ]
        answer = (
            f"Anomaly rules ({len(rows)} total — "
            f"{len(triggers)} trigger, {len(suppresses)} suppress):\n\n"
            + "\n".join(lines)
        )
        return {**state, "final_answer": answer, "results": rows}

    if intent == "reasoning_rules":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No reasoning rules found.", "results": []}
        lines = [
            f"- Rule **#{r.get('id')}** [{r.get('rule_type')}]: "
            f"{r.get('rule_name','N/A')} (priority={r.get('priority',0)}, active={r.get('active')})"
            for r in rows
        ]
        answer = f"VAD reasoning rules ({len(rows)} total):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "rule_conflicts":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No rule conflicts recorded.", "results": []}
        pending = [r for r in rows if r.get("status") == "pending"]
        lines = [
            f"- Conflict **#{r.get('id')}**: rule {r.get('rule_id_1')} vs rule {r.get('rule_id_2')}, "
            f"status={r.get('status')}, reason={str(r.get('conflict_reason','N/A'))[:80]}"
            for r in rows
        ]
        answer = f"Rule conflicts ({len(rows)} total, {len(pending)} pending):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "schedules":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No access schedules found.", "results": []}
        lines = [
            f"- **{r.get('name','N/A')}**: "
            f"{r.get('access_start_time','?')} → {r.get('access_end_time','?')}, "
            f"weekdays={r.get('applies_to_weekdays')}, weekends={r.get('applies_to_weekends')}"
            for r in rows
        ]
        answer = f"Access schedules ({len(rows)}):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "audit_logs":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No audit logs found.", "results": []}
        lines = [
            f"- {r.get('created_at','N/A')}: [{r.get('user_email','N/A')}] "
            f"{r.get('action','N/A')} on {r.get('resource','N/A')} #{r.get('resource_id','N/A')}"
            for r in rows
        ]
        answer = f"Audit logs ({len(rows)} entries):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    # ── Meta ────────────────────────────────────────────────────────────────
    if intent == "table_counts":
        rows = data if isinstance(data, list) else []
        q_lower = question.lower()
        if not rows:
            return {**state, "final_answer": "No table data found.", "results": []}
        counts = {r["table_name"]: r["record_count"] for r in rows}
        _TABLE_KW = {
            "camera": "cameras",
            "employee": "employees", "visitor": "visitors",
            "entry log": "entry_logs", "unknown face": "unknown_face_events",
            "anomaly rule": "anomaly_rules", "schedule": "schedules",
            "audit log": "audit_logs", "activity log": "audit_logs",
            "vad case": "vad_anomaly_cases", "reasoning job": "vad_reasoning_jobs",
        }
        matched = next((tname for kw, tname in _TABLE_KW.items() if kw in q_lower), None)
        if matched:
            count = counts.get(matched, "N/A")
            answer = f"There are **{count}** record(s) in the `{matched}` table."
        elif "most" in q_lower or "largest" in q_lower:
            top = rows[0]
            answer = f"The largest table is **{top['table_name']}** with {top['record_count']:,} records."
        elif "empty" in q_lower:
            empty = [r for r in rows if r["record_count"] == 0]
            answer = ("No empty tables." if not empty else
                      f"Empty tables ({len(empty)}):\n\n" + "\n".join(f"- {r['table_name']}" for r in empty))
        else:
            lines = [f"- {r['table_name']}: {r['record_count']:,}" for r in rows]
            answer = f"Record counts ({len(rows)} tables):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    if intent == "daily_summary":
        d = data if isinstance(data, dict) else {}
        answer = (
            f"### 🛡️ Daily Security Summary ({d.get('date', 'today')})\n\n"
            f"- **Total Detections:** {d.get('total_detections', 0)}\n"
            f"- **Known Detections:** {d.get('known_detections', 0)}\n"
            f"- **Unknown Faces:** {d.get('unknown_detections', 0)}\n"
            f"- **Average Quality Score:** {d.get('avg_quality', 0.0):.3f}\n"
            f"- **VAD Cases:** {d.get('vad_cases_today', 0)} "
            f"({d.get('vad_confirmed', 0)} confirmed)\n"
            f"- **Reasoning Jobs:** {d.get('reasoning_jobs', 0)} "
            f"({d.get('reasoning_failed', 0)} failed)"
        )
        return {**state, "final_answer": answer, "results": [d]}

    if intent == "camera_activity":
        rows = data if isinstance(data, list) else []
        if not rows:
            return {**state, "final_answer": "No camera activity found.", "results": []}
        lines = [
            f"- **{r.get('camera_name','N/A')}** ({r.get('location','N/A')}): "
            f"{r.get('detections',0)} detection(s), "
            f"first={r.get('first_seen','N/A')}, last={r.get('last_seen','N/A')}"
            for r in rows
        ]
        answer = f"Camera activity ({len(rows)} camera(s)):\n\n" + "\n".join(lines)
        return {**state, "final_answer": answer, "results": rows}

    # ── Generic LLM fallback for any unhandled tool ──────────────────────────
    prompt = f"""You are a surveillance security assistant. Answer naturally and concisely.
Base your answer ONLY on the data below. Do not invent facts.

USER QUESTION: {question}
TOOL RESULT:
{_safe_json(_strip_embeddings(result))}

ANSWER:"""
    answer = _llm_instance().generate(prompt, temperature=0.2)
    return {**state, "final_answer": answer, "results": _flatten(result)}


# ─────────────────────────────────────────────────────────────────────────────
# Routing functions
# ─────────────────────────────────────────────────────────────────────────────

def _after_validate_params(state: SQLState) -> str:
    if state.get("needs_clarification"):
        return "clarification"
    route = state.get("route", "sql")
    if route == "small_talk":
        return "small_talk"
    if route == "vector":
        return "vector"
    if route == "tool":
        return "tool"
    return "sql"


def _after_safety(state: SQLState) -> str:
    return "safe" if state.get("sql_safe", False) else "blocked"


def _after_validate_sql(state: SQLState) -> str:
    return "execute" if state.get("sql_valid", False) else "retry"


def _should_retry(state: SQLState) -> str:
    if state.get("sql_valid", False):
        return "format"
    if state.get("retry_count", 0) < 2:
        return "retry"
    return "give_up"


# ─────────────────────────────────────────────────────────────────────────────
# Graph assembly
# ─────────────────────────────────────────────────────────────────────────────

def _build_workflow():
    wf = StateGraph(SQLState)

    wf.add_node("normalize",         normalize_question)
    wf.add_node("route_intent",      route_intent)
    wf.add_node("validate_params",   validate_intent_params)
    wf.add_node("ask_clarification", ask_clarification)
    wf.add_node("small_talk",        handle_small_talk)
    wf.add_node("run_tool",          run_tool)
    wf.add_node("run_vector_tool",   run_vector_tool)
    wf.add_node("format_tool",       format_tool_result)
    wf.add_node("load_schema",       load_schema)
    wf.add_node("generate_sql",      generate_sql)
    wf.add_node("safety_check",      check_sql_safety)
    wf.add_node("reject_write",      reject_write_sql)
    wf.add_node("validate_sql",      validate_sql_query)
    wf.add_node("execute",           execute_query)
    wf.add_node("format_sql",        format_sql_response)
    wf.add_node("give_up",           give_up_sql)

    wf.set_entry_point("normalize")
    wf.add_edge("normalize",    "route_intent")
    wf.add_edge("route_intent", "validate_params")

    wf.add_conditional_edges(
        "validate_params", _after_validate_params,
        {
            "clarification": "ask_clarification",
            "small_talk":    "small_talk",
            "tool":          "run_tool",
            "vector":        "run_vector_tool",
            "sql":           "load_schema",
        },
    )

    wf.add_edge("ask_clarification", END)
    wf.add_edge("small_talk",        END)
    wf.add_edge("run_tool",          "format_tool")
    wf.add_edge("run_vector_tool",   "format_tool")
    wf.add_edge("format_tool",       END)

    wf.add_edge("load_schema",  "generate_sql")
    wf.add_edge("generate_sql", "safety_check")

    wf.add_conditional_edges("safety_check", _after_safety,
                              {"safe": "validate_sql", "blocked": "reject_write"})
    wf.add_edge("reject_write", END)

    wf.add_conditional_edges("validate_sql", _after_validate_sql,
                              {"execute": "execute", "retry": "generate_sql"})
    wf.add_conditional_edges("execute", _should_retry,
                              {"format": "format_sql", "retry": "generate_sql", "give_up": "give_up"})
    wf.add_edge("format_sql", END)
    wf.add_edge("give_up",    END)

    return wf.compile()


def _get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = _build_workflow()
    return _workflow


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def process_question(question: str, history: list | None = None) -> dict:
    initial_state: SQLState = {
        "question":    question,
        "history":     history or [],
        "retry_count": 0,
    }
    try:
        final = _get_workflow().invoke(initial_state, config={"recursion_limit": 20})

        tool_result = final.get("tool_result") or {}
        tool_failed = bool(tool_result) and tool_result.get("found") is False
        sql_failed = (
            final.get("route") == "sql"
            and final.get("error_message")
            and not final.get("sql_valid", True)
        )
        blocked = bool(final.get("_write_blocked")) or final.get("sql_safe") is False
        needs_clarification = bool(final.get("needs_clarification"))

        success = not (tool_failed or sql_failed or blocked)
        # Clarifications are successful interactions, not backend failures.
        if needs_clarification:
            success = True

        err = None
        if tool_failed:
            err = tool_result.get("message") or tool_result.get("error")
        elif sql_failed:
            err = final.get("error_message")
        elif blocked:
            err = final.get("safety_reason") or "Request was blocked in read-only mode."

        return {
            "success":  success,
            "question": question,
            "sql":      final.get("sql", ""),
            "results":  final.get("results", []),
            "answer":   final.get("final_answer", "No answer generated"),
            "error":    err,
        }
    except Exception as e:
        return {
            "success":  False,
            "question": question,
            "sql":      "",
            "results":  [],
            "answer":   "The investigation workflow encountered an error.",
            "error":    str(e),
        }
