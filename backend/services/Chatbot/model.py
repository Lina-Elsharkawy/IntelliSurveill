"""
Ollama LLM wrapper
"""
import ollama
from config import OLLAMA_HOST, LLM_MODEL
from pydantic import BaseModel
from typing import List, Any, Dict, TypedDict

class OllamaLLM:
    """Wrapper for Ollama API"""
    
    def __init__(self, model: str = LLM_MODEL, host: str = OLLAMA_HOST):
        self.model = model
        self.client = ollama.Client(host=host)
    
    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        """
        Generate text using Ollama
        
        Args:
            prompt: Input prompt
            temperature: 0.0 = deterministic, 1.0 = creative
        
        Returns:
            Generated text
        """
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
                options={
                    "temperature": temperature,
                    "num_predict": 150,   # was 500 — SQL is short, don't generate more
                    "num_ctx": 1536,    
                }
            )
            
            content = response.get("message", {}).get("content", "")
            return content.strip()
        
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")
    
    def test_connection(self) -> bool:
        """Test if Ollama is accessible"""
        try:
            self.client.list()
            return True
        except Exception as e:
            print(f"Ollama connection failed: {e}")
            return False
            
# State definition
class SQLState(TypedDict):
    """State for SQL generation workflow"""
    question: str           # User's natural language question
    schema: str            # Database schema
    sql: str               # Generated SQL query
    sql_valid: bool        # Whether SQL passed validation
    error_message: str     # Error message if SQL failed
    results: list          # Query results
    final_answer: str      # Natural language response
    retry_count: int       # Number of retry attempts

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    success: bool
    question: str
    sql: str
    results: List[Dict[str, Any]]
    answer: str
    error: str | None = None