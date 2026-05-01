"""
Ollama LLM wrapper + Pydantic models
"""
import ollama
from config import OLLAMA_HOST, LLM_MODEL
from pydantic import BaseModel
from typing import List, Any, Dict, Optional, TypedDict


class OllamaLLM:
    def __init__(self, model: str = LLM_MODEL, host: str = OLLAMA_HOST):
        self.model = model
        self.host = host

    def _client(self):
        return ollama.Client(host=self.host)

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        try:
            response = self._client().chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={"temperature": temperature, "num_predict": 400, "num_ctx": 4096}
            )
            return response.get("message", {}).get("content", "").strip()
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")

    def test_connection(self) -> bool:
        try:
            self._client().list()
            return True
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            return False


class SQLState(TypedDict, total=False):
    question: str
    history: list
    schema: str
    sql: str
    sql_valid: bool
    error_message: str
    results: list
    final_answer: str
    retry_count: int
    intent: dict         # set by route_intent node
    tool_result: dict    # set by run_tool node


class ChatMessage(BaseModel):
    role: str            # "user" or "assistant"
    content: str         # the message text
    sql: Optional[str] = None


class QueryRequest(BaseModel):
    question: str
    history: Optional[List[ChatMessage]] = []


class QueryResponse(BaseModel):
    success: bool
    question: str
    sql: str
    results: List[Dict[str, Any]]
    answer: str
    error: str | None = None