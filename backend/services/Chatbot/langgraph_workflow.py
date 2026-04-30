"""
LangGraph workflow for NL-to-SQL + Investigation Tools

Graph structure:
  route_intent → [tool path] → run_tool → format_tool_result → END
              → [small talk]  → small_talk → END
              → [sql path]    → load_schema → generate → safety_check
                                              ↑              ↓ (safe)
                                           generate  ←  (unsafe → give_up)
                                                          ↓ (safe)
                                                       validate → execute → format → END
                                                                    ↓ (error)
                                                                 generate (retry ≤2)
"""
from langgraph.graph import StateGraph, END
from model import OllamaLLM, SQLState
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql, safety_gate
from prompts import get_sql_generation_prompt, get_error_correction_prompt, get_result_formatting_prompt
from intent_router import route
from tools import (
    get_person_last_seen,
    get_person_first_seen,
    get_person_timeline,
    get_unknown_faces_today,
    get_unknown_face_events,
    get_repeated_unknowns,
    get_anomalies_near_face,
    get_people_seen_today,
    get_table_record_counts,
)

# ── Lazy singletons ──────────────────────────────────────────────────────────
_llm = None
_workflow = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = OllamaLLM()
    return _llm


TOOL_MAP = {
    "last_seen":            get_person_last_seen,
    "first_seen":           get_person_first_seen,
    "timeline":             get_person_timeline,
    "unknown_faces":        get_unknown_faces_today,
    "unknown_face_events":  get_unknown_face_events,
    "repeated_unknowns":    get_repeated_unknowns,
    "anomalies_near_face":  get_anomalies_near_face,
    "people_seen_today":    get_people_seen_today,
    "table_record_counts":  get_table_record_counts,
}

# ── Small-talk detector ──────────────────────────────────────────────────────
import re as _re

_SMALL_TALK_PATTERNS = [
    r'\b(hello|hi|hey|hiya|howdy)\b',
    r'\bhow are you\b',
    r"\bwhat('s| is) your name\b",
    r'\bwho are you\b',
    r'\bthank(s| you)\b',
    r'\bgood (morning|afternoon|evening|night)\b',
    r'\bwhat can you do\b',
    r'\bhelp\b',
]
_SMALL_TALK_RE = [_re.compile(p, _re.IGNORECASE) for p in _SMALL_TALK_PATTERNS]


def _is_small_talk(question: str) -> bool:
    return any(p.search(question) for p in _SMALL_TALK_RE)


# ── Nodes ────────────────────────────────────────────────────────────────────

def route_intent(state: SQLState) -> SQLState:
    """Decide: small-talk, tool path, or SQL path."""
    q = state["question"]
    if _is_small_talk(q):
        return {**state, "intent": {"path": "small_talk"}}
    decision = route(q)
    return {**state, "intent": decision}


def handle_small_talk(state: SQLState) -> SQLState:
    """Reply to greetings / off-topic questions without touching the DB."""
    q = state["question"].lower()
    if any(p in q for p in ["hello", "hi", "hey", "hiya", "howdy"]):
        answer = ("👋 Hello! I'm the AI-Edge surveillance chatbot. "
                  "Ask me anything about the system — detections, anomalies, cameras, people, and more!")
    elif "how are you" in q:
        answer = "I'm operational and ready to help! 🟢 Ask me anything about the surveillance data."
    elif any(p in q for p in ["thank", "thanks"]):
        answer = "You're welcome! Let me know if you need anything else. 😊"
    elif any(p in q for p in ["what can you do", "help"]):
        answer = (
            "I can help you query the surveillance database! For example:\n"
            "• *When was Lina last detected?*\n"
            "• *How many unknown faces were seen today?*\n"
            "• *Show anomalies in the last 7 days*\n"
            "• *Who entered the Robotics Lab yesterday?*\n"
            "• *How many times was Maged logged in entry_logs?*"
        )
    else:
        answer = ("I'm the AI-Edge surveillance chatbot. Ask me about detections, "
                  "anomalies, people, cameras, or any system data!")
    return {**state, "final_answer": answer, "sql": "", "results": []}


def load_schema(state: SQLState) -> SQLState:
    schema = get_database_schema()
    return {**state, "schema": schema}


def run_tool(state: SQLState) -> SQLState:
    """Execute the matched investigation tool directly — no LLM SQL needed."""
    intent = state.get("intent", {})
    tool_name = intent.get("tool")
    params = intent.get("params", {})

    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {**state, "tool_result": {"found": False, "message": "Unknown tool."}}

    result = fn(**params)
    return {**state, "tool_result": result}


def format_tool_result(state: SQLState) -> SQLState:
    """Turn tool result dict into a natural language answer."""
    result = state.get("tool_result", {})
    question = state["question"]

    if not result.get("found"):
        answer = result.get("message") or result.get("error") or "No results found."
        return {**state, "final_answer": answer, "sql": "", "results": []}

    tool = result.get("tool", "")
    data = result.get("data", [])

    # ─────────────────────────────────────────────────────────────
    # Deterministic formatter: table record counts
    # Do NOT send this to the LLM because it may hallucinate
    # ─────────────────────────────────────────────────────────────
    if tool == "table_record_counts":
        q = question.lower()

        empty_tables = [r for r in data if r["record_count"] == 0]
        top_table = data[0] if data else None

        if "empty" in q:
            if not empty_tables:
                answer = "There are no empty tables in the database."
            else:
                names = "\n".join(
                    f"- {r['table_name']}" for r in empty_tables
                )
                answer = (
                    f"There are {len(empty_tables)} empty tables:\n\n"
                    f"{names}"
                )

            return {
                **state,
                "final_answer": answer,
                "sql": "[Tool: table_record_counts]",
                "results": data
            }

        if "most records" in q or "largest" in q:
            if not top_table:
                answer = "I could not find any tables."
            else:
                answer = (
                    f"The table with the most records is "
                    f"{top_table['table_name']}, with "
                    f"{top_table['record_count']} records."
                )

            return {
                **state,
                "final_answer": answer,
                "sql": "[Tool: table_record_counts]",
                "results": data
            }

        lines = [
            f"- {r['table_name']}: {r['record_count']} records"
            for r in data
        ]

        answer = (
            f"Here are the record counts for all {len(data)} public tables:\n\n"
            + "\n".join(lines)
        )

        if empty_tables:
            answer += (
                "\n\nEmpty tables: "
                + ", ".join(r["table_name"] for r in empty_tables)
            )

        return {
            **state,
            "final_answer": answer,
            "sql": "[Tool: table_record_counts]",
            "results": data
        }

    # ─────────────────────────────────────────────────────────────
    # Deterministic formatter: real unknown_face_events table
    # ─────────────────────────────────────────────────────────────
    if tool == "unknown_face_events":
        if not data:
            if result.get("days_back"):
                answer = (
                    f"No unknown face events were found in the last "
                    f"{result.get('days_back')} days."
                )
            else:
                answer = "No unknown face events were found."

            return {
                **state,
                "final_answer": answer,
                "sql": "[Tool: unknown_face_events]",
                "results": []
            }

        lines = []
        for r in data:
            event_id = r.get("id", "N/A")
            created_at = r.get("created_at", "N/A")
            status = r.get("status", "N/A")
            assigned = r.get("assigned_detected_id")
            quality = r.get("quality_score", "N/A")
            best_sim = r.get("best_similarity_score", "N/A")

            review_state = (
                "unreviewed"
                if assigned is None
                else f"assigned to detected_id={assigned}"
            )

            lines.append(
                f"- Event {event_id}: {created_at}, status={status}, "
                f"{review_state}, quality={quality}, best_similarity={best_sim}"
            )

        if result.get("days_back"):
            heading = (
                f"Latest {len(data)} unknown face events from the last "
                f"{result.get('days_back')} days:"
            )
        else:
            heading = f"Latest {len(data)} unknown face events:"

        answer = heading + "\n\n" + "\n".join(lines)

        return {
            **state,
            "final_answer": answer,
            "sql": "[Tool: unknown_face_events]",
            "results": data
        }

    # ─────────────────────────────────────────────────────────────
    # Existing tool formatters that can still use the LLM
    # ─────────────────────────────────────────────────────────────
    if tool in ("last_seen", "first_seen"):
        d = data
        label = "Last seen" if tool == "last_seen" else "First detected"
        summary = (
            f"Person: {d.get('person_name')}\n"
            f"{label} at: {d.get('camera_name')} ({d.get('camera_location')})\n"
            f"Time: {d.get('timestamp')}\n"
            f"Evidence: {d.get('evidence_url') or 'N/A'}"
        )

    elif tool == "timeline":
        lines = [
            f"  {r['timestamp']} — {r['camera_name']} ({r['camera_location']})"
            for r in data
        ]
        summary = (
            f"Timeline for {data[0]['person_name'] if data else 'person'} "
            f"on {result.get('date')} ({result.get('count')} detections):\n"
            + "\n".join(lines)
        )

    elif tool == "unknown_faces":
        lines = [
            f"  {r['timestamp']} — {r['camera_name']} ({r['camera_location']})"
            for r in data[:50]
        ]
        summary = (
            f"Unknown faces on {result.get('date')}: {result.get('count')} total.\n"
            + "\n".join(lines)
        )

    elif tool == "repeated_unknowns":
        lines = [
            f"  {r['camera_name']} on {r['day']}: {r['appearances']} appearances "
            f"({r['first_seen']} → {r['last_seen']})"
            for r in data
        ]
        summary = (
            f"Repeated unknown visitors in last {result.get('days_back')} days:\n"
            + "\n".join(lines)
        )

    elif tool == "anomalies_near_face":
        if not data:
            summary = (
                f"No anomalies found within {result.get('window_seconds')}s "
                f"of {result.get('reference_time')}."
            )
        else:
            lines = [
                f"  {r['event_type']} at {r['camera_name']} — {r['detected_at']} "
                f"({r['seconds_apart']:.0f}s apart, severity: {r['severity']})"
                for r in data
            ]
            summary = (
                f"{result.get('count')} anomalies near the reference time "
                f"({result.get('reference_time')}):\n"
                + "\n".join(lines)
            )

    elif tool == "people_seen_today":
        lines = [
            f"  {r['person_name']} ({r['person_type']}): {r['detections']} detections, "
            f"first at {r['first_seen']}, last at {r['last_seen']}, cameras: {r['cameras_seen']}"
            for r in data
        ]
        summary = (
            f"People seen on {result.get('date')} ({result.get('count')} people):\n"
            + "\n".join(lines)
        )

    else:
        summary = str(data[:10])

    prompt = f"""You are a surveillance security assistant. Answer the user's question naturally and concisely.

USER QUESTION: {question}

INVESTIGATION RESULT:
{summary}

Give a clear, conversational answer based ONLY on the data above.
Do not make up any information. If the data is empty, say so clearly.
ANSWER:"""

    answer = get_llm().generate(prompt, temperature=0.2)

    return {
        **state,
        "final_answer": answer,
        "sql": f"[Tool: {tool}]",
        "results": data if isinstance(data, list) else [data]
    }


def generate_sql(state: SQLState) -> SQLState:
    retry = state.get("retry_count", 0)
    if retry == 0:
        prompt = get_sql_generation_prompt(
            state["question"],
            state["schema"],
            history=state.get("history", [])
        )
    else:
        prompt = get_error_correction_prompt(
            state["question"], state["sql"], state["error_message"], state["schema"]
        )
    raw_sql = get_llm().generate(prompt, temperature=0.0)
    cleaned_sql = sanitize_sql(raw_sql)
    return {**state, "sql": cleaned_sql}


def check_sql_safety(state: SQLState) -> SQLState:
    """
    Post-generation safety gate.
    If the LLM produced a write query despite the read-only prompt, block it here
    instead of crashing or hitting the DB.
    """
    is_safe, reason = safety_gate(state["sql"])
    return {**state, "sql_safe": is_safe, "safety_reason": reason}


def validate_sql_query(state: SQLState) -> SQLState:
    is_valid, error_msg = validate_sql(state["sql"])

    if is_valid:
        return {
            **state,
            "sql_valid": True,
            "error_message": ""
        }

    return {
        **state,
        "sql_valid": False,
        "error_message": error_msg,
        "retry_count": state.get("retry_count", 0) + 1
    }

def execute_query(state: SQLState) -> SQLState:
    result = execute_sql_safely(state["sql"])
    if result["success"]:
        return {**state, "results": result["data"], "sql_valid": True}
    return {
        **state,
        "sql_valid": False,
        "error_message": result["error"],
        "retry_count": state.get("retry_count", 0) + 1
    }


def format_sql_response(state: SQLState) -> SQLState:
    results = state.get("results", [])
    if not results:
        return {**state, "final_answer": "I searched the database but found no matching records for your question."}
    prompt = get_result_formatting_prompt(state["question"], state["sql"], results)
    answer = get_llm().generate(prompt, temperature=0.3)
    return {**state, "final_answer": answer}


def reject_write_sql(state: SQLState) -> SQLState:
    """Called when safety_gate rejects the generated SQL."""
    reason = state.get("safety_reason", "")
    answer = (
        "⛔ This chatbot is **read-only** — it can only query data, not modify it. "
        "Your question seems to require a write operation which I cannot perform.\n\n"
        f"_Technical reason: {reason}_"
    )
    return {**state, "final_answer": answer, "results": []}
def give_up_sql(state: SQLState) -> SQLState:
    """
    Final fallback when SQL generation/execution failed after retries.
    Always returns a useful answer instead of 'No answer generated'.
    """
    answer = (
        "I could not answer this because the generated SQL failed after retrying.\n\n"
        f"Last SQL attempted:\n{state.get('sql', '')}\n\n"
        f"Error:\n{state.get('error_message', 'Unknown error')}"
    )
    return {
        **state,
        "final_answer": answer,
        "results": state.get("results", [])
    }

# ── Routing functions ────────────────────────────────────────────────────────

def after_route(state: SQLState) -> str:
    path = state.get("intent", {}).get("path")
    if path == "tool":
        return "tool"
    if path == "small_talk":
        return "small_talk"
    return "sql"


def after_safety_check(state: SQLState) -> str:
    return "safe" if state.get("sql_safe", False) else "blocked"


def after_validate(state: SQLState) -> str:
    return "execute" if state.get("sql_valid", False) else "retry"


def should_retry(state: SQLState) -> str:
    if state.get("sql_valid", False):
        return "format"
    elif state.get("retry_count", 0) < 2:
        return "retry"
    return "give_up"


# ── Graph ────────────────────────────────────────────────────────────────────

def create_workflow():
    wf = StateGraph(SQLState)

    wf.add_node("route_intent",       route_intent)
    wf.add_node("small_talk",         handle_small_talk)
    wf.add_node("load_schema",        load_schema)
    wf.add_node("run_tool",           run_tool)
    wf.add_node("format_tool_result", format_tool_result)
    wf.add_node("generate",           generate_sql)
    wf.add_node("safety_check",       check_sql_safety)
    wf.add_node("reject_write",       reject_write_sql)
    wf.add_node("validate",           validate_sql_query)
    wf.add_node("execute",            execute_query)
    wf.add_node("format",             format_sql_response)
    wf.add_node("give_up",            give_up_sql)

    wf.set_entry_point("route_intent")

    # Branch after routing
    wf.add_conditional_edges(
        "route_intent", after_route,
        {"tool": "run_tool", "small_talk": "small_talk", "sql": "load_schema"}
    )

    # Small-talk path
    wf.add_edge("small_talk", END)

    # Tool path
    wf.add_edge("run_tool", "format_tool_result")
    wf.add_edge("format_tool_result", END)

    # SQL path: generate → safety check → (blocked → reject) OR (safe → validate → execute → format)
    wf.add_edge("load_schema", "generate")
    wf.add_edge("generate", "safety_check")
    wf.add_conditional_edges(
        "safety_check", after_safety_check,
        {"safe": "validate", "blocked": "reject_write"}
    )
    wf.add_edge("reject_write", END)
    wf.add_conditional_edges(
        "validate", after_validate,
        {"execute": "execute", "retry": "generate"}
    )
    wf.add_conditional_edges(
        "execute", should_retry,
        {"format": "format", "retry": "generate", "give_up": "give_up"}
    )
    wf.add_edge("give_up", END)
    wf.add_edge("format", END)

    return wf.compile()


def get_workflow():
    global _workflow
    if _workflow is None:
        _workflow = create_workflow()
    return _workflow


def process_question(question: str, history: list = None) -> dict:
    initial_state = {
        "question": question,
        "history": history or [],
        "retry_count": 0,
    }
    try:
        final_state = get_workflow().invoke(
            initial_state,
            config={"recursion_limit": 15}
        )
        return {
            "success": True,
            "question": question,
            "sql": final_state.get("sql", ""),
            "results": final_state.get("results", []),
            "answer": final_state.get("final_answer", "No answer generated"),
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "question": question,
            "sql": "",
            "results": [],
            "answer": "I could not answer that question. Please try rephrasing it.",
            "error": str(e)
        }