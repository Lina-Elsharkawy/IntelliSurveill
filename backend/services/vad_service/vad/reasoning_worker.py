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
from .reasoning.reasoning_prompts import build_deep_vlm_visual_prompt, build_llm_policy_prompt, build_pose_vlm_visual_prompt, build_vlm_observation_hints
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
    return sanitize_json(value)


def _frame_index_from_key(key: str) -> int:
    """Return the numeric frame index for .../frames/frame_###.jpg keys."""
    match = re.search(r"(?:^|/)frames/frame_(\d+)\.(?:jpg|jpeg|png|webp)$", key.lower())
    if not match:
        return 10**9
    return int(match.group(1))


def _infer_image_role_from_key(key: str) -> str:
    """Infer evidence role from object-key naming used by EvidenceWriter."""
    lower = key.lower().strip().lstrip("/")
    name = lower.rsplit("/", 1)[-1]
    if name == "tubelet_montage.jpg":
        return "tubelet_montage"
    if name == "annotated_frame.jpg":
        return "annotated_frame"
    if re.search(r"(?:^|/)frames/frame_\d+\.(?:jpg|jpeg|png|webp)$", lower):
        return "tubelet_frame"
    return "image"


def _evenly_sample(keys: list[str], limit: int) -> list[str]:
    """Keep temporal coverage across the whole tubelet when frames exceed budget."""
    if limit <= 0:
        return []
    if len(keys) <= limit:
        return list(keys)
    if limit == 1:
        return [keys[0]]
    last = len(keys) - 1
    indexes = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    # Rounding can theoretically collapse adjacent indexes. Fill missing slots from the front
    # while keeping chronological order and without exceeding the budget.
    if len(indexes) < limit:
        for idx in range(len(keys)):
            if idx not in indexes:
                indexes.append(idx)
                if len(indexes) == limit:
                    break
        indexes = sorted(indexes)
    return [keys[i] for i in indexes[:limit]]


def _select_evidence_object_keys(bundle: dict[str, Any], cfg: VadConfig) -> list[str]:
    """Select VLM evidence with raw chronological tubelet frames as the primary input.

    Current reasoning design:
    - The VLM should inspect the event as a temporal sequence.
    - For the local MiniCPM/Ollama VLM, tiny montage cells and annotated overview images can
      be less useful than full raw evidence frames.
    - Therefore the default selection is frame-first / frame-only: all chronological
      frames/frame_### images up to VAD_REASONING_MAX_IMAGES.

    Configuration:
    - VAD_REASONING_IMAGE_ROLES controls which roles are preferred.
      Recommended default: "tubelet_frame".
    - If "tubelet_montage" or "annotated_frame" are explicitly included in
      VAD_REASONING_IMAGE_ROLES, they will be included before frames.
    - If no tubelet frames are available, the function falls back to montage/annotated/other
      images rather than failing with no visual evidence.

    If the number of frame images is greater than the configured budget, frames are sampled
    evenly across the full event window, never by taking only the first frames.
    """
    visual = bundle.get("visual_evidence") or {}
    preferred_roles = [r.strip() for r in str(cfg.reasoning_image_roles).split(",") if r.strip()]
    if not preferred_roles:
        preferred_roles = ["tubelet_frame"]
    preferred_set = set(preferred_roles)
    max_images = max(1, int(cfg.reasoning_max_images or 32))

    # role -> ordered unique keys. Collect all roles first, then apply preference/fallback
    # after role grouping. This avoids accidentally discarding fallback evidence.
    by_role: dict[str, list[str]] = {
        "tubelet_montage": [],
        "annotated_frame": [],
        "tubelet_frame": [],
        "image": [],
    }
    seen: set[str] = set()

    def add_key(key: Any, role: str | None = None) -> None:
        if not isinstance(key, str):
            return
        clean = key.strip().lstrip("/")
        if not clean:
            return
        if not clean.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return
        inferred_role = (role or "").strip() or _infer_image_role_from_key(clean)
        if clean in seen:
            return
        seen.add(clean)
        by_role.setdefault(inferred_role, []).append(clean)

    # Manual-test bundle format: visual_evidence.object_keys = ["...jpg", "...jpg"]
    for key in visual.get("object_keys") or []:
        add_key(key)

    # Automatic bundle formats: visual_evidence.objects or visual_evidence.evidence_objects.
    objects: list[Any] = []
    objects.extend(visual.get("objects") or [])
    objects.extend(visual.get("evidence_objects") or [])

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
        if object_key and is_image:
            add_key(object_key, role=role)

    montage = by_role.get("tubelet_montage", [])
    annotated = by_role.get("annotated_frame", [])
    frames = sorted(by_role.get("tubelet_frame", []), key=_frame_index_from_key)
    other = by_role.get("image", [])

    selected: list[str] = []

    # Include overview images only when explicitly requested. The default compose/config now
    # requests tubelet_frame only because raw frames are more legible for the VLM.
    if "tubelet_montage" in preferred_set:
        selected.extend(montage[:1])
    if "annotated_frame" in preferred_set:
        selected.extend([k for k in annotated[:1] if k not in selected])

    # Raw chronological frames are the primary evidence for temporal reasoning.
    if "tubelet_frame" in preferred_set:
        remaining = max_images - len(selected)
        selected.extend([k for k in _evenly_sample(frames, remaining) if k not in selected])

    # If the preferred roles produced nothing, fall back gracefully.
    if not selected:
        fallback_order = frames + montage[:1] + annotated[:1] + other
        selected = _evenly_sample(fallback_order, max_images)

    # If preferred roles included only overview images and there is still budget, add frames.
    if len(selected) < max_images and "tubelet_frame" not in preferred_set:
        for key in _evenly_sample(frames, max_images - len(selected)):
            if key not in selected:
                selected.append(key)

    selected = selected[:max_images]

    role_counts = {role: len(keys) for role, keys in by_role.items() if keys}
    selected_role_counts: dict[str, int] = {}
    for key in selected:
        role = _infer_image_role_from_key(key)
        selected_role_counts[role] = selected_role_counts.get(role, 0) + 1
    log.info(
        "VLM evidence selection: available_image_count=%s selected_image_count=%s max_images=%s preferred_roles=%s role_counts=%s selected_role_counts=%s selected_keys=%s",
        sum(role_counts.values()),
        len(selected),
        max_images,
        preferred_roles,
        role_counts,
        selected_role_counts,
        selected,
    )
    return selected

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
def _build_pose_context(bundle: dict[str, Any], image_object_keys: list[str]) -> PoseReasoningContext:
    event = bundle.get("event") or {}
    pose_gate = bundle.get("pose_gate") or {}
    threshold = _safe_float(event.get("threshold_value"))
    score = _safe_float(event.get("peak_score"))
    ratio = _safe_float(event.get("ratio"))
    if ratio is None and score is not None and threshold and threshold > 0:
        ratio = score / threshold
    return PoseReasoningContext(
        event_id=int(event.get("gate_event_id")) if event.get("gate_event_id") is not None else None,
        case_id=int(event.get("case_id")) if event.get("case_id") is not None else None,
        gate_name="pose",
        pose_score=score,
        threshold_value=threshold,
        score_ratio=ratio,
        camera_id=int(event.get("camera_id")) if event.get("camera_id") is not None else None,
        stream_key=event.get("stream_key"),
        camera_key=event.get("camera_key"),
        tracker_track_id=int(event.get("tracker_track_id")) if event.get("tracker_track_id") is not None else None,
        tubelet_id=int(event.get("tubelet_id")) if event.get("tubelet_id") is not None else None,
        evidence_object_keys=image_object_keys,
        event_metadata=event,
        pose_gate_metadata=pose_gate,
        scene_context=bundle.get("scene_context") or {},
    )

# Maximum age of a reasoning job to still be processed.  Jobs older than this
# were queued when Ollama was down and the evidence images are no longer fresh.
_MAX_JOB_AGE_SEC = 3 * 3600  # 3 hours

# If the VLM returns NO with at least this confidence we trust it and skip
# the LLM stage entirely to save compute.
_VLM_NO_SKIP_LLM_CONFIDENCE = 0.95


class GateReasoningWorker:
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
        source_gate = metadata.get("source_gate_name")
        if source_gate not in {"deep", "pose"}:
            raise RuntimeError(f"Unsupported source_gate_name in reasoning job: {source_gate}")

        bundle = job.get("input_bundle_json") or {}
        if not isinstance(bundle, dict):
            raise RuntimeError("input_bundle_json is not an object")

        scope = bundle.get("reasoning_scope")
        if scope not in {"deep_gate_only", "pose_gate_only"}:
            raise RuntimeError(f"Unsupported reasoning scope: {scope}")

        object_keys = _select_evidence_object_keys(bundle, self.cfg)
        if not object_keys:
            raise RuntimeError("No usable visual evidence object keys found in reasoning bundle")
        images_b64 = _load_images_b64(self.minio, object_keys)

        if source_gate == "pose":
            ctx = _build_pose_context(bundle, object_keys)
        else:
            ctx = _build_context(bundle, object_keys)

        # Load active rules from DB (falls back to built-ins on failure).
        with self.db.connect() as _conn:
            rules = load_active_vad_rules(self.db, _conn)
        llm_rules = serialize_rules_for_llm(rules)

        # Stage 1: VLM grounded perception review.
        # The VLM receives only perception-oriented observation hints derived from
        # the active rule set. It must not apply rules or make the final anomaly
        # decision; rule cognition remains in the LLM/Python layers.
        visual_observation_hints = build_vlm_observation_hints(llm_rules)
        if source_gate == "pose":
            vlm_prompt = build_pose_vlm_visual_prompt(ctx, visual_observation_hints=visual_observation_hints)
        else:
            vlm_prompt = build_deep_vlm_visual_prompt(ctx, visual_observation_hints=visual_observation_hints)
        raw_vlm = self.ollama.generate(model=self.cfg.ollama_vlm_model, prompt=vlm_prompt, images_b64=images_b64)
        vlm_review, vlm_parse_info = parse_vlm_visual_review(raw_vlm)

        # Stage 2: LLM policy/rules review.
        # Per the decoupled P2C architecture, this stage should normally run for
        # every VLM perception result because active anomaly rules are injected here.
        # The legacy skip path is effectively disabled by _VLM_NO_SKIP_LLM_CONFIDENCE > 1.0.
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
            llm_review = LlmPolicyReview(
                policy_alert_decision="NO",
                policy_severity="NONE",
                policy_confidence=min(1.0, max(0.0, float(vlm_review.visual_confidence))),
                recommended_action="ignore",
                score_assessment=ScoreAssessment(
                    score_ratio=ctx.score_ratio,
                    ratio_band=ctx.ratio_band(),
                    score_reasoning="LLM stage skipped because the VLM produced a high-confidence visual NO; score is not used to override visible normality.",
                ),
                evidence_assessment=EvidenceAssessment(
                    uses_only_vlm_evidence=True,
                    has_strong_visual_anomaly_evidence=False,
                    has_normality_evidence=bool(vlm_review.normality_evidence),
                    has_false_positive_risk=bool(vlm_review.false_positive_risks),
                ),
                matched_trigger_rules=[],
                matched_suppress_rules=[],
                rule_reasoning=["LLM stage skipped after high-confidence VLM NO to save compute."],
                decision_reason=(
                    f"The VLM returned a high-confidence NO (confidence={vlm_review.visual_confidence:.2f}). "
                    "The policy layer preserves that conservative NO instead of converting it to UNCERTAIN."
                ),
                limitations=["No separate LLM cognition call was made for this high-confidence visual NO."],
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
            "Starting Deep + Pose VAD reasoning worker provider=%s vlm=%s llm=%s poll=%.2fs batch=%s policy=%s rules=%s",
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
    worker = GateReasoningWorker(cfg, db)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
