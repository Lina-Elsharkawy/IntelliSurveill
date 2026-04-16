FROM python:3.11-slim

WORKDIR /app

COPY backend/services/vector_match/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/services /app/services

CMD ["python", "-m", "uvicorn", "services.vector_match.app:app", "--host", "0.0.0.0", "--port", "8000"]