"""
tools.py — Investigation tools rewritten for the new schema.

Every function is a precise, hand-written SQL query.
No LLM involvement — deterministic, fast, reliable.

Schema groups:
  Face pipeline   → entry_logs, detected_people, employees, visitors,
                    face_embeddings, unknown_face_events, cameras
  VAD pipeline    → vad_anomaly_cases, vad_gate_events, vad_reasoning_jobs,
                    vad_reasoning_results, vad_case_reviews, vad_streams,
                    vad_stream_sessions, vad_reasoning_rules
  System/Admin    → anomaly_rules, edge_devices, rule_conflicts, schedules,
                    activity_logs, audit_logs
"""
from __future__ import annotations

import logging
import psycopg2
import psycopg2.pool
from psycopg2 import sql as pg_sql
from contextlib import contextmanager
from datetime import date, timedelta
from config import DB_DSN

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Connection pool
# ─────────────────────────────────────────────────────────────────────────────
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, dsn=DB_DSN)
    return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE 'Africa/Cairo'")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _resolve_date(target_date: str | None, default_today: bool = True) -> str | None:
    if target_date:
        try:
            date.fromisoformat(target_date)
            return target_date
        except ValueError:
            pass
    return date.today().isoformat() if default_today else None


def _ok(tool: str, data, **extra) -> dict:
    return {"found": True, "tool": tool, "data": data, **extra}


def _err(msg: str) -> dict:
    return {"found": False, "message": msg}


# ─────────────────────────────────────────────────────────────────────────────
# Name matching helper
# ─────────────────────────────────────────────────────────────────────────────
def _name_clause(name: str, params: list) -> str:
    """Match name against employees, visitors, and detected_people."""
    tokens = [t.strip() for t in name.split() if t.strip()] or [name]
    patterns = []
    full = f"%{name}%"
    patterns.append("(e.name ILIKE %s OR v.name ILIKE %s OR dp.name ILIKE %s)")
    params += [full, full, full]
    if len(tokens) > 1:
        for tok in tokens:
            p = f"%{tok}%"
            patterns.append("(e.name ILIKE %s OR v.name ILIKE %s OR dp.name ILIKE %s)")
            params += [p, p, p]
    return "(" + " OR ".join(patterns) + ")"


# ═════════════════════════════════════════════════════════════════════════════
# FACE / PERSON TRACKING TOOLS
# ═════════════════════════════════════════════════════════════════════════════

def tool_person_last_seen(name: str, target_date: str | None = None) -> dict:
    """Most recent detection of a named person."""
    params: list = []
    clause = _name_clause(name, params)
    resolved = _resolve_date(target_date, default_today=False)
    date_filter = f' AND DATE(el."timestamp") = %s' if resolved else ""
    if resolved:
        params.append(resolved)
    sql = f"""
        SELECT
            COALESCE(e.name, v.name, dp.name) AS person_name,
            c.name                             AS camera_name,
            c.location                         AS camera_location,
            el."timestamp"                     AS timestamp,
            el.image_video_ref                 AS evidence_url,
            el.authorized,
            el.event_type
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE {clause}{date_filter}
        ORDER BY el."timestamp" DESC
        LIMIT 1
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return _err(f"No detection found for '{name}'.")
            cols = ["person_name","camera_name","camera_location","timestamp","evidence_url","authorized","event_type"]
            return _ok("person_last_seen", dict(zip(cols, row)))
    except Exception as e:
        return _err(str(e))


def tool_person_first_seen(name: str, target_date: str | None = None) -> dict:
    """Earliest detection of a named person."""
    params: list = []
    clause = _name_clause(name, params)
    resolved = _resolve_date(target_date, default_today=False)
    date_filter = f' AND DATE(el."timestamp") = %s' if resolved else ""
    if resolved:
        params.append(resolved)
    sql = f"""
        SELECT
            COALESCE(e.name, v.name, dp.name) AS person_name,
            c.name                             AS camera_name,
            c.location                         AS camera_location,
            el."timestamp"                     AS timestamp,
            el.image_video_ref                 AS evidence_url,
            el.authorized,
            el.event_type
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE {clause}{date_filter}
        ORDER BY el."timestamp" ASC
        LIMIT 1
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                return _err(f"No detection found for '{name}'.")
            cols = ["person_name","camera_name","camera_location","timestamp","evidence_url","authorized","event_type"]
            return _ok("person_first_seen", dict(zip(cols, row)))
    except Exception as e:
        return _err(str(e))


def tool_person_timeline(name: str, target_date: str | None = None) -> dict:
    """Full movement timeline for a named person. Defaults to last 7 days if no date given."""
    params: list = []
    clause = _name_clause(name, params)
    resolved = _resolve_date(target_date, default_today=False)

    if resolved:
        time_filter = f' AND DATE(el."timestamp") = %s'
        params.append(resolved)
        period_label = resolved
    else:
        time_filter = ' AND el."timestamp" >= NOW() - INTERVAL \'7 days\''
        period_label = "last 7 days"

    sql = f"""
        SELECT
            COALESCE(e.name, v.name, dp.name) AS person_name,
            c.name                             AS camera_name,
            c.location                         AS camera_location,
            el."timestamp"                     AS timestamp,
            el.image_video_ref                 AS evidence_url,
            el.authorized,
            el.event_type
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE {clause}{time_filter}
        ORDER BY el."timestamp" ASC
        LIMIT 200
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            if not rows:
                return _err(f"No detections found for '{name}' in {period_label}.")
            return _ok("person_timeline", rows, period=period_label, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_people_seen_on_date(target_date: str | None = None) -> dict:
    """All identified people seen on a given date."""
    resolved = _resolve_date(target_date, default_today=True)
    sql = """
        SELECT
            COALESCE(e.name, v.name, dp.name, 'Unknown') AS person_name,
            CASE WHEN e.id IS NOT NULL THEN 'employee'
                 WHEN v.id IS NOT NULL THEN 'visitor'
                 ELSE 'unknown' END                       AS person_type,
            COUNT(*)                                      AS detections,
            MIN(el."timestamp")                           AS first_seen,
            MAX(el."timestamp")                           AS last_seen,
            STRING_AGG(DISTINCT c.name, ', ')             AS cameras_seen
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE DATE(el."timestamp") = %s
          AND (e.id IS NOT NULL OR v.id IS NOT NULL OR dp.name IS NOT NULL)
        GROUP BY e.name, v.name, dp.name, e.id, v.id
        ORDER BY detections DESC
        LIMIT 100
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (resolved,))
            rows = _rows(cur)
            return _ok("people_seen_on_date", rows, date=resolved)
    except Exception as e:
        return _err(str(e))


def tool_known_people(limit: int = 100) -> dict:
    """List all known employees and visitors."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, 'employee' AS person_type, NULL AS visit_date, NULL AS purpose
                FROM employees ORDER BY name LIMIT %s
            """, (limit,))
            employees = _rows(cur)
            cur.execute("""
                SELECT id, name, 'visitor' AS person_type, visit_date::text, purpose
                FROM visitors ORDER BY name LIMIT %s
            """, (limit,))
            visitors = _rows(cur)
            # Also enrolled detected_people without employee/visitor link
            cur.execute("""
                SELECT id, name, 'enrolled' AS person_type, NULL AS visit_date, NULL AS purpose
                FROM detected_people
                WHERE employee_id IS NULL AND visitor_id IS NULL AND name IS NOT NULL
                ORDER BY name LIMIT %s
            """, (limit,))
            enrolled = _rows(cur)
            all_people = employees + visitors + enrolled
            return _ok("known_people", all_people, count=len(all_people))
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Detection counts
# ─────────────────────────────────────────────────────────────────────────────

def tool_count_unknown_detections(target_date: str | None = None, days_back: int | None = None, hour: int | None = None) -> dict:
    """Count unknown face events."""
    params: list = []
    where: list = []
    if days_back is not None:
        where.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)
        label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append("DATE(created_at) = %s")
        params.append(resolved)
        label = resolved
    if hour is not None:
        where.append("EXTRACT(HOUR FROM created_at) = %s")
        params.append(int(hour))
    sql = f"SELECT COUNT(*) FROM unknown_face_events WHERE {' AND '.join(where)}"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return _ok("count_unknown_detections", {"count": count, "period": label, "hour": hour})
    except Exception as e:
        return _err(str(e))


def tool_count_known_detections(target_date: str | None = None, days_back: int | None = None, hour: int | None = None) -> dict:
    """Count known face detections from entry_logs."""
    params: list = []
    where: list = ["(dp.employee_id IS NOT NULL OR dp.visitor_id IS NOT NULL OR dp.name IS NOT NULL)"]
    if days_back is not None:
        where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
        params.append(days_back)
        label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append('DATE(el."timestamp") = %s')
        params.append(resolved)
        label = resolved
    if hour is not None:
        where.append('EXTRACT(HOUR FROM el."timestamp") = %s')
        params.append(int(hour))
    sql = f"""
        SELECT COUNT(*) FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        WHERE {' AND '.join(where)}
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return _ok("count_known_detections", {"count": count, "period": label, "hour": hour})
    except Exception as e:
        return _err(str(e))


def tool_count_all_detections(target_date: str | None = None, days_back: int | None = None, hour: int | None = None) -> dict:
    """Count all entry_log detections."""
    params: list = []
    where: list = []
    if days_back is not None:
        where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
        params.append(days_back)
        label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append('DATE(el."timestamp") = %s')
        params.append(resolved)
        label = resolved
    if hour is not None:
        where.append('EXTRACT(HOUR FROM el."timestamp") = %s')
        params.append(int(hour))
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f'SELECT COUNT(*) FROM entry_logs el {where_sql}'
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return _ok("count_all_detections", {"count": count, "period": label, "hour": hour})
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Unknown face pipeline
# ─────────────────────────────────────────────────────────────────────────────

def tool_unknown_face_events(
    status: str | None = None,
    days_back: int | None = None,
    limit: int = 20,
) -> dict:
    """List unknown face events with optional status filter."""
    params: list = []
    where: list = []
    if status:
        where.append("ufe.status = %s")
        params.append(status)
    if days_back is not None:
        where.append("ufe.created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(200, int(limit or 20))))
    sql = f"""
        SELECT
            ufe.id,
            ufe.status,
            ufe.created_at,
            ufe.quality_score,
            ufe.best_similarity,
            ufe.assigned_detected_id,
            ufe.notes,
            el."timestamp"   AS event_timestamp,
            c.name           AS camera_name,
            c.location       AS camera_location,
            el.image_video_ref
        FROM unknown_face_events ufe
        LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
        LEFT JOIN cameras    c  ON el.camera_id = c.id
        {where_sql}
        ORDER BY ufe.created_at DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("unknown_face_events", rows, count=len(rows), status_filter=status)
    except Exception as e:
        return _err(str(e))


def tool_unknown_face_details(event_id: int) -> dict:
    """Full details for one unknown face event."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    ufe.id, ufe.entry_log_id, ufe.status,
                    ufe.assigned_detected_id, ufe.embedding_model,
                    ufe.notes, ufe.created_at, ufe.quality_score,
                    ufe.best_similarity, ufe.second_similarity, ufe.margin,
                    el."timestamp"    AS event_timestamp,
                    el.image_video_ref,
                    c.name            AS camera_name,
                    c.location        AS camera_location
                FROM unknown_face_events ufe
                LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
                LEFT JOIN cameras    c  ON el.camera_id = c.id
                WHERE ufe.id = %s
                LIMIT 1
            """, (event_id,))
            row = cur.fetchone()
            if not row:
                return _err(f"No unknown face event found with id={event_id}.")
            cols = [d[0] for d in cur.description]
            return _ok("unknown_face_details", dict(zip(cols, row)), event_id=event_id)
    except Exception as e:
        return _err(str(e))


def tool_similar_unknown_faces(event_id: int, threshold: float = 0.60, limit: int = 10) -> dict:
    """Find visually similar unknown faces using pgvector cosine distance."""
    max_dist = 1.0 - float(threshold)
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                WITH ref AS (SELECT embedding FROM unknown_face_events WHERE id = %s LIMIT 1)
                SELECT
                    ufe.id AS event_id, ufe.status, ufe.created_at,
                    1 - (ufe.embedding <=> ref.embedding) AS similarity,
                    c.name AS camera_name, c.location AS camera_location
                FROM unknown_face_events ufe
                CROSS JOIN ref
                LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
                LEFT JOIN cameras    c  ON el.camera_id = c.id
                WHERE ufe.id <> %s
                  AND (ufe.embedding <=> ref.embedding) <= %s
                ORDER BY ufe.embedding <=> ref.embedding ASC
                LIMIT %s
            """, (event_id, event_id, max_dist, max(1, min(50, int(limit)))))
            rows = _rows(cur)
            return _ok("similar_unknown_faces", rows, event_id=event_id, threshold=threshold)
    except Exception as e:
        return _err(str(e))


def tool_possible_identity_match(event_id: int, threshold: float = 0.55, limit: int = 5) -> dict:
    """Find closest known people for an unknown face event."""
    max_dist = 1.0 - float(threshold)
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                WITH ref AS (SELECT embedding FROM unknown_face_events WHERE id = %s LIMIT 1)
                SELECT
                    COALESCE(e.name, v.name, dp.name, 'Unknown') AS person_name,
                    CASE WHEN e.id IS NOT NULL THEN 'employee'
                         WHEN v.id IS NOT NULL THEN 'visitor'
                         ELSE 'enrolled' END AS person_type,
                    1 - (fe.embedding <=> ref.embedding) AS similarity,
                    fe.quality_score, fe.is_authoritative
                FROM face_embeddings fe
                JOIN detected_people dp ON fe.detected_id = dp.id
                LEFT JOIN employees  e  ON dp.employee_id = e.id
                LEFT JOIN visitors   v  ON dp.visitor_id  = v.id
                CROSS JOIN ref
                WHERE (e.id IS NOT NULL OR v.id IS NOT NULL OR dp.name IS NOT NULL)
                  AND (fe.embedding <=> ref.embedding) <= %s
                ORDER BY fe.embedding <=> ref.embedding ASC
                LIMIT %s
            """, (event_id, max_dist, max(1, min(20, int(limit)))))
            rows = _rows(cur)
            return _ok("possible_identity_match", rows, event_id=event_id, threshold=threshold)
    except Exception as e:
        return _err(str(e))


def tool_investigate_unknown_face(event_id: int) -> dict:
    """Full investigation: details + similar unknowns + identity matches."""
    details  = tool_unknown_face_details(event_id)
    similar  = tool_similar_unknown_faces(event_id)
    identity = tool_possible_identity_match(event_id)
    return _ok("investigate_unknown_face", {
        "details":  details,
        "similar":  similar,
        "identity": identity,
    }, event_id=event_id)


# ═════════════════════════════════════════════════════════════════════════════
# VAD ANOMALY PIPELINE TOOLS
# ═════════════════════════════════════════════════════════════════════════════

def tool_vad_cases(
    status: str | None = None,
    severity: str | None = None,
    days_back: int | None = None,
    camera_id: int | None = None,
    limit: int = 20,
) -> dict:
    """List VAD anomaly cases with optional filters."""
    params: list = []
    where: list = []
    if status:
        where.append("vc.status = %s")
        params.append(status)
    if severity:
        where.append("vc.severity = %s")
        params.append(severity)
    if days_back is not None:
        where.append("vc.start_ts >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)
    if camera_id is not None:
        where.append("vc.camera_id = %s")
        params.append(camera_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            vc.id, vc.case_key, vc.status, vc.severity, vc.case_type,
            vc.start_ts, vc.end_ts, vc.peak_ts,
            vc.primary_gate_name, vc.case_summary,
            c.name AS camera_name, c.location AS camera_location,
            vc.created_at, vc.updated_at
        FROM vad_anomaly_cases vc
        LEFT JOIN cameras c ON vc.camera_id = c.id
        {where_sql}
        ORDER BY vc.start_ts DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_cases", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_vad_case_details(case_id: int) -> dict:
    """Full details for one VAD anomaly case including reasoning result."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    vc.*, c.name AS camera_name, c.location AS camera_location
                FROM vad_anomaly_cases vc
                LEFT JOIN cameras c ON vc.camera_id = c.id
                WHERE vc.id = %s
                LIMIT 1
            """, (case_id,))
            row = cur.fetchone()
            if not row:
                return _err(f"No VAD case found with id={case_id}.")
            case_data = dict(zip([d[0] for d in cur.description], row))
            # Also fetch the latest reasoning result
            cur.execute("""
                SELECT alert_decision, severity, event_type, confidence,
                       reasoning_summary, decision_reason, created_at
                FROM vad_reasoning_results
                WHERE case_id = %s
                ORDER BY created_at DESC LIMIT 1
            """, (case_id,))
            rr = cur.fetchone()
            if rr:
                case_data["reasoning_result"] = dict(zip(
                    ["alert_decision","severity","event_type","confidence",
                     "reasoning_summary","decision_reason","created_at"], rr
                ))
            return _ok("vad_case_details", case_data, case_id=case_id)
    except Exception as e:
        return _err(str(e))


def tool_vad_gate_events(
    severity: str | None = None,
    status: str | None = None,
    camera_id: int | None = None,
    days_back: int | None = None,
    limit: int = 20,
) -> dict:
    """List VAD gate events (low-level anomaly triggers)."""
    params: list = []
    where: list = []
    if severity:
        where.append("ge.severity = %s")
        params.append(severity)
    if status:
        where.append("ge.status = %s")
        params.append(status)
    if camera_id is not None:
        where.append("ge.camera_id = %s")
        params.append(camera_id)
    if days_back is not None:
        where.append("ge.start_ts >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(200, int(limit or 20))))
    sql = f"""
        SELECT
            ge.id, ge.gate_name, ge.event_type, ge.status, ge.severity,
            ge.start_ts, ge.peak_ts, ge.end_ts, ge.peak_score,
            ge.threshold_value, ge.reason_when_fired,
            c.name AS camera_name, c.location AS camera_location
        FROM vad_gate_events ge
        LEFT JOIN cameras c ON ge.camera_id = c.id
        {where_sql}
        ORDER BY ge.start_ts DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_gate_events", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_vad_reasoning_jobs(status: str | None = None, limit: int = 20) -> dict:
    """List VAD reasoning jobs (LLM job queue)."""
    params: list = []
    where = "WHERE status = %s" if status else ""
    if status:
        params.append(status)
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            rj.id, rj.case_id, rj.status, rj.reasoner_type,
            rj.vlm_model, rj.llm_model, rj.priority,
            rj.attempts, rj.max_attempts,
            rj.queued_at, rj.started_at, rj.finished_at
        FROM vad_reasoning_jobs rj
        {where}
        ORDER BY rj.queued_at DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_reasoning_jobs", rows, count=len(rows), status_filter=status)
    except Exception as e:
        return _err(str(e))


def tool_vad_reasoning_results(
    case_id: int | None = None,
    alert_decision: str | None = None,
    limit: int = 20,
) -> dict:
    """List VAD reasoning results / LLM decisions."""
    params: list = []
    where: list = []
    if case_id is not None:
        where.append("rr.case_id = %s")
        params.append(case_id)
    if alert_decision:
        where.append("rr.alert_decision = %s")
        params.append(alert_decision.upper())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            rr.id, rr.case_id, rr.alert_decision, rr.severity,
            rr.event_type, rr.confidence,
            rr.reasoning_summary, rr.decision_reason,
            rr.created_at
        FROM vad_reasoning_results rr
        {where_sql}
        ORDER BY rr.created_at DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_reasoning_results", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_vad_case_reviews(
    decision: str | None = None,
    limit: int = 20,
) -> dict:
    """List human review decisions on VAD cases."""
    params: list = []
    where = "WHERE decision = %s" if decision else ""
    if decision:
        params.append(decision)
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            cr.id, cr.case_id, cr.reviewer, cr.decision,
            cr.corrected_event_type, cr.corrected_severity,
            cr.notes, cr.created_at
        FROM vad_case_reviews cr
        {where}
        ORDER BY cr.created_at DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_case_reviews", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_vad_streams(is_active: bool | None = None, limit: int = 50) -> dict:
    """List VAD camera streams."""
    params: list = []
    where = "WHERE is_active = %s" if is_active is not None else ""
    if is_active is not None:
        params.append(is_active)
    params.append(max(1, min(200, int(limit or 50))))
    sql = f"""
        SELECT
            vs.id, vs.stream_key, vs.display_name, vs.location,
            vs.source_type, vs.is_active,
            vs.target_sample_fps, vs.frame_width, vs.frame_height,
            c.name AS camera_name
        FROM vad_streams vs
        LEFT JOIN cameras c ON vs.camera_id = c.id
        {where}
        ORDER BY vs.display_name
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_streams", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


def tool_vad_stream_sessions(status: str | None = None, limit: int = 20) -> dict:
    """List recent VAD stream sessions."""
    params: list = []
    where = "WHERE ss.status = %s" if status else ""
    if status:
        params.append(status)
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            ss.id, ss.status, ss.started_at, ss.stopped_at,
            ss.sampled_frame_count, ss.dropped_frame_count,
            ss.actual_sample_fps, ss.reconnect_count,
            c.name AS camera_name
        FROM vad_stream_sessions ss
        LEFT JOIN cameras c ON ss.camera_id = c.id
        {where}
        ORDER BY ss.started_at DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = _rows(cur)
            return _ok("vad_stream_sessions", rows, count=len(rows))
    except Exception as e:
        return _err(str(e))


# ═════════════════════════════════════════════════════════════════════════════
# SYSTEM / ADMIN TOOLS
# ═════════════════════════════════════════════════════════════════════════════

def tool_cameras(limit: int = 50) -> dict:
    """List all cameras."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, location, stream_url FROM cameras ORDER BY name LIMIT %s", (limit,))
            return _ok("cameras", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_edge_devices(limit: int = 50) -> dict:
    """List registered edge devices."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, device_key, name, location, created_at FROM edge_devices ORDER BY name LIMIT %s", (limit,))
            return _ok("edge_devices", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_anomaly_rules(
    is_active: bool | None = None,
    rule_type: str | None = None,
    limit: int = 50,
) -> dict:
    """List anomaly rules with optional filters."""
    params: list = []
    where: list = []
    if is_active is not None:
        where.append("active = %s")
        params.append(is_active)
    if rule_type:
        where.append("rule_type = %s")
        params.append(rule_type)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(200, int(limit or 50))))
    sql = f"""
        SELECT id, rule_type, event_type, source, active, rule_text, created_at
        FROM anomaly_rules {where_sql}
        ORDER BY created_at DESC LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return _ok("anomaly_rules", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_reasoning_rules(
    rule_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 50,
) -> dict:
    """List VAD reasoning rules."""
    params: list = []
    where: list = []
    if rule_type:
        where.append("rule_type = %s")
        params.append(rule_type)
    if is_active is not None:
        where.append("active = %s")
        params.append(is_active)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(200, int(limit or 50))))
    sql = f"""
        SELECT id, rule_name, rule_type, source, active, priority, description, created_at
        FROM vad_reasoning_rules {where_sql}
        ORDER BY priority DESC, created_at DESC LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return _ok("reasoning_rules", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_rule_conflicts(status: str | None = None, limit: int = 50) -> dict:
    """List rule conflicts."""
    params: list = []
    where = "WHERE status = %s" if status else ""
    if status:
        params.append(status)
    params.append(max(1, min(200, int(limit or 50))))
    sql = f"""
        SELECT id, rule_id_1, rule_id_2, conflict_reason, status, created_at
        FROM rule_conflicts {where}
        ORDER BY created_at DESC LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return _ok("rule_conflicts", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_schedules(limit: int = 50) -> dict:
    """List access schedules."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, access_start_time, access_end_time,
                       applies_to_weekdays, applies_to_weekends
                FROM schedules ORDER BY name LIMIT %s
            """, (limit,))
            return _ok("schedules", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_activity_logs(limit: int = 50) -> dict:
    """List recent user activity logs."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, user_email, action, "timestamp"
                FROM activity_logs ORDER BY "timestamp" DESC LIMIT %s
            """, (limit,))
            return _ok("activity_logs", _rows(cur))
    except Exception as e:
        return _err(str(e))


def tool_audit_logs(limit: int = 50) -> dict:
    """List recent audit logs."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, user_email, action, resource, resource_id, created_at
                FROM audit_logs ORDER BY created_at DESC LIMIT %s
            """, (limit,))
            return _ok("audit_logs", _rows(cur))
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# META / SUMMARY TOOLS
# ─────────────────────────────────────────────────────────────────────────────

def tool_table_counts() -> dict:
    """Count rows in every public table."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [r[0] for r in cur.fetchall()]
            data = []
            for tname in tables:
                cur.execute(pg_sql.SQL("SELECT COUNT(*) FROM {}").format(pg_sql.Identifier(tname)))
                data.append({"table_name": tname, "record_count": cur.fetchone()[0]})
            data.sort(key=lambda x: x["record_count"], reverse=True)
            return _ok("table_counts", data)
    except Exception as e:
        return _err(str(e))


def tool_daily_summary() -> dict:
    """Today's security summary across face and VAD pipelines."""
    today = date.today().isoformat()
    try:
        with _conn() as conn:
            cur = conn.cursor()
            # Face pipeline stats
            cur.execute("""
                SELECT
                    COUNT(*) AS total_detections,
                    COUNT(CASE WHEN dp.employee_id IS NOT NULL OR dp.visitor_id IS NOT NULL OR dp.name IS NOT NULL THEN 1 END) AS known_detections,
                    AVG(el.quality_score) AS avg_quality
                FROM entry_logs el
                LEFT JOIN detected_people dp ON el.detected_id = dp.id
                WHERE DATE(el."timestamp") = %s
            """, (today,))
            face = cur.fetchone()
            # Unknown face events today
            cur.execute("SELECT COUNT(*) FROM unknown_face_events WHERE DATE(created_at) = %s", (today,))
            unknowns = cur.fetchone()[0]
            # VAD cases today
            cur.execute("SELECT COUNT(*), COUNT(CASE WHEN status='confirmed' THEN 1 END) FROM vad_anomaly_cases WHERE DATE(start_ts) = %s", (today,))
            vad = cur.fetchone()
            # Reasoning jobs today
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN status='failed' THEN 1 END) AS failed
                FROM vad_reasoning_jobs WHERE DATE(queued_at) = %s
            """, (today,))
            jobs = cur.fetchone()
            data = {
                "date": today,
                "total_detections":  int(face[0] or 0),
                "known_detections":  int(face[1] or 0),
                "unknown_detections": int(unknowns or 0),
                "avg_quality":        round(float(face[2] or 0), 3),
                "vad_cases_today":    int(vad[0] or 0),
                "vad_confirmed":      int(vad[1] or 0),
                "reasoning_jobs":     int(jobs[0] or 0),
                "reasoning_failed":   int(jobs[1] or 0),
            }
            return _ok("daily_summary", data)
    except Exception as e:
        return _err(str(e))


def tool_camera_activity(
    target_date: str | None = None,
    days_back: int | None = None,
    limit: int = 20,
) -> dict:
    """Detection counts grouped by camera."""
    params: list = []
    where: list = []
    if days_back is not None:
        where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
        params.append(days_back)
    elif target_date:
        where.append('DATE(el."timestamp") = %s')
        params.append(target_date)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(max(1, min(100, int(limit or 20))))
    sql = f"""
        SELECT
            COALESCE(c.name, 'Camera ' || el.camera_id::text) AS camera_name,
            c.location,
            COUNT(*) AS detections,
            MIN(el."timestamp") AS first_seen,
            MAX(el."timestamp") AS last_seen
        FROM entry_logs el
        LEFT JOIN cameras c ON el.camera_id = c.id
        {where_sql}
        GROUP BY c.name, c.location, el.camera_id
        ORDER BY detections DESC
        LIMIT %s
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return _ok("camera_activity", _rows(cur))
    except Exception as e:
        return _err(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# TOOL MAP — used by LangGraph workflow
# ─────────────────────────────────────────────────────────────────────────────
TOOL_MAP = {
    "person_last_seen":        tool_person_last_seen,
    "person_first_seen":       tool_person_first_seen,
    "person_timeline":         tool_person_timeline,
    "people_seen_on_date":     tool_people_seen_on_date,
    "known_people":            tool_known_people,
    "unknown_face_events":     tool_unknown_face_events,
    "unknown_face_details":    tool_unknown_face_details,
    "similar_unknown_faces":   tool_similar_unknown_faces,
    "possible_identity_match": tool_possible_identity_match,
    "investigate_unknown_face": tool_investigate_unknown_face,
    "count_unknown_detections": tool_count_unknown_detections,
    "count_known_detections":  tool_count_known_detections,
    "count_all_detections":    tool_count_all_detections,
    "vad_cases":               tool_vad_cases,
    "vad_case_details":        tool_vad_case_details,
    "vad_gate_events":         tool_vad_gate_events,
    "vad_reasoning_jobs":      tool_vad_reasoning_jobs,
    "vad_reasoning_results":   tool_vad_reasoning_results,
    "vad_case_reviews":        tool_vad_case_reviews,
    "vad_streams":             tool_vad_streams,
    "vad_stream_sessions":     tool_vad_stream_sessions,
    "cameras":                 tool_cameras,
    "edge_devices":            tool_edge_devices,
    "anomaly_rules":           tool_anomaly_rules,
    "reasoning_rules":         tool_reasoning_rules,
    "rule_conflicts":          tool_rule_conflicts,
    "schedules":               tool_schedules,
    "activity_logs":           tool_activity_logs,
    "audit_logs":              tool_audit_logs,
    "table_counts":            tool_table_counts,
    "daily_summary":           tool_daily_summary,
    "camera_activity":         tool_camera_activity,
}