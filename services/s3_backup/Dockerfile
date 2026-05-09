FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ────────────────────────────────────────────────
FROM python:3.11-slim

# Non-root user (ignore if already exists)
RUN groupadd -r backup 2>/dev/null || true && \
    useradd -r -g backup -d /app backup 2>/dev/null || true

WORKDIR /app

# Copy installed deps
COPY --from=builder /install /usr/local

# Copy source
COPY *.py ./

# State volume
RUN mkdir -p /data && chown backup:backup /data
VOLUME /data

USER backup

EXPOSE 8020

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8020/health')" || exit 1

CMD ["python", "api.py"]