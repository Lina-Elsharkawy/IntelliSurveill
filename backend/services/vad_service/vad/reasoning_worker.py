from __future__ import annotations

import base64
import json
import logging
import re
import signal
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import VadConfig, load_vad_config
from .db import VadDB
from .minio_client import VadMinioClient

log = logging.getLogger("vad.reasoning_worker")

_ALLOWED_ALERTS = {"YES", "NO", "UNCERTAIN"}
_ALLOWED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@dataclass(frozen=True)
class ReasoningCallResult:
    raw_vlm_output: str
    raw_llm_output: str | None
    structured: dict[str, Any]
    image_object_keys: list[str]


class OllamaClient:
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


def _json_default(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a possibly chatty model response."""
    text = (text or "").strip()
    if not text:
        return {}
    # Remove fenced code wrappers if present.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            val = json.loads(text[start : end + 1])
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}
    return {}


def _clamp_confidence(value: Any) -> float | None:
    try:
        f = float(value)
    except Exception:
        return None
    if f != f:
        return None
    return max(0.0, min(1.0, f))


def _normalize_structured_output(raw: dict[str, Any], *, fallback_text: str) -> dict[str, Any]:
    alert = str(raw.get("alert_decision", raw.get("final_decision", "UNCERTAIN"))).strip().upper()
    if alert in {"TRUE_ANOMALY", "LIKELY_ANOMALY", "ALERT", "ANOMALY", "YES"}:
        alert = "YES"
    elif alert in {"FALSE_POSITIVE", "LIKELY_FALSE_POSITIVE", "NORMAL", "NO"}:
        alert = "NO"
    elif alert not in _ALLOWED_ALERTS:
        alert = "UNCERTAIN"

    severity = str(raw.get("severity", "LOW")).strip().upper()
    if severity not in _ALLOWED_SEVERITIES:
        severity = "LOW" if alert == "NO" else "MEDIUM" if alert == "UNCERTAIN" else "HIGH"

    out = {
        "alert_decision": alert,
        "severity": severity,
        "event_type": str(raw.get("event_type", "deep_semantic_spatiotemporal_anomaly")),
        "confidence": _clamp_confidence(raw.get("confidence")),
        "visual_evidence": str(raw.get("visual_evidence", raw.get("visual_observation", ""))).strip(),
        "reasoning_summary": str(raw.get("reasoning_summary", raw.get("summary", ""))).strip(),
        "decision_reason": str(raw.get("decision_reason", raw.get("reason", ""))).strip(),
        "recommended_action": str(raw.get("recommended_action", "review_only")).strip() or "review_only",
        "possible_false_positive_causes": raw.get("possible_false_positive_causes", []),
    }
    if out["confidence"] is None:
        out["confidence"] = 0.5
    if not out["reasoning_summary"]:
        out["reasoning_summary"] = fallback_text[:1000]
    if not out["decision_reason"]:
        out["decision_reason"] = "The reasoning model did not provide a separate decision reason."
    return out


def _short_json(obj: Any, max_chars: int = 6000) -> str:
    txt = json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default)
    return txt if len(txt) <= max_chars else txt[:max_chars] + "\n...<truncated>"


def _select_evidence_object_keys(bundle: dict[str, Any], cfg: VadConfig) -> list[str]:
    visual = bundle.get("visual_evidence") or {}
    objects = visual.get("objects") or []
    allowed_roles = {r.strip() for r in cfg.reasoning_image_roles.split(",") if r.strip()}

    selected: list[str] = []

    def add_by_role(role: str, limit: int | None = None) -> None:
        nonlocal selected
        matches = [str(o.get("object_key")) for o in objects if o.get("role") == role and o.get("object_key")]
        if limit is not None:
            matches = matches[:limit]
        for key in matches:
            if key not in selected:
                selected.append(key)

    if "annotated_frame" in allowed_roles:
        add_by_role("annotated_frame", 1)
    if "tubelet_montage" in allowed_roles:
        add_by_role("tubelet_montage", 1)
    if "tubelet_frame" in allowed_roles and len(selected) < cfg.reasoning_max_images:
        frame_keys = [str(o.get("object_key")) for o in objects if o.get("role") == "tubelet_frame" and o.get("object_key")]
        if frame_keys:
            # Spread frames across the tubelet rather than taking only the beginning.
            remaining = max(0, int(cfg.reasoning_max_images) - len(selected))
            if remaining >= len(frame_keys):
                picks = frame_keys
            elif remaining == 1:
                picks = [frame_keys[len(frame_keys) // 2]]
            else:
                idxs = sorted({round(i * (len(frame_keys) - 1) / max(1, remaining - 1)) for i in range(remaining)})
                picks = [frame_keys[int(i)] for i in idxs]
            for key in picks:
                if key not in selected:
                    selected.append(key)
    return selected[: int(cfg.reasoning_max_images)]


def _load_images_b64(minio: VadMinioClient, object_keys: list[str]) -> list[str]:
    images: list[str] = []
    for key in object_keys:
        data = minio.download_bytes(key)
        images.append(base64.b64encode(data).decode("ascii"))
    return images


def build_vlm_prompt(bundle: dict[str, Any], image_object_keys: list[str]) -> str:
    event = bundle.get("event", {})
    deep_gate = bundle.get("deep_gate", {})
    scene_context = bundle.get("scene_context", {})
    schema = bundle.get("requested_output_schema", {})
    return f"""
You are reviewing a Deep-gate video anomaly candidate from an indoor lab camera.

Important rules:
- This job is Deep-gate only. Do not discuss Pose or Homography as active triggers.
- Use only the provided images and metadata. Do not invent missing facts.
- The Deep gate already fired because VideoMAE+kNN distance exceeded its calibrated normal threshold and persistence rule.
- Your role is a second-stage visual reviewer: decide whether the visual evidence appears to require an alert or is likely a false positive.
- Normal lab activities can include walking, standing, sitting, working near equipment, and slow chair movement.
- If evidence is unclear, choose UNCERTAIN rather than guessing.

Event metadata:
{_short_json(event, 2500)}

Deep gate metadata:
{_short_json(deep_gate, 3500)}

Scene context:
{_short_json(scene_context, 2500)}

Images supplied in order:
{_short_json(image_object_keys, 1200)}

Return ONLY one JSON object matching this schema:
{_short_json(schema, 2000)}

Use these exact allowed values:
- alert_decision: YES, NO, or UNCERTAIN
- severity: LOW, MEDIUM, HIGH, or CRITICAL
- confidence: number from 0 to 1
""".strip()


def build_llm_normalizer_prompt(bundle: dict[str, Any], raw_vlm_output: str) -> str:
    return f"""
Normalize the VLM response into strict JSON for a VAD Deep-gate reasoning result.

Rules:
- Output ONLY valid JSON. No markdown.
- alert_decision must be YES, NO, or UNCERTAIN.
- severity must be LOW, MEDIUM, HIGH, or CRITICAL.
- confidence must be a number from 0 to 1.
- Do not add facts not present in the VLM output or event metadata.
- If unclear, use alert_decision=UNCERTAIN and recommended_action=review_only.

Event metadata:
{_short_json(bundle.get('event', {}), 2500)}

Raw VLM output:
{raw_vlm_output[:6000]}

Required JSON keys:
{{
  "alert_decision": "YES | NO | UNCERTAIN",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "event_type": "deep_semantic_spatiotemporal_anomaly",
  "confidence": 0.0,
  "visual_evidence": "what is visible in the frames",
  "reasoning_summary": "brief final interpretation",
  "decision_reason": "why this decision was chosen",
  "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
  "possible_false_positive_causes": []
}}
""".strip()


class DeepReasoningWorker:
    def __init__(self, cfg: VadConfig, db: VadDB) -> None:
        self.cfg = cfg
        self.db = db
        self.minio = VadMinioClient(cfg)
        self.ollama = OllamaClient(base_url=cfg.ollama_base_url, timeout_sec=cfg.ollama_timeout_sec)
        self._stop = False

    def stop(self, *_: Any) -> None:
        self._stop = True

    def process_one(self) -> bool:
        with self.db.connect() as conn:
            with conn.transaction():
                job = self.db.claim_next_deep_reasoning_job(
                    conn,
                    vlm_model=self.cfg.ollama_vlm_model,
                    llm_model=self.cfg.ollama_llm_model if self.cfg.reasoning_use_llm_normalizer else None,
                )
        if not job:
            return False

        job_id = int(job["id"])
        case_id = int(job["case_id"])
        attempts = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or self.cfg.deep_reasoning_max_attempts)
        try:
            result = self._process_claimed_job(job)
            s = result.structured
            with self.db.connect() as conn:
                with conn.transaction():
                    self.db.insert_reasoning_result(
                        conn,
                        reasoning_job_id=job_id,
                        case_id=case_id,
                        alert_decision=s.get("alert_decision"),
                        severity=s.get("severity"),
                        event_type=s.get("event_type"),
                        confidence=s.get("confidence"),
                        visual_evidence=s.get("visual_evidence"),
                        reasoning_summary=s.get("reasoning_summary"),
                        decision_reason=s.get("decision_reason"),
                        raw_vlm_output=result.raw_vlm_output,
                        raw_llm_output=result.raw_llm_output,
                        structured_output_json=s | {"image_object_keys": result.image_object_keys},
                        matched_rules_json={"routing_policy": "deep_persistent_only_v1"},
                        uncertainty_json={
                            "needs_human_review": s.get("alert_decision") in {"YES", "UNCERTAIN"},
                            "model_confidence": s.get("confidence"),
                        },
                    )
                    self.db.mark_reasoning_job_succeeded(conn, job_id=job_id)
            log.info("Reasoning job %s succeeded: decision=%s severity=%s confidence=%s", job_id, s.get("alert_decision"), s.get("severity"), s.get("confidence"))
            return True
        except Exception as e:
            retry = attempts < max_attempts
            log.exception("Reasoning job %s failed%s: %s", job_id, "; will retry" if retry else " permanently", e)
            with self.db.connect() as conn:
                with conn.transaction():
                    self.db.mark_reasoning_job_failed(
                        conn,
                        job_id=job_id,
                        retry=retry,
                        error_json={
                            "error": str(e),
                            "attempts": attempts,
                            "max_attempts": max_attempts,
                            "provider": self.cfg.reasoning_provider,
                        },
                    )
            return True

    def _process_claimed_job(self, job: dict[str, Any]) -> ReasoningCallResult:
        metadata = job.get("metadata_json") or {}
        if metadata.get("source_gate_name") != "deep":
            raise RuntimeError(f"Refusing non-Deep reasoning job: metadata={metadata}")

        bundle = job.get("input_bundle_json") or {}
        if not isinstance(bundle, dict):
            raise RuntimeError("input_bundle_json is not an object")
        if bundle.get("reasoning_scope") != "deep_gate_only":
            raise RuntimeError(f"Unsupported reasoning scope: {bundle.get('reasoning_scope')}")

        object_keys = _select_evidence_object_keys(bundle, self.cfg)
        if not object_keys:
            raise RuntimeError("No usable visual evidence object keys found in reasoning bundle")
        images_b64 = _load_images_b64(self.minio, object_keys)

        vlm_prompt = build_vlm_prompt(bundle, object_keys)
        raw_vlm = self.ollama.generate(model=self.cfg.ollama_vlm_model, prompt=vlm_prompt, images_b64=images_b64)

        raw_llm: str | None = None
        parsed = _extract_json_object(raw_vlm)
        if self.cfg.reasoning_use_llm_normalizer and self.cfg.ollama_llm_model:
            normalizer_prompt = build_llm_normalizer_prompt(bundle, raw_vlm)
            raw_llm = self.ollama.generate(model=self.cfg.ollama_llm_model, prompt=normalizer_prompt)
            parsed_llm = _extract_json_object(raw_llm)
            if parsed_llm:
                parsed = parsed_llm
        structured = _normalize_structured_output(parsed, fallback_text=raw_llm or raw_vlm)
        return ReasoningCallResult(raw_vlm_output=raw_vlm, raw_llm_output=raw_llm, structured=structured, image_object_keys=object_keys)

    def run_forever(self) -> None:
        log.info(
            "Starting Deep-only VAD reasoning worker provider=%s vlm=%s llm=%s poll=%.2fs batch=%s",
            self.cfg.reasoning_provider,
            self.cfg.ollama_vlm_model,
            self.cfg.ollama_llm_model if self.cfg.reasoning_use_llm_normalizer else "disabled",
            self.cfg.reasoning_poll_interval_sec,
            self.cfg.reasoning_batch_size,
        )
        if not self.cfg.reasoning_worker_enabled:
            log.warning("VAD_REASONING_WORKER_ENABLED=0; worker will idle")
        while not self._stop:
            processed_any = False
            if self.cfg.reasoning_worker_enabled:
                for _ in range(max(1, int(self.cfg.reasoning_batch_size))):
                    if self._stop:
                        break
                    processed_any = self.process_one() or processed_any
            if not processed_any:
                time.sleep(float(self.cfg.reasoning_poll_interval_sec))


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_vad_config()
    db = VadDB(cfg.db_dsn)
    worker = DeepReasoningWorker(cfg, db)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
