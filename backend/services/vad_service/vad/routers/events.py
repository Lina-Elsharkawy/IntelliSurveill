from __future__ import annotations

import logging
import time
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from psycopg import Connection

from .deps import cfg, db

log = logging.getLogger("vad.routers.events")

router = APIRouter(prefix="/vad", tags=["VAD Events"])


@contextmanager
def db_connect_with_retry(attempts: int = 3, base_delay_sec: float = 0.25) -> Iterator[Connection]:
    """Open a PostgreSQL connection with a tiny retry for transient Docker DNS hiccups.

    This is intentionally used by read/API routes so a momentary Docker name-resolution
    failure such as "Temporary failure in name resolution" does not immediately surface
    to the frontend as a 500 error.
    """
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with db.connect() as conn:
                yield conn
                return
        except psycopg.OperationalError as exc:
            last_exc = exc
            if attempt >= attempts:
                break

            delay = base_delay_sec * attempt
            log.warning(
                "DB connection attempt %s/%s failed in events route; retrying in %.2fs: %s",
                attempt,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


@router.get("/rtsp/events")
def get_events(gate: str | None = None, limit: str | None = "50") -> dict[str, Any]:
    try:
        parsed_limit = _parse_optional_limit(limit, default=50)
        with db_connect_with_retry() as conn:
            events = db.get_recent_gate_events(conn, limit=parsed_limit, gate_name=gate)
            # Do not synthesize persistence fields here. Return DB values as-is so
            # the UI/evaluation layer does not mistake display defaults for measured state.
            return {"events": events}
    except Exception as e:
        log.exception("Failed to get VAD events")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rtsp/events/{event_id}")
def get_event_details(event_id: int) -> dict[str, Any]:
    try:
        from vad.minio_client import VadMinioClient

        minio_client = VadMinioClient(cfg)
        with db_connect_with_retry() as conn:
            evidence = db.get_event_evidence(conn, event_id=event_id)
            for item in evidence:
                if item.get("object_key"):
                    try:
                        url = minio_client.generate_presigned_url(item["object_key"])
                        item["presigned_url"] = url
                        item["url"] = url
                    except Exception as e:
                        log.warning("Could not generate presigned URL for %s: %s", item["object_key"], e)
            return {"evidence": evidence}
    except Exception as e:
        log.exception("Failed to get details for event %s", event_id)
        raise HTTPException(status_code=500, detail=str(e))




def _summary_int(row: dict[str, Any], key: str) -> int:
    value = row.get(key, 0)
    return int(value or 0)


def _parse_optional_limit(value: str | int | None, *, default: int = 50) -> int | None:
    """Parse list endpoint limits.

    Returns None for an intentionally uncapped/full result set. Supported
    uncapped values are: all, none, unlimited, 0, and -1.
    """
    if value is None or value == "":
        return default

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"all", "none", "unlimited", "0", "-1"}:
            return None
        value = normalized

    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit must be a positive integer or 'all'")

    if parsed <= 0:
        return None
    return parsed


def _build_reasoning_summary(
    conn: Connection,
    *,
    status: str | None,
    decision: str | None,
    case_id: int | None,
    returned_count: int,
    limit: int | None,
) -> dict[str, Any]:
    """Count reasoning jobs across the full filtered result set, not only the limited page.

    The final decision expression mirrors the worker output priority:
    python_final_result_json > structured_output_json fallback > raw result alert_decision.
    """
    final_decision_sql = """COALESCE(
        NULLIF(r.python_final_result_json->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_final_guardrails'->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_validation_result'->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_final_result'->>'final_alert_decision', ''),
        r.alert_decision,
        CASE WHEN j.status = 'failed' AND r.id IS NULL THEN 'FAILED' END
    )"""

    query = f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE j.status = 'queued') AS queued,
            COUNT(*) FILTER (WHERE j.status = 'running') AS running,
            COUNT(*) FILTER (WHERE j.status = 'succeeded') AS succeeded,
            COUNT(*) FILTER (WHERE j.status = 'failed') AS failed,
            COUNT(*) FILTER (WHERE {final_decision_sql} = 'YES') AS final_yes,
            COUNT(*) FILTER (WHERE {final_decision_sql} = 'NO') AS final_no,
            COUNT(*) FILTER (WHERE {final_decision_sql} = 'UNCERTAIN') AS final_uncertain
        FROM vad_reasoning_jobs j
        LEFT JOIN LATERAL (
            SELECT *
            FROM vad_reasoning_results rr
            WHERE rr.reasoning_job_id = j.id
            ORDER BY rr.id DESC
            LIMIT 1
        ) r ON true
        WHERE 1=1
    """
    params: dict[str, Any] = {}

    if status:
        query += " AND j.status = %(status)s"
        params["status"] = status
    if case_id:
        query += " AND j.case_id = %(case_id)s"
        params["case_id"] = case_id
    if decision:
        query += f" AND {final_decision_sql} = %(decision)s"
        params["decision"] = decision

    row = dict(conn.execute(query, params).fetchone() or {})
    return {
        "total": _summary_int(row, "total"),
        "returned": int(returned_count),
        "limit": None if limit is None else int(limit),
        "queued": _summary_int(row, "queued"),
        "running": _summary_int(row, "running"),
        "succeeded": _summary_int(row, "succeeded"),
        "failed": _summary_int(row, "failed"),
        "final_yes": _summary_int(row, "final_yes"),
        "final_no": _summary_int(row, "final_no"),
        "final_uncertain": _summary_int(row, "final_uncertain"),
    }

class EvidenceUrlsRequest(BaseModel):
    object_keys: list[str]

@router.post("/rtsp/evidence/urls")
def get_evidence_urls(req: EvidenceUrlsRequest) -> dict[str, Any]:
    """Generate presigned URLs for a batch of MinIO object keys."""
    try:
        from vad.minio_client import VadMinioClient
        minio_client = VadMinioClient(cfg)
        
        urls = {}
        for key in req.object_keys:
            if not key:
                continue
            try:
                urls[key] = minio_client.generate_presigned_url(key)
            except Exception as e:
                log.warning("Could not generate presigned URL for %s: %s", key, e)
                
        return {"urls": urls}
    except Exception as e:
        log.exception("Failed to generate evidence urls")
        raise HTTPException(status_code=500, detail=str(e))




# ─────────────────────────────────────────────────────────────────────────────
# Analytics summary endpoint
# ─────────────────────────────────────────────────────────────────────────────
# The frontend analytics tab used to call /events?limit=500 and then aggregate
# everything client-side. That is unsafe for "All Data": the dashboard can only
# ever show the latest page. This endpoint returns server-side analytics over the
# full filtered DB result set.

_GATE_LABELS = {
    "pose": "Pose Micro-Motion",
    "deep": "Deep Visual Similarity",
    "homography": "Homography Motion",
}

_GATE_COLORS = {
    "pose": "#d97706",
    "deep": "#6366f1",
    "homography": "#0891b2",
}

_DECISION_COLORS = {
    "YES": "#ef4444",
    "NO": "#22c55e",
    "UNCERTAIN": "#6366f1",
    "FAILED": "#6b7280",
}

_SEVERITY_COLORS = {
    "NONE": "#52525b",
    "LOW": "#16a34a",
    "MEDIUM": "#d97706",
    "HIGH": "#ea580c",
    "CRITICAL": "#dc2626",
}


def _normalise_gate(raw: Any) -> str:
    g = str(raw or "").lower().strip()
    if g in {"homography", "homo", "macro", "homography_macro"} or "homography" in g or "macro" in g:
        return "homography"
    if g == "pose" or "pose" in g:
        return "pose"
    return "deep"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dt_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _event_timestamp(row: dict[str, Any]) -> Any:
    return row.get("peak_ts") or row.get("start_ts")


def _final_decision(row: dict[str, Any]) -> str:
    pfr = _as_dict(row.get("python_final_result_json"))
    if pfr.get("final_alert_decision"):
        return str(pfr.get("final_alert_decision")).upper()

    structured = _as_dict(row.get("structured_output_json"))
    for key in ("python_final_guardrails", "python_validation_result", "python_final_result"):
        sub = _as_dict(structured.get(key))
        if sub.get("final_alert_decision"):
            return str(sub.get("final_alert_decision")).upper()

    if row.get("alert_decision"):
        return str(row.get("alert_decision")).upper()
    if row.get("job_status") == "failed":
        return "FAILED"
    return "UNCERTAIN"


def _final_severity(row: dict[str, Any]) -> str:
    pfr = _as_dict(row.get("python_final_result_json"))
    if pfr.get("final_severity"):
        return str(pfr.get("final_severity")).upper()
    if row.get("result_severity"):
        return str(row.get("result_severity")).upper()
    return "NONE"


def _job_gate(row: dict[str, Any]) -> str:
    metadata = _as_dict(row.get("metadata_json"))
    bundle = _as_dict(row.get("input_bundle_json"))
    event = _as_dict(bundle.get("event"))
    return _normalise_gate(
        metadata.get("source_gate_name")
        or row.get("primary_gate_name")
        or event.get("gate_name")
        or "deep"
    )


def _job_score_ratio(row: dict[str, Any], event_by_id: dict[int, dict[str, Any]]) -> float:
    bundle = _as_dict(row.get("input_bundle_json"))
    event = _as_dict(bundle.get("event"))
    score_summary = _as_dict(row.get("score_summary_json"))
    for value in (
        event.get("ratio"),
        event.get("score_ratio"),
        bundle.get("score_ratio"),
        score_summary.get("score_ratio"),
    ):
        ratio = _safe_float(value, 0.0)
        if ratio > 0:
            return ratio

    event_id = _safe_int(row.get("gate_event_id"), 0)
    ev = event_by_id.get(event_id)
    if ev:
        threshold = _safe_float(ev.get("threshold_value"), 0.0)
        if threshold > 0:
            return _safe_float(ev.get("peak_score"), 0.0) / threshold
    return 0.0


def _evidence_keys(row: dict[str, Any]) -> list[str]:
    bundle = _as_dict(row.get("input_bundle_json"))
    visual_evidence = _as_dict(bundle.get("visual_evidence"))
    keys = visual_evidence.get("object_keys")
    if isinstance(keys, list):
        return [str(k) for k in keys if k]

    evidence_bundle = row.get("evidence_bundle_json")
    if isinstance(evidence_bundle, dict):
        keys = evidence_bundle.get("object_keys")
        if isinstance(keys, list):
            return [str(k) for k in keys if k]
    if isinstance(evidence_bundle, list):
        return [str(e.get("object_key")) for e in evidence_bundle if isinstance(e, dict) and e.get("object_key")]
    return []


def _build_volume(events: list[dict[str, Any]], time_range: str) -> list[dict[str, Any]]:
    hourly = time_range in {"today", "24h"}
    if hourly:
        buckets: dict[str, dict[str, int]] = {
            f"{h:02d}:00": {"pose": 0, "deep": 0, "homography": 0} for h in range(24)
        }
        for ev in events:
            ts = _event_timestamp(ev)
            if not ts:
                continue
            hour = ts.hour if hasattr(ts, "hour") else datetime.fromisoformat(str(ts).replace("Z", "+00:00")).hour
            key = f"{hour:02d}:00"
            gate = _normalise_gate(ev.get("gate_name"))
            if key in buckets:
                buckets[key][gate] += 1
        return [{"time": k, **v} for k, v in buckets.items()]

    buckets: dict[str, dict[str, int]] = {}
    for ev in events:
        ts = _event_timestamp(ev)
        if not ts:
            continue
        if hasattr(ts, "date"):
            key = ts.date().isoformat()
        else:
            key = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
        buckets.setdefault(key, {"pose": 0, "deep": 0, "homography": 0})
        buckets[key][_normalise_gate(ev.get("gate_name"))] += 1
    return [{"time": k, **buckets[k]} for k in sorted(buckets)]


def _build_summary_strip(events_count: int, dominant_gate: str | None, alert_rate: int, evidence_coverage: int) -> str:
    if events_count == 0:
        return "No anomaly events detected for the selected period"
    parts = [f"{events_count} anomaly event{'s' if events_count != 1 else ''} detected"]
    if dominant_gate:
        parts.append(f"{_GATE_LABELS[dominant_gate]} is dominant")
    parts.append(f"{alert_rate}% alert decision rate")
    if evidence_coverage > 0:
        parts.append(f"{evidence_coverage}% evidence coverage")
    return "  ·  ".join(parts)


def _reasoning_filter_sql() -> tuple[str, str]:
    final_decision_sql = """COALESCE(
        NULLIF(r.python_final_result_json->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_final_guardrails'->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_validation_result'->>'final_alert_decision', ''),
        NULLIF(r.structured_output_json->'python_final_result'->>'final_alert_decision', ''),
        r.alert_decision,
        CASE WHEN j.status = 'failed' AND r.id IS NULL THEN 'FAILED' END
    )"""
    final_severity_sql = """COALESCE(
        NULLIF(r.python_final_result_json->>'final_severity', ''),
        r.severity
    )"""
    return final_decision_sql, final_severity_sql


def _fetch_analytics_events(
    conn: Connection,
    *,
    cutoff_ts: datetime | None,
    gate: str | None,
    decision: str | None,
    severity: str | None,
) -> list[dict[str, Any]]:
    final_decision_sql, final_severity_sql = _reasoning_filter_sql()
    params: dict[str, Any] = {"cutoff_ts": cutoff_ts, "gate": gate, "decision": decision, "severity": severity}
    query = """
        SELECT e.id, e.event_key, e.gate_name, e.severity, e.start_ts, e.peak_ts, e.peak_score,
               e.threshold_value, e.persistence_hits, e.persistence_window,
               TRUE AS persistent,
               e.track_id,
               t.tracker_track_id, t.global_track_key,
               e.reason_when_fired
        FROM vad_gate_events e
        LEFT JOIN vad_tracks t ON e.track_id = t.id
        WHERE 1=1
    """
    if cutoff_ts is not None:
        query += " AND COALESCE(e.peak_ts, e.start_ts) >= %(cutoff_ts)s"
    if gate:
        query += " AND e.gate_name = %(gate)s"
    if decision or severity:
        query += f"""
            AND EXISTS (
                SELECT 1
                FROM vad_case_gate_events cge
                JOIN vad_anomaly_cases c ON c.id = cge.case_id
                JOIN vad_reasoning_jobs j ON j.case_id = c.id
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM vad_reasoning_results rr
                    WHERE rr.reasoning_job_id = j.id
                    ORDER BY rr.id DESC
                    LIMIT 1
                ) r ON true
                WHERE cge.gate_event_id = e.id
        """
        if decision:
            query += f" AND {final_decision_sql} = %(decision)s"
        if severity:
            query += f" AND {final_severity_sql} = %(severity)s"
        query += " )"
    query += " ORDER BY e.start_ts ASC, e.id ASC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def _fetch_analytics_jobs(
    conn: Connection,
    *,
    cutoff_ts: datetime | None,
    gate: str | None,
    decision: str | None,
    severity: str | None,
) -> list[dict[str, Any]]:
    final_decision_sql, final_severity_sql = _reasoning_filter_sql()
    gate_sql = """COALESCE(
        NULLIF(j.metadata_json->>'source_gate_name', ''),
        NULLIF(c.primary_gate_name, ''),
        NULLIF(j.input_bundle_json->'event'->>'gate_name', ''),
        'deep'
    )"""
    params: dict[str, Any] = {"cutoff_ts": cutoff_ts, "gate": gate, "decision": decision, "severity": severity}
    query = f"""
        SELECT
            j.id AS job_id, j.case_id AS job_case_id, j.status AS job_status,
            j.queued_at, j.started_at, j.finished_at,
            j.input_bundle_json, j.metadata_json,
            c.id AS case_id, c.case_key, c.primary_gate_name, c.case_type,
            c.status AS case_status, c.severity AS case_severity,
            c.session_id, c.primary_track_id, c.start_ts, c.peak_ts,
            c.score_summary_json, c.evidence_bundle_json,
            cge.gate_event_id,
            r.id AS result_id, r.alert_decision, r.severity AS result_severity,
            r.event_type, r.confidence, r.structured_output_json,
            r.vlm_visual_review_json, r.llm_policy_review_json,
            r.python_final_result_json, r.uncertainty_json
        FROM vad_reasoning_jobs j
        LEFT JOIN vad_anomaly_cases c ON j.case_id = c.id
        LEFT JOIN LATERAL (
            SELECT cge.gate_event_id
            FROM vad_case_gate_events cge
            WHERE cge.case_id = c.id
            ORDER BY (cge.relation = 'primary') DESC, cge.gate_event_id DESC
            LIMIT 1
        ) cge ON true
        LEFT JOIN LATERAL (
            SELECT *
            FROM vad_reasoning_results rr
            WHERE rr.reasoning_job_id = j.id
            ORDER BY rr.id DESC
            LIMIT 1
        ) r ON true
        WHERE 1=1
    """
    if cutoff_ts is not None:
        query += " AND COALESCE(c.peak_ts, j.queued_at) >= %(cutoff_ts)s"
    if gate:
        query += f" AND {gate_sql} = %(gate)s"
    if decision:
        query += f" AND {final_decision_sql} = %(decision)s"
    if severity:
        query += f" AND {final_severity_sql} = %(severity)s"
    query += " ORDER BY COALESCE(c.peak_ts, j.queued_at) ASC, j.id ASC"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


@router.get("/rtsp/analytics/summary")
def get_anomaly_analytics_summary(
    cutoff_ts: datetime | None = None,
    time_range: str = "all",
    gate: str | None = None,
    decision: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    """Return VAD anomaly analytics over the full filtered DB result set.

    This endpoint intentionally avoids page limits. It should be used by the
    analytics dashboard instead of aggregating `/events?limit=N` in the browser.
    """
    try:
        gate = None if gate in (None, "", "all") else _normalise_gate(gate)
        decision = None if decision in (None, "", "all") else str(decision).upper()
        severity = None if severity in (None, "", "all") else str(severity).upper()
        time_range = str(time_range or "all")

        with db_connect_with_retry() as conn:
            events = _fetch_analytics_events(conn, cutoff_ts=cutoff_ts, gate=gate, decision=decision, severity=severity)
            jobs = _fetch_analytics_jobs(conn, cutoff_ts=cutoff_ts, gate=gate, decision=decision, severity=severity)

        event_by_id = {_safe_int(e.get("id")): e for e in events}
        gate_counts = {"pose": 0, "deep": 0, "homography": 0}
        ratios: list[float] = []
        for ev in events:
            ev_gate = _normalise_gate(ev.get("gate_name"))
            gate_counts[ev_gate] += 1
            threshold = _safe_float(ev.get("threshold_value"), 0.0)
            if threshold > 0:
                ratios.append(_safe_float(ev.get("peak_score"), 0.0) / threshold)

        dominant_gate = None
        if events:
            dominant_gate = max(gate_counts.items(), key=lambda kv: kv[1])[0]
            if gate_counts.get(dominant_gate, 0) <= 0:
                dominant_gate = None

        persistent_events = sum(
            1 for ev in events
            if bool(ev.get("persistent")) or _safe_int(ev.get("persistence_hits"), 0) > 0
        )
        jobs_with_result = [j for j in jobs if j.get("result_id") is not None]
        yes_count = sum(1 for j in jobs_with_result if _final_decision(j) == "YES")
        alert_rate = round((yes_count / len(jobs_with_result)) * 100) if jobs_with_result else 0
        evidence_keys_by_job = [_evidence_keys(j) for j in jobs]
        jobs_with_evidence = sum(1 for keys in evidence_keys_by_job if keys)
        evidence_coverage = round((jobs_with_evidence / len(jobs)) * 100) if jobs else 0

        gate_health = []
        for g in ("pose", "deep", "homography"):
            gate_events = [e for e in events if _normalise_gate(e.get("gate_name")) == g]
            gate_ratios = []
            for ev in gate_events:
                threshold = _safe_float(ev.get("threshold_value"), 0.0)
                if threshold > 0:
                    gate_ratios.append(_safe_float(ev.get("peak_score"), 0.0) / threshold)
            last_ts = max((_event_timestamp(e) for e in gate_events if _event_timestamp(e)), default=None)
            gate_health.append({
                "gate": g,
                "eventCount": len(gate_events),
                "avgRatio": (sum(gate_ratios) / len(gate_ratios)) if gate_ratios else 0,
                "maxRatio": max(gate_ratios) if gate_ratios else 0,
                "lastEventTime": _dt_iso(last_ts),
                "hasReasoning": any(_job_gate(j) == g for j in jobs),
            })

        decision_map = {"YES": 0, "NO": 0, "UNCERTAIN": 0, "FAILED": 0}
        severity_map = {"NONE": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for j in jobs:
            if j.get("result_id") is None and j.get("job_status") != "failed":
                continue
            d = _final_decision(j)
            decision_map[d if d in decision_map else "UNCERTAIN"] += 1
            if j.get("result_id") is not None:
                s = _final_severity(j)
                severity_map[s if s in severity_map else "NONE"] += 1

        score_ratio_points = []
        for ev in events:
            threshold = _safe_float(ev.get("threshold_value"), 0.0)
            if threshold <= 0:
                continue
            ratio = _safe_float(ev.get("peak_score"), 0.0) / threshold
            g = _normalise_gate(ev.get("gate_name"))
            score_ratio_points.append({
                "time": _dt_iso(_event_timestamp(ev)) or "",
                "pose": ratio if g == "pose" else None,
                "deep": ratio if g == "deep" else None,
                "homography": ratio if g == "homography" else None,
            })
        for j in jobs:
            ratio = _job_score_ratio(j, event_by_id)
            if ratio <= 0:
                continue
            g = _job_gate(j)
            score_ratio_points.append({
                "time": _dt_iso(j.get("queued_at")) or "",
                "pose": ratio if g == "pose" else None,
                "deep": ratio if g == "deep" else None,
                "homography": ratio if g == "homography" else None,
            })
        score_ratio_points = sorted(score_ratio_points, key=lambda x: x.get("time") or "")[-200:]

        jobs_annotated = 0
        jobs_montage = 0
        jobs_frames = 0
        total_frame_count = 0
        missing_evidence = 0
        for keys in evidence_keys_by_job:
            if not keys:
                missing_evidence += 1
                continue
            has_annotated = any("annotated_frame" in k for k in keys)
            has_montage = any("tubelet_montage" in k for k in keys)
            frame_count = sum(1 for k in keys if "frames/" in k or "frame_" in k or "tubelet_frame" in k)
            if has_annotated:
                jobs_annotated += 1
            if has_montage:
                jobs_montage += 1
            if frame_count > 0:
                jobs_frames += 1
                total_frame_count += frame_count
            if not has_annotated and not has_montage and frame_count == 0:
                missing_evidence += 1

        priority = []
        for j in jobs:
            if j.get("result_id") is None:
                continue
            g = _job_gate(j)
            bundle = _as_dict(j.get("input_bundle_json"))
            ev_bundle = _as_dict(bundle.get("event"))
            metadata = _as_dict(j.get("metadata_json"))
            priority.append({
                "time": _dt_iso(j.get("peak_ts") or j.get("queued_at")) or "",
                "gate": g,
                "peakRatio": _job_score_ratio(j, event_by_id),
                "decision": _final_decision(j),
                "severity": _final_severity(j),
                "trackId": str(
                    ev_bundle.get("tracker_track_id")
                    or metadata.get("tracker_track_id")
                    or j.get("primary_track_id")
                    or ""
                ),
                "eventId": str(j.get("gate_event_id") or metadata.get("source_gate_event_id") or ev_bundle.get("id") or ""),
                "caseId": str(j.get("case_id") or j.get("job_case_id") or ""),
                "hasEvidence": bool(_evidence_keys(j)),
            })

        decision_rank = {"YES": 0, "UNCERTAIN": 1, "NO": 2, "FAILED": 3}
        severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
        priority.sort(
            key=lambda item: (
                decision_rank.get(item["decision"], 99),
                severity_rank.get(item["severity"], 99),
                -float(item["peakRatio"] or 0),
                item["time"],
            )
        )

        pipeline_health = {
            "total": len(jobs),
            "returned": len(jobs),
            "limit": len(jobs),
            "queued": sum(1 for j in jobs if j.get("job_status") == "queued"),
            "running": sum(1 for j in jobs if j.get("job_status") == "running"),
            "succeeded": sum(1 for j in jobs if j.get("job_status") == "succeeded"),
            "failed": sum(1 for j in jobs if j.get("job_status") == "failed"),
            "final_yes": decision_map["YES"],
            "final_no": decision_map["NO"],
            "final_uncertain": decision_map["UNCERTAIN"],
        }

        return {
            "kpis": {
                "totalEvents": len(events),
                "persistentEvents": persistent_events,
                "alertDecisionRate": alert_rate,
                "dominantGate": dominant_gate,
                "avgScoreRatio": (sum(ratios) / len(ratios)) if ratios else 0,
                "evidenceCoverage": evidence_coverage,
            },
            "gateHealth": gate_health,
            "volumeOverTime": _build_volume(events, time_range),
            "gateDistribution": [
                {"name": _GATE_LABELS[g], "value": count, "color": _GATE_COLORS[g]}
                for g, count in gate_counts.items() if count > 0
            ],
            "decisionCounts": [
                {"name": name, "value": value, "color": _DECISION_COLORS[name]}
                for name, value in decision_map.items()
            ],
            "severityCounts": [
                {"name": name, "value": value, "color": _SEVERITY_COLORS[name]}
                for name, value in severity_map.items()
            ],
            "scoreRatioTimeline": score_ratio_points,
            "evidenceHealth": {
                "totalJobs": len(jobs),
                "jobsWithEvidence": jobs_with_evidence,
                "jobsAnnotatedFrame": jobs_annotated,
                "jobsTubeletMontage": jobs_montage,
                "jobsWithFrames": jobs_frames,
                "totalFrameCount": total_frame_count,
                "missingEvidence": missing_evidence,
            },
            "pipelineHealth": pipeline_health,
            "prioritizedEvents": priority[:25],
            "summaryStrip": _build_summary_strip(len(events), dominant_gate, alert_rate, evidence_coverage),
            "sourceMeta": {
                "source": "backend_full_db_aggregation",
                "cutoffTs": _dt_iso(cutoff_ts),
                "timeRange": time_range,
                "eventsScanned": len(events),
                "reasoningJobsScanned": len(jobs),
            },
        }
    except Exception as e:
        log.exception("Failed to build VAD anomaly analytics summary")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rtsp/reasoning/jobs")
def get_reasoning_jobs(status: str | None = None, decision: str | None = None, case_id: int | None = None, limit: str | None = "50") -> dict[str, Any]:
    """List queued/running/completed VAD reasoning jobs with joined case and result data for UI/debugging."""
    try:
        status = None if status in (None, "", "all") else status
        decision = None if decision in (None, "", "all") else decision
        parsed_limit = _parse_optional_limit(limit, default=50)
        with db_connect_with_retry() as conn:
            joined_data = db.get_joined_reasoning_jobs(conn, status=status, decision=decision, case_id=case_id, limit=parsed_limit)

            summary = _build_reasoning_summary(
                conn,
                status=status,
                decision=decision,
                case_id=case_id,
                returned_count=len(joined_data),
                limit=parsed_limit,
            )

            return {"items": joined_data, "summary": summary}
    except Exception as e:
        log.exception("Failed to get VAD reasoning jobs")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rtsp/events/{event_id}/reasoning")
def get_event_reasoning(event_id: int) -> dict[str, Any]:
    """Return reasoning jobs associated with one gate event."""
    try:
        with db_connect_with_retry() as conn:
            jobs = db.get_reasoning_jobs_for_gate_event(conn, gate_event_id=event_id)
            results = db.get_reasoning_results_for_gate_event(conn, gate_event_id=event_id)
            return {"reasoning_jobs": jobs, "reasoning_results": results}
    except Exception as e:
        log.exception("Failed to get reasoning jobs for VAD event %s", event_id)
        raise HTTPException(status_code=500, detail=str(e))
