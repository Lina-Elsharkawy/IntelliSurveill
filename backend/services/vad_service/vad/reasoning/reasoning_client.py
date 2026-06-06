from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

log = logging.getLogger("vad.reasoning_client")

# Retry configuration: up to 3 attempts with exponential backoff.
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_SEC = 2.0
_RETRY_BACKOFF_FACTOR = 2.0

# HTTP status codes that are worth retrying (server-side transient errors).
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class OllamaClient:
    """Blocking Ollama /api/generate client with retry + exponential backoff.

    Up to _MAX_RETRIES attempts are made for transient network or server errors.
    A permanent HTTP error (e.g. 400 Bad Request) is raised immediately without
    retrying, since retrying would not help.
    """

    def __init__(self, *, base_url: str, timeout_sec: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = float(timeout_sec)

    def generate(self, *, model: str, prompt: str, images_b64: list[str] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_ctx": 8192,
            },
        }
        if images_b64:
            payload["images"] = images_b64

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        url = f"{self.base_url}/api/generate"

        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    body = resp.read().decode("utf-8", errors="replace")

                try:
                    parsed = json.loads(body)
                except Exception as e:
                    raise RuntimeError(f"Ollama returned non-JSON response: {body[:500]}") from e

                if "error" in parsed:
                    raise RuntimeError(str(parsed["error"]))

                return str(parsed.get("response", "")).strip()

            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
                exc = RuntimeError(f"Ollama HTTP {e.code}: {err_body}")
                if e.code not in _RETRYABLE_HTTP_CODES:
                    # Permanent error — no point retrying.
                    raise exc from e
                last_exc = exc

            except (urllib.error.URLError, OSError, TimeoutError) as e:
                # Network-level transient error.
                last_exc = RuntimeError(f"Ollama request failed (attempt {attempt}/{_MAX_RETRIES}): {e}")

            except RuntimeError:
                raise  # Non-retryable application error (bad JSON, Ollama error field).

            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY_SEC * (_RETRY_BACKOFF_FACTOR ** (attempt - 1))
                log.warning(
                    "Ollama call to model=%s failed on attempt %d/%d; retrying in %.1fs: %s",
                    model, attempt, _MAX_RETRIES, delay, last_exc,
                )
                time.sleep(delay)

        raise RuntimeError(
            f"Ollama call to model={model} failed after {_MAX_RETRIES} attempts: {last_exc}"
        ) from last_exc


def encode_image_file_b64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")
