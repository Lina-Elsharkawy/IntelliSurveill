from __future__ import annotations

from typing import Optional
import json

import psycopg
from pgvector.psycopg import register_vector

from .config import DB_DSN


class DB:
    def __init__(self, dsn: str = DB_DSN):
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn)
        register_vector(conn)
        return conn

    def get_active_model_id(self, conn: psycopg.Connection) -> int:
        row = conn.execute(
            "SELECT id FROM normal_behavior_models WHERE is_active = TRUE LIMIT 1"
        ).fetchone()
        if not row:
            raise RuntimeError("No active normal_behavior_models row found (is_active=true).")
        return int(row[0])

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

    def insert_scene_embedding(
        self,
        conn: psycopg.Connection,
        *,
        model_id: int,
        device_id: Optional[int],
        camera_id: Optional[int],
        entry_log_id: Optional[int],
        window_start_ts: str,
        window_end_ts: Optional[str],
        event_key: Optional[str],
        embedding_pca: list[float],
        embedding_raw: Optional[list[float]],
        embedding_model: str,
        cosine_distance: Optional[float],
        radius_threshold: Optional[float],
        is_normal: Optional[bool],
        score: Optional[float],
        nearest_cluster_id: Optional[int] = None,
        nearest_cluster_index: Optional[int] = None,
    ) -> int:
        # Idempotency: if event_key exists, return existing id
        if event_key:
            existing = conn.execute(
                "SELECT id FROM scene_window_embeddings WHERE event_key = %s",
                (event_key,),
            ).fetchone()
            if existing:
                return int(existing[0])

        row = conn.execute(
            """
            INSERT INTO scene_window_embeddings (
                model_id, device_id, camera_id, entry_log_id,
                window_start_ts, window_end_ts, event_key,
                embedding_pca, embedding_raw,
                nearest_cluster_index, nearest_cluster_id,
                cosine_distance, radius_threshold, is_normal, score,
                embedding_model
            )
            VALUES (
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,
                %s,%s,
                %s,%s,%s,%s,
                %s
            )
            RETURNING id
            """,
            (
                model_id, device_id, camera_id, entry_log_id,
                window_start_ts, window_end_ts, event_key,
                embedding_pca, embedding_raw,
                nearest_cluster_index, nearest_cluster_id,
                cosine_distance, radius_threshold, is_normal, score,
                embedding_model,
            ),
        ).fetchone()
        return int(row[0])

    def create_anomaly_candidate(
        self,
        conn: psycopg.Connection,
        scene_window_embedding_id: int,
        reason: str,
        image_ref: Optional[str],
        video_ref: Optional[str],
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidates (
                scene_window_embedding_id, reason, status, image_ref, video_ref
            )
            VALUES (%s, %s, 'pending', %s, %s)
            RETURNING id
            """,
            (scene_window_embedding_id, reason, image_ref, video_ref),
        ).fetchone()
        return int(row[0])

    def enqueue_ollama_job(
        self,
        conn: psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        model_name: str,
        prompt: str,
        request_json: dict,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO ollama_jobs (anomaly_candidate_id, model_name, prompt, request_json)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (anomaly_candidate_id, model_name, prompt, json.dumps(request_json)),
        ).fetchone()
        return int(row[0])

    # -------------------------------
    # Human feedback / retraining loop
    # -------------------------------

    def insert_anomaly_feedback(
        self,
        conn: psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        label: str,
        reviewer: Optional[str] = None,
        notes: Optional[str] = None,
        system_decision: Optional[dict] = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidate_feedback (
                anomaly_candidate_id, label, reviewer, notes, system_decision
            )
            VALUES (%s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                anomaly_candidate_id,
                label,
                reviewer,
                notes,
                json.dumps(system_decision) if system_decision is not None else None,
            ),
        ).fetchone()
        return int(row[0])

    def count_pending_false_positives(self, conn: psycopg.Connection) -> int:
        """Count false positives that haven't been used for retraining yet."""
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM anomaly_candidate_feedback
            WHERE label = 'false_positive'
              AND used_for_retrain = FALSE
            """
        ).fetchone()
        return int(row[0])

    def mark_false_positives_used_for_retrain(self, conn: psycopg.Connection) -> int:
        """Mark currently pending false positives as consumed by a retraining run."""
        row = conn.execute(
            """
            UPDATE anomaly_candidate_feedback
            SET used_for_retrain = TRUE
            WHERE label = 'false_positive'
              AND used_for_retrain = FALSE
            RETURNING id
            """
        ).fetchall()
        return len(row)

    # -------------------------------
    # Admin workflow helpers
    # -------------------------------

    def update_anomaly_candidate_status(
        self,
        conn: psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        status: str,
    ) -> bool:
        """Update anomaly_candidates.status. Returns True if the row existed/was updated."""
        row = conn.execute(
            """
            UPDATE anomaly_candidates
            SET status = %s
            WHERE id = %s
            RETURNING id
            """,
            (status, anomaly_candidate_id),
        ).fetchone()
        return bool(row)
