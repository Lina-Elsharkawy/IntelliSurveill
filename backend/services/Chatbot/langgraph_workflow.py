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
from datetime import date
from typing import Any

from langgraph.graph import StateGraph, END

from model import OllamaLLM, SQLState
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql, safety_gate
from prompts import get_sql_generation_prompt, get_error_correction_prompt, get_result_formatting_prompt
from intent_router import route
from capabilities import required_params, tool_type
from tools import (
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
)

_llm = None
_workflow = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = OllamaLLM()
    return _llm


TOOL_MAP = {
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


# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────

def normalize_question(state: SQLState) -> SQLState:
    q = (state.get("question") or "").strip()
    return {**state, "question": q, "retry_count": state.get("retry_count", 0)}


def route_intent(state: SQLState) -> SQLState:
    decision = route(state["question"], history=state.get("history", []))
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
    q = state["question"].lower()
    if any(p in q for p in ["hello", "hi", "hey", "hiya", "howdy"]):
        answer = "👋 Hello! I’m the AI-Edge surveillance investigation assistant. Ask me about detections, unknown faces, anomalies, cameras, or security summaries."
    elif "how are you" in q:
        answer = "I’m operational and ready to investigate the surveillance data. 🟢"
    elif any(p in q for p in ["thank", "thanks"]):
        answer = "You’re welcome!"
    elif any(p in q for p in ["what can you do", "help"]):
        answer = (
            "I can help with surveillance investigations, for example:\n"
            "• Where was Maged last seen?\n"
            "• Show latest unknown face events from the past week.\n"
            "• Did unknown face event 274 appear before?\n"
            "• Who is the closest known match to unknown event 274?\n"
            "• Were there anomalies near Maged?\n"
            "• Give me today’s security summary."
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
    if tool == "table_record_counts":
        rows = data if isinstance(data, list) else []
        empty = [r for r in rows if r.get("record_count") == 0]
        top = rows[0] if rows else None
        q = question.lower()
        if "empty" in q:
            answer = "There are no empty tables in the database." if not empty else (
                f"There are {len(empty)} empty tables:\n\n" + "\n".join(f"- {r['table_name']}" for r in empty)
            )
        elif "most records" in q or "largest" in q:
            answer = "I could not find any tables." if not top else (
                f"The table with the most records is {top['table_name']}, with {top['record_count']} records."
            )
        else:
            answer = "Here are the record counts:\n\n" + "\n".join(
                f"- {r['table_name']}: {r['record_count']} records" for r in rows
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
        # Let the LLM polish the composite report, but only from structured data.
        prompt = f"""You are a surveillance investigation assistant.
Answer the user based only on this structured investigation result.
Do not invent facts. Mention clearly if vector matching is unavailable or returned no matches.

USER QUESTION:
{question}

STRUCTURED RESULT:
{_safe_json(result)}

Write a concise investigation report with sections: Event, Similar unknown faces, Possible identity matches, Nearby anomalies, Conclusion.
"""
        answer = get_llm().generate(prompt, temperature=0.2)
        return {**state, "final_answer": answer, "results": [data] if isinstance(data, dict) else _flatten_results(result)}

    # Generic fallback for other successful tools: LLM summary over structured data.
    prompt = f"""You are a surveillance security assistant. Answer naturally and concisely.
Base your answer ONLY on the structured data below.

USER QUESTION: {question}
TOOL RESULT:
{_safe_json(result)}

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
