from __future__ import annotations

import logging
from typing import Any

import psycopg

from .config import VadConfig
from .db import VadDB

log = logging.getLogger("vad.reasoning_jobs")

DEEP_REASONING_ROUTING_POLICY = "deep_persistent_only_v1"
POSE_REASONING_ROUTING_POLICY = "pose_persistent_only_v1"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:  # NaN guard
            return default
        return out
    except Exception:
        return default


def _ratio(score: Any, threshold: Any) -> float | None:
    threshold_f = _safe_float(threshold)
    if threshold_f <= 0:
        return None
    return _safe_float(score) / threshold_f


def _role_from_object_key(object_key: str) -> str:
    name = object_key.rsplit("/", 1)[-1]
    if name == "annotated_frame.jpg":
        return "annotated_frame"
    if name == "tubelet_montage.jpg":
        return "tubelet_montage"
    if name == "event_metadata.json":
        return "event_metadata"
    if name.startswith("frames/") or "/frames/" in object_key:
        return "tubelet_frame"
    return "other"


def build_deep_reasoning_bundle(
    *,
    cfg: VadConfig,
    case_id: int,
    gate_event_id: int,
    session_id: int,
    stream_id: int,
    camera_id: int | None,
    db_track_id: int | None,
    tracker_track_id: int,
    tubelet_id: int,
    score_id: int,
    gate_out: Any,
    gate_summary: dict[str, Any],
    event_policy: dict[str, Any],
    evidence_result: Any,
) -> dict[str, Any]:
    """Build the compact Deep-only input packet stored for later VLM+LLM work."""
    object_keys = list(getattr(evidence_result, "object_keys", []) or [])
    media_object_ids = list(getattr(evidence_result, "media_object_ids", []) or [])
    evidence_item_ids = list(getattr(evidence_result, "evidence_item_ids", []) or [])
    role_counts: dict[str, int] = {}
    evidence_objects: list[dict[str, Any]] = []
    for rank, key in enumerate(object_keys):
        role = _role_from_object_key(str(key))
        role_counts[role] = role_counts.get(role, 0) + 1
        evidence_objects.append({"rank": rank, "role": role, "object_key": str(key)})

    ratio = _ratio(gate_out.smoothed_score, gate_out.threshold_value)
    gate_metadata = dict(getattr(gate_out, "metadata", {}) or {})
    feature_values = dict(getattr(gate_out, "feature_values", {}) or {})

    return {
        "job_type": "vad_event_reasoning",
        "reasoning_scope": "deep_gate_only",
        "routing_policy": DEEP_REASONING_ROUTING_POLICY,
        "event": {
            "case_id": int(case_id),
            "gate_event_id": int(gate_event_id),
            "gate_name": "deep",
            "gate_display_name": "Deep Visual Similarity Gate",
            "session_id": int(session_id),
            "stream_id": int(stream_id),
            "camera_id": int(camera_id) if camera_id is not None else None,
            "stream_key": cfg.stream_key,
            "camera_key": cfg.camera_key,
            "db_track_id": int(db_track_id) if db_track_id is not None else None,
            "tracker_track_id": int(tracker_track_id),
            "tubelet_id": int(tubelet_id),
            "score_id": int(score_id),
            "peak_score": _safe_float(gate_out.smoothed_score),
            "raw_score": _safe_float(gate_out.raw_score),
            "threshold_value": _safe_float(gate_out.threshold_value),
            "ratio": ratio,
            "above_threshold": bool(getattr(gate_out, "above_threshold", False)),
            "persistent": bool(gate_out.persistent),
            "persistence_hits": int(gate_out.persistence_hits),
            "persistence_window": int(gate_summary.get("persistence_window", cfg.deep_persistence_window)),
            "persistence_required_hits": int(cfg.deep_persistence_required_hits),
            "event_type": gate_summary.get("event_type", "deep_semantic_spatiotemporal_anomaly"),
            "severity": gate_summary.get("severity", "medium"),
            "reason_when_fired": gate_summary.get("reason_when_fired", "deep_semantic_spatiotemporal_anomaly"),
            "event_policy": event_policy,
        },
        "deep_gate": {
            "model_family": "VideoMAE + kNN normal-memory distance",
            "videomae_model": cfg.deep_videomae_model,
            "embedding_type": "union person crop sequence",
            "deep_k": int(cfg.deep_k),
            "threshold_key": cfg.deep_threshold_key,
            "threshold_method": "calibrated percentile threshold, usually p99.5",
            "sample_fps": float(cfg.deep_route_fps),
            "tubelet_frames": int(cfg.deep_tubelet_frames),
            "stride": int(cfg.deep_stride),
            "bbox_pad_ratio": float(cfg.deep_bbox_pad_ratio),
            "crop_size": int(cfg.deep_crop_size),
            "smoothing_sigma": float(cfg.deep_smoothing_sigma),
            "feature_values": feature_values,
            "metadata": gate_metadata,
        },
        "visual_evidence": {
            "storage_backend": "minio",
            "bucket": cfg.minio_bucket,
            "object_keys": object_keys,
            "objects": evidence_objects,
            "role_counts": role_counts,
            "media_object_ids": [int(x) for x in media_object_ids],
            "evidence_item_ids": [int(x) for x in evidence_item_ids],
            "expected_roles": [
                "annotated_frame",
                "tubelet_montage",
                "tubelet_frame",
                "event_metadata",
            ],
            "notes": "A later reasoning worker should resolve MinIO object keys into signed URLs or local bytes before calling the VLM.",
        },
        "scene_context": {
            "environment": "indoor lab",
            "camera_type": "fixed wide security camera",
            "normal_activity_examples": [
                "walking normally",
                "standing",
                "sitting",
                "working near lab equipment",
                "moving chairs slowly",
            ],
            "known_false_positive_risks": [
                "chair movement",
                "partial occlusion",
                "sitting or standing transition",
                "poor crop quality",
                "person near frame edge",
                "normal activity that is visually rare in the calibration set",
            ],
        },
        "requested_output_schema": {
            "alert_decision": "YES | NO | UNCERTAIN",
            "severity": "LOW | MEDIUM | HIGH | CRITICAL",
            "confidence": "float from 0 to 1",
            "visual_evidence": "short visual description grounded in the provided frames",
            "reasoning_summary": "concise explanation of whether the event appears abnormal",
            "decision_reason": "why the final alert_decision was chosen",
            "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
            "possible_false_positive_causes": "array of strings",
        },
    }


def should_queue_deep_reasoning(
    cfg: VadConfig,
    *,
    gate_name: str,
    persistent: bool,
    peak_score: float,
    threshold_value: float,
    evidence_result: Any,
) -> tuple[bool, str, float | None]:
    if not cfg.deep_reasoning_enabled:
        return False, "deep_reasoning_disabled", None
    if gate_name != "deep":
        return False, "not_deep_gate", None
    if not persistent:
        return False, "event_not_persistent", None
    ratio = _ratio(peak_score, threshold_value)
    if ratio is None:
        return False, "invalid_threshold", None
    if ratio < float(cfg.deep_reasoning_min_ratio):
        return False, "ratio_below_minimum", ratio
    object_keys = list(getattr(evidence_result, "object_keys", []) or [])
    if cfg.deep_reasoning_require_evidence and not object_keys:
        return False, "evidence_required_but_missing", ratio
    return True, "queued", ratio


def queue_deep_reasoning_job(
    conn: psycopg.Connection,
    *,
    cfg: VadConfig,
    db: VadDB,
    case_id: int,
    gate_event_id: int,
    session_id: int,
    stream_id: int,
    camera_id: int | None,
    db_track_id: int | None,
    tracker_track_id: int,
    tubelet_id: int,
    score_id: int,
    gate_out: Any,
    gate_summary: dict[str, Any],
    event_policy: dict[str, Any],
    evidence_result: Any,
) -> int | None:
    """Queue one VLM+LLM reasoning job for a Deep gate event.

    This function intentionally only writes a queued DB job. It never calls a VLM
    directly, so the live RTSP pipeline is not blocked by reasoning.
    """
    should_queue, reason, ratio = should_queue_deep_reasoning(
        cfg,
        gate_name=str(gate_summary.get("gate_name", "")),
        persistent=bool(gate_summary.get("persistent", False)),
        peak_score=_safe_float(gate_summary.get("smoothed_score", gate_summary.get("raw_score"))),
        threshold_value=_safe_float(gate_summary.get("threshold_value")),
        evidence_result=evidence_result,
    )
    metadata = {
        "source": "vad-service",
        "source_gate_event_id": int(gate_event_id),
        "source_gate_name": "deep",
        "routing_policy": DEEP_REASONING_ROUTING_POLICY,
        "routing_decision": reason,
        "ratio": ratio,
    }
    if not should_queue:
        log.info("Skipped Deep reasoning job for gate_event_id=%s: %s", gate_event_id, reason)
        return None

    existing = db.get_existing_reasoning_job_for_gate_event(
        conn,
        case_id=int(case_id),
        gate_event_id=int(gate_event_id),
        gate_name="deep",
    )
    if existing:
        log.info("Deep reasoning job already exists for gate_event_id=%s: job_id=%s", gate_event_id, existing.get("id"))
        return int(existing["id"])

    bundle = build_deep_reasoning_bundle(
        cfg=cfg,
        case_id=case_id,
        gate_event_id=gate_event_id,
        session_id=session_id,
        stream_id=stream_id,
        camera_id=camera_id,
        db_track_id=db_track_id,
        tracker_track_id=tracker_track_id,
        tubelet_id=tubelet_id,
        score_id=score_id,
        gate_out=gate_out,
        gate_summary=gate_summary,
        event_policy=event_policy,
        evidence_result=evidence_result,
    )
    job_id = db.insert_reasoning_job(
        conn,
        case_id=int(case_id),
        reasoner_type="vlm_llm",
        priority=cfg.deep_reasoning_priority,
        input_bundle_json=bundle,
        prompt_version=cfg.deep_reasoning_prompt_version,
        max_attempts=cfg.deep_reasoning_max_attempts,
        metadata_json=metadata,
    )
    log.info("Queued Deep VLM/LLM reasoning job %s for gate_event_id=%s", job_id, gate_event_id)
    return int(job_id)

def queue_cofire_reasoning_job(
    conn: psycopg.Connection,
    *,
    cfg: VadConfig,
    db: VadDB,
    my_gate_name: str,
    my_case_id: int,
    my_gate_event_id: int,
    my_gate_out: Any,
    my_gate_summary: dict[str, Any],
    my_event_policy: dict[str, Any],
    my_evidence_result: Any,
    overlap: dict[str, Any],
    session_id: int,
    stream_id: int,
    camera_id: int | None,
    db_track_id: int | None,
    tracker_track_id: int,
    tubelet_id: int,
    score_id: int,
    tubelet_start_ts: Any,
    tubelet_peak_ts: Any,
) -> int | None:
    """Queue exactly one VLM job for a co-fire event (pose + deep both fired).

    Always uses Deep evidence frames regardless of which gate is calling this.
    Pose signal is injected as metadata text only.
    Returns None if a job was already queued for this co-fire.
    """
    # Determine which gate is deep and which is pose
    if my_gate_name == "deep":
        deep_case_id = my_case_id
        deep_gate_event_id = my_gate_event_id
        deep_gate_out = my_gate_out
        deep_gate_summary = my_gate_summary
        deep_evidence_result = my_evidence_result
        pose_case_id = int(overlap["case_id"])
        pose_gate_event_id = int(overlap["id"])
        pose_evidence_bundle = overlap.get("evidence_bundle_json") or {}
        pose_score = _safe_float(overlap.get("peak_score"))
        pose_smooth = _safe_float(overlap.get("smoothed_score"))
    else:
        # I am pose, overlap is deep
        deep_case_id = int(overlap["case_id"])
        deep_gate_event_id = int(overlap["id"])
        deep_evidence_bundle = overlap.get("evidence_bundle_json") or {}
        deep_object_keys = deep_evidence_bundle.get("object_keys") or []
        pose_case_id = my_case_id
        pose_gate_event_id = my_gate_event_id
        pose_gate_out = my_gate_out
        pose_gate_summary = my_gate_summary
        pose_evidence_result = my_evidence_result
        pose_score = _safe_float(my_gate_summary.get("smoothed_score"))
        pose_smooth = pose_score

    # Check for existing job on the deep case (the canonical one)
    existing = db.get_existing_reasoning_job_for_gate_event(
        conn,
        case_id=deep_case_id,
        gate_event_id=deep_gate_event_id,
        gate_name="deep",
    )
    if existing:
        log.info(
            "Co-fire: VLM job already exists for deep case_id=%s gate_event_id=%s job_id=%s",
            deep_case_id, deep_gate_event_id, existing.get("id"),
        )
        return int(existing["id"])

    # Build the deep bundle as the primary bundle but inject pose co-fire signal
    if my_gate_name == "deep":
        object_keys = list(getattr(deep_evidence_result, "object_keys", []) or [])
        media_object_ids = list(getattr(deep_evidence_result, "media_object_ids", []) or [])
        evidence_item_ids = list(getattr(deep_evidence_result, "evidence_item_ids", []) or [])
        ratio = _ratio(deep_gate_out.smoothed_score, deep_gate_out.threshold_value)
        gate_metadata = dict(getattr(deep_gate_out, "metadata", {}) or {})
        feature_values = dict(getattr(deep_gate_out, "feature_values", {}) or {})
        peak_score = _safe_float(deep_gate_out.smoothed_score)
        raw_score = _safe_float(deep_gate_out.raw_score)
        threshold_value = _safe_float(deep_gate_out.threshold_value)
        persistence_hits = int(deep_gate_out.persistence_hits)
        persistence_window = int(deep_gate_summary.get("persistence_window", cfg.deep_persistence_window))
        persistence_required = int(cfg.deep_persistence_required_hits)
    else:
        object_keys = list(deep_object_keys)
        media_object_ids = []
        evidence_item_ids = []
        ratio = None
        gate_metadata = {}
        feature_values = {}
        peak_score = 0.0
        raw_score = 0.0
        threshold_value = _safe_float(cfg.deep_threshold_value)
        persistence_hits = 0
        persistence_window = int(cfg.deep_persistence_window)
        persistence_required = int(cfg.deep_persistence_required_hits)

    role_counts: dict[str, int] = {}
    evidence_objects: list[dict[str, Any]] = []
    for rank, key in enumerate(object_keys):
        role = _role_from_object_key(str(key))
        role_counts[role] = role_counts.get(role, 0) + 1
        evidence_objects.append({"rank": rank, "role": role, "object_key": str(key)})

    bundle: dict[str, Any] = {
        "job_type": "vad_event_reasoning",
        "reasoning_scope": "deep_gate_only",
        "routing_policy": "cofire_deep_pose_v1",
        "cofire": {
            "detected": True,
            "gates_fired": ["deep", "pose"],
            "deep_case_id": deep_case_id,
            "deep_gate_event_id": deep_gate_event_id,
            "pose_case_id": pose_case_id,
            "pose_gate_event_id": pose_gate_event_id,
            "pose_score": pose_score,
            "pose_smoothed_score": pose_smooth,
            "note": "Both Deep and Pose gates fired on this track with overlapping time. Deep frames are used for VLM. Pose signal is provided as metadata only.",
        },
        "event": {
            "case_id": int(deep_case_id),
            "gate_event_id": int(deep_gate_event_id),
            "gate_name": "deep",
            "gate_display_name": "Deep Visual Similarity Gate (co-fire with Pose)",
            "session_id": int(session_id),
            "stream_id": int(stream_id),
            "camera_id": int(camera_id) if camera_id is not None else None,
            "stream_key": cfg.stream_key,
            "camera_key": cfg.camera_key,
            "db_track_id": int(db_track_id) if db_track_id is not None else None,
            "tracker_track_id": int(tracker_track_id),
            "tubelet_id": int(tubelet_id),
            "score_id": int(score_id),
            "peak_score": peak_score,
            "raw_score": raw_score,
            "threshold_value": threshold_value,
            "ratio": ratio,
            "above_threshold": True,
            "persistent": True,
            "persistence_hits": persistence_hits,
            "persistence_window": persistence_window,
            "persistence_required_hits": persistence_required,
            "event_type": "deep_semantic_spatiotemporal_anomaly",
            "severity": "medium",
            "reason_when_fired": "cofire_deep_and_pose",
            "event_policy": my_event_policy,
        },
        "deep_gate": {
            "model_family": "VideoMAE + kNN normal-memory distance",
            "videomae_model": cfg.deep_videomae_model,
            "embedding_type": "union person crop sequence",
            "deep_k": int(cfg.deep_k),
            "threshold_key": cfg.deep_threshold_key,
            "threshold_method": "calibrated percentile threshold, usually p99.5",
            "sample_fps": float(cfg.deep_route_fps),
            "tubelet_frames": int(cfg.deep_tubelet_frames),
            "stride": int(cfg.deep_stride),
            "smoothing_sigma": float(cfg.deep_smoothing_sigma),
            "feature_values": feature_values,
            "metadata": gate_metadata,
        },
        "visual_evidence": {
            "storage_backend": "minio",
            "bucket": cfg.minio_bucket,
            "object_keys": object_keys,
            "objects": evidence_objects,
            "role_counts": role_counts,
            "media_object_ids": [int(x) for x in media_object_ids],
            "evidence_item_ids": [int(x) for x in evidence_item_ids],
            "expected_roles": ["annotated_frame", "tubelet_montage", "tubelet_frame", "event_metadata"],
            "notes": "Deep frames used. Pose evidence stored separately in MinIO under pose case.",
        },
        "scene_context": {
            "environment": "indoor lab",
            "camera_type": "fixed wide security camera",
            "normal_activity_examples": [
                "walking normally", "standing", "sitting",
                "working near lab equipment", "moving chairs slowly",
            ],
            "known_false_positive_risks": [
                "chair movement", "partial occlusion",
                "sitting or standing transition", "poor crop quality",
                "person near frame edge",
                "normal activity that is visually rare in the calibration set",
            ],
        },
        "requested_output_schema": {
            "alert_decision": "YES | NO | UNCERTAIN",
            "severity": "LOW | MEDIUM | HIGH | CRITICAL",
            "confidence": "float from 0 to 1",
            "visual_evidence": "short visual description grounded in the provided frames",
            "reasoning_summary": "concise explanation of whether the event appears abnormal",
            "decision_reason": "why the final alert_decision was chosen",
            "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
            "possible_false_positive_causes": "array of strings",
        },
    }

    metadata = {
        "source": "vad-service",
        "source_gate_event_id": int(deep_gate_event_id),
        "source_gate_name": "deep",
        "routing_policy": "cofire_deep_pose_v1",
        "cofire": True,
        "pose_gate_event_id": int(pose_gate_event_id),
        "pose_case_id": int(pose_case_id),
        "routing_decision": "cofire_queued",
    }

    job_id = db.insert_reasoning_job(
        conn,
        case_id=int(deep_case_id),
        reasoner_type="vlm_llm",
        priority=cfg.deep_reasoning_priority,
        input_bundle_json=bundle,
        prompt_version=cfg.deep_reasoning_prompt_version,
        max_attempts=cfg.deep_reasoning_max_attempts,
        metadata_json=metadata,
    )
    log.info(
        "Queued co-fire VLM job %s: deep_case=%s pose_case=%s track=%s",
        job_id, deep_case_id, pose_case_id, tracker_track_id,
    )
    return int(job_id)

def build_pose_reasoning_bundle(
    *,
    cfg: VadConfig,
    case_id: int,
    gate_event_id: int,
    session_id: int,
    stream_id: int,
    camera_id: int | None,
    db_track_id: int | None,
    tracker_track_id: int,
    tubelet_id: int,
    score_id: int,
    gate_out: Any,
    gate_summary: dict[str, Any],
    event_policy: dict[str, Any],
    evidence_result: Any,
) -> dict[str, Any]:
    """Build the compact Pose-only input packet stored for later VLM+LLM work."""
    object_keys = list(getattr(evidence_result, "object_keys", []) or [])
    media_object_ids = list(getattr(evidence_result, "media_object_ids", []) or [])
    evidence_item_ids = list(getattr(evidence_result, "evidence_item_ids", []) or [])
    role_counts: dict[str, int] = {}
    evidence_objects: list[dict[str, Any]] = []
    for rank, key in enumerate(object_keys):
        role = _role_from_object_key(str(key))
        role_counts[role] = role_counts.get(role, 0) + 1
        evidence_objects.append({"rank": rank, "role": role, "object_key": str(key)})

    ratio = _ratio(gate_out.smoothed_score, gate_out.threshold_value)
    gate_metadata = dict(getattr(gate_out, "metadata", {}) or {})
    feature_values = dict(getattr(gate_out, "feature_values", {}) or {})

    return {
        "job_type": "vad_event_reasoning",
        "reasoning_scope": "pose_gate_only",
        "routing_policy": POSE_REASONING_ROUTING_POLICY,
        "event": {
            "case_id": int(case_id),
            "gate_event_id": int(gate_event_id),
            "gate_name": "pose",
            "gate_display_name": "Pose Micro GMM Gate",
            "session_id": int(session_id),
            "stream_id": int(stream_id),
            "camera_id": int(camera_id) if camera_id is not None else None,
            "stream_key": cfg.stream_key,
            "camera_key": cfg.camera_key,
            "db_track_id": int(db_track_id) if db_track_id is not None else None,
            "tracker_track_id": int(tracker_track_id),
            "tubelet_id": int(tubelet_id),
            "score_id": int(score_id),
            "peak_score": _safe_float(gate_out.smoothed_score),
            "raw_score": _safe_float(gate_out.raw_score),
            "threshold_value": _safe_float(gate_out.threshold_value),
            "ratio": ratio,
            "above_threshold": bool(getattr(gate_out, "above_threshold", False)),
            "persistent": bool(gate_out.persistent),
            "persistence_hits": int(gate_out.persistence_hits),
            "persistence_window": int(gate_summary.get("persistence_window", cfg.pose_persistence_window)),
            "persistence_required_hits": int(cfg.pose_persistence_required_hits),
            "event_type": gate_summary.get("event_type", "rare_pose_articulation"),
            "severity": gate_summary.get("severity", "low"),
            "reason_when_fired": gate_summary.get("reason_when_fired", "rare_pose_articulation"),
            "event_policy": event_policy,
        },
        "pose_gate": {
            "model_family": "YOLO Pose + RobustScaler + GMM negative log-likelihood",
            "pose_model": str(cfg.pose_model),
            "gmm_components": int(cfg.pose_gmm_components),
            "threshold_key": cfg.pose_threshold_key,
            "threshold_method": "calibrated percentile threshold, usually p99.5",
            "sample_fps": float(cfg.pose_route_fps),
            "tubelet_frames": int(cfg.pose_tubelet_frames),
            "stride": int(cfg.pose_stride),
            "kpt_conf": float(cfg.pose_kpt_conf),
            "reinfer_enabled": bool(cfg.pose_reinfer_enabled),
            "smoothing_sigma": float(cfg.pose_smoothing_sigma),
            "feature_values": feature_values,
            "metadata": gate_metadata,
        },
        "visual_evidence": {
            "storage_backend": "minio",
            "bucket": cfg.minio_bucket,
            "object_keys": object_keys,
            "objects": evidence_objects,
            "role_counts": role_counts,
            "media_object_ids": [int(x) for x in media_object_ids],
            "evidence_item_ids": [int(x) for x in evidence_item_ids],
            "expected_roles": [
                "annotated_frame",
                "tubelet_montage",
                "tubelet_frame",
                "event_metadata",
            ],
            "notes": "A later reasoning worker should resolve MinIO object keys into signed URLs or local bytes before calling the VLM.",
        },
        "scene_context": {
            "environment": "indoor lab",
            "camera_type": "fixed wide security camera",
            "normal_activity_examples": [
                "walking normally",
                "standing",
                "sitting",
                "working near lab equipment",
                "moving chairs slowly",
            ],
            "known_false_positive_risks": [
                "sitting or standing transition",
                "reaching for nearby object",
                "partial occlusion hiding limbs",
                "poor keypoint quality or noisy crop",
                "person near frame edge",
                "normal asymmetric movement such as picking something up",
            ],
        },
        "requested_output_schema": {
            "alert_decision": "YES | NO | UNCERTAIN",
            "severity": "LOW | MEDIUM | HIGH | CRITICAL",
            "confidence": "float from 0 to 1",
            "visual_evidence": "short visual description grounded in the provided frames",
            "reasoning_summary": "concise explanation of whether the pose event appears abnormal",
            "decision_reason": "why the final alert_decision was chosen",
            "recommended_action": "ignore | review_only | save_for_dataset | alert_operator | urgent_alert",
            "possible_false_positive_causes": "array of strings",
        },
    }


def should_queue_pose_reasoning(
    cfg: VadConfig,
    *,
    gate_name: str,
    persistent: bool,
    peak_score: float,
    threshold_value: float,
    evidence_result: Any,
) -> tuple[bool, str, float | None]:
    if not cfg.deep_reasoning_enabled:
        return False, "reasoning_disabled", None
    if gate_name != "pose":
        return False, "not_pose_gate", None
    if not persistent:
        return False, "event_not_persistent", None
    ratio = _ratio(peak_score, threshold_value)
    if ratio is None:
        return False, "invalid_threshold", None
    if ratio < float(cfg.deep_reasoning_min_ratio):
        return False, "ratio_below_minimum", ratio
    object_keys = list(getattr(evidence_result, "object_keys", []) or [])
    if cfg.deep_reasoning_require_evidence and not object_keys:
        return False, "evidence_required_but_missing", ratio
    return True, "queued", ratio


def queue_pose_reasoning_job(
    conn: psycopg.Connection,
    *,
    cfg: VadConfig,
    db: VadDB,
    case_id: int,
    gate_event_id: int,
    session_id: int,
    stream_id: int,
    camera_id: int | None,
    db_track_id: int | None,
    tracker_track_id: int,
    tubelet_id: int,
    score_id: int,
    gate_out: Any,
    gate_summary: dict[str, Any],
    event_policy: dict[str, Any],
    evidence_result: Any,
) -> int | None:
    """Queue one VLM+LLM reasoning job for a Pose gate event.

    This function intentionally only writes a queued DB job. It never calls a VLM
    directly, so the live RTSP pipeline is not blocked by reasoning.
    """
    should_queue, reason, ratio = should_queue_pose_reasoning(
        cfg,
        gate_name=str(gate_summary.get("gate_name", "")),
        persistent=bool(gate_summary.get("persistent", False)),
        peak_score=_safe_float(gate_summary.get("smoothed_score", gate_summary.get("raw_score"))),
        threshold_value=_safe_float(gate_summary.get("threshold_value")),
        evidence_result=evidence_result,
    )
    metadata = {
        "source": "vad-service",
        "source_gate_event_id": int(gate_event_id),
        "source_gate_name": "pose",
        "routing_policy": POSE_REASONING_ROUTING_POLICY,
        "routing_decision": reason,
        "ratio": ratio,
    }
    if not should_queue:
        log.info("Skipped Pose reasoning job for gate_event_id=%s: %s", gate_event_id, reason)
        return None

    existing = db.get_existing_reasoning_job_for_gate_event(
        conn,
        case_id=int(case_id),
        gate_event_id=int(gate_event_id),
        gate_name="pose",
    )
    if existing:
        log.info("Pose reasoning job already exists for gate_event_id=%s: job_id=%s", gate_event_id, existing.get("id"))
        return int(existing["id"])

    bundle = build_pose_reasoning_bundle(
        cfg=cfg,
        case_id=case_id,
        gate_event_id=gate_event_id,
        session_id=session_id,
        stream_id=stream_id,
        camera_id=camera_id,
        db_track_id=db_track_id,
        tracker_track_id=tracker_track_id,
        tubelet_id=tubelet_id,
        score_id=score_id,
        gate_out=gate_out,
        gate_summary=gate_summary,
        event_policy=event_policy,
        evidence_result=evidence_result,
    )
    job_id = db.insert_reasoning_job(
        conn,
        case_id=int(case_id),
        reasoner_type="vlm_llm",
        priority=cfg.deep_reasoning_priority,
        input_bundle_json=bundle,
        prompt_version=cfg.deep_reasoning_prompt_version,
        max_attempts=cfg.deep_reasoning_max_attempts,
        metadata_json=metadata,
    )
    log.info("Queued Pose VLM/LLM reasoning job %s for gate_event_id=%s", job_id, gate_event_id)
    return int(job_id)
    