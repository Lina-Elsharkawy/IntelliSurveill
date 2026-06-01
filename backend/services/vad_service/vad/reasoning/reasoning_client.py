from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class OllamaClient:
    """Small blocking Ollama /api/generate client used by the reasoning worker."""

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
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace") if e.fp else str(e)
            raise RuntimeError(f"Ollama HTTP {e.code}: {err}") from e
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {e}") from e

        try:
            parsed = json.loads(body)
        except Exception as e:
            raise RuntimeError(f"Ollama returned non-JSON response: {body[:500]}") from e
        if "error" in parsed:
            raise RuntimeError(str(parsed["error"]))
        return str(parsed.get("response", "")).strip()


def encode_image_file_b64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")
