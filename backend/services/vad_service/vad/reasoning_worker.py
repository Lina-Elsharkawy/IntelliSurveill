from __future__ import annotations

import json
import logging
import signal
import time
from dataclasses import dataclass
from typing import Any

from .config import VadConfig, load_vad_config
from .db import VadDB
from .json_utils import sanitize_json
from .minio_client import VadMinioClient
from .reasoning_evidence import images_b64_from_map, select_evidence_object_keys
from .reasoning.reasoning_client import OllamaClient
from .reasoning.reasoning_policy import (
    POLICY_VERSION,
    apply_python_final_guardrails,
    build_structured_result,
)
from .reasoning.reasoning_prompts import (
    build_deep_vlm_visual_prompt,
    build_llm_policy_prompt,
    build_pose_vlm_visual_prompt,
    build_vlm_observation_hints,
)
from .reasoning.reasoning_schema import (
    DeepReasoningContext,
    PoseReasoningContext,
    EvidenceAssessment,
    LlmPolicyReview,
    ScoreAssessment,
    fallback_llm_uncertain,
    model_to_dict,
    parse_llm_policy_review,
    parse_vlm_visual_review,
)
from .vad_anomaly_rules import (
    RULES_VERSION,
    deterministic_rule_matches,
    load_anomaly_rules,
)

log = logging.getLogger("vad.reasoning_worker")


@dataclass(frozen=True)
class ReasoningCallResult:
    raw_vlm_output: str
    raw_llm_output: str | None
    structured: dict[str, Any]
    image_object_keys: list[str]


def _json_default(value: Any) -> Any:
    return sanitize_json(value)



def _final_event_type_from_rules(final: dict[str, Any], rules_json: dict[str, Any], vlm_json: dict[str, Any]) -> str:
    """Return a dashboard-safe event type.

    The VLM is only a visual witness, so we do not store VLM event_type as the
    final result event type. If the final decision is YES, use the first matched
    trigger rule event_type. Otherwise return a neutral final-state label.
    """
    decision = str((final or {}).get("final_alert_decision") or "UNCERTAIN").upper()
    if decision == "YES":
        # Try both field names: reasoning_policy stores as llm_matched_trigger_rules,
        # but the LLM JSON itself may use matched_trigger_rules.
        trigger_rules = (
            (rules_json or {}).get("llm_matched_trigger_rules")
            or (rules_json or {}).get("matched_trigger_rules")
            or []
        )
        for rule in trigger_rules:
            if not isinstance(rule, dict):
                continue
            # Only consider rules that were actually applied.
            if rule.get("applied") is False:
                continue
            et = rule.get("event_type")
            if not et:
                # Some rules store event_types as a list.
                ets = rule.get("event_types")
                if isinstance(ets, list) and ets:
                    et = ets[0]
            if et and str(et).strip():
                return str(et).strip()
        return "rule_matched_alert"
    if decision == "NO":
        return "no_rule_alert"
    return "requires_human_review"


# ─────────────────────────────────────────────────────────────────────────────
# Rule loading: Anomaly_Rules table only
# ─────────────────────────────────────────────────────────────────────────────

def _load_merged_rules(db: VadDB, conn) -> list[dict[str, Any]]:
    """Load active rules from the Anomaly_Rules table.

    Single rule source — vad_reasoning_rules is unused.
    Rules are created by admins via the anomaly-rules-service UI.

    AnomalyRuler (ECCV 2024): the LLM matches the VLM caption against
    this rule list — it cannot reason freely beyond what the rules cover.
    """
    rules = load_anomaly_rules(conn)
    if not rules:
        log.warning(
            "No active rules loaded from Anomaly_Rules. "
            "The LLM will have no rules to match against. "
            "Reasoning results will be UNCERTAIN with metadata: no_active_rules."
        )
    else:
        log.info("Rules loaded from Anomaly_Rules: %d active", len(rules))
    return rules


# ─────────────────────────────────────────────────────────────────────────────
# Context builders
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
        return None if out != out else out
    except Exception:
        return None


def _safe_int(event: dict[str, Any], field: str) -> int | None:
    """Return event[field] as int, or None if absent/null."""
    v = event.get(field)
    return int(v) if v is not None else None


def _compute_score_ratio(
    event: dict[str, Any],
) -> tuple[float | None, float | None, float | None]:
    """Extract score, threshold, and ratio from a bundle event dict.

    Computes ratio from score/threshold when the bundle omits it.
    Returns (score, threshold, ratio) — all may be None.
    """
    score = _safe_float(event.get("peak_score"))
    threshold = _safe_float(event.get("threshold_value"))
    ratio = _safe_float(event.get("ratio"))
    if ratio is None and score is not None and threshold and threshold > 0:
        ratio = score / threshold
    return score, threshold, ratio


def _build_context(bundle: dict[str, Any], image_object_keys: list[str]) -> DeepReasoningContext:
    event = bundle.get("event") or {}
    deep_gate = bundle.get("deep_gate") or {}
    score, threshold, ratio = _compute_score_ratio(event)
    return DeepReasoningContext(
        event_id=_safe_int(event, "gate_event_id"),
        case_id=_safe_int(event, "case_id"),
        gate_name="deep",
        deep_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=_safe_int(event, "camera_id"),
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=_safe_int(event, "tracker_track_id"),
        tubelet_id=_safe_int(event, "tubelet_id"),
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        deep_gate_metadata=deep_gate,
        scene_context=bundle.get("scene_context") or {},
    )


def _build_pose_context(bundle: dict[str, Any], image_object_keys: list[str]) -> PoseReasoningContext:
    event = bundle.get("event") or {}
    pose_gate = bundle.get("pose_gate") or {}
    score, threshold, ratio = _compute_score_ratio(event)
    return PoseReasoningContext(
        event_id=_safe_int(event, "gate_event_id"),
        case_id=_safe_int(event, "case_id"),
        gate_name="pose",
        pose_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=_safe_int(event, "camera_id"),
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=_safe_int(event, "tracker_track_id"),
        tubelet_id=_safe_int(event, "tubelet_id"),
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        pose_gate_metadata=pose_gate,
        scene_context=bundle.get("scene_context") or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_MAX_JOB_AGE_SEC = 3 * 3600  # skip jobs older than 3 hours
# Set to 2.0 so the LLM always runs (no model can return confidence >= 2.0).
# AnomalyRuler closed-world policy: the LLM is the semantic decision layer and
# must run for every job.  Raise to e.g. 0.97 only if you intentionally want to
# skip the LLM on near-certain high-confidence VLM NO outputs.
_VLM_NO_SKIP_LLM_CONFIDENCE = 2.0  # always run LLM


# ─────────────────────────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────────────────────────

class GateReasoningWorker:
    def __init__(self, cfg: VadConfig, db: VadDB) -> None:
        self.cfg = cfg
        self.db = db
        self.minio = VadMinioClient(cfg)
        self.ollama = OllamaClient(
            base_url=cfg.ollama_base_url,
            timeout_sec=cfg.ollama_timeout_sec,
        )
        self._stop = False

        # Gate-aware selector models are loaded lazily on first use.
        # This keeps the worker alive even if optional VideoMAE/YOLO artifacts are missing.

    def stop(self, *_: Any) -> None:
        self._stop = True

    def process_one(self) -> bool:
        with self.db.connect() as conn:
            with conn.transaction():
                job = self.db.claim_next_reasoning_job(
                    conn,
                    gate_name="deep",
                    vlm_model=self.cfg.ollama_vlm_model,
                    llm_model=self.cfg.ollama_llm_model,
                    max_age_sec=_MAX_JOB_AGE_SEC,
                )
                if not job:
                    job = self.db.claim_next_reasoning_job(
                        conn,
                        gate_name="pose",
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
            # build_structured_result stores the deterministic final decision under
            # "python_final_guardrails". Keep fallbacks for older result schemas.
            final = (
                s.get("python_final_guardrails")
                or s.get("python_final_result")
                or {}
            )
            vlm_json = s.get("vlm_visual_review") or {}
            llm_json = s.get("llm_policy_review") or {}
            rules_json = (
                s.get("rule_evaluation")
                or s.get("rules_result")
                or {}
            )

            with self.db.connect() as conn:
                with conn.transaction():
                    self.db.insert_reasoning_result(
                        conn,
                        reasoning_job_id=job_id,
                        case_id=case_id,
                        alert_decision=final.get("final_alert_decision"),
                        severity=final.get("final_severity"),
                        event_type=_final_event_type_from_rules(final, rules_json, vlm_json),
                        confidence=final.get("final_confidence"),
                        visual_evidence=json.dumps(
                            sanitize_json({
                                "visible_scene": vlm_json.get("visible_scene"),
                                "person_observation": vlm_json.get("person_observation"),
                                "motion_observation": vlm_json.get("motion_observation"),
                                "anomaly_evidence": vlm_json.get("anomaly_evidence"),
                                "normality_evidence": vlm_json.get("normality_evidence"),
                                "false_positive_risks": vlm_json.get("false_positive_risks"),
                                "observation_status": vlm_json.get("observation_status"),
                            }),
                            ensure_ascii=False,
                            default=_json_default,
                            allow_nan=False,
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
                "Job %s done: decision=%s severity=%s confidence=%s",
                job_id,
                final.get("final_alert_decision"),
                final.get("final_severity"),
                final.get("final_confidence"),
            )
            return True

        except Exception as e:
            retry = attempts < max_attempts
            log.exception(
                "Job %s failed%s: %s", job_id, "; will retry" if retry else " permanently", e
            )
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
        source_gate = metadata.get("source_gate_name")
        if source_gate not in {"deep", "pose"}:
            raise RuntimeError(f"Unsupported source_gate_name: {source_gate}")

        bundle = job.get("input_bundle_json") or {}
        if not isinstance(bundle, dict):
            raise RuntimeError("input_bundle_json is not an object")

        scope = bundle.get("reasoning_scope")
        if scope not in {"deep_gate_only", "pose_gate_only"}:
            raise RuntimeError(f"Unsupported reasoning scope: {scope}")

        # ── Step 1: Download + gate-aware frame selection ─────────────────────
        object_keys, image_bytes_map, frame_selection_audit = select_evidence_object_keys(
            bundle, self.cfg, self.minio
        )
        if not object_keys:
            raise RuntimeError("No usable visual evidence keys found in bundle.")

        images_b64 = images_b64_from_map(object_keys, image_bytes_map)
        if not images_b64:
            raise RuntimeError("All frame downloads failed — no images to send to VLM.")

        # ── Step 2: Build reasoning context ──────────────────────────────────
        if source_gate == "pose":
            ctx = _build_pose_context(bundle, object_keys)
        else:
            ctx = _build_context(bundle, object_keys)

        # ── Step 3: Load active rules from Anomaly_Rules ─────────────────
        with self.db.connect() as _conn:
            rules = _load_merged_rules(self.db, _conn)

        # ── Step 4: VLM visual caption (Phase 2 — Perception) ────────────────
        # No anomaly vocabulary. Action-grounded observation questions only.
        # (ASK-Hint, arXiv:2510.02155)
        visual_hints = build_vlm_observation_hints(rules)

        if source_gate == "pose":
            vlm_prompt = build_pose_vlm_visual_prompt(ctx, visual_observation_hints=visual_hints)
        else:
            vlm_prompt = build_deep_vlm_visual_prompt(ctx, visual_observation_hints=visual_hints)

        raw_vlm = self.ollama.generate(
            model=self.cfg.ollama_vlm_model,
            prompt=vlm_prompt,
            images_b64=images_b64,
        )
        vlm_review, vlm_parse_info = parse_vlm_visual_review(raw_vlm)

        # ── Step 5: LLM rule-matching (Phase 3 — Cognition) ──────────────────
        # Rules-constrained decision only. No open-set escape hatch.
        # (AnomalyRuler, arXiv:2407.10299)
        raw_llm: str | None = None
        llm_parse_info: dict[str, Any]

        skip_llm = (
            vlm_review.visual_alert_decision == "NO"
            and vlm_review.visual_confidence >= _VLM_NO_SKIP_LLM_CONFIDENCE
            and not (vlm_parse_info or {}).get("parse_error")
        )

        if skip_llm:
            log.info(
                "Skipping LLM for event_id=%s: VLM returned NO confidence=%.2f",
                ctx.event_id, vlm_review.visual_confidence,
            )
            llm_review = LlmPolicyReview(
                policy_alert_decision="NO",
                policy_severity="NONE",
                policy_confidence=min(1.0, float(vlm_review.visual_confidence)),
                recommended_action="ignore",
                score_assessment=ScoreAssessment(
                    score_ratio=ctx.score_ratio,
                    ratio_band=ctx.ratio_band(),
                    score_reasoning="LLM skipped — high-confidence visual NO.",
                ),
                evidence_assessment=EvidenceAssessment(
                    uses_only_vlm_evidence=True,
                    has_strong_visual_anomaly_evidence=False,
                    has_normality_evidence=bool(vlm_review.normality_evidence),
                    has_false_positive_risk=bool(vlm_review.false_positive_risks),
                ),
                matched_trigger_rules=[],
                matched_suppress_rules=[],
                rule_reasoning=["LLM stage skipped after high-confidence VLM NO."],
                decision_reason=(
                    f"VLM returned high-confidence NO (confidence={vlm_review.visual_confidence:.2f}). "
                    "Conservative NO preserved."
                ),
                limitations=["No separate LLM call made for this high-confidence visual NO."],
            )
            llm_parse_info = {"parse_error": None, "skipped": True, "reason": "vlm_high_confidence_no"}
        else:
            try:
                llm_prompt = build_llm_policy_prompt(
                    ctx=ctx,
                    vlm_review=vlm_review,
                    active_rules=rules,
                )
                raw_llm = self.ollama.generate(
                    model=self.cfg.ollama_llm_model,
                    prompt=llm_prompt,
                )
                llm_review, llm_parse_info = parse_llm_policy_review(
                    raw_llm, ctx=ctx, vlm=vlm_review
                )
            except Exception as e:
                log.exception(
                    "LLM policy review failed for event_id=%s: %s", ctx.event_id, e
                )
                raw_llm = None
                llm_review = fallback_llm_uncertain(
                    f"LLM failed: {e}", ctx=ctx, vlm=vlm_review
                )
                llm_parse_info = {"parse_error": "llm_call_failed", "error": str(e)}

        # ── Step 6: Python guardrails (Phase 4 — Deterministic validation) ───
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
        # Store rule source status for frontend audit display.
        if not rules:
            structured.setdefault("rule_evaluation", {})["rule_source_status"] = "no_active_rules"
        else:
            structured.setdefault("rule_evaluation", {})["rule_source_status"] = "active"
            structured.setdefault("rule_evaluation", {})["active_rule_count"] = len(rules)
        structured["frame_selection"] = sanitize_json(frame_selection_audit)
        return ReasoningCallResult(
            raw_vlm_output=raw_vlm,
            raw_llm_output=raw_llm,
            structured=structured,
            image_object_keys=object_keys,
        )

    def run_forever(self) -> None:
        log.info(
            "VAD reasoning worker started  provider=%s vlm=%s llm=%s "
            "poll=%.2fs batch=%s policy=%s rules=%s",
            self.cfg.reasoning_provider,
            self.cfg.ollama_vlm_model,
            self.cfg.ollama_llm_model,
            self.cfg.reasoning_poll_interval_sec,
            self.cfg.reasoning_batch_size,
            POLICY_VERSION,
            RULES_VERSION,
        )
        if not self.cfg.reasoning_worker_enabled:
            log.warning("VAD_REASONING_WORKER_ENABLED=0; worker idling.")

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
    worker = GateReasoningWorker(cfg, db)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()