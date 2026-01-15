from typing import Optional, Dict, Any, List

import psycopg
from psycopg.rows import dict_row

from .config import DB_DSN

print("VECTOR_MATCH USING DB_DSN =", DB_DSN)


def get_conn() -> psycopg.Connection:
    print("CONNECTING WITH =", DB_DSN)
    return psycopg.connect(DB_DSN, row_factory=dict_row)


def insert_entry_log(conn, *, detected_id: Optional[int], camera_id: int, authorized: Optional[bool],
                     event_type: Optional[str], location: Optional[str], device_status: Optional[str],
                     image_video_ref: Optional[str], processing_time_interval: Optional[str],
                     model_version: Optional[str]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_logs (
                detected_id, camera_id, authorized, event_type, location,
                device_status, image_video_ref, processing_time, model_version
            )
            VALUES (%s, %s, %s, %s, %s,
                    %s, %s, %s::interval, %s)
            RETURNING id
            """,
            (
                detected_id,
                camera_id,
                authorized,
                event_type,
                location,
                device_status,
                image_video_ref,
                processing_time_interval,
                model_version,
            ),
        )
        return int(cur.fetchone()["id"])


def search_top2(conn, *, qvec_literal: str, only_authoritative: bool) -> List[Dict[str, Any]]:
    where_clause = "WHERE fe.is_authoritative = TRUE" if only_authoritative else ""
    sql = f"""
        SELECT
            fe.detected_id,
            1 - (fe.embedding <=> %s::vector) AS sim,
            fe.is_authoritative
        FROM face_embeddings fe
        {where_clause}
        ORDER BY fe.embedding <=> %s::vector
        LIMIT 2
    """
    with conn.cursor() as cur:
        cur.execute(sql, (qvec_literal, qvec_literal))
        return list(cur.fetchall())


def insert_unknown_face_event(conn, *, entry_log_id: int, qvec_literal: str,
                              embedding_model: str, notes: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO unknown_face_events (
                entry_log_id, embedding, embedding_model, status, notes
            )
            VALUES (%s, %s::vector, %s, 'pending', %s)
            RETURNING id
            """,
            (entry_log_id, qvec_literal, embedding_model, notes),
        )
        return int(cur.fetchone()["id"])


def insert_face_embedding(conn, *, detected_id: int, entry_log_id: int, qvec_literal: str,
                          embedding_model: str, is_authoritative: bool,
                          quality_score: Optional[float], match_confidence: Optional[float],
                          notes: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO face_embeddings (
                detected_id, entry_log_id, embedding, embedding_model,
                is_authoritative, quality_score, match_confidence, notes
            )
            VALUES (%s, %s, %s::vector, %s,
                    %s, %s, %s, %s)
            RETURNING id
            """,
            (
                detected_id,
                entry_log_id,
                qvec_literal,
                embedding_model,
                is_authoritative,
                quality_score,
                match_confidence,
                notes,
            ),
        )
        return int(cur.fetchone()["id"])


def count_embeddings(conn, *, detected_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM face_embeddings WHERE detected_id = %s", (detected_id,))
        return int(cur.fetchone()["c"])


def prune_embeddings_if_needed(conn, *, detected_id: int, keep_max: int) -> None:
    """
    Prune oldest non-authoritative embeddings if total count exceeds keep_max.
    Never deletes authoritative.
    """
    current = count_embeddings(conn, detected_id=detected_id)
    if current <= keep_max:
        return

    to_delete = current - keep_max
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM face_embeddings
            WHERE id IN (
                SELECT id
                FROM face_embeddings
                WHERE detected_id = %s
                  AND is_authoritative = FALSE
                ORDER BY created_at ASC
                LIMIT %s
            )
            """,
            (detected_id, to_delete),
        )


def admin_assign_unknown(conn, *, unknown_face_event_id: int, detected_id: int,
                         promote_to_authoritative: bool, notes: Optional[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, entry_log_id, embedding_model
            FROM unknown_face_events
            WHERE id = %s
            """,
            (unknown_face_event_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError("unknown_face_event_id not found")

        # Mark unknown as assigned
        cur.execute(
            """
            UPDATE unknown_face_events
            SET status='assigned',
                assigned_detected_id=%s,
                notes=COALESCE(%s, notes)
            WHERE id=%s
            """,
            (detected_id, notes, unknown_face_event_id),
        )

        # Update entry log linkage
        cur.execute(
            """
            UPDATE entry_logs
            SET detected_id=%s
            WHERE id=%s
            """,
            (detected_id, int(row["entry_log_id"])),
        )

        if promote_to_authoritative:
            # Insert embedding into face_embeddings as authoritative/admin_confirmed
            cur.execute(
                """
                INSERT INTO face_embeddings (
                    detected_id, entry_log_id, embedding, embedding_model,
                    is_authoritative, notes
                )
                SELECT
                    %s, entry_log_id, embedding, embedding_model,
                    TRUE, COALESCE(%s, 'admin_confirmed')
                FROM unknown_face_events
                WHERE id=%s
                """,
                (detected_id, notes, unknown_face_event_id),
            )
