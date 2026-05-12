from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import (
    ALLOW_SERVICE_BOOT_WITHOUT_MODEL,
    VIDEO_ENCODER_MODEL,
    TUBELET_FRAMES,
    SAMPLE_FPS,
    STRIDE,
    PERSON_SIZE,
    CONTEXT_SIZE,
    PERSON_PADDING,
    CONTEXT_SCALE,
    DISTRIBUTION_THRESHOLD_NAME,
    HIGH_SPEED_THRESHOLD,
    ABRUPT_ANGLE_THRESHOLD,
    MIN_TURN_SPEED,
    MAX_TRACK_GAP,
    CANDIDATE_COOLDOWN_SEC,
    OLLAMA_HOST,
    VLM_MODEL,
    LLM_MODEL,
)
from db import DB
from distribution_scorer import DistributionScorer
from evidence_io import fetch_clip_frames, fetch_frames
from motion_gates import evaluate_motion_gates, build_candidate_reasons, assign_priority, GateDecision

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("anomaly_service")

app = FastAPI(title="Anomaly Service - Dual Stream Distribution")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = DB()
scorer = DistributionScorer()


NEW_STATUS_FALLBACK = {
    "alert_confirmed": "resolved",
    "dismissed_normal": "discarded",
    "needs_review": "resolved",
    "reasoning_failed": "pending",
}


def update_candidate_status_compatible(conn, candidate_id: int, preferred_status: str) -> str:
    """Use the improved status names when the DB allows them; otherwise fall back."""
    fallback = NEW_STATUS_FALLBACK.get(preferred_status, "pending")
    conn.execute("SAVEPOINT candidate_status_update")
    try:
        updated = db.update_anomaly_candidate_status(
            conn,
            anomaly_candidate_id=candidate_id,
            status=preferred_status,
        )
        conn.execute("RELEASE SAVEPOINT candidate_status_update")
        if not updated:
            raise HTTPException(404, detail="Anomaly candidate not found")
        return preferred_status
    except HTTPException:
        raise
    except Exception as e:
        conn.execute("ROLLBACK TO SAVEPOINT candidate_status_update")
        log.warning("Could not use candidate status '%s' (%s); falling back to '%s'", preferred_status, e, fallback)
        updated = db.update_anomaly_candidate_status(
            conn,
            anomaly_candidate_id=candidate_id,
            status=fallback,
        )
        if not updated:
            raise HTTPException(404, detail="Anomaly candidate not found")
        return fallback


class PersonContextTubeletPayload(BaseModel):
    device_key: str
    camera_id: int
    track_id: Optional[int] = None
    event_key: Optional[str] = None
    window_start_ts: str
    window_end_ts: Optional[str] = None

    person_frames: Optional[list[str]] = None
    context_frames: Optional[list[str]] = None
    person_clip_ref: Optional[str] = None
    context_clip_ref: Optional[str] = None
    representative_frame_ref: Optional[str] = None

    person_bbox_sequence: Optional[list[dict[str, Any]]] = None
    motion_stats: Optional[dict[str, Any]] = None

    high_speed_gate: Optional[bool] = None
    abrupt_direction_gate: Optional[bool] = None
    track_instability_gate: Optional[bool] = None

    precomputed_person_embedding: Optional[list[float]] = None
    precomputed_context_embedding: Optional[list[float]] = None
    metadata: Optional[dict[str, Any]] = None


class ReviewPayload(BaseModel):
    decision: str = Field(..., pattern=r"^(confirmed|dismissed|uncertain|normal_calibration)$")
    rule_text: Optional[str] = None
    rule_type: str = Field("trigger", pattern=r"^(trigger|suppress)$")
    event_type: str = "other"
    conditions: Optional[dict[str, Any]] = None
    reviewer: Optional[str] = None
    notes: Optional[str] = None


class CreateRulePayload(BaseModel):
    rule_text: str
    rule_type: str = Field("trigger", pattern=r"^(trigger|suppress)$")
    event_type: str = "other"
    conditions: Optional[dict[str, Any]] = None
    source: str = "Admin"


@app.on_event("startup")
async def startup() -> None:
    try:
        scorer.load_distribution_artifacts()
    except Exception as e:
        log.warning("Distribution artifacts not ready at startup: %s", e)
        if not ALLOW_SERVICE_BOOT_WITHOUT_MODEL:
            raise


def _threshold_from_db_or_artifact(thresholds: dict[str, Any]) -> tuple[str, float]:
    # Prefer DB thresholds, but keep artifact threshold as fallback.
    name = DISTRIBUTION_THRESHOLD_NAME.replace("final.", "")
    db_key = f"final_{name}"
    if thresholds.get(db_key) is not None:
        return name, float(thresholds[db_key])
    if thresholds.get("recommended_threshold_value") is not None:
        raw = str(thresholds.get("recommended_threshold_name") or DISTRIBUTION_THRESHOLD_NAME)
        return raw.replace("final.", ""), float(thresholds["recommended_threshold_value"])
    return scorer.get_threshold(DISTRIBUTION_THRESHOLD_NAME)


def _motion_value(stats: dict[str, Any] | None, *keys: str) -> float | None:
    for key in keys:
        value = (stats or {}).get(key)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _motion_reason(stats: dict[str, Any] | None) -> str | None:
    value = (stats or {}).get("track_instability_reason") or (stats or {}).get("instability_reason")
    return str(value) if value else None


def _gate_decision_rows(
    *,
    distribution_gate: bool,
    final_score: float,
    threshold_value: float,
    motion_decisions: dict[str, GateDecision],
) -> list[GateDecision]:
    return [
        GateDecision(
            name="distribution_score",
            fired=distribution_gate,
            score_value=final_score,
            threshold_value=threshold_value,
            reason=(
                f"final_score={final_score:.4f} exceeded threshold={threshold_value:.4f}"
                if distribution_gate else "Distribution score gate did not fire"
            ),
            details={"final_score": final_score, "threshold_value": threshold_value},
        ),
        *motion_decisions.values(),
    ]


@app.get("/health")
def health() -> dict[str, Any]:
    active_model_id = None
    threshold_name = None
    threshold_value = None
    try:
        with db.connect() as conn:
            active_model = db.get_active_model(conn)
            active_model_id = active_model["id"]
            thresholds = db.get_distribution_thresholds(conn, active_model_id)
            threshold_name, threshold_value = _threshold_from_db_or_artifact(thresholds)
    except Exception as e:
        log.warning("Health DB/model check failed: %s", e)

    return {
        "ok": True,
        "video_encoder_loaded": scorer.encoder_loaded,
        "video_encoder_model": VIDEO_ENCODER_MODEL,
        "distribution_artifacts_loaded": scorer.artifacts_loaded,
        "distribution_artifact_error": scorer.artifact_error,
        "active_model_id": active_model_id,
        "threshold_name": threshold_name,
        "threshold_value": threshold_value,
        "vlm_model": VLM_MODEL,
        "llm_model": LLM_MODEL,
        "ollama_host": OLLAMA_HOST,
    }


@app.post("/ingest/scene_embedding")
def deprecated_scene_embedding() -> dict[str, Any]:
    raise HTTPException(
        status_code=410,
        detail=(
            "Deprecated endpoint. The old student/teacher /ingest/scene_embedding flow is disabled. "
            "Use POST /ingest/person-context-tubelet with person/context embeddings or evidence refs."
        ),
    )


@app.post("/ingest/person-context-tubelet")
def ingest_person_context_tubelet(p: PersonContextTubeletPayload) -> dict[str, Any]:
    try:
        scorer.load_distribution_artifacts()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Distribution artifacts not ready: {e}")

    # 1) Embeddings: use provided embeddings or extract from evidence.
    try:
        if p.precomputed_person_embedding is not None:
            person_embedding = scorer.validate_embedding(p.precomputed_person_embedding, name="precomputed_person_embedding")
        else:
            person_frames = fetch_frames(p.person_frames or []) if p.person_frames else fetch_clip_frames(p.person_clip_ref) if p.person_clip_ref else []
            if not person_frames:
                raise ValueError("person embedding missing and no person_frames/person_clip_ref was provided")
            person_embedding = scorer.extract_videomae_embedding(person_frames)

        if p.precomputed_context_embedding is not None:
            context_embedding = scorer.validate_embedding(p.precomputed_context_embedding, name="precomputed_context_embedding")
        else:
            context_frames = fetch_frames(p.context_frames or []) if p.context_frames else fetch_clip_frames(p.context_clip_ref) if p.context_clip_ref else []
            if not context_frames:
                raise ValueError("context embedding missing and no context_frames/context_clip_ref was provided")
            context_embedding = scorer.extract_videomae_embedding(context_frames)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            active_model = db.get_active_model(conn)
            model_id = int(active_model["id"])
            thresholds = db.get_distribution_thresholds(conn, model_id)
            gate_configs = db.get_gate_configs(conn, model_id)
            device_id = db.upsert_edge_device(conn, p.device_key)

            score = scorer.score_person_context(
                person_embedding,
                context_embedding,
                threshold_name=DISTRIBUTION_THRESHOLD_NAME,
            )
            threshold_name, threshold_value = _threshold_from_db_or_artifact(thresholds)
            distribution_gate = bool(score.final_score > threshold_value)

            high_speed_threshold = float(gate_configs.get("high_speed", {}).get("threshold_value") or HIGH_SPEED_THRESHOLD)
            abrupt_threshold = float(gate_configs.get("abrupt_direction_change", {}).get("threshold_value") or ABRUPT_ANGLE_THRESHOLD)
            track_gap_threshold = int(gate_configs.get("track_instability", {}).get("threshold_value") or MAX_TRACK_GAP)
            abrupt_params = gate_configs.get("abrupt_direction_change", {}).get("params") or {}
            min_turn_speed = float(abrupt_params.get("min_turn_speed", MIN_TURN_SPEED))

            motion_decisions = evaluate_motion_gates(
                p.motion_stats or {},
                high_speed_threshold=high_speed_threshold,
                abrupt_angle_threshold=abrupt_threshold,
                min_turn_speed=min_turn_speed,
                max_track_gap=track_gap_threshold,
                edge_high_speed_gate=p.high_speed_gate,
                edge_abrupt_direction_gate=p.abrupt_direction_gate,
                edge_track_instability_gate=p.track_instability_gate,
            )
            candidate_reasons = build_candidate_reasons(
                distribution_gate=distribution_gate,
                motion_decisions=motion_decisions,
            )
            priority = assign_priority(
                final_score=score.final_score,
                p97=thresholds.get("final_p97") or threshold_value,
                p99=thresholds.get("final_p99"),
                p99_5=thresholds.get("final_p99_5"),
                candidate_reasons=candidate_reasons,
            )
            is_candidate = bool(candidate_reasons)

            evidence_payload = {
                "person_frames": p.person_frames or [],
                "context_frames": p.context_frames or [],
                "person_clip_ref": p.person_clip_ref,
                "context_clip_ref": p.context_clip_ref,
                "representative_frame_ref": p.representative_frame_ref,
                "event_key": p.event_key,
                "device_key": p.device_key,
                "camera_id": p.camera_id,
                "track_id": p.track_id,
                "window_start_ts": p.window_start_ts,
                "window_end_ts": p.window_end_ts,
            }

            scene_id = db.insert_scene_window_embedding(
                conn,
                model_id=model_id,
                device_id=device_id,
                camera_id=p.camera_id,
                track_id=p.track_id,
                event_key=p.event_key,
                window_start_ts=p.window_start_ts,
                window_end_ts=p.window_end_ts,
                person_embedding=person_embedding.tolist(),
                context_embedding=context_embedding.tolist(),
                person_score=score.person_score,
                context_score=score.context_score,
                person_score_norm=score.person_score_norm,
                context_score_norm=score.context_score_norm,
                final_score=score.final_score,
                threshold_name=threshold_name,
                threshold_value=threshold_value,
                distribution_gate=distribution_gate,
                high_speed_gate=motion_decisions["high_speed"].fired,
                abrupt_direction_gate=motion_decisions["abrupt_direction_change"].fired,
                track_instability_gate=motion_decisions["track_instability"].fired,
                candidate_reasons=candidate_reasons,
                priority=priority,
                sample_fps=SAMPLE_FPS,
                tubelet_frames=TUBELET_FRAMES,
                stride=STRIDE,
                person_bbox_sequence=p.person_bbox_sequence or [],
                motion_stats=p.motion_stats or {},
                person_clip_ref=p.person_clip_ref,
                context_clip_ref=p.context_clip_ref,
                representative_frame_ref=p.representative_frame_ref,
                person_frame_refs=p.person_frames or [],
                context_frame_refs=p.context_frames or [],
                evidence_payload=evidence_payload,
                video_encoder=VIDEO_ENCODER_MODEL,
            )

            anomaly_candidate_id = None
            reasoning_job_id = None
            dedup_skipped = False

            if is_candidate:
                recent = db.find_recent_candidate(
                    conn,
                    camera_id=p.camera_id,
                    track_id=p.track_id,
                    candidate_reasons=candidate_reasons,
                    final_score=score.final_score,
                    cooldown_sec=CANDIDATE_COOLDOWN_SEC,
                )
                if recent and not recent["allow_duplicate"]:
                    dedup_skipped = True
                else:
                    primary_reason = candidate_reasons[0]
                    anomaly_candidate_id = db.create_anomaly_candidate(
                        conn,
                        scene_window_embedding_id=scene_id,
                        candidate_reasons=candidate_reasons,
                        primary_reason=primary_reason,
                        priority=priority,
                        final_score=score.final_score,
                        person_score=score.person_score,
                        context_score=score.context_score,
                        person_score_norm=score.person_score_norm,
                        context_score_norm=score.context_score_norm,
                        threshold_name=threshold_name,
                        threshold_value=threshold_value,
                        distribution_gate=distribution_gate,
                        high_speed_gate=motion_decisions["high_speed"].fired,
                        abrupt_direction_gate=motion_decisions["abrupt_direction_change"].fired,
                        track_instability_gate=motion_decisions["track_instability"].fired,
                        max_speed_norm=_motion_value(p.motion_stats, "max_speed_norm", "max_speed"),
                        max_turn_angle=_motion_value(p.motion_stats, "max_turn_angle", "turn_angle"),
                        track_instability_reason=_motion_reason(p.motion_stats),
                        person_clip_ref=p.person_clip_ref,
                        context_clip_ref=p.context_clip_ref,
                        representative_frame_ref=p.representative_frame_ref,
                    )

                    for decision in _gate_decision_rows(
                        distribution_gate=distribution_gate,
                        final_score=score.final_score,
                        threshold_value=threshold_value,
                        motion_decisions=motion_decisions,
                    ):
                        db.insert_candidate_gate_decision(
                            conn,
                            candidate_id=anomaly_candidate_id,
                            gate_name=decision.name,
                            gate_fired=decision.fired,
                            score_value=decision.score_value,
                            threshold_value=decision.threshold_value,
                            details=decision.details,
                            reason=decision.reason,
                        )

                    active_rules = db.get_active_rules(conn)
                    request_json = {
                        "scene_window_embedding_id": scene_id,
                        "candidate_id": anomaly_candidate_id,
                        "device_key": p.device_key,
                        "camera_id": p.camera_id,
                        "track_id": p.track_id,
                        "event_key": p.event_key,
                        "window_start_ts": p.window_start_ts,
                        "window_end_ts": p.window_end_ts,
                        "person_clip_ref": p.person_clip_ref,
                        "context_clip_ref": p.context_clip_ref,
                        "representative_frame_ref": p.representative_frame_ref,
                        "person_frames": p.person_frames or [],
                        "context_frames": p.context_frames or [],
                        "candidate_metadata": {
                            "final_score": score.final_score,
                            "threshold_name": threshold_name,
                            "threshold_value": threshold_value,
                            "candidate_reasons": candidate_reasons,
                            "priority": priority,
                            "camera_id": p.camera_id,
                            "window_start_ts": p.window_start_ts,
                            "window_end_ts": p.window_end_ts,
                            "motion_stats": p.motion_stats or {},
                        },
                        "active_rules": active_rules,
                    }
                    reasoning_job_id = db.enqueue_reasoning_job(
                        conn,
                        anomaly_candidate_id=anomaly_candidate_id,
                        model_name=VLM_MODEL,
                        job_type="vlm_reasoning",
                        prompt=(
                            "Describe visible people, posture, movement, interactions, and physical contact. "
                            "Count all people visible. Be factual. Do not speculate beyond visible evidence."
                        ),
                        request_json=request_json,
                    )

            conn.execute("COMMIT")
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(status_code=500, detail=str(e))

    return {
        "scene_window_embedding_id": scene_id,
        "is_candidate": is_candidate and not dedup_skipped,
        "dedup_skipped": dedup_skipped,
        "candidate_reasons": candidate_reasons,
        "priority": priority,
        "final_score": score.final_score,
        "person_score": score.person_score,
        "context_score": score.context_score,
        "person_score_norm": score.person_score_norm,
        "context_score_norm": score.context_score_norm,
        "threshold_name": threshold_name,
        "threshold_value": threshold_value,
        "distribution_gate": distribution_gate,
        "high_speed_gate": motion_decisions["high_speed"].fired,
        "abrupt_direction_gate": motion_decisions["abrupt_direction_change"].fired,
        "track_instability_gate": motion_decisions["track_instability"].fired,
        "anomaly_candidate_id": anomaly_candidate_id,
        "reasoning_job_id": reasoning_job_id,
    }


@app.post("/anomaly-candidates/{candidate_id}/review")
def review_candidate(candidate_id: int, rv: ReviewPayload) -> dict[str, Any]:
    status_map = {
        "confirmed": "alert_confirmed",
        "dismissed": "dismissed_normal",
        "uncertain": "needs_review",
        "normal_calibration": "dismissed_normal"
    }
    new_status = status_map[rv.decision]
    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            created_rule_id = None
            if rv.rule_text:
                created_rule_id = db.insert_anomaly_rule(
                    conn,
                    rule_text=rv.rule_text,
                    rule_type=rv.rule_type,
                    event_type=rv.event_type,
                    conditions=rv.conditions or {},
                )
            review_id = db.insert_candidate_review(
                conn,
                anomaly_candidate_id=candidate_id,
                decision=rv.decision,
                reviewer=rv.reviewer,
                notes=rv.notes,
                rule_text=rv.rule_text,
                created_rule_id=created_rule_id,
            )
            new_status = update_candidate_status_compatible(conn, candidate_id, new_status)
            conn.execute("COMMIT")
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(500, detail=str(e))
    return {"review_id": review_id, "anomaly_candidate_id": candidate_id, "candidate_status": new_status, "rule_id": created_rule_id}


@app.post("/anomaly-rules")
def create_rule(p: CreateRulePayload) -> dict[str, Any]:
    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            rule_id = db.insert_anomaly_rule(
                conn,
                rule_text=p.rule_text,
                rule_type=p.rule_type,
                event_type=p.event_type,
                conditions=p.conditions or {},
                source=p.source,
            )
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(500, detail=str(e))
    return {"rule_id": rule_id, "rule_text": p.rule_text, "rule_type": p.rule_type}


@app.get("/anomaly-candidates")
def list_anomaly_candidates(limit: int = 500, offset: int = 0) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ac.id, ac.status, ac.created_at,
                swe.camera_id, swe.track_id,
                ac.priority, ac.final_score, ac.candidate_reasons,
                ac.person_clip_ref, ac.context_clip_ref, ac.representative_frame_ref,
                llm.response_json->'structured_decision'->>'alert_decision' AS alert_decision,
                llm.response_json->'structured_decision'->>'severity' AS severity,
                llm.response_json->'structured_decision'->>'event_type' AS event_type,
                llm.response_json->'structured_decision'->>'confidence' AS confidence,
                llm.response_json->'structured_decision'->>'reason' AS reason,
                ac.threshold_value, ac.threshold_name,
                ac.person_score, ac.context_score,
                ac.person_score_norm, ac.context_score_norm,
                COALESCE(swe.person_frame_refs, swe.evidence_payload->'person_frames', '[]'::jsonb) AS person_frame_refs,
                COALESCE(swe.context_frame_refs, swe.evidence_payload->'context_frames', '[]'::jsonb) AS context_frame_refs
            FROM anomaly_candidates ac
            LEFT JOIN scene_window_embeddings swe ON swe.id = ac.scene_window_embedding_id
            LEFT JOIN LATERAL (
                SELECT response_json
                FROM reasoning_jobs
                WHERE anomaly_candidate_id = ac.id
                  AND status = 'succeeded'
                  AND job_type = 'llm_reasoning'
                ORDER BY finished_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            ) llm ON TRUE
            ORDER BY ac.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
    return [
        {
            "id": r[0],
            "status": r[1],
            "createdAt": r[2],
            "cameraId": r[3],
            "trackId": r[4],
            "priority": r[5],
            "finalScore": r[6],
            "candidateReasons": r[7] or [],
            "personClipRef": r[8],
            "contextClipRef": r[9],
            "representativeFrameRef": r[10],
            "alertDecision": r[11],
            "severity": r[12],
            "eventType": r[13],
            "confidence": float(r[14]) if r[14] else None,
            "reason": r[15],
            "thresholdValue": r[16],
            "thresholdName": r[17],
            "personScore": r[18],
            "contextScore": r[19],
            "personScoreNorm": r[20],
            "contextScoreNorm": r[21],
            "personFrameRefs": r[22] or [],
            "contextFrameRefs": r[23] or [],
        }
        for r in rows
    ]


@app.get("/anomaly-candidates/{candidate_id}")
def get_anomaly_candidate(candidate_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT
                ac.id, ac.status, ac.created_at,
                swe.camera_id, swe.track_id,
                ac.priority, ac.final_score, ac.candidate_reasons,
                ac.person_clip_ref, ac.context_clip_ref, ac.representative_frame_ref,
                ac.threshold_value, ac.threshold_name,
                ac.person_score, ac.context_score,
                ac.person_score_norm, ac.context_score_norm,
                COALESCE(swe.person_frame_refs, swe.evidence_payload->'person_frames', '[]'::jsonb) AS person_frame_refs,
                COALESCE(swe.context_frame_refs, swe.evidence_payload->'context_frames', '[]'::jsonb) AS context_frame_refs,
                swe.motion_stats,
                COALESCE(swe.evidence_payload, '{}'::jsonb) AS evidence_payload,
                ac.distribution_gate, ac.high_speed_gate, ac.abrupt_direction_gate, ac.track_instability_gate,
                ac.max_speed_norm, ac.max_turn_angle, ac.track_instability_reason
            FROM anomaly_candidates ac
            LEFT JOIN scene_window_embeddings swe ON swe.id = ac.scene_window_embedding_id
            WHERE ac.id = %s
            """,
            (candidate_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")

        gate_rows = conn.execute(
            """
            SELECT gate_name, gate_fired, score_value, threshold_value, reason, details
            FROM candidate_gate_decisions
            WHERE candidate_id = %s
            ORDER BY gate_name
            """,
            (candidate_id,),
        ).fetchall()

        job_rows = conn.execute(
            """
            SELECT job_type, status, model_name, response_json, response_text, created_at, finished_at AS completed_at
            FROM reasoning_jobs
            WHERE anomaly_candidate_id = %s
            ORDER BY created_at ASC
            """,
            (candidate_id,),
        ).fetchall()

    # Extract structured decision from LLM job if available
    structured_decision = None
    visual_evidence = None
    uncertainty = None
    matched_trigger_rules = []
    matched_suppress_rules = []
    frames_used_info = {}
    
    for job in job_rows:
        if job[0] == "llm_reasoning" and job[1] == "succeeded" and job[3]:
            response_json = job[3]
            structured_decision = response_json.get("structured_decision")
            if structured_decision:
                visual_evidence = structured_decision.get("visual_evidence")
                uncertainty = structured_decision.get("uncertainty")
                matched_trigger_rules = structured_decision.get("matched_trigger_rules", [])
                matched_suppress_rules = structured_decision.get("matched_suppress_rules", [])
            frames_used_info = {
                "frames_used": response_json.get("frames_used", 0),
                "person_frame_count": response_json.get("person_frame_count", 0),
                "context_frame_count": response_json.get("context_frame_count", 0),
            }

    return {
        "id": row[0],
        "status": row[1],
        "createdAt": row[2],
        "cameraId": row[3],
        "trackId": row[4],
        "priority": row[5],
        "finalScore": row[6],
        "candidateReasons": row[7] or [],
        "personClipRef": row[8],
        "contextClipRef": row[9],
        "representativeFrameRef": row[10],
        "thresholdValue": row[11],
        "thresholdName": row[12],
        "personScore": row[13],
        "contextScore": row[14],
        "personScoreNorm": row[15],
        "contextScoreNorm": row[16],
        "personFrameRefs": row[17] or [],
        "contextFrameRefs": row[18] or [],
        "motionStats": row[19] or {},
        "evidencePayload": row[20] or {},
        "distributionGate": row[21],
        "highSpeedGate": row[22],
        "abruptDirectionGate": row[23],
        "trackInstabilityGate": row[24],
        "maxSpeedNorm": row[25],
        "maxTurnAngle": row[26],
        "trackInstabilityReason": row[27],
        # Enhanced frontend visibility fields
        "structuredDecision": structured_decision,
        "visualEvidence": visual_evidence,
        "uncertainty": uncertainty,
        "matchedTriggerRules": matched_trigger_rules,
        "matchedSuppressRules": matched_suppress_rules,
        "framesUsedInfo": frames_used_info,
        "gateDecisions": [
            {
                "gateName": g[0],
                "fired": g[1],
                "scoreValue": g[2],
                "thresholdValue": g[3],
                "reason": g[4],
                "details": g[5] or {},
            }
            for g in gate_rows
        ],
        "reasoningJobs": [
            {
                "jobType": j[0],
                "status": j[1],
                "modelName": j[2],
                "responseJson": j[3],
                "responseText": j[4],
                "createdAt": j[5],
                "completedAt": j[6],
            }
            for j in job_rows
        ],
    }