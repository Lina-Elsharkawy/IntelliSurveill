from __future__ import annotations

import json
import logging
import re
import signal
import time
from dataclasses import dataclass
from typing import Any

from .config import VadConfig, load_vad_config
from .db import VadDB
from .json_utils import sanitize_json
from .minio_client import VadMinioClient
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


# ─────────────────────────────────────────────────────────────────────────────
# CLIP keyframe selector singleton
# Loaded once at worker startup, reused across all jobs.
# ─────────────────────────────────────────────────────────────────────────────

def _get_clip_selector():
    """Return the module-level CLIP keyframe selector singleton."""
    try:
        from .keyframe_selector import get_selector
        return get_selector()
    except ImportError:
        log.warning("keyframe_selector module not found — will use even-spacing fallback.")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Frame key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _frame_index_from_key(key: str) -> int:
    match = re.search(r"(?:^|/)frames/frame_(\d+)\.(?:jpg|jpeg|png|webp)$", key.lower())
    if not match:
        return 10**9
    return int(match.group(1))


def _infer_image_role_from_key(key: str) -> str:
    lower = key.lower().strip().lstrip("/")
    name = lower.rsplit("/", 1)[-1]
    if name == "tubelet_montage.jpg":
        return "tubelet_montage"
    if name == "annotated_frame.jpg":
        return "annotated_frame"
    if re.search(r"(?:^|/)frames/frame_\d+\.(?:jpg|jpeg|png|webp)$", lower):
        return "tubelet_frame"
    return "image"


def _even_sample(keys: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    if len(keys) <= limit:
        return list(keys)
    last = len(keys) - 1
    indexes = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    return [keys[i] for i in indexes[:limit]]


# ─────────────────────────────────────────────────────────────────────────────
# Evidence key collection + CLIP keyframe selection
# ─────────────────────────────────────────────────────────────────────────────

def _collect_frame_keys(bundle: dict[str, Any]) -> list[str]:
    """Collect all tubelet_frame keys from the reasoning bundle in chronological order."""
    visual = bundle.get("visual_evidence") or {}
    seen: set[str] = set()
    frames: list[str] = []

    def _add(key: Any, role: str | None = None) -> None:
        if not isinstance(key, str):
            return
        clean = key.strip().lstrip("/")
        if not clean or clean in seen:
            return
        if not clean.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return
        inferred = role or _infer_image_role_from_key(clean)
        if inferred == "tubelet_frame":
            seen.add(clean)
            frames.append(clean)

    for key in visual.get("object_keys") or []:
        _add(key)
    for obj in (visual.get("objects") or []) + (visual.get("evidence_objects") or []):
        if isinstance(obj, dict):
            _add(
                obj.get("object_key"),
                role=(obj.get("role") or obj.get("media_role") or "").strip() or None,
            )

    frames.sort(key=_frame_index_from_key)
    return frames


def _select_evidence_object_keys(
    bundle: dict[str, Any],
    cfg: VadConfig,
    minio: VadMinioClient,
) -> tuple[list[str], dict[str, bytes]]:
    """
    Download all tubelet frames then apply CLIP keyframe selection.

    Returns
    -------
    selected_keys : list[str]
        Up to VAD_REASONING_MAX_IMAGES frame keys in chronological order.
    image_bytes_map : dict[str, bytes]
        Raw JPEG bytes for every selected key (needed by _load_images_b64).
    """
    max_images = max(1, int(cfg.reasoning_max_images or 8))
    frame_keys = _collect_frame_keys(bundle)

    if not frame_keys:
        # No tubelet frames — fall back to montage/annotated.
        visual = bundle.get("visual_evidence") or {}
        fallback: list[str] = []
        for key in visual.get("object_keys") or []:
            if isinstance(key, str) and key.strip().lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                fallback.append(key.strip().lstrip("/"))
        fallback = fallback[:max_images]
        bytes_map = {}
        for k in fallback:
            try:
                bytes_map[k] = minio.download_bytes(k)
            except Exception as e:
                log.warning("Could not download fallback frame %s: %s", k, e)
        return fallback, bytes_map

    # Download all frames first (needed for CLIP).
    all_bytes: dict[str, bytes] = {}
    for key in frame_keys:
        try:
            all_bytes[key] = minio.download_bytes(key)
        except Exception as e:
            log.warning("Could not download frame %s: %s", key, e)

    # Apply CLIP keyframe selection.
    selector = _get_clip_selector()
    if selector is not None and len(frame_keys) > max_images:
        selected = selector.select(
            frame_keys=frame_keys,
            image_bytes_map=all_bytes,
            budget=max_images,
        )
    else:
        selected = _even_sample(frame_keys, max_images)

    # Keep only bytes for selected keys.
    selected_bytes = {k: all_bytes[k] for k in selected if k in all_bytes}

    log.info(
        "Frame selection: total_frames=%d selected=%d max_images=%d",
        len(frame_keys), len(selected), max_images,
    )
    return selected, selected_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Load images as base64 from already-downloaded bytes
# ─────────────────────────────────────────────────────────────────────────────

def _images_b64_from_map(object_keys: list[str], image_bytes_map: dict[str, bytes]) -> list[str]:
    import base64
    result = []
    for key in object_keys:
        data = image_bytes_map.get(key)
        if data:
            result.append(base64.b64encode(data).decode("ascii"))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Merged rule loading: vad_reasoning_rules + Anomaly_Rules table
# ─────────────────────────────────────────────────────────────────────────────

def _load_merged_rules(db: VadDB, conn) -> list[dict[str, Any]]:
    """Load active rules from the Anomaly_Rules table.

    Single rule source — vad_reasoning_rules is unused.
    Rules are created by admins via the anomaly-rules-service UI.

    AnomalyRuler (ECCV 2024): the LLM matches the VLM caption against
    this rule list — it cannot reason freely beyond what the rules cover.
    """
    rules = load_anomaly_rules(conn)
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


def _build_context(bundle: dict[str, Any], image_object_keys: list[str]) -> DeepReasoningContext:
    event = bundle.get("event") or {}
    deep_gate = bundle.get("deep_gate") or {}
    threshold = _safe_float(event.get("threshold_value"))
    score = _safe_float(event.get("peak_score"))
    ratio = _safe_float(event.get("ratio"))
    if ratio is None and score is not None and threshold and threshold > 0:
        ratio = score / threshold
    return DeepReasoningContext(
        event_id=int(event["gate_event_id"]) if event.get("gate_event_id") is not None else None,
        case_id=int(event["case_id"]) if event.get("case_id") is not None else None,
        gate_name="deep",
        deep_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=int(event["camera_id"]) if event.get("camera_id") is not None else None,
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=int(event["tracker_track_id"]) if event.get("tracker_track_id") is not None else None,
        tubelet_id=int(event["tubelet_id"]) if event.get("tubelet_id") is not None else None,
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        deep_gate_metadata=deep_gate,
        scene_context=bundle.get("scene_context") or {},
    )


def _build_pose_context(bundle: dict[str, Any], image_object_keys: list[str]) -> PoseReasoningContext:
    event = bundle.get("event") or {}
    pose_gate = bundle.get("pose_gate") or {}
    threshold = _safe_float(event.get("threshold_value"))
    score = _safe_float(event.get("peak_score"))
    ratio = _safe_float(event.get("ratio"))
    if ratio is None and score is not None and threshold and threshold > 0:
        ratio = score / threshold
    return PoseReasoningContext(
        event_id=int(event["gate_event_id"]) if event.get("gate_event_id") is not None else None,
        case_id=int(event["case_id"]) if event.get("case_id") is not None else None,
        gate_name="pose",
        pose_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=int(event["camera_id"]) if event.get("camera_id") is not None else None,
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=int(event["tracker_track_id"]) if event.get("tracker_track_id") is not None else None,
        tubelet_id=int(event["tubelet_id"]) if event.get("tubelet_id") is not None else None,
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        pose_gate_metadata=pose_gate,
        scene_context=bundle.get("scene_context") or {},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_MAX_JOB_AGE_SEC = 3 * 3600  # skip jobs older than 3 hours
_VLM_NO_SKIP_LLM_CONFIDENCE = 0.95  # effectively disabled (> 1.0 would fully disable)


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

        # Load CLIP selector once at startup.
        self._clip_selector = _get_clip_selector()
        if self._clip_selector is not None:
            # Trigger lazy load now so the first job doesn't pay the load cost.
            self._clip_selector._load()

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
                            sanitize_json({
                                "visible_scene": vlm_json.get("visible_scene"),
                                "person_observation": vlm_json.get("person_observation"),
                                "motion_observation": vlm_json.get("motion_observation"),
                                "anomaly_evidence": vlm_json.get("anomaly_evidence"),
                                "normality_evidence": vlm_json.get("normality_evidence"),
                                "false_positive_risks": vlm_json.get("false_positive_risks"),
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

        # ── Step 1: Download + CLIP keyframe selection ────────────────────────
        object_keys, image_bytes_map = _select_evidence_object_keys(
            bundle, self.cfg, self.minio
        )
        if not object_keys:
            raise RuntimeError("No usable visual evidence keys found in bundle.")

        images_b64 = _images_b64_from_map(object_keys, image_bytes_map)
        if not images_b64:
            raise RuntimeError("All frame downloads failed — no images to send to VLM.")

        # ── Step 2: Build reasoning context ──────────────────────────────────
        if source_gate == "pose":
            ctx = _build_pose_context(bundle, object_keys)
        else:
            ctx = _build_context(bundle, object_keys)

        # ── Step 3: Load merged rules (vad_reasoning_rules + Anomaly_Rules) ──
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