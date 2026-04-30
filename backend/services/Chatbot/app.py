"""
FastAPI application for NL-to-SQL + Investigation chatbot
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph_workflow import process_question
from db import test_connection, get_database_schema
from model import OllamaLLM, QueryRequest, QueryResponse
from config import API_HOST, API_PORT

app = FastAPI(
    title="Surveillance Chatbot",
    description="Natural Language investigation + SQL Query API",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "running", "service": "Surveillance Chatbot", "version": "2.1.0"}


@app.get("/health")
def health_check():
    db_ok = test_connection()
    llm = OllamaLLM()
    ollama_ok = llm.test_connection()
    return {
        "database": "connected" if db_ok else "disconnected",
        "ollama": "connected" if ollama_ok else "disconnected",
        "status": "healthy" if (db_ok and ollama_ok) else "degraded"
    }


@app.get("/schema")
def get_schema():
    try:
        return {"schema": get_database_schema()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query", response_model=QueryResponse)
def query_database(request: QueryRequest):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Convert ChatMessage objects to plain dicts for the workflow
    history = [
        {"role": m.role, "content": m.content, "sql": m.sql}
        for m in (request.history or [])
    ]

    try:
        result = process_question(request.question, history=history)
        return QueryResponse(**result)
    except Exception as e:
        return QueryResponse(
            success=False,
            question=request.question,
            sql="",
            results=[],
            answer="I could not answer that question. Please try rephrasing it.",
            error=str(e)
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=API_HOST, port=API_PORT, reload=True)