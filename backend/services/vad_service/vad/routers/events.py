from __future__ import annotations

import logging
import time
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
def get_events(gate: str | None = None, limit: int = 50) -> dict[str, Any]:
    try:
        with db_connect_with_retry() as conn:
            events = db.get_recent_gate_events(conn, limit=limit, gate_name=gate)
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


@router.get("/rtsp/reasoning/jobs")
def get_reasoning_jobs(status: str | None = None, decision: str | None = None, case_id: int | None = None, limit: int = 50) -> dict[str, Any]:
    """List queued/running/completed VAD reasoning jobs with joined case and result data for UI/debugging."""
    try:
        safe_limit = max(1, min(int(limit), 200))
        with db_connect_with_retry() as conn:
            joined_data = db.get_joined_reasoning_jobs(conn, status=status, decision=decision, case_id=case_id, limit=safe_limit)

            # Compute summary
            summary = {
                "total": len(joined_data),
                "queued": 0,
                "running": 0,
                "succeeded": 0,
                "failed": 0,
                "final_yes": 0,
                "final_no": 0,
                "final_uncertain": 0,
            }

            for item in joined_data:
                job_status = item.get("job", {}).get("status")
                if job_status in summary:
                    summary[job_status] += 1

                result = item.get("result")
                if result:
                    # Also check python_final_result_json as requested.
                    final_res = result.get("python_final_result_json") or result.get("structured_output_json", {}).get("python_final_result") or {}
                    decision_val = final_res.get("final_alert_decision") or result.get("alert_decision")
                    if decision_val == "YES":
                        summary["final_yes"] += 1
                    elif decision_val == "NO":
                        summary["final_no"] += 1
                    elif decision_val == "UNCERTAIN":
                        summary["final_uncertain"] += 1

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
