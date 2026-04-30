"""
LangGraph workflow for NL-to-SQL + Investigation Tools
"""
from langgraph.graph import StateGraph, END
from model import OllamaLLM, SQLState
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql
from prompts import get_sql_generation_prompt, get_error_correction_prompt, get_result_formatting_prompt
from intent_router import route
from tools import (
    get_person_last_seen,
    get_person_timeline,
    get_unknown_faces_today,
    get_repeated_unknowns,
    get_anomalies_near_face,
    get_people_seen_today,
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
    "last_seen":          get_person_last_seen,
    "timeline":           get_person_timeline,
    "unknown_faces":      get_unknown_faces_today,
    "repeated_unknowns":  get_repeated_unknowns,
    "anomalies_near_face": get_anomalies_near_face,
    "people_seen_today":  get_people_seen_today,
}

# ── Nodes ────────────────────────────────────────────────────────────────────

def route_intent(state: SQLState) -> SQLState:
    """Decide: tool path or SQL path."""
    decision = route(state["question"])
    return {**state, "intent": decision}


def load_schema(state: SQLState) -> SQLState:
    schema = get_database_schema()
    return {**state, "schema": schema}


def run_tool(state: SQLState) -> SQLState:
    """Execute the matched investigation tool directly — no LLM needed."""
    intent = state.get("intent", {})
    tool_name = intent.get("tool")
    params = intent.get("params", {})

    fn = TOOL_MAP.get(tool_name)
    if not fn:
        return {**state, "tool_result": {"found": False, "message": "Unknown tool."}}

    result = fn(**params)
    return {**state, "tool_result": result}


def format_tool_result(state: SQLState) -> SQLState:
    """Turn tool result dict into a natural language answer via LLM."""
    result = state.get("tool_result", {})
    question = state["question"]

    if not result.get("found"):
        answer = result.get("message") or result.get("error") or "No results found."
        return {**state, "final_answer": answer, "sql": "", "results": []}

    tool = result.get("tool", "")
    data = result.get("data", [])

    # Build a readable summary for the LLM to narrate
    if tool == "last_seen":
        d = data
        summary = (
            f"Person: {d.get('person_name')}\n"
            f"Last seen at: {d.get('camera_name')} ({d.get('camera_location')})\n"
            f"Time: {d.get('timestamp')}\n"
            f"Evidence: {d.get('evidence_url') or 'N/A'}"
        )
    elif tool == "timeline":
        lines = [f"  {r['timestamp']} — {r['camera_name']} ({r['camera_location']})" for r in data]
        summary = (
            f"Timeline for {data[0]['person_name'] if data else 'person'} "
            f"on {result.get('date')} ({result.get('count')} detections):\n"
            + "\n".join(lines)
        )
    elif tool == "unknown_faces":
        lines = [f"  {r['timestamp']} — {r['camera_name']} ({r['camera_location']})" for r in data[:100]]
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
        summary = f"Repeated unknown visitors in last {result.get('days_back')} days:\n" + "\n".join(lines)
    elif tool == "anomalies_near_face":
        if not data:
            summary = f"No anomalies found within {result.get('window_seconds')}s of {result.get('reference_time')}."
        else:
            lines = [
                f"  {r['event_type']} at {r['camera_name']} — {r['detected_at']} "
                f"({r['seconds_apart']:.0f}s apart, severity: {r['severity']})"
                for r in data
            ]
            summary = (
                f"{result.get('count')} anomalies near the reference time "
                f"({result.get('reference_time')}):\n" + "\n".join(lines)
            )
    elif tool == "people_seen_today":
        lines = [
            f"  {r['person_name']} ({r['person_type']}): {r['detections']} detections, "
            f"first at {r['first_seen']}, last at {r['last_seen']}, cameras: {r['cameras_seen']}"
            for r in data
        ]
        summary = f"People seen on {result.get('date')} ({result.get('count')} people):\n" + "\n".join(lines)
    else:
        summary = str(data[:10])

    prompt = f"""You are a surveillance security assistant. Answer the user's question naturally.

USER QUESTION: {question}

INVESTIGATION RESULT:
{summary}

Give a clear, conversational answer based only on the data above.
Do not make up any information. If the data is empty, say so.
ANSWER:"""

    answer = get_llm().generate(prompt, temperature=0.2)
    return {
        **state,
        "final_answer": answer,
        "sql": f"[Tool: {tool}]",
        "results": data if isinstance(data, list) else [data]
    }


def generate_sql(state: SQLState) -> SQLState:
    if state.get("retry_count", 0) == 0:
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


def validate_sql_query(state: SQLState) -> SQLState:
    is_valid, error_msg = validate_sql(state["sql"])
    return {**state, "sql_valid": is_valid, "error_message": "" if is_valid else error_msg}


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
        return {**state, "final_answer": "No results found."}
    prompt = get_result_formatting_prompt(state["question"], state["sql"], results)
    answer = get_llm().generate(prompt, temperature=0.3)
    return {**state, "final_answer": answer}


# ── Routing functions ────────────────────────────────────────────────────────

def after_route(state: SQLState) -> str:
    """Branch: tool path or sql path."""
    return "tool" if state.get("intent", {}).get("path") == "tool" else "sql"


def should_retry(state: SQLState) -> str:
    if state["sql_valid"]:
        return "format"
    elif state.get("retry_count", 0) < 3:
        return "retry"
    return "give_up"


# ── Graph ────────────────────────────────────────────────────────────────────

def create_workflow():
    wf = StateGraph(SQLState)

    wf.add_node("route_intent",       route_intent)
    wf.add_node("load_schema",        load_schema)
    wf.add_node("run_tool",           run_tool)
    wf.add_node("format_tool_result", format_tool_result)
    wf.add_node("generate",           generate_sql)
    wf.add_node("validate",           validate_sql_query)
    wf.add_node("execute",            execute_query)
    wf.add_node("format",             format_sql_response)

    wf.set_entry_point("route_intent")

    # After routing: branch to tool or sql
    wf.add_conditional_edges(
        "route_intent", after_route,
        {"tool": "run_tool", "sql": "load_schema"}
    )

    # Tool path
    wf.add_edge("run_tool", "format_tool_result")
    wf.add_edge("format_tool_result", END)

    # SQL path
    wf.add_edge("load_schema", "generate")
    wf.add_edge("generate", "validate")
    wf.add_conditional_edges(
        "validate",
        lambda s: "execute" if s["sql_valid"] else "retry",
        {"execute": "execute", "retry": "generate"}
    )
    wf.add_conditional_edges(
        "execute", should_retry,
        {"format": "format", "retry": "generate", "give_up": END}
    )
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
        "retry_count": 0
    }
    try:
        final_state = get_workflow().invoke(initial_state)
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