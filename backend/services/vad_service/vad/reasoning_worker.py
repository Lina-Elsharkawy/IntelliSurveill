from __future__ import annotations

import json
import logging
import signal
import time
from dataclasses import dataclass
from typing import Any

from .config import VadConfig, load_vad_config
from .db import VadDB
from .minio_client import VadMinioClient
from .reasoning.reasoning_client import OllamaClient
from .reasoning.reasoning_policy import (
    POLICY_VERSION,
    apply_python_final_guardrails,
    build_structured_result,
)
from .reasoning.reasoning_prompts import build_deep_vlm_visual_prompt, build_llm_policy_prompt
from .reasoning.reasoning_schema import (
    DeepReasoningContext,
    fallback_llm_uncertain,
    model_to_dict,
    parse_llm_policy_review,
    parse_vlm_visual_review,
)
from .vad_anomaly_rules import (
    RULES_VERSION,
    deterministic_rule_matches,
    load_active_vad_rules,
    serialize_rules_for_llm,
)

log = logging.getLogger("vad.reasoning_worker")


@dataclass(frozen=True)
class ReasoningCallResult:
    raw_vlm_output: str
    raw_llm_output: str | None
    structured: dict[str, Any]
    image_object_keys: list[str]


def _json_default(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _select_evidence_object_keys(bundle: dict[str, Any], cfg: VadConfig) -> list[str]:
    visual = bundle.get("visual_evidence") or {}
    selected: list[str] = []

    def add_key(key: Any) -> None:
        if not isinstance(key, str):
            return
        key = key.strip().lstrip("/")
        if not key:
            return
        if not key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return
        if key not in selected:
            selected.append(key)

    # Manual-test bundle format: visual_evidence.object_keys = ["...jpg", "...jpg"]
    for key in visual.get("object_keys") or []:
        add_key(key)

    # Automatic bundle formats: visual_evidence.objects or visual_evidence.evidence_objects.
    objects: list[Any] = []
    objects.extend(visual.get("objects") or [])
    objects.extend(visual.get("evidence_objects") or [])

    allowed_roles = {r.strip() for r in str(cfg.reasoning_image_roles).split(",") if r.strip()}

    for obj in objects:
        if not isinstance(obj, dict):
            continue
        role = str(obj.get("role") or obj.get("media_role") or obj.get("evidence_role") or "").strip()
        object_key = str(obj.get("object_key") or "").strip().lstrip("/")
        media_type = str(obj.get("media_type") or "").lower()
        content_type = str(obj.get("content_type") or "").lower()
        is_image = (
            media_type == "image"
            or content_type.startswith("image/")
            or object_key.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        )
        role_ok = not allowed_roles or role in allowed_roles
        if object_key and is_image and role_ok:
            add_key(object_key)

    return selected[: max(1, int(cfg.reasoning_max_images or 6))]


def _load_images_b64(minio: VadMinioClient, object_keys: list[str]) -> list[str]:
    import base64

    images: list[str] = []
    for key in object_keys:
        data = minio.download_bytes(key)
        images.append(base64.b64encode(data).decode("ascii"))
    return images


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
        if out != out:
            return None
        return out
    except Exception:
        return None


def _build_context(bundle: dict[str, Any], image_object_keys: list[str]) -> DeepReasoningContext:
    event = bundle.get("event") or {}
    deep_gate = bundle.get("deep_gate") or {}
    threshold = _safe_float(event.get("threshold_value"))
    score = _safe_float(event.get("peak_score"))
    ratio = _safe_float(event.get("ratio"))
    if ratio is None and score is not None and threshold and threshold > 0:
        ratio = score / threshold
    return DeepReasoningContext(
        event_id=int(event.get("gate_event_id")) if event.get("gate_event_id") is not None else None,
        case_id=int(event.get("case_id")) if event.get("case_id") is not None else None,
        gate_name="deep",
        deep_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=int(event.get("camera_id")) if event.get("camera_id") is not None else None,
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=int(event.get("tracker_track_id")) if event.get("tracker_track_id") is not None else None,
        tubelet_id=int(event.get("tubelet_id")) if event.get("tubelet_id") is not None else None,
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        deep_gate_metadata=deep_gate,
        scene_context=bundle.get("scene_context") or {},
    )


# Maximum age of a reasoning job to still be processed.  Jobs older than this
# were queued when Ollama was down and the evidence images are no longer fresh.
_MAX_JOB_AGE_SEC = 3 * 3600  # 3 hours

# If the VLM returns NO with at least this confidence we trust it and skip
# the LLM stage entirely to save compute.
_VLM_NO_SKIP_LLM_CONFIDENCE = 0.70


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
                    llm_model=self.cfg.ollama_llm_model,
                    max_age_sec=_MAX_JOB_AGE_SEC,
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
            final = s.get("python_final_result") or {}
            vlm_json = s.get("vlm_visual_review") or {}
            llm_json = s.get("llm_policy_review") or {}
            rules_json = s.get("rules_result") or {}

            with self.db.connect() as conn:
                with conn.transaction():
                    self.db.insert_reasoning_result(
                        conn,
                        reasoning_job_id=job_id,
                        case_id=case_id,
                        alert_decision=final.get("final_alert_decision"),
                        severity=final.get("final_severity"),
                        event_type=vlm_json.get("event_type"),
                        confidence=final.get("final_confidence"),
                        visual_evidence=json.dumps(
                            {
                                "visible_scene": vlm_json.get("visible_scene"),
                                "person_observation": vlm_json.get("person_observation"),
                                "motion_observation": vlm_json.get("motion_observation"),
                                "anomaly_evidence": vlm_json.get("anomaly_evidence"),
                                "normality_evidence": vlm_json.get("normality_evidence"),
                                "false_positive_risks": vlm_json.get("false_positive_risks"),
                            },
                            ensure_ascii=False,
                            default=_json_default,
                        ),
                        reasoning_summary=final.get("final_decision_reason"),
                        decision_reason=final.get("final_decision_reason"),
                        raw_vlm_output=result.raw_vlm_output,
                        raw_llm_output=result.raw_llm_output,
                        structured_output_json=s,
                        matched_rules_json=rules_json,
                        uncertainty_json={
                            "needs_human_review": final.get("final_alert_decision") in {"YES", "UNCERTAIN"},
                            "model_confidence": final.get("final_confidence"),
                            "guardrail_actions": final.get("guardrail_actions") or [],
                        },
                        vlm_visual_review_json=vlm_json,
                        llm_policy_review_json=llm_json,
                        python_final_result_json=final,
                        policy_version=s.get("policy_version") or POLICY_VERSION,
                        rules_version=s.get("rules_version") or RULES_VERSION,
                    )
                    self.db.mark_reasoning_job_succeeded(conn, job_id=job_id)
            log.info(
                "Reasoning job %s succeeded: final_decision=%s severity=%s confidence=%s",
                job_id,
                final.get("final_alert_decision"),
                final.get("final_severity"),
                final.get("final_confidence"),
            )
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
        ctx = _build_context(bundle, object_keys)

        # Load active rules from DB (falls back to built-ins on failure).
        with self.db.connect() as _conn:
            rules = load_active_vad_rules(self.db, _conn)
        llm_rules = serialize_rules_for_llm(rules)

        # Stage 1: VLM grounded visual review.
        vlm_prompt = build_deep_vlm_visual_prompt(ctx)
        raw_vlm = self.ollama.generate(model=self.cfg.ollama_vlm_model, prompt=vlm_prompt, images_b64=images_b64)
        vlm_review, vlm_parse_info = parse_vlm_visual_review(raw_vlm)

        # Stage 2: LLM policy/rules review.
        # Optimisation: if the VLM already returned a high-confidence NO, trust it
        # and skip the LLM call entirely.  The Python guardrails will still run.
        raw_llm: str | None = None
        llm_parse_info: dict[str, Any]
        skip_llm = (
            vlm_review.visual_alert_decision == "NO"
            and vlm_review.visual_confidence >= _VLM_NO_SKIP_LLM_CONFIDENCE
            and not (vlm_parse_info or {}).get("parse_error")
        )
        if skip_llm:
            log.info(
                "Skipping LLM stage for event_id=%s: VLM returned NO with confidence=%.2f",
                ctx.event_id, vlm_review.visual_confidence,
            )
            llm_review = fallback_llm_uncertain(
                f"LLM stage skipped: VLM returned high-confidence NO (confidence={vlm_review.visual_confidence:.2f}).",
                ctx=ctx,
                vlm=vlm_review,
            )
            llm_parse_info = {"parse_error": None, "skipped": True, "reason": "vlm_high_confidence_no"}
        else:
            # LLM is part of the architecture; if it fails, record an explicit UNCERTAIN
            # fallback rather than silently skipping it.
            try:
                llm_prompt = build_llm_policy_prompt(ctx=ctx, vlm_review=vlm_review, active_rules=llm_rules)
                raw_llm = self.ollama.generate(model=self.cfg.ollama_llm_model, prompt=llm_prompt)
                llm_review, llm_parse_info = parse_llm_policy_review(raw_llm, ctx=ctx, vlm=vlm_review)
            except Exception as e:
                log.exception(
                    "LLM policy review failed for event_id=%s; using explicit UNCERTAIN fallback: %s",
                    ctx.event_id, e,
                )
                raw_llm = None
                llm_review = fallback_llm_uncertain(
                    f"LLM policy review failed or timed out: {e}", ctx=ctx, vlm=vlm_review
                )
                llm_parse_info = {"parse_error": "llm_call_failed", "error": str(e)}

        # Stage 3: Python deterministic final guardrails.
        final_result, rules_result = apply_python_final_guardrails(
            ctx=ctx,
            vlm=vlm_review,
            llm=llm_review,
            rules=rules,
            vlm_parse_info=vlm_parse_info,
            llm_parse_info=llm_parse_info,
        )

        structured = build_structured_result(
            ctx=ctx,
            vlm=vlm_review,
            llm=llm_review,
            final=final_result,
            rules_result=rules_result,
            image_object_keys=object_keys,
            raw_vlm_output=raw_vlm,
            raw_llm_output=raw_llm,
            vlm_parse_info=vlm_parse_info,
            llm_parse_info=llm_parse_info,
        )
        return ReasoningCallResult(
            raw_vlm_output=raw_vlm,
            raw_llm_output=raw_llm,
            structured=structured,
            image_object_keys=object_keys,
        )

    def run_forever(self) -> None:
        log.info(
            "Starting Deep-only VAD reasoning worker provider=%s vlm=%s llm=%s poll=%.2fs batch=%s policy=%s rules=%s",
            self.cfg.reasoning_provider,
            self.cfg.ollama_vlm_model,
            self.cfg.ollama_llm_model,
            self.cfg.reasoning_poll_interval_sec,
            self.cfg.reasoning_batch_size,
            POLICY_VERSION,
            RULES_VERSION,
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
