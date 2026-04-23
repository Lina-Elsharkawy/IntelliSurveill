from typing import Optional, Dict, Any, List
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import DB_DSN

print("VECTOR_MATCH USING DB_DSN =", DB_DSN)

_pool = ConnectionPool(
    conninfo=DB_DSN,
    min_size=1,
    max_size=int(os.getenv("DB_POOL_MAX", "10")),
    kwargs={"row_factory": dict_row},
)


def get_conn():
    # returns a context manager; connection is returned to the pool automatically
    return _pool.connection()



def insert_entry_log(conn, *, detected_id: Optional[int], camera_id: Optional[int], authorized: Optional[bool],
                     event_type: Optional[str], location: Optional[str], device_status: Optional[str],
                     image_video_ref: Optional[str], processing_time_interval: Optional[str],
                     model_version: Optional[str], quality_score: Optional[float],
                     best_similarity: Optional[float], second_similarity: Optional[float],
                     margin: Optional[float]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_logs (
                detected_id, camera_id, authorized, event_type, location,
                device_status, image_video_ref, processing_time, model_version,
                quality_score, best_similarity, second_similarity, margin
            )
            VALUES (%s, %s, %s, %s, %s,
                    %s, %s, %s::interval, %s,
                    %s, %s, %s, %s)
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
                quality_score,
                best_similarity,
                second_similarity,
                margin,
            ),
        )
        return int(cur.fetchone()["id"])


def ensure_camera_exists(conn, *, camera_id: int) -> None:
    """Ensure cameras(id=camera_id) exists.

    Your schema uses GENERATED ALWAYS AS IDENTITY for cameras.id.
    For streaming systems, events may carry an external camera_id.
    We support that by inserting with OVERRIDING SYSTEM VALUE when missing.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM cameras WHERE id=%s", (camera_id,))
        if cur.fetchone():
            return
        cur.execute(
            """
            INSERT INTO cameras (id, name, location, lab_id)
            OVERRIDING SYSTEM VALUE
            VALUES (%s, %s, NULL, NULL)
            """,
            (camera_id, f"auto:{camera_id}"),
        )


def count_distinct_identities(conn, *, only_authoritative: bool) -> int:
    where = "WHERE is_authoritative = TRUE" if only_authoritative else ""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(DISTINCT detected_id) AS c FROM face_embeddings {where}")
        return int(cur.fetchone()["c"])


def list_pending_unknowns(conn, *, limit: int, offset: int) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                u.id,
                u.entry_log_id,
                u.embedding_model,
                u.status,
                u.assigned_detected_id,
                u.notes,
                u.created_at,
                u.quality_score,
                u.best_similarity,
                u.second_similarity,
                u.margin,
                el.camera_id,
                el.location,
                el.event_type,
                el.image_video_ref
            FROM unknown_face_events u
            JOIN entry_logs el ON el.id = u.entry_log_id
            WHERE u.status = 'pending'
            ORDER BY u.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (int(limit), int(offset)),
        )
        return list(cur.fetchall())


def list_recent_entry_logs(conn, *, limit: int, offset: int) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                el.id,
                el."timestamp",
                el.detected_id,
                dp.name AS identity_name,
                el.camera_id,
                el.authorized,
                el.event_type,
                el.location,
                el.device_status,
                el.image_video_ref,
                el.processing_time,
                el.model_version,
                el.quality_score,
                el.best_similarity,
                el.second_similarity,
                el.margin,
                ufe.id AS unknown_face_event_id
            FROM entry_logs el
            LEFT JOIN detected_people dp
                ON dp.id = el.detected_id
            LEFT JOIN unknown_face_events ufe
                ON ufe.entry_log_id = el.id
            ORDER BY el."timestamp" DESC
            LIMIT %s OFFSET %s
            """,
            (int(limit), int(offset)),
        )
        return list(cur.fetchall())

def get_entry_log_by_id(conn, *, entry_log_id: int) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                el.id,
                el."timestamp",
                el.detected_id,
                dp.name AS identity_name,
                el.camera_id,
                el.authorized,
                el.event_type,
                el.location,
                el.device_status,
                el.image_video_ref,
                el.processing_time,
                el.model_version,
                el.quality_score,
                el.best_similarity,
                el.second_similarity,
                el.margin,
                ufe.id AS unknown_face_event_id
            FROM entry_logs el
            LEFT JOIN detected_people dp
                ON dp.id = el.detected_id
            LEFT JOIN unknown_face_events ufe
                ON ufe.entry_log_id = el.id
            WHERE el.id = %s
            """,
            (int(entry_log_id),),
        )
        return cur.fetchone()

def list_identities(conn, *, limit: int, offset: int) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                dp.id,
                dp.name,
                dp.additional_info,
                dp.employee_id,
                dp.visitor,
                dp.visitor_id,
                (SELECT COUNT(*) FROM face_embeddings fe WHERE fe.detected_id = dp.id) AS embeddings_count,
                (SELECT COUNT(*) FROM face_embeddings fe WHERE fe.detected_id = dp.id AND fe.is_authoritative = TRUE) AS authoritative_count
            FROM detected_people dp
            ORDER BY dp.id DESC
            LIMIT %s OFFSET %s
            """,
            (int(limit), int(offset)),
        )
        return list(cur.fetchall())


def search_topk(conn, *, qvec_literal: str, only_authoritative: bool, k: int) -> List[Dict[str, Any]]:
    where_clause = "WHERE fe.is_authoritative = TRUE" if only_authoritative else ""
    sql = f"""
        SELECT
            fe.detected_id,
            1 - (fe.embedding <=> %s::vector) AS sim,
            fe.is_authoritative
        FROM face_embeddings fe
        {where_clause}
        ORDER BY fe.embedding <=> %s::vector
        LIMIT {int(k)}
    """
    with conn.cursor() as cur:
        cur.execute(sql, (qvec_literal, qvec_literal))
        return list(cur.fetchall())


def max_similarity_for_identity(conn, *, detected_id: int, qvec_literal: str) -> Optional[float]:
    """Return max cosine similarity between qvec and any embedding of detected_id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 - (embedding <=> %s::vector) AS sim
            FROM face_embeddings
            WHERE detected_id = %s
            ORDER BY embedding <=> %s::vector
            LIMIT 1
            """,
            (qvec_literal, detected_id, qvec_literal),
        )
        row = cur.fetchone()
        if not row:
            return None
        return float(row["sim"])


def seconds_since_last_autolearn(conn, *, detected_id: int) -> Optional[int]:
    """Return seconds since last 'auto_learned' embedding insert for this identity.

    Returns None if no prior auto-learn record exists.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXTRACT(EPOCH FROM (now() - MAX(created_at)))::int AS seconds
            FROM face_embeddings
            WHERE detected_id = %s
              AND notes = 'auto_learned'
            """,
            (detected_id,),
        )
        row = cur.fetchone()
        if not row or row["seconds"] is None:
            return None
        return int(row["seconds"])


def insert_unknown_face_event(conn, *, entry_log_id: int, qvec_literal: str,
                              embedding_model: str, notes: str,
                              quality_score: Optional[float],
                              best_similarity: Optional[float],
                              second_similarity: Optional[float],
                              margin: Optional[float]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO unknown_face_events (
                entry_log_id, embedding, embedding_model, status, notes,
                quality_score, best_similarity, second_similarity, margin
            )
            VALUES (%s, %s::vector, %s, 'pending', %s,
                    %s, %s, %s, %s)
            RETURNING id
            """,
            (
                entry_log_id,
                qvec_literal,
                embedding_model,
                notes,
                quality_score,
                best_similarity,
                second_similarity,
                margin,
            ),
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

        # Always store the corrected embedding so admin feedback improves recognition.
        # Promote to authoritative only when explicitly requested.
        cur.execute(
            """
            INSERT INTO face_embeddings (
                detected_id,
                entry_log_id,
                embedding,
                embedding_model,
                is_authoritative,
                notes,
                quality_score,
                match_confidence
            )
            SELECT
                %s,
                entry_log_id,
                embedding,
                embedding_model,
                %s,
                COALESCE(
                    %s,
                    CASE
                        WHEN %s THEN 'admin_confirmed_authoritative'
                        ELSE 'admin_confirmed_non_authoritative'
                    END
              ),
                quality_score,
                best_similarity
            FROM unknown_face_events
            WHERE id=%s
            """,
            (
                detected_id,
                bool(promote_to_authoritative),
                notes,
                bool(promote_to_authoritative),
                unknown_face_event_id,
            ),
        )


def admin_create_identity_from_unknown(conn, *, unknown_face_event_id: int, name: Optional[str],
                                      additional_info: Optional[str], promote_to_authoritative: bool,
                                      notes: Optional[str]) -> int:
    """Create a new detected_people identity from an unknown event.

    Returns the newly created detected_people.id.
    """
    with conn.cursor() as cur:
        # Fetch unknown event
        cur.execute(
            """
            SELECT id, entry_log_id, embedding, embedding_model
            FROM unknown_face_events
            WHERE id = %s
            """,
            (unknown_face_event_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError("unknown_face_event_id not found")

        # Create new identity
        cur.execute(
            """
            INSERT INTO detected_people (name, additional_info)
            VALUES (%s, %s)
            RETURNING id
            """,
            (name, additional_info),
        )
        new_detected_id = int(cur.fetchone()["id"])

        # Mark unknown as assigned
        cur.execute(
            """
            UPDATE unknown_face_events
            SET status='assigned',
                assigned_detected_id=%s,
                notes=COALESCE(%s, notes)
            WHERE id=%s
            """,
            (new_detected_id, notes, unknown_face_event_id),
        )

        # Update entry log linkage
        cur.execute(
            """
            UPDATE entry_logs
            SET detected_id=%s
            WHERE id=%s
            """,
            (new_detected_id, int(row["entry_log_id"])),
        )

        # Insert the reviewed unknown as the seed embedding for the new identity
        cur.execute(
            """
            INSERT INTO face_embeddings (
                detected_id,
                entry_log_id,
                embedding,
                embedding_model,
                is_authoritative,
                notes,
                quality_score,
                match_confidence
            )
            SELECT
                %s,
                entry_log_id,
                embedding,
                embedding_model,
                %s,
                COALESCE(
                    %s,
                    CASE
                        WHEN %s THEN 'admin_confirmed_authoritative'
                        ELSE 'admin_confirmed_non_authoritative'
                    END
                ),

                quality_score,
                best_similarity
            FROM unknown_face_events
            WHERE id=%s
            """,
            (
                new_detected_id,
                bool(promote_to_authoritative),
                notes,
                bool(promote_to_authoritative),
                unknown_face_event_id,
            ),
        )

        return new_detected_id


def count_identities(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM detected_people")
        return int(cur.fetchone()["c"])


def count_pending_unknowns(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM unknown_face_events
            WHERE status = 'pending'
            """
        )
        return int(cur.fetchone()["c"])


def count_entry_logs(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM entry_logs")
        return int(cur.fetchone()["c"])