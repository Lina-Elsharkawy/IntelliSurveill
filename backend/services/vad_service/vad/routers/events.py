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
def get_reasoning_jobs(status: str | None = None, decision: str | None = None, case_id: int | None = None, limit: int = 50) -> dict[str, Any]:
    """List queued/running/completed VAD reasoning jobs with joined case and result data for UI/debugging."""
    try:
        safe_limit = max(1, min(int(limit), 200))
        with db.connect() as conn:
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
                "final_uncertain": 0
            }
            
            for item in joined_data:
                job_status = item.get("job", {}).get("status")
                if job_status in summary:
                    summary[job_status] += 1
                
                result = item.get("result")
                if result:
                    # Also check python_final_result_json as requested
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
        with db.connect() as conn:
            jobs = db.get_reasoning_jobs_for_gate_event(conn, gate_event_id=event_id)
            results = db.get_reasoning_results_for_gate_event(conn, gate_event_id=event_id)
            return {"reasoning_jobs": jobs, "reasoning_results": results}
    except Exception as e:
        log.exception("Failed to get reasoning jobs for VAD event %s", event_id)
        raise HTTPException(status_code=500, detail=str(e))
