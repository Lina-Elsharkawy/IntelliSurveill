from typing import Optional, Dict, Any, List

import psycopg
from psycopg.rows import dict_row

from .config import DB_DSN

print("VECTOR_MATCH USING DB_DSN =", DB_DSN)


def get_conn() -> psycopg.Connection:
    print("CONNECTING WITH =", DB_DSN)
    return psycopg.connect(DB_DSN, row_factory=dict_row)


def insert_entry_log(conn, *, detected_id: Optional[int], camera_id: Optional[int], authorized: Optional[bool],
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
                id,
                "timestamp",
                detected_id,
                camera_id,
                authorized,
                event_type,
                location,
                device_status,
                image_video_ref,
                processing_time,
                model_version
            FROM entry_logs
            ORDER BY "timestamp" DESC
            LIMIT %s OFFSET %s
            """,
            (int(limit), int(offset)),
        )
        return list(cur.fetchall())


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
        new_id = int(cur.fetchone()["id"])

        # Mark unknown as assigned to this new identity
        cur.execute(
            """
            UPDATE unknown_face_events
            SET status='assigned',
                assigned_detected_id=%s,
                notes=COALESCE(%s, notes)
            WHERE id=%s
            """,
            (new_id, notes, unknown_face_event_id),
        )

        # Update entry log linkage
        cur.execute(
            """
            UPDATE entry_logs
            SET detected_id=%s
            WHERE id=%s
            """,
            (new_id, int(row["entry_log_id"])),
        )

        # Optionally promote the unknown embedding as authoritative anchor for the new identity.
        if promote_to_authoritative:
            cur.execute(
                """
                INSERT INTO face_embeddings (
                    detected_id, entry_log_id, embedding, embedding_model,
                    is_authoritative, notes
                )
                VALUES (%s, %s, %s, %s, TRUE, COALESCE(%s, 'admin_created_identity'))
                """,
                (new_id, int(row["entry_log_id"]), row["embedding"], row["embedding_model"], notes),
            )

        return new_id
