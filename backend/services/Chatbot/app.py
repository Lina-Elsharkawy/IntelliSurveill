"""
FastAPI application for NL-to-SQL chatbot
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
from langgraph_workflow import process_question
from db import test_connection, get_database_schema
from model import OllamaLLM, QueryRequest, QueryResponse
from config import API_HOST, API_PORT
from typing import TypedDict
from validators import is_write_intent

# Initialize FastAPI
app = FastAPI(
    title="NL-to-SQL Chatbot",
    description="Natural Language to SQL Query API using LangGraph and Ollama",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your React app URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response models


# API endpoints
@app.get("/")
def root():
    """Health check"""
    return {
        "status": "running",
        "service": "NL-to-SQL Chatbot",
        "version": "1.0.0"
    }

@app.get("/health")
def health_check():
    """Check system health"""
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
    """Get database schema"""
    try:
        schema = get_database_schema()
        return {"schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query", response_model=QueryResponse)
def query_database(request: QueryRequest):
    """
    Process natural language question and return SQL + results
    
    Example request:
    {
        "question": "Show me the last 5 anomalies"
    }
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if is_write_intent(request.question):
        return QueryResponse(
            success=False,
            question=request.question,
            sql="",
            results=[],
            answer="⛔ This action is not allowed. The chatbot is read-only and cannot delete, update, insert, or modify any data. Please contact your system administrator for data changes.",
            error="Write operation rejected"
        )

    
    try:
        result = process_question(request.question)
        return QueryResponse(**result)
    
    except Exception as e:
        # Catch recursion limit and any other crash — never show raw error
        return QueryResponse(
            success=False,
            question=request.question,
            sql="",
            results=[],
            answer="❌ I could not understand or answer that question. Please try rephrasing it.",
            error=str(e)
        )


# Run the application
if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("🚀 Starting NL-to-SQL Chatbot API")
    print("=" * 60)
    print(f"API: http://{API_HOST}:{API_PORT}")
    print(f"Docs: http://{API_HOST}:{API_PORT}/docs")
    print("=" * 60)
    
    uvicorn.run(
        "app:app",
        host=API_HOST,
        port=API_PORT,
        reload=True
    )