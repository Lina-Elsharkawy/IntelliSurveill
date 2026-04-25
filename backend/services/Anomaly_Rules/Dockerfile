FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db.py .
COPY llm_service.py .
COPY rules_engine.py .
COPY model.py .
COPY app.py .
COPY config.py .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]