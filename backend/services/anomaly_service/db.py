from __future__ import annotations

import json
from typing import Optional

import psycopg
from pgvector.psycopg import register_vector

from config import DB_DSN


class DB:
    def __init__(self, dsn: str = DB_DSN) -> None:
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn)
        register_vector(conn)
        return conn

    # ------------------------------------------------------------------
    # Model & threshold helpers
    # ------------------------------------------------------------------

    def get_active_model_id(self, conn: psycopg.Connection) -> int:
        return int(self.get_active_model(conn)["id"])

    def get_active_model(self, conn: psycopg.Connection) -> dict:
        row = conn.execute(
            '''
            SELECT id, name, version, teacher_model, extract_layers,
                   student_model, embedding_dim, num_frames, window_stride, image_size
            FROM normal_behavior_models
            WHERE is_active = TRUE
            LIMIT 1
            '''
        ).fetchone()
        if not row:
            raise RuntimeError(
                "No active normal_behavior_models row found (is_active=true)."
            )
        return {
            "id": int(row[0]),
            "name": row[1],
            "version": row[2],
            "teacher_model": row[3],
            "extract_layers": row[4],
            "student_model": row[5],
            "embedding_dim": int(row[6]),
            "num_frames": int(row[7]),
            "window_stride": int(row[8]),
            "image_size": int(row[9]),
        }

    def get_thresholds(self, conn: psycopg.Connection, model_id: int) -> dict:
        row = conn.execute(
            """
            SELECT l2_p95, mse_p95, cos_p95,
                   min_metrics_agree, min_consecutive
            FROM anomaly_thresholds
            WHERE model_id = %s
            """,
            (model_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"No anomaly_thresholds found for model_id={model_id}. "
                f"Run offline scoring and insert thresholds first."
            )
        return {
            "l2_p95":            float(row[0]),
            "mse_p95":           float(row[1]),
            "cos_p95":           float(row[2]),
            "min_metrics_agree": int(row[3]),
            "min_consecutive":   int(row[4]),
        }

    # ------------------------------------------------------------------
    # Edge device
    # ------------------------------------------------------------------

    def upsert_edge_device(self, conn: psycopg.Connection, device_key: str) -> int:
        row = conn.execute(
            """
            INSERT INTO edge_devices (device_key)
            VALUES (%s)
            ON CONFLICT (device_key) DO UPDATE
                SET device_key = EXCLUDED.device_key
            RETURNING id
            """,
            (device_key,),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Scene window embeddings
    # ------------------------------------------------------------------

    def insert_scene_embedding(
        self,
        conn:              psycopg.Connection,
        *,
        model_id:          int,
        device_id:         Optional[int],
        camera_id:         Optional[int],
        track_id:          Optional[int],
        window_start_ts:   str,
        window_end_ts:     Optional[str],
        event_key:         Optional[str],
        student_embedding: list[float],
        teacher_embedding: Optional[list[float]],
        frames:            Optional[list[str]],
        embedding_model:   str,
        l2_score:          Optional[float],
        mse_score:         Optional[float],
        cosine_distance:   Optional[float],
        l2_flag:           Optional[bool],
        mse_flag:          Optional[bool],
        cos_flag:          Optional[bool],
        metrics_agreed:    Optional[int],
        is_anomalous:      Optional[bool],
    ) -> int:
        sql = '''
            INSERT INTO scene_window_embeddings (
                model_id, device_id, camera_id, track_id,
                window_start_ts, window_end_ts, event_key,
                student_embedding, teacher_embedding,
                frames,
                l2_score, mse_score, cosine_distance,
                l2_flag, mse_flag, cos_flag,
                metrics_agreed, is_anomalous,
                embedding_model
            )
            VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s
            )
        '''
        params = (
            model_id, device_id, camera_id, track_id,
            window_start_ts, window_end_ts, event_key,
            student_embedding, teacher_embedding,
            frames,
            l2_score, mse_score, cosine_distance,
            l2_flag, mse_flag, cos_flag,
            metrics_agreed, is_anomalous,
            embedding_model,
        )

        if event_key:
            row = conn.execute(
                sql + " ON CONFLICT DO NOTHING RETURNING id",
                params,
            ).fetchone()
            if row:
                return int(row[0])
            existing = conn.execute(
                "SELECT id FROM scene_window_embeddings WHERE event_key = %s",
                (event_key,),
            ).fetchone()
            if existing:
                return int(existing[0])

        row = conn.execute(sql + " RETURNING id", params).fetchone()
        return int(row[0])


    def get_recent_windows(
        self,
        conn:       psycopg.Connection,
        camera_id:  int,
        track_id:   int,
        model_id:   int,
        lookback_n: int = 20,
    ) -> list[dict]:
        """
        Return the last N windows for a camera+track sorted ascending by time.
        Used for temporal consistency (run detection).
        """
        rows = conn.execute(
            """
            SELECT id, window_start_ts, is_anomalous, l2_score, event_key
            FROM scene_window_embeddings
            WHERE camera_id = %s
              AND track_id  = %s
              AND model_id  = %s
            ORDER BY window_start_ts DESC
            LIMIT %s
            """,
            (camera_id, track_id, model_id, lookback_n),
        ).fetchall()
        return [
            {
                "id":              int(r[0]),
                "window_start_ts": r[1],
                "is_anomalous":    r[2],
                "l2_score":        float(r[3]) if r[3] is not None else None,
                "event_key":       r[4],
            }
            for r in reversed(rows)   # return oldest first
        ]

    # ------------------------------------------------------------------
    # Anomaly candidates
    # ------------------------------------------------------------------

    def create_anomaly_candidate(
        self,
        conn:                      psycopg.Connection,
        *,
        scene_window_embedding_id: int,
        reason:                    str,
        image_ref:                 Optional[str],
        video_ref:                 Optional[str],
        run_id:                    Optional[str],
        l2_score:                  Optional[float],
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidates (
                scene_window_embedding_id, reason, status,
                image_ref, video_ref, run_id, l2_score
            )
            VALUES (%s, %s, 'pending', %s, %s, %s, %s)
            RETURNING id
            """,
            (
                scene_window_embedding_id, reason,
                image_ref, video_ref, run_id, l2_score,
            ),
        ).fetchone()
        return int(row[0])

    def update_anomaly_candidate_status(
        self,
        conn:                 psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        status:               str,
    ) -> bool:
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

    # ------------------------------------------------------------------
    # Anomaly rules
    # ------------------------------------------------------------------

    def insert_anomaly_rule(
        self,
        conn:                psycopg.Connection,
        *,
        rule_text:           str,
        rule_type:           str           = "anomalous",
        reviewer:            Optional[str] = None,
        source_candidate_id: Optional[int] = None,
        camera_id:           Optional[int] = None,
        lab_id:              Optional[int] = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_rules (
                rule_text, rule_type, reviewer,
                source_candidate_id, camera_id, lab_id,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
            """,
            (
                rule_text, rule_type, reviewer,
                source_candidate_id, camera_id, lab_id,
            ),
        ).fetchone()
        return int(row[0])

    def get_active_rules(
        self,
        conn:      psycopg.Connection,
        camera_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Fetch all active rules applicable to the given camera:
          - global rules (camera_id IS NULL)
          - rules scoped to this specific camera
        Sorted oldest-first so rules accumulate in creation order.
        """
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, camera_id, lab_id
            FROM anomaly_rules
            WHERE is_active = TRUE
              AND (camera_id IS NULL OR camera_id = %s)
            ORDER BY created_at ASC
            """,
            (camera_id,),
        ).fetchall()
        return [
            {
                "id":        int(r[0]),
                "rule_text": r[1],
                "rule_type": r[2],
                "camera_id": r[3],
                "lab_id":    r[4],
            }
            for r in rows
        ]

    def get_all_rules(
        self,
        conn:        psycopg.Connection,
        camera_id:   Optional[int] = None,
        active_only: bool          = True,
    ) -> list[dict]:
        """List rules with full metadata for the admin UI."""
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, camera_id, lab_id,
                   reviewer, source_candidate_id, is_active, created_at
            FROM anomaly_rules
            WHERE (%s IS NULL OR camera_id = %s OR camera_id IS NULL)
              AND (%s = FALSE OR is_active = TRUE)
            ORDER BY created_at DESC
            """,
            (camera_id, camera_id, active_only),
        ).fetchall()
        return [
            {
                "id":                  int(r[0]),
                "rule_text":           r[1],
                "rule_type":           r[2],
                "camera_id":           r[3],
                "lab_id":              r[4],
                "reviewer":            r[5],
                "source_candidate_id": r[6],
                "is_active":           r[7],
                "created_at":          r[8],
            }
            for r in rows
        ]

    def deactivate_rule(
        self,
        conn:    psycopg.Connection,
        rule_id: int,
    ) -> bool:
        row = conn.execute(
            """
            UPDATE anomaly_rules
            SET is_active = FALSE
            WHERE id = %s
            RETURNING id
            """,
            (rule_id,),
        ).fetchone()
        return bool(row)

    # ------------------------------------------------------------------
    # Candidate review
    # ------------------------------------------------------------------

    def insert_candidate_review(
        self,
        conn:                 psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        decision:             str,
        reviewer:             Optional[str] = None,
        notes:                Optional[str] = None,
        rule_text:            Optional[str] = None,
        created_rule_id:      Optional[int] = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO anomaly_candidate_review (
                anomaly_candidate_id, decision,
                reviewer, notes, rule_text, created_rule_id
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                anomaly_candidate_id, decision,
                reviewer, notes, rule_text, created_rule_id,
            ),
        ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # Ollama jobs
    # ------------------------------------------------------------------

    def enqueue_ollama_job(
        self,
        conn:                 psycopg.Connection,
        *,
        anomaly_candidate_id: int,
        model_name:           str,
        prompt:               str,
        request_json:         dict,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO ollama_jobs (
                anomaly_candidate_id, model_name, prompt, request_json
            )
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                anomaly_candidate_id,
                model_name,
                prompt,
                json.dumps(request_json),
            ),
        ).fetchone()
        return int(row[0])