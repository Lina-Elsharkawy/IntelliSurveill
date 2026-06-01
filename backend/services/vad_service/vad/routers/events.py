from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, HTTPException

from .deps import cfg, db

log = logging.getLogger("vad.routers.events")

router = APIRouter(prefix="/vad", tags=["VAD Events"])

@router.get("/rtsp/events")
def get_events(gate: str | None = None, limit: int = 50) -> dict[str, Any]:
    try:
        with db.connect() as conn:
            events = db.get_recent_gate_events(conn, limit=limit, gate_name=gate)
            for evt in events:
                evt["persistent"] = True
                evt["event_emitted"] = True
            return {"events": events}
    except Exception as e:
        log.exception("Failed to get VAD events")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rtsp/events/{event_id}")
def get_event_details(event_id: int) -> dict[str, Any]:
    try:
        from vad.minio_client import VadMinioClient
        minio_client = VadMinioClient(cfg)
        with db.connect() as conn:
            evidence = db.get_event_evidence(conn, event_id=event_id)
            for item in evidence:
                if item.get("object_key"):
                    try:
                        url = minio_client.generate_presigned_url(item["object_key"])
                        item["presigned_url"] = url
                        item["url"] = url
                    except Exception as e:
                        log.warning(f"Could not generate presigned URL for {item['object_key']}: {e}")
            return {"evidence": evidence}
    except Exception as e:
        log.exception(f"Failed to get details for event {event_id}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rtsp/reasoning/jobs")
def get_reasoning_jobs(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    """List queued/running/completed VAD reasoning jobs for UI/debugging."""
    try:
        safe_limit = max(1, min(int(limit), 200))
        with db.connect() as conn:
            jobs = db.get_recent_reasoning_jobs(conn, status=status, limit=safe_limit)
            return {"jobs": jobs}
    except Exception as e:
        log.exception("Failed to get VAD reasoning jobs")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rtsp/events/{event_id}/reasoning")
def get_event_reasoning(event_id: int) -> dict[str, Any]:
    """Return reasoning jobs associated with one gate event."""
    try:
        with db.connect() as conn:
            jobs = db.get_reasoning_jobs_for_gate_event(conn, gate_event_id=event_id)
            results = db.get_reasoning_results_for_gate_event(conn, gate_event_id=event_id)
            return {"reasoning_jobs": jobs, "reasoning_results": results}
    except Exception as e:
        log.exception("Failed to get reasoning jobs for VAD event %s", event_id)
        raise HTTPException(status_code=500, detail=str(e))
