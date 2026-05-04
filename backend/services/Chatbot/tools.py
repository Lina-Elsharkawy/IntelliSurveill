"""
Investigation tools for the surveillance chatbot.
Each function is a precise, hand-written SQL query for a specific
investigation task — more reliable than asking a small LLM to write them.
"""
import logging
import psycopg2
import psycopg2.pool
from psycopg2 import sql as pg_sql
from contextlib import contextmanager
from datetime import date, timedelta
from config import DB_DSN

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Connection pool — reuses connections instead of creating/destroying per query.
# Prevents DB connection exhaustion under load.
# ─────────────────────────────────────────────────────────────────────────────
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=DB_DSN,
        )
    return _pool


@contextmanager
def _conn():
    """
    Context manager that gets a connection from the pool and guarantees
    it is returned (not leaked) even on exceptions.

    Usage:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(...)
    """
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


def _resolve_date(target_date: str | None, default_today: bool = True) -> str | None:
    """
    Validate and return target_date.
    - If target_date is a valid ISO date string, return it unchanged.
    - If target_date is None and default_today is True, return today.
    - If target_date is None and default_today is False, return None
      (meaning "no date filter — search all time").
    """
    if target_date:
        try:
            date.fromisoformat(target_date)
            return target_date
        except ValueError:
            pass
    return date.today().isoformat() if default_today else None

def get_unknown_face_events(
    limit: int = 10,
    days_back: int | None = None,
    only_unreviewed: bool | None = None,
) -> dict:
    """
    Query the real unknown_face_events table.

    Unknown face event = row in unknown_face_events.
    Unreviewed unknown face event = assigned_detected_id IS NULL.
    """
    where_clauses = []
    params = []

    if days_back is not None:
        where_clauses.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)

    if only_unreviewed is True:
        where_clauses.append("assigned_detected_id IS NULL")
    elif only_unreviewed is False:
        where_clauses.append("assigned_detected_id IS NOT NULL")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
        SELECT *
        FROM unknown_face_events
        {where_sql}
        ORDER BY created_at DESC
        LIMIT %s
    """
    params.append(limit)

    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)

            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

            data = [dict(zip(columns, row)) for row in rows]

            return {
                "found": True,
                "tool": "latest_unknown_face_events",
                "count": len(data),
                "days_back": days_back,
                "only_unreviewed": only_unreviewed,
                "data": data,
            }

    except Exception as e:
        return {"found": False, "error": str(e)}

def get_unknown_detection_count(target_date: str | None = None, hour: int | None = None, days_back: int | None = None) -> dict:
    """
    Count unknown face detections/events from unknown_face_events.

    If days_back is set, counts over the past N days (range).
    Otherwise counts a single date (default: today).
    """
    params: list = []
    where: list[str] = []
    if days_back is not None:
        where.append("created_at >= NOW() - (%s * INTERVAL '1 day')")
        params.append(days_back)
        date_label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append("DATE(created_at) = %s")
        params.append(resolved)
        date_label = resolved
    if hour is not None:
        where.append("EXTRACT(HOUR FROM created_at) = %s")
        params.append(int(hour))
    sql = f"""
        SELECT COUNT(*) AS count
        FROM unknown_face_events
        WHERE {' AND '.join(where)}
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return {
                "found": True,
                "tool": "unknown_detection_count",
                "data": {
                    "count": count,
                    "target_date": date_label,
                    "hour": hour,
                    "source_table": "unknown_face_events",
                    "meaning": "Unknown face events/detections",
                },
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_known_face_detection_count(target_date: str | None = None, hour: int | None = None, days_back: int | None = None) -> dict:
    """
    Count known face detections from entry_logs joined to detected_people.

    If days_back is set, counts over the past N days (range).
    Otherwise counts a single date (default: today).
    """
    params: list = []
    where: list[str] = [
        "(dp.employee_id IS NOT NULL OR dp.visitor_id IS NOT NULL OR dp.name IS NOT NULL)",
    ]
    if days_back is not None:
        where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
        params.append(days_back)
        date_label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append('DATE(el."timestamp") = %s')
        params.append(resolved)
        date_label = resolved
    if hour is not None:
        where.append('EXTRACT(HOUR FROM el."timestamp") = %s')
        params.append(int(hour))
    sql = f"""
        SELECT COUNT(*) AS count
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        WHERE {' AND '.join(where)}
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return {
                "found": True,
                "tool": "known_face_detection_count",
                "data": {
                    "count": count,
                    "target_date": date_label,
                    "hour": hour,
                    "source_table": "entry_logs + detected_people",
                    "meaning": "Known detections where employee_id or visitor_id is present",
                },
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_face_detection_count(target_date: str | None = None, hour: int | None = None, days_back: int | None = None) -> dict:
    """Count all face/person detections from entry_logs for a date, hour, or date range."""
    params: list = []
    where: list[str] = []
    if days_back is not None:
        where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
        params.append(days_back)
        date_label = f"last {days_back} day(s)"
    else:
        resolved = _resolve_date(target_date, default_today=True)
        where.append('DATE(el."timestamp") = %s')
        params.append(resolved)
        date_label = resolved
    if hour is not None:
        where.append('EXTRACT(HOUR FROM el."timestamp") = %s')
        params.append(int(hour))
    sql = f"""
        SELECT COUNT(*) AS count
        FROM entry_logs el
        WHERE {' AND '.join(where)}
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            count = cur.fetchone()[0]
            return {
                "found": True,
                "tool": "face_detection_count",
                "data": {
                    "count": count,
                    "target_date": date_label,
                    "hour": hour,
                    "source_table": "entry_logs",
                    "meaning": "All entry-log detections",
                },
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_table_record_counts() -> dict:
    """
    Count rows in every public table.
    Used for questions like:
    - Which table has the most records?
    - Which tables are empty?
    - How many records are in each table?
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)

            tables = [row[0] for row in cur.fetchall()]
            data = []

            for table_name in tables:
                query = pg_sql.SQL("SELECT COUNT(*) FROM {}").format(
                    pg_sql.Identifier(table_name)
                )
                cur.execute(query)
                record_count = cur.fetchone()[0]

                data.append({
                    "table_name": table_name,
                    "record_count": record_count
                })

            data.sort(key=lambda x: x["record_count"], reverse=True)

            return {
                "found": True,
                "tool": "table_record_counts",
                "count": len(data),
                "data": data
            }

    except Exception as e:
        return {"found": False, "error": str(e)}
# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _name_where_clause(name: str, params: list) -> str:
    """
    Build a WHERE fragment that matches a person name against
    employee, visitor, and detected_people name columns (ILIKE).

    Strategy:
    - First try the FULL name as a single ILIKE match (most accurate).
    - Then OR in each individual token so "Eng Maged" also matches
      a DB row that just stores "Maged".

    This means:
      - "Alice Johnson" matches dp.name ILIKE '%Alice Johnson%'  (exact)
      - "Eng Maged"     matches dp.name ILIKE '%Maged%'          (token)

    The result is: (full_name_match OR any_single_token_match)
    across all three name columns.

    Side-effect: appends the required bind values to `params`.
    """
    tokens = [t.strip() for t in name.split() if t.strip()]
    if not tokens:
        tokens = [name]

    # Strategy: match FULL name OR any individual token in any name column.
    # This is both precise (full match preferred) and lenient (single token works).
    all_patterns = []

    # Full name match
    full_pattern = f"%{name}%"
    all_patterns.append("(e.name ILIKE %s OR v.name ILIKE %s OR dp.name ILIKE %s)")
    params += [full_pattern, full_pattern, full_pattern]

    # Individual token matches (only add if multi-word to avoid duplicate)
    if len(tokens) > 1:
        for tok in tokens:
            pattern = f"%{tok}%"
            all_patterns.append("(e.name ILIKE %s OR v.name ILIKE %s OR dp.name ILIKE %s)")
            params += [pattern, pattern, pattern]

    return "(" + " OR ".join(all_patterns) + ")"


# ─────────────────────────────────────────────────────────────────────────────
# 1. PERSON LAST / FIRST SEEN  (shared implementation)
# ─────────────────────────────────────────────────────────────────────────────

def _get_person_detection(
    name: str,
    target_date: str | None,
    order: str,          # "DESC" → last seen,  "ASC" → first seen
    tool_label: str,     # "last_seen" or "first_seen"
) -> dict:
    """
    Core implementation shared by get_person_last_seen and get_person_first_seen.
    """
    params: list = []
    name_clause = _name_where_clause(name, params)

    base_sql = f"""
        SELECT
            el.id                                  AS detection_id,
            COALESCE(e.name, v.name, dp.name)      AS person_name,
            c.name                                  AS camera_name,
            c.location                              AS camera_location,
            el."timestamp"                          AS timestamp,
            el.image_video_ref                      AS evidence_url
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE {name_clause}
    """

    resolved = _resolve_date(target_date, default_today=False)

    if resolved:
        sql = base_sql + f' AND DATE(el."timestamp") = %s ORDER BY el."timestamp" {order} LIMIT 1'
        params.append(resolved)
        date_label = resolved
    else:
        sql = base_sql + f' ORDER BY el."timestamp" {order} LIMIT 1'
        date_label = "all time"

    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            if not row:
                msg = (f"No detection found for '{name}' on {date_label}."
                       if resolved else f"No detection found for '{name}'.")
                return {"found": False, "message": msg}
            cols = ["detection_id", "person_name", "camera_name",
                    "camera_location", "timestamp", "evidence_url"]
            return {"found": True, "tool": tool_label, "data": dict(zip(cols, row))}
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_person_last_seen(name: str, target_date: str | None = None) -> dict:
    """Find the most recent detection of a named person."""
    return _get_person_detection(name, target_date, order="DESC", tool_label="last_seen")


def get_person_first_seen(name: str, target_date: str | None = None) -> dict:
    """Find the very first (earliest) detection of a named person."""
    return _get_person_detection(name, target_date, order="ASC", tool_label="first_seen")


# ─────────────────────────────────────────────────────────────────────────────
# 2. PERSON MOVEMENT TIMELINE
# ─────────────────────────────────────────────────────────────────────────────
def get_person_timeline(name: str, target_date: str | None = None) -> dict:
    """
    Full movement timeline for a named person on a given date.
    Defaults to today when target_date is None.
    """
    resolved = _resolve_date(target_date, default_today=True)
    params: list = []
    name_clause = _name_where_clause(name, params)
    params.append(resolved)

    sql = f"""
        SELECT
            COALESCE(e.name, v.name, dp.name)  AS person_name,
            c.name                              AS camera_name,
            c.location                          AS camera_location,
            el."timestamp"                      AS timestamp,
            el.image_video_ref                  AS evidence_url
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN employees e   ON dp.employee_id = e.id
        LEFT JOIN visitors  v   ON dp.visitor_id  = v.id
        LEFT JOIN cameras   c   ON el.camera_id   = c.id
        WHERE {name_clause}
          AND DATE(el."timestamp") = %s
        ORDER BY el."timestamp" ASC
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                return {"found": False, "message": f"No detections for '{name}' on {resolved}."}
            cols = ["person_name", "camera_name", "camera_location", "timestamp", "evidence_url"]
            return {
                "found": True, "tool": "timeline",
                "date": resolved, "count": len(rows),
                "data": [dict(zip(cols, r)) for r in rows],
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 3. UNKNOWN FACES — by date
# ─────────────────────────────────────────────────────────────────────────────
def get_unknown_faces_today(target_date: str | None = None) -> dict:
    """
    All unidentified face detections for a given date (default: today).
    Unknown = employee_id IS NULL AND visitor_id IS NULL.
    """
    resolved = _resolve_date(target_date, default_today=True)

    sql = """
        SELECT
            el.id              AS detection_id,
            c.name             AS camera_name,
            c.location         AS camera_location,
            el."timestamp"     AS timestamp,
            el.image_video_ref AS evidence_url
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN cameras c     ON el.camera_id   = c.id
        WHERE dp.employee_id IS NULL
          AND dp.visitor_id  IS NULL
          AND dp.name IS NULL
          AND DATE(el."timestamp") = %s
        ORDER BY el."timestamp" DESC
        LIMIT 100
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (resolved,))
            rows = cur.fetchall()
            cols = ["detection_id", "camera_name", "camera_location", "timestamp", "evidence_url"]
            return {
                "found": True, "tool": "unknown_faces",
                "date": resolved, "count": len(rows),
                "data": [dict(zip(cols, r)) for r in rows],
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 4. REPEATED UNKNOWN VISITORS
# ─────────────────────────────────────────────────────────────────────────────
def get_repeated_unknowns(min_appearances: int = 2, days_back: int = 7) -> dict:
    """
    Unknown people who appeared more than once in the last `days_back` days.
    Groups by camera + day as a proxy for the same person returning.
    """
    since = (date.today() - timedelta(days=days_back)).isoformat()

    sql = """
        SELECT
            DATE(el."timestamp")    AS day,
            c.name                  AS camera_name,
            COUNT(*)                AS appearances,
            MIN(el."timestamp")     AS first_seen,
            MAX(el."timestamp")     AS last_seen,
            MAX(el.image_video_ref) AS evidence_url
        FROM entry_logs el
        JOIN detected_people dp ON el.detected_id = dp.id
        LEFT JOIN cameras c     ON el.camera_id   = c.id
        WHERE dp.employee_id IS NULL
          AND dp.visitor_id  IS NULL
          AND dp.name IS NULL
          AND el."timestamp" >= %s
        GROUP BY DATE(el."timestamp"), c.name, el.camera_id
        HAVING COUNT(*) >= %s
        ORDER BY appearances DESC
        LIMIT 20
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (since, min_appearances))
            rows = cur.fetchall()
            cols = ["day", "camera_name", "appearances", "first_seen", "last_seen", "evidence_url"]
            return {
                "found": True, "tool": "repeated_unknowns",
                "days_back": days_back, "count": len(rows),
                "data": [dict(zip(cols, r)) for r in rows],
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 5. ANOMALIES NEAR A FACE EVENT
# ─────────────────────────────────────────────────────────────────────────────
def get_anomalies_near_face(
    camera_id: int | None = None,
    timestamp: str | None = None,
    person_name: str | None = None,
    window_seconds: int = 60,
) -> dict:
    """
    Anomalies within `window_seconds` of a face detection.
    Resolves the reference timestamp from person_name → their last detection,
    or uses a raw timestamp directly.
    """
    if person_name:
        last = get_person_last_seen(person_name)
        if not last.get("found"):
            return {"found": False, "message": f"Could not find detections for '{person_name}'."}
        ts = last["data"]["timestamp"]
    elif timestamp:
        ts = timestamp
    else:
        return {"found": False, "message": "Provide either person_name or timestamp."}

    sql = """
        SELECT
            al.id                                                            AS anomaly_id,
            a.description                                                    AS event_type,
            a.description                                                    AS description,
            a.severity_level                                                 AS severity,
            al."timestamp"                                                   AS detected_at,
            c.name                                                           AS camera_name,
            c.location                                                       AS camera_location,
            NULL                                                             AS evidence_url,
            ABS(EXTRACT(EPOCH FROM (al."timestamp" - %s::timestamptz)))      AS seconds_apart
        FROM anomalies_logs al
        JOIN anomalies a ON al.anomaly_id = a.id
        LEFT JOIN cameras c ON al.camera_id = c.id
        WHERE ABS(EXTRACT(EPOCH FROM (al."timestamp" - %s::timestamptz))) <= %s
        ORDER BY seconds_apart ASC
        LIMIT 10
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (ts, ts, window_seconds))
            rows = cur.fetchall()
            cols = ["anomaly_id", "event_type", "description", "severity",
                    "detected_at", "camera_name", "camera_location", "evidence_url", "seconds_apart"]
            return {
                "found": True, "tool": "anomalies_near_face",
                "reference_time": str(ts), "window_seconds": window_seconds,
                "count": len(rows),
                "data": [dict(zip(cols, r)) for r in rows],
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 6. WHO WAS SEEN ON A DATE
# ─────────────────────────────────────────────────────────────────────────────
def get_people_seen_today(target_date: str | None = None) -> dict:
    """
    All identified people seen on a given date (default: today).
    """
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
        LIMIT 50
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (resolved,))
            rows = cur.fetchall()
            cols = ["person_name", "person_type", "detections",
                    "first_seen", "last_seen", "cameras_seen"]
            return {
                "found": True, "tool": "people_seen_today",
                "date": resolved, "count": len(rows),
                "data": [dict(zip(cols, r)) for r in rows],
            }
    except Exception as e:
        return {"found": False, "error": str(e)}
# ─────────────────────────────────────────────────────────────────────────────
# Additional investigation tools for LangGraph tool-first architecture
# These functions are defensive: they inspect schema where possible and return a
# helpful message instead of crashing if optional tables/columns are missing.
# ─────────────────────────────────────────────────────────────────────────────

def _table_exists(cur, table_name: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
    """, (table_name,))
    return bool(cur.fetchone()[0])


def _column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        )
    """, (table_name, column_name))
    return bool(cur.fetchone()[0])


def _columns(cur, table_name: str) -> set[str]:
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
    """, (table_name,))
    return {r[0] for r in cur.fetchall()}


def _rows_to_dicts(cur, rows):
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, r)) for r in rows]


def get_unknown_face_event_details(event_id: int) -> dict:
    """Return one unknown_face_events row with its source entry log and camera context."""
    try:
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "unknown_face_events"):
                return {"found": False, "message": "The unknown_face_events table does not exist."}
            cur.execute("""
                SELECT
                    ufe.id,
                    ufe.entry_log_id,
                    ufe.status,
                    ufe.assigned_detected_id,
                    ufe.embedding_model,
                    ufe.notes,
                    ufe.created_at,
                    el."timestamp" AS event_timestamp,
                    el.camera_id,
                    c.name AS camera_name,
                    c.location AS camera_location,
                    el.image_video_ref
                FROM unknown_face_events ufe
                LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
                LEFT JOIN cameras c ON el.camera_id = c.id
                WHERE ufe.id = %s
                LIMIT 1
            """, (event_id,))
            row = cur.fetchone()
            if not row:
                return {"found": False, "message": f"No unknown face event found with id={event_id}."}
            data = _rows_to_dicts(cur, [row])[0]
            return {"found": True, "tool": "unknown_face_event_details", "event_id": event_id, "data": data}
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_latest_anomalies(limit: int = 10, days_back: int | None = None) -> dict:
    """Latest anomalies from anomalies_logs joined to anomalies/cameras when available."""
    try:
        limit = max(1, min(100, int(limit or 10)))
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "anomalies_logs"):
                return {"found": False, "message": "The anomalies_logs table does not exist."}
            where = ""
            params = []
            if days_back:
                where = "WHERE al.\"timestamp\" >= NOW() - (%s * INTERVAL '1 day')"
                params.append(days_back)
            sql = f"""
                SELECT
                    al.id AS anomaly_log_id,
                    al.\"timestamp\" AS timestamp,
                    al.camera_id,
                    c.name AS camera_name,
                    c.location AS camera_location,
                    a.description AS description,
                    a.severity_level AS severity
                FROM anomalies_logs al
                LEFT JOIN anomalies a ON al.anomaly_id = a.id
                LEFT JOIN cameras c ON al.camera_id = c.id
                {where}
                ORDER BY al.\"timestamp\" DESC
                LIMIT %s
            """
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return {"found": True, "tool": "latest_anomalies", "count": len(rows), "data": _rows_to_dicts(cur, rows)}
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_anomalies_near_unknown_event(event_id: int, window_seconds: int = 60) -> dict:
    """Find anomaly logs near the entry_log timestamp/camera of an unknown face event."""
    try:
        window_seconds = max(1, min(3600, int(window_seconds or 60)))
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "unknown_face_events"):
                return {"found": False, "message": "The unknown_face_events table does not exist."}
            cur.execute("""
                SELECT
                    ufe.id,
                    ufe.entry_log_id,
                    COALESCE(el."timestamp", ufe.created_at) AS reference_time,
                    el.camera_id
                FROM unknown_face_events ufe
                LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
                WHERE ufe.id = %s
                LIMIT 1
            """, (event_id,))
            ref = cur.fetchone()
            if not ref:
                return {"found": False, "message": f"No unknown face event found with id={event_id}."}

            _, entry_log_id, ref_ts, ref_cam = ref
            camera_filter = "AND al.camera_id = %s" if ref_cam is not None else ""
            params = [ref_ts, ref_ts, window_seconds]
            if ref_cam is not None:
                params.append(ref_cam)

            sql = f"""
                SELECT
                    al.id AS anomaly_log_id,
                    al."timestamp" AS timestamp,
                    al.camera_id,
                    c.name AS camera_name,
                    c.location AS camera_location,
                    a.description AS description,
                    a.severity_level AS severity,
                    ABS(EXTRACT(EPOCH FROM (al."timestamp" - %s::timestamptz))) AS seconds_apart
                FROM anomalies_logs al
                LEFT JOIN anomalies a ON al.anomaly_id = a.id
                LEFT JOIN cameras c ON al.camera_id = c.id
                WHERE ABS(EXTRACT(EPOCH FROM (al."timestamp" - %s::timestamptz))) <= %s
                {camera_filter}
                ORDER BY seconds_apart ASC
                LIMIT 20
            """
            cur.execute(sql, params)
            rows = cur.fetchall()
            return {
                "found": True,
                "tool": "anomalies_near_unknown_event",
                "event_id": event_id,
                "entry_log_id": entry_log_id,
                "reference_time": str(ref_ts),
                "camera_id": ref_cam,
                "window_seconds": window_seconds,
                "count": len(rows),
                "data": _rows_to_dicts(cur, rows),
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_camera_activity_summary(target_date: str | None = None, days_back: int | None = None, limit: int = 20) -> dict:
    """Detection counts grouped by camera from entry_logs."""
    try:
        limit = max(1, min(100, int(limit or 20)))
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "entry_logs"):
                return {"found": False, "message": "The entry_logs table does not exist."}
            where = []
            params = []
            if target_date:
                where.append('DATE(el."timestamp") = %s')
                params.append(target_date)
            elif days_back:
                where.append('el."timestamp" >= NOW() - (%s * INTERVAL \'1 day\')')
                params.append(days_back)
            where_sql = "WHERE " + " AND ".join(where) if where else ""
            sql = f"""
                SELECT
                    c.id AS camera_id,
                    COALESCE(c.name, 'Camera ' || el.camera_id::text) AS camera_name,
                    c.location AS camera_location,
                    COUNT(*) AS detections,
                    MIN(el.\"timestamp\") AS first_seen,
                    MAX(el.\"timestamp\") AS last_seen
                FROM entry_logs el
                LEFT JOIN cameras c ON el.camera_id = c.id
                {where_sql}
                GROUP BY c.id, c.name, c.location, el.camera_id
                ORDER BY detections DESC
                LIMIT %s
            """
            params.append(limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            return {"found": True, "tool": "camera_activity_summary", "count": len(rows), "data": _rows_to_dicts(cur, rows)}
    except Exception as e:
        return {"found": False, "error": str(e)}


def get_daily_security_summary(target_date: str | None = None) -> dict:
    """Compact daily summary across detections, unknown events, and anomalies."""
    resolved = _resolve_date(target_date, default_today=True)
    data = {"date": resolved}
    try:
        with _conn() as conn:
            cur = conn.cursor()
            if _table_exists(cur, "entry_logs"):
                cur.execute('SELECT COUNT(*) FROM entry_logs WHERE DATE("timestamp") = %s', (resolved,))
                data["entry_log_detections"] = cur.fetchone()[0]
            if _table_exists(cur, "unknown_face_events"):
                cols = _columns(cur, "unknown_face_events")
                ts_col = "created_at" if "created_at" in cols else ("timestamp" if "timestamp" in cols else None)
                if ts_col:
                    cur.execute(f"SELECT COUNT(*) FROM unknown_face_events WHERE DATE({ts_col}) = %s", (resolved,))
                    data["unknown_face_events"] = cur.fetchone()[0]
            if _table_exists(cur, "anomalies_logs"):
                cur.execute('SELECT COUNT(*) FROM anomalies_logs WHERE DATE("timestamp") = %s', (resolved,))
                data["anomaly_logs"] = cur.fetchone()[0]
            if _table_exists(cur, "cameras") and _table_exists(cur, "entry_logs"):
                cur.execute('''
                    SELECT COALESCE(c.name, 'Camera ' || el.camera_id::text) AS camera_name, COUNT(*) AS detections
                    FROM entry_logs el
                    LEFT JOIN cameras c ON el.camera_id = c.id
                    WHERE DATE(el."timestamp") = %s
                    GROUP BY c.name, el.camera_id
                    ORDER BY detections DESC
                    LIMIT 5
                ''', (resolved,))
                data["top_cameras"] = _rows_to_dicts(cur, cur.fetchall())
            return {"found": True, "tool": "daily_security_summary", "date": resolved, "data": data}
    except Exception as e:
        return {"found": False, "error": str(e)}


def _unknown_event_embedding_exists(cur, event_id: int) -> bool:
    """unknown_face_events stores the 512-d embedding directly in this schema."""
    if not _table_exists(cur, "unknown_face_events"):
        return False
    cur.execute("SELECT 1 FROM unknown_face_events WHERE id = %s LIMIT 1", (event_id,))
    return cur.fetchone() is not None


def find_similar_unknown_faces(event_id: int, threshold: float = 0.60, limit: int = 10) -> dict:
    """Find similar unknown_face_events using direct pgvector cosine distance on ufe.embedding."""
    try:
        limit = max(1, min(100, int(limit or 10)))
        threshold = float(threshold or 0.60)
        max_distance = 1.0 - threshold
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "unknown_face_events"):
                return {"found": False, "message": "The unknown_face_events table does not exist."}
            if not _unknown_event_embedding_exists(cur, event_id):
                return {"found": False, "message": f"No unknown face event found with id={event_id}."}

            cur.execute("""
                WITH ref AS (
                    SELECT embedding
                    FROM unknown_face_events
                    WHERE id = %s
                    LIMIT 1
                )
                SELECT
                    ufe.id AS event_id,
                    ufe.entry_log_id,
                    ufe.status,
                    ufe.assigned_detected_id,
                    ufe.created_at,
                    el."timestamp" AS event_timestamp,
                    el.camera_id,
                    c.name AS camera_name,
                    c.location AS camera_location,
                    1 - (ufe.embedding <=> ref.embedding) AS similarity,
                    (ufe.embedding <=> ref.embedding) AS distance
                FROM unknown_face_events ufe
                CROSS JOIN ref
                LEFT JOIN entry_logs el ON ufe.entry_log_id = el.id
                LEFT JOIN cameras c ON el.camera_id = c.id
                WHERE ufe.id <> %s
                  AND (ufe.embedding <=> ref.embedding) <= %s
                ORDER BY ufe.embedding <=> ref.embedding ASC
                LIMIT %s
            """, (event_id, event_id, max_distance, limit))
            rows = cur.fetchall()
            return {
                "found": True,
                "tool": "similar_unknown_faces",
                "event_id": event_id,
                "threshold": threshold,
                "count": len(rows),
                "data": _rows_to_dicts(cur, rows),
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def find_possible_identity_match(event_id: int, threshold: float = 0.55, limit: int = 5) -> dict:
    """Find closest known people by comparing unknown_face_events.embedding to face_embeddings.embedding."""
    try:
        limit = max(1, min(50, int(limit or 5)))
        threshold = float(threshold or 0.55)
        max_distance = 1.0 - threshold
        with _conn() as conn:
            cur = conn.cursor()
            if not _table_exists(cur, "unknown_face_events"):
                return {"found": False, "message": "The unknown_face_events table does not exist."}
            if not _table_exists(cur, "face_embeddings"):
                return {"found": False, "message": "The face_embeddings table does not exist."}
            if not _unknown_event_embedding_exists(cur, event_id):
                return {"found": False, "message": f"No unknown face event found with id={event_id}."}

            cur.execute("""
                WITH ref AS (
                    SELECT embedding
                    FROM unknown_face_events
                    WHERE id = %s
                    LIMIT 1
                )
                SELECT
                    dp.id AS detected_id,
                    COALESCE(e.name, v.name, dp.name, 'Unknown') AS person_name,
                    CASE WHEN e.id IS NOT NULL THEN 'employee'
                         WHEN v.id IS NOT NULL THEN 'visitor'
                         ELSE 'detected_person' END AS person_type,
                    fe.id AS face_embedding_id,
                    fe.entry_log_id,
                    fe.is_authoritative,
                    fe.quality_score,
                    1 - (fe.embedding <=> ref.embedding) AS similarity,
                    (fe.embedding <=> ref.embedding) AS distance
                FROM face_embeddings fe
                JOIN detected_people dp ON fe.detected_id = dp.id
                LEFT JOIN employees e ON dp.employee_id = e.id
                LEFT JOIN visitors v ON dp.visitor_id = v.id
                CROSS JOIN ref
                WHERE (e.id IS NOT NULL OR v.id IS NOT NULL OR dp.name IS NOT NULL)
                  AND (fe.embedding <=> ref.embedding) <= %s
                ORDER BY fe.embedding <=> ref.embedding ASC
                LIMIT %s
            """, (event_id, max_distance, limit))
            rows = cur.fetchall()
            return {
                "found": True,
                "tool": "possible_identity_match",
                "event_id": event_id,
                "threshold": threshold,
                "count": len(rows),
                "data": _rows_to_dicts(cur, rows),
            }
    except Exception as e:
        return {"found": False, "error": str(e)}


def investigate_unknown_face_event(event_id: int, threshold: float = 0.60, limit: int = 10) -> dict:
    """Composite investigation: event context + similar unknowns + possible identities + nearby anomalies."""
    details = get_unknown_face_event_details(event_id)
    similar = find_similar_unknown_faces(event_id, threshold=threshold, limit=limit)
    identity = find_possible_identity_match(event_id, threshold=max(0.0, threshold - 0.05), limit=5)
    anomalies = get_anomalies_near_unknown_event(event_id, window_seconds=60)
    found = any(r.get("found") for r in [details, similar, identity, anomalies])
    return {
        "found": found,
        "tool": "investigate_unknown_face_event",
        "event_id": event_id,
        "data": {
            "details": details,
            "similar_unknown_faces": similar,
            "possible_identity_matches": identity,
            "nearby_anomalies": anomalies,
        },
    }

# ─────────────────────────────────────────────────────────────────────────────
# LIST ALL KNOWN PEOPLE (registry, no date filter)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_known_people(limit: int = 100, person_type: str | None = None) -> dict:
    """
    Return all known people from the employees and visitors registry tables.
    This is a registry lookup — not tied to any detection date.
    person_type: 'employee', 'visitor', or None (both).
    """
    try:
        with _conn() as conn:
            cur = conn.cursor()
            results = []

            if person_type in (None, "employee"):
                cur.execute("""
                    SELECT
                        e.id,
                        e.name,
                        'employee' AS person_type,
                        d.name AS department
                    FROM employees e
                    LEFT JOIN departments d ON e.department_id = d.id
                    ORDER BY e.name
                    LIMIT %s
                """, (limit,))
                cols = ["id", "name", "person_type", "department"]
                results += [dict(zip(cols, r)) for r in cur.fetchall()]

            if person_type in (None, "visitor"):
                cur.execute("""
                    SELECT
                        v.id,
                        v.name,
                        'visitor' AS person_type,
                        v.visit_date::text AS visit_date,
                        v.purpose
                    FROM visitors v
                    ORDER BY v.name
                    LIMIT %s
                """, (limit,))
                cols = ["id", "name", "person_type", "visit_date", "purpose"]
                results += [dict(zip(cols, r)) for r in cur.fetchall()]

            if person_type in (None, "detected_person", "enrolled"):
                cur.execute("""
                    SELECT
                        id,
                        name,
                        'enrolled' AS person_type,
                        'Manual Enrollment' AS department
                    FROM detected_people
                    WHERE employee_id IS NULL
                      AND visitor_id IS NULL
                      AND name IS NOT NULL
                    ORDER BY name
                    LIMIT %s
                """, (limit,))
                cols = ["id", "name", "person_type", "department"]
                results += [dict(zip(cols, r)) for r in cur.fetchall()]

            return {
                "found": True,
                "tool": "all_known_people",
                "count": len(results),
                "person_type_filter": person_type,
                "data": results,
            }
    except Exception as e:
        logger.exception("get_all_known_people failed")
        return {"found": False, "error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
# 7. NEW INVESTIGATION TOOLS (Anomaly Candidates, Rules, Jobs, etc.)
# ─────────────────────────────────────────────────────────────────────────────

def get_anomaly_candidates(status: str | None = None, limit: int = 20) -> dict:
    where = "WHERE status = %s" if status else ""
    params = [status, limit] if status else [limit]
    sql = f"SELECT * FROM anomaly_candidates {where} ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "anomaly_candidates", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_anomaly_candidate_review(decision: str | None = None, limit: int = 20) -> dict:
    where = "WHERE decision = %s" if decision else ""
    params = [decision, limit] if decision else [limit]
    sql = f"SELECT * FROM anomaly_candidate_review {where} ORDER BY reviewed_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "anomaly_candidate_review", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_ollama_jobs(status: str | None = None, limit: int = 20) -> dict:
    where = "WHERE status = %s" if status else ""
    params = [status, limit] if status else [limit]
    sql = f"SELECT * FROM ollama_jobs {where} ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "ollama_jobs", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_scene_window_embeddings(is_anomalous: bool | None = None, limit: int = 20) -> dict:
    where = "WHERE is_anomalous = %s" if is_anomalous is not None else ""
    params = [is_anomalous, limit] if is_anomalous is not None else [limit]
    sql = f"SELECT id, camera_id, start_time, end_time, is_anomalous, l2_score, mse_score, cos_flag FROM scene_window_embeddings {where} ORDER BY start_time DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "scene_window_embeddings", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_anomaly_rules(
    is_active: bool | None = None,
    rule_type: str | None = None,
    rule_id: int | None = None,
    limit: int = 20,
) -> dict:
    conditions: list[str] = []
    params: list = []
    if is_active is not None:
        conditions.append("active = %s")
        params.append(is_active)
    if rule_type is not None:
        conditions.append("rule_type = %s")
        params.append(rule_type)
    if rule_id is not None:
        conditions.append("id = %s")
        params.append(rule_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    sql = f"SELECT * FROM anomaly_rules {where} ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "anomaly_rules", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_edge_devices(limit: int = 20) -> dict:
    sql = "SELECT * FROM edge_devices ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, [limit])
            return {"found": True, "tool": "edge_devices", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_normal_behavior_models(is_active: bool | None = None, limit: int = 20) -> dict:
    where = "WHERE is_active = %s" if is_active is not None else ""
    params = [is_active, limit] if is_active is not None else [limit]
    sql = f"SELECT * FROM normal_behavior_models {where} ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "normal_behavior_models", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}

def get_rule_conflicts(status: str | None = None, limit: int = 20) -> dict:
    where = "WHERE status = %s" if status else ""
    params = [status, limit] if status else [limit]
    sql = f"SELECT * FROM rule_conflicts {where} ORDER BY created_at DESC LIMIT %s"
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return {"found": True, "tool": "rule_conflicts", "data": _rows_to_dicts(cur, cur.fetchall())}
    except Exception as e:
        return {"found": False, "error": str(e)}