from __future__ import annotations

import json
from typing import Any, Optional

import psycopg
from pgvector.psycopg import register_vector

from config import DB_DSN, CANDIDATE_COOLDOWN_SEC, VIDEO_ENCODER_MODEL


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


class DB:
    def __init__(self, dsn: str = DB_DSN) -> None:
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn)
        register_vector(conn)
        return conn

    # ------------------------------------------------------------------
    # Model / thresholds / gate config
    # ------------------------------------------------------------------

    def get_active_model_id(self, conn: psycopg.Connection) -> int:
        return int(self.get_active_model(conn)["id"])

    def get_active_model(self, conn: psycopg.Connection) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT id, name, version, model_type, video_encoder,
                   person_embedding_dim, context_embedding_dim, pca_components,
                   score_method, score_normalization, person_weight, context_weight,
                   sample_fps, tubelet_frames, stride,
                   person_size, context_size, person_padding, context_scale,
                   training_dataset_ref, is_active
            FROM normal_behavior_models
            WHERE is_active = TRUE
            ORDER BY activated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            raise RuntimeError("No active normal_behavior_models row found (is_active=true).")

        artifacts = conn.execute(
            """
            SELECT artifact_type, artifact_uri
            FROM normal_behavior_model_artifacts
            WHERE model_id = %s
            """,
            (row[0],),
        ).fetchall()

        return {
            "id": int(row[0]),
            "name": row[1],
            "version": row[2],
            "model_type": row[3],
            "video_encoder": row[4],
            "person_embedding_dim": int(row[5]),
            "context_embedding_dim": int(row[6]),
            "pca_components": int(row[7]),
            "score_method": row[8],
            "score_normalization": row[9],
            "person_weight": float(row[10]),
            "context_weight": float(row[11]),
            "sample_fps": int(row[12]),
            "tubelet_frames": int(row[13]),
            "stride": int(row[14]),
            "person_size": int(row[15]),
            "context_size": int(row[16]),
            "person_padding": float(row[17]),
            "context_scale": float(row[18]),
            "artifact_uri": row[19],
            "artifacts": {r[0]: r[1] for r in artifacts},
            "is_active": bool(row[20]),
        }

    def get_distribution_thresholds(self, conn: psycopg.Connection, model_id: int) -> dict[str, Any]:
        row = conn.execute(
            """
            SELECT person_p95, person_p97, person_p99, person_p99_5,
                   context_p95, context_p97, context_p99, context_p99_5,
                   person_norm_p95, person_norm_p97, person_norm_p99, person_norm_p99_5,
                   context_norm_p95, context_norm_p97, context_norm_p99, context_norm_p99_5,
                   final_p95, final_p97, final_p99, final_p99_5,
                   recommended_threshold_name, recommended_threshold_value,
                   person_weight, context_weight, thresholds_json
            FROM anomaly_thresholds
            WHERE model_id = %s
            LIMIT 1
            """,
            (model_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"No anomaly_thresholds found for model_id={model_id}.")
        return {
            "person_p95": row[0], "person_p97": row[1], "person_p99": row[2], "person_p99_5": row[3],
            "context_p95": row[4], "context_p97": row[5], "context_p99": row[6], "context_p99_5": row[7],
            "person_norm_p95": row[8], "person_norm_p97": row[9], "person_norm_p99": row[10], "person_norm_p99_5": row[11],
            "context_norm_p95": row[12], "context_norm_p97": row[13], "context_norm_p99": row[14], "context_norm_p99_5": row[15],
            "final_p95": row[16], "final_p97": row[17], "final_p99": row[18], "final_p99_5": row[19],
            "recommended_threshold_name": row[20],
            "recommended_threshold_value": row[21],
            "person_weight": row[22], "context_weight": row[23],
            "thresholds_json": row[24] or {},
        }

    def get_gate_configs(self, conn: psycopg.Connection, model_id: int) -> dict[str, dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT gate_name, is_active, threshold_value, params
            FROM anomaly_gate_configs
            WHERE is_active = TRUE AND (model_id = %s OR model_id IS NULL)
            ORDER BY model_id NULLS FIRST, gate_name
            """,
            (model_id,),
        ).fetchall()
        configs: dict[str, dict[str, Any]] = {}
        for name, is_active, threshold_value, params in rows:
            configs[name] = {
                "gate_name": name,
                "is_active": bool(is_active),
                "threshold_value": float(threshold_value) if threshold_value is not None else None,
                "params": params or {},
            }
        return configs

    # ------------------------------------------------------------------
    # Edge device
    # ------------------------------------------------------------------

    def upsert_edge_device(self, conn: psycopg.Connection, device_key: str) -> int:
        row = conn.execute(
            """
            INSERT INTO edge_devices (device_key)
            VALUES (%s)
            ON CONFLICT (device_key) DO UPDATE SET device_key = EXCLUDED.device_key
            RETURNING id
            """,
            (device_key,),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Runtime tubelet storage
    # ------------------------------------------------------------------

    def insert_scene_window_embedding(
        self,
        conn: psycopg.Connection,
        *,
        model_id: int,
        device_id: Optional[int],
        camera_id: Optional[int],
        track_id: Optional[int],
        event_key: Optional[str],
        window_start_ts: str,
        window_end_ts: Optional[str],
        person_embedding: list[float],
        context_embedding: list[float],
        person_score: float,
        context_score: float,
        person_score_norm: float,
        context_score_norm: float,
        final_score: float,
        threshold_name: str,
        threshold_value: float,
        distribution_gate: bool,
        high_speed_gate: bool,
        abrupt_direction_gate: bool,
        track_instability_gate: bool,
        candidate_reasons: list[str],
        priority: str,
        sample_fps: int,
        tubelet_frames: int,
        stride: int,
        person_bbox_sequence: Any,
        motion_stats: dict[str, Any],
        person_clip_ref: Optional[str],
        context_clip_ref: Optional[str],
        representative_frame_ref: Optional[str],
        person_frame_refs: Optional[list[str]] = None,
        context_frame_refs: Optional[list[str]] = None,
        evidence_payload: Optional[dict[str, Any]] = None,
        video_encoder: str = VIDEO_ENCODER_MODEL,
    ) -> int:
        sql = """
            INSERT INTO scene_window_embeddings (
                model_id, device_id, camera_id, track_id, event_key,
                window_start_ts, window_end_ts,
                person_embedding, context_embedding,
                person_score, context_score, person_score_norm, context_score_norm,
                final_score, threshold_name, threshold_value,
                distribution_gate, high_speed_gate, abrupt_direction_gate, track_instability_gate,
                candidate_reasons, priority,
                sample_fps, tubelet_frames, stride,
                person_bbox_sequence, motion_stats,
                person_clip_ref, context_clip_ref, representative_frame_ref,
                person_frame_refs, context_frame_refs, evidence_payload,
                video_encoder
            )
            VALUES (
                %s,%s,%s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,
                %s,%s,%s,
                %s::jsonb,%s::jsonb,
                %s,%s,%s,
                %s::jsonb,%s::jsonb,%s::jsonb,
                %s
            )
        """
        params = (
            model_id, device_id, camera_id, track_id, event_key,
            window_start_ts, window_end_ts,
            person_embedding, context_embedding,
            person_score, context_score, person_score_norm, context_score_norm,
            final_score, threshold_name, threshold_value,
            distribution_gate, high_speed_gate, abrupt_direction_gate, track_instability_gate,
            candidate_reasons, priority,
            sample_fps, tubelet_frames, stride,
            json.dumps(person_bbox_sequence if person_bbox_sequence is not None else [], ensure_ascii=False),
            _json(motion_stats),
            person_clip_ref, context_clip_ref, representative_frame_ref,
            _json(person_frame_refs if person_frame_refs is not None else []),
            _json(context_frame_refs if context_frame_refs is not None else []),
            _json(evidence_payload if evidence_payload is not None else {}),
            video_encoder,
        )
        if event_key:
            row = conn.execute(sql + " ON CONFLICT DO NOTHING RETURNING id", params).fetchone()
            if row:
                return int(row[0])
            existing = conn.execute("SELECT id FROM scene_window_embeddings WHERE event_key = %s", (event_key,)).fetchone()
            if existing:
                # The consumer may retry the same Kafka event after a failed/no-commit
                # cycle. If the first insert happened before these evidence columns
                # existed, or if a later retry carries richer evidence, preserve it.
                conn.execute(
                    """
                    UPDATE scene_window_embeddings
                    SET person_frame_refs = COALESCE(%s::jsonb, person_frame_refs),
                        context_frame_refs = COALESCE(%s::jsonb, context_frame_refs),
                        evidence_payload = COALESCE(%s::jsonb, evidence_payload),
                        representative_frame_ref = COALESCE(%s, representative_frame_ref),
                        person_clip_ref = COALESCE(%s, person_clip_ref),
                        context_clip_ref = COALESCE(%s, context_clip_ref)
                    WHERE id = %s
                    """,
                    (
                        _json(person_frame_refs if person_frame_refs is not None else []),
                        _json(context_frame_refs if context_frame_refs is not None else []),
                        _json(evidence_payload if evidence_payload is not None else {}),
                        representative_frame_ref,
                        person_clip_ref,
                        context_clip_ref,
                        existing[0],
                    ),
                )
                return int(existing[0])
        row = conn.execute(sql + " RETURNING id", params).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Candidate creation / explainability
    # ------------------------------------------------------------------

    def find_recent_candidate(
        self,
        conn: psycopg.Connection,
        *,
        camera_id: Optional[int],
        track_id: Optional[int],
        candidate_reasons: list[str],
        final_score: float,
        cooldown_sec: float = CANDIDATE_COOLDOWN_SEC,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT ac.id, ac.final_score, ac.candidate_reasons
            FROM anomaly_candidates ac
            JOIN scene_window_embeddings swe ON swe.id = ac.scene_window_embedding_id
            WHERE (%s IS NULL OR swe.camera_id = %s)
              AND (%s IS NULL OR swe.track_id = %s)
              AND ac.created_at > now() - (%s || ' seconds')::interval
            ORDER BY ac.created_at DESC
            LIMIT 1
            """,
            (camera_id, camera_id, track_id, track_id, cooldown_sec),
        ).fetchone()
        if not row:
            return None
        old_reasons = list(row[2] or [])
        new_reason = bool(set(candidate_reasons) - set(old_reasons))
        old_score = float(row[1] or 0.0)
        much_higher = final_score > (old_score + 0.75) or final_score > old_score * 1.35
        return {
            "id": int(row[0]),
            "final_score": old_score,
            "candidate_reasons": old_reasons,
            "allow_duplicate": new_reason or much_higher,
        }

    def create_anomaly_candidate(
        self,
        conn: psycopg.Connection,
        *,
        scene_window_embedding_id: int,
        candidate_reasons: list[str],
        primary_reason: str,
        priority: str,
        final_score: float,
        person_score: float,
        context_score: float,
        person_score_norm: float,
        context_score_norm: float,
        threshold_name: str,
        threshold_value: float,
        distribution_gate: bool,
        high_speed_gate: bool,
        abrupt_direction_gate: bool,
        track_instability_gate: bool,
        max_speed_norm: Optional[float],
        max_turn_angle: Optional[float],
        track_instability_reason: Optional[str],
        person_clip_ref: Optional[str],
        context_clip_ref: Optional[str],
        representative_frame_ref: Optional[str],
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidates (
                scene_window_embedding_id, candidate_reasons, primary_reason, priority,
                final_score, person_score, context_score, person_score_norm, context_score_norm,
                threshold_name, threshold_value,
                distribution_gate, high_speed_gate, abrupt_direction_gate, track_instability_gate,
                max_speed_norm, max_turn_angle, track_instability_reason,
                person_clip_ref, context_clip_ref, representative_frame_ref,
                status
            )
            VALUES (
                %s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                'pending'
            )
            RETURNING id
            """,
            (
                scene_window_embedding_id, candidate_reasons, primary_reason, priority,
                final_score, person_score, context_score, person_score_norm, context_score_norm,
                threshold_name, threshold_value,
                distribution_gate, high_speed_gate, abrupt_direction_gate, track_instability_gate,
                max_speed_norm, max_turn_angle, track_instability_reason,
                person_clip_ref, context_clip_ref, representative_frame_ref,
            ),
        ).fetchone()
        return int(row[0])

    def insert_candidate_gate_decision(
        self,
        conn: psycopg.Connection,
        *,
        candidate_id: int,
        gate_name: str,
        gate_fired: bool,
        score_value: Optional[float],
        threshold_value: Optional[float],
        details: dict[str, Any],
        reason: str,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO candidate_gate_decisions (
                candidate_id, gate_name, gate_fired, score_value, threshold_value, details, reason
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT (candidate_id, gate_name) DO UPDATE
            SET gate_fired = EXCLUDED.gate_fired,
                score_value = EXCLUDED.score_value,
                threshold_value = EXCLUDED.threshold_value,
                details = EXCLUDED.details,
                reason = EXCLUDED.reason
            RETURNING id
            """,
            (candidate_id, gate_name, gate_fired, score_value, threshold_value, _json(details), reason),
        ).fetchone()
        return int(row[0])

    def enqueue_reasoning_job(
        self,
        conn: psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        model_name: str,
        job_type: str,
        prompt: str,
        request_json: dict[str, Any],
        provider: str = "ollama",
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO reasoning_jobs (
                anomaly_candidate_id, provider, model_name, job_type, prompt, request_json, status
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'queued')
            RETURNING id
            """,
            (anomaly_candidate_id, provider, model_name, job_type, prompt, _json(request_json)),
        ).fetchone()
        conn.execute(
            """
            UPDATE anomaly_candidates
            SET status = 'sent_to_reasoning', sent_to_reasoning_at = now()
            WHERE id = %s
            """,
            (anomaly_candidate_id,),
        )
        return int(row[0])

    def update_anomaly_candidate_status(self, conn: psycopg.Connection, *, anomaly_candidate_id: int, status: str) -> bool:
        row = conn.execute(
            "UPDATE anomaly_candidates SET status=%s WHERE id=%s RETURNING id",
            (status, anomaly_candidate_id),
        ).fetchone()
        return bool(row)

    # ------------------------------------------------------------------
    # Anomaly rules / reviews
    # ------------------------------------------------------------------

    def get_active_rules(self, conn: psycopg.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, event_type, conditions, source, active
            FROM Anomaly_Rules
            WHERE active = TRUE
            ORDER BY id ASC
            """
        ).fetchall()
        return [
            {
                "id": int(r[0]),
                "rule_text": r[1],
                "rule_type": r[2],
                "event_type": r[3],
                "conditions": r[4] or {},
                "source": r[5],
                "active": bool(r[6]),
            }
            for r in rows
        ]

    def insert_anomaly_rule(
        self,
        conn: psycopg.Connection,
        *,
        rule_text: str,
        rule_type: str = "trigger",
        event_type: str = "other",
        conditions: Optional[dict[str, Any]] = None,
        source: str = "Admin",
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO Anomaly_Rules (rule_text, rule_type, event_type, conditions, source, active)
            VALUES (%s, %s, %s, %s::jsonb, %s, TRUE)
            RETURNING id
            """,
            (rule_text, rule_type, event_type, _json(conditions or {}), source),
        ).fetchone()
        return int(row[0])

    def insert_candidate_review(
        self,
        conn: psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        decision: str,
        reviewer: Optional[str] = None,
        notes: Optional[str] = None,
        rule_text: Optional[str] = None,
        created_rule_id: Optional[int] = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidate_review (
                anomaly_candidate_id, decision, reviewer, notes, rule_text, created_rule_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (anomaly_candidate_id, decision, reviewer, notes, rule_text, created_rule_id),
        ).fetchone()
        return int(row[0])
