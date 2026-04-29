"""
LangGraph workflow for NL-to-SQL with error handling
"""
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from model import OllamaLLM, SQLState
from db import get_database_schema, execute_sql_safely
from validators import validate_sql, sanitize_sql
from prompts import (
    get_sql_generation_prompt,
    get_error_correction_prompt,
    get_result_formatting_prompt
)



# Initialize LLM
llm = OllamaLLM()

# Node functions
def load_schema(state: SQLState) -> SQLState:
    """Load database schema"""
    schema = get_database_schema()
    return {**state, "schema": schema}

def generate_sql(state: SQLState) -> SQLState:
    """Generate SQL from natural language"""
    if state.get("retry_count", 0) == 0:
        # First attempt
        prompt = get_sql_generation_prompt(
            state["question"],
            state["schema"]
        )
    else:
        # Retry with error context
        prompt = get_error_correction_prompt(
            state["question"],
            state["sql"],
            state["error_message"],
            state["schema"]
        )
    
    raw_sql = llm.generate(prompt, temperature=0.0)
    cleaned_sql = sanitize_sql(raw_sql)
    
    return {**state, "sql": cleaned_sql}

def validate_sql_query(state: SQLState) -> SQLState:
    """Validate SQL for safety"""
    is_valid, error_msg = validate_sql(state["sql"])
    
    if is_valid:
        return {**state, "sql_valid": True, "error_message": ""}
    else:
        return {
            **state,
            "sql_valid": False,
            "error_message": error_msg
        }

def execute_query(state: SQLState) -> SQLState:
    """Execute SQL query on database"""
    result = execute_sql_safely(state["sql"])
    
    if result["success"]:
        return {
            **state,
            "results": result["data"],
            "sql_valid": True
        }
    else:
        return {
            **state,
            "sql_valid": False,
            "error_message": result["error"],
            "retry_count": state.get("retry_count", 0) + 1
        }

def format_response(state: SQLState) -> SQLState:
    """Format results as natural language"""
    results = state.get("results", [])
    if not results:
        answer = "No results found."
    # elif len(results) > 5:
    #     # Too many results to format efficiently via LLM
    #     answer = f"Found {len(results)} matches. Here is a summary of the first few: {str(results[:2])}..."
    else:
        prompt = get_result_formatting_prompt(
            state["question"],
            state["sql"],
            results
        )
        answer = llm.generate(prompt, temperature=0.3)
    
    return {**state, "final_answer": answer}

# Routing logic
def should_retry(state: SQLState) -> str:
    """Decide whether to retry SQL generation"""
    if state["sql_valid"]:
        return "format"  # Success - format results
    elif state.get("retry_count", 0) < 3:
        return "retry"   # Retry with error context
    else:
        return "give_up" # Too many retries

# Build the graph
def create_workflow() -> StateGraph:
    """Create the LangGraph workflow"""
    workflow = StateGraph(SQLState)
    
    # Add nodes
    workflow.add_node("load_schema", load_schema)
    workflow.add_node("generate", generate_sql)
    workflow.add_node("validate", validate_sql_query)
    workflow.add_node("execute", execute_query)
    workflow.add_node("format", format_response)
    
    # Define flow
    workflow.set_entry_point("load_schema")
    workflow.add_edge("load_schema", "generate")
    workflow.add_edge("generate", "validate")
    
    # Conditional routing after validation
    workflow.add_conditional_edges(
        "validate",
        lambda state: "execute" if state["sql_valid"] else "retry",
        {
            "execute": "execute",
            "retry": "generate"  # Loop back to regenerate
        }
    )
    
    # Conditional routing after execution
    workflow.add_conditional_edges(
        "execute",
        should_retry,
        {
            "format": "format",
            "retry": "generate",
            "give_up": END
        }
    )
    
    workflow.add_edge("format", END)
    
    return workflow.compile()

# Create compiled workflow
nl_to_sql_workflow = create_workflow()

def process_question(question: str) -> dict:
    """
    Main entry point for processing natural language questions
    
    Args:
        question: Natural language question
    
    Returns:
        dict with 'sql', 'results', 'answer', 'success'
    """
    initial_state = {
        "question": question,
        "retry_count": 0
    }
    
    try:
        final_state = nl_to_sql_workflow.invoke(initial_state)
        
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
            "answer": "",
            "error": str(e)
        }