"""
Investigation tools for the surveillance chatbot.
Each function is a precise, hand-written SQL query for a specific
investigation task — more reliable than asking a small LLM to write them.
"""
import psycopg2
from datetime import date, timedelta
from config import DB_DSN


def _conn():
    return psycopg2.connect(DB_DSN)


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


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _name_where_clause(name: str, params: list) -> str:
    """
    Build a WHERE fragment that matches ANY word in `name` against
    employee, visitor, and detected_people name columns (ILIKE).

    Handles prefixed names like "Eng Maged" — splits on whitespace and
    creates one OR condition per token so "Maged" always matches even when
    the prefix "Eng" is not stored in the DB.

    Side-effect: appends the required bind values to `params`.
    """
    tokens = [t.strip() for t in name.split() if t.strip()]
    if not tokens:
        tokens = [name]

    clauses = []
    for tok in tokens:
        pattern = f"%{tok}%"
        clauses.append("(e.name ILIKE %s OR v.name ILIKE %s OR dp.name ILIKE %s)")
        params += [pattern, pattern, pattern]

    return "(" + " AND ".join(clauses) + ")"


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