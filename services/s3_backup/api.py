"""
FastAPI REST API for the S3 backup service.

Provides endpoints to:
  - GET  /backup/config   – read current backup config
  - PUT  /backup/config   – update schedule & prefixes
  - POST /backup/trigger  – trigger an immediate backup
  - GET  /backup/status   – last sync statistics
  - GET  /health          – health check
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backup import run_sync, _load_state
from config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("s3_backup.api")

# ── Persisted runtime config ────────────────────────────────────


class BackupConfigModel(BaseModel):
    """Runtime-editable backup configuration."""
    enabled: bool = Field(True, description="Whether scheduled backup is enabled")
    interval_hours: int = Field(6, ge=1, le=168, description="Hours between backups")
    prefixes: list[str] = Field(
        default_factory=lambda: ["faces/"],
        description="MinIO object prefixes to back up",
    )


def _load_config() -> BackupConfigModel:
    """Load persisted backup configuration."""
    try:
        data = Path(settings.config_file).read_text(encoding="utf-8")
        return BackupConfigModel(**json.loads(data))
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        # Build from env defaults
        prefixes = [p.strip() for p in settings.backup_prefixes.split(",") if p.strip()]
        return BackupConfigModel(
            enabled=True,
            interval_hours=settings.backup_interval_hours,
            prefixes=prefixes or ["faces/"],
        )


def _save_config(cfg: BackupConfigModel) -> None:
    """Persist backup configuration to disk."""
    p = Path(settings.config_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(p)


# ── Scheduler ────────────────────────────────────────────────────

scheduler = BackgroundScheduler(daemon=True)
_sync_lock = threading.Lock()
_is_running = False


def _scheduled_sync() -> None:
    """Run sync as a scheduled job (thread-safe)."""
    global _is_running
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already in progress, skipping scheduled run")
        return
    try:
        _is_running = True
        cfg = _load_config()
        logger.info("Scheduled sync starting (prefixes=%s)", cfg.prefixes)
        result = run_sync(prefixes=cfg.prefixes)
        logger.info("Scheduled sync complete: %s", result)
    except Exception as exc:
        logger.error("Scheduled sync failed: %s", exc)
    finally:
        _is_running = False
        _sync_lock.release()


def _reschedule(cfg: BackupConfigModel) -> None:
    """Update the scheduler based on current config."""
    job_id = "backup_sync"

    # Remove existing job if present
    existing = scheduler.get_job(job_id)
    if existing:
        scheduler.remove_job(job_id)

    if cfg.enabled:
        scheduler.add_job(
            _scheduled_sync,
            trigger=IntervalTrigger(hours=cfg.interval_hours),
            id=job_id,
            name="MinIO → S3 backup sync",
            replace_existing=True,
        )
        logger.info("Scheduler armed: every %dh", cfg.interval_hours)
    else:
        logger.info("Scheduler disabled")


# ── App lifecycle ────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop scheduler with the app."""
    cfg = _load_config()
    scheduler.start()
    _reschedule(cfg)
    logger.info("S3 backup service started (port=%d)", settings.api_port)

    yield

    scheduler.shutdown(wait=False)
    logger.info("S3 backup service stopped")


# ── Graceful shutdown ────────────────────────────────────────────


def _handle_signal(signum, frame):
    logger.info("Received signal %d, shutting down…", signum)
    scheduler.shutdown(wait=False)
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ── FastAPI app ──────────────────────────────────────────────────

app = FastAPI(
    title="S3 Backup Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Request / Response models ────────────────────────────────────


class ConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = Field(None, ge=1, le=168)
    prefixes: list[str] | None = None


class ConfigResponse(BaseModel):
    enabled: bool
    interval_hours: int
    prefixes: list[str]
    aws_s3_bucket: str
    aws_s3_region: str


class SyncStatusResponse(BaseModel):
    last_sync_timestamp: str | None = None
    last_sync_objects: int = 0
    last_sync_bytes: int = 0
    last_sync_duration: float = 0.0
    last_sync_failed: int = 0
    is_running: bool = False


class TriggerResponse(BaseModel):
    message: str
    objects_synced: int = 0
    objects_failed: int = 0
    bytes_transferred: int = 0
    duration_seconds: float = 0.0


# ── Routes ───────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "s3-backup"}


@app.get("/backup/config", response_model=ConfigResponse)
def get_config():
    cfg = _load_config()
    return ConfigResponse(
        enabled=cfg.enabled,
        interval_hours=cfg.interval_hours,
        prefixes=cfg.prefixes,
        aws_s3_bucket=settings.aws_s3_bucket,
        aws_s3_region=settings.aws_s3_region,
    )


@app.put("/backup/config", response_model=ConfigResponse)
def update_config(req: ConfigUpdateRequest):
    cfg = _load_config()

    if req.enabled is not None:
        cfg.enabled = req.enabled
    if req.interval_hours is not None:
        cfg.interval_hours = req.interval_hours
    if req.prefixes is not None:
        # Validate prefixes
        valid = [p.strip() for p in req.prefixes if p.strip()]
        if not valid:
            raise HTTPException(400, "At least one prefix is required")
        cfg.prefixes = valid

    _save_config(cfg)
    _reschedule(cfg)

    logger.info("Config updated: %s", cfg.model_dump())

    return ConfigResponse(
        enabled=cfg.enabled,
        interval_hours=cfg.interval_hours,
        prefixes=cfg.prefixes,
        aws_s3_bucket=settings.aws_s3_bucket,
        aws_s3_region=settings.aws_s3_region,
    )


@app.get("/backup/status", response_model=SyncStatusResponse)
def get_status():
    state = _load_state(settings.sync_state_file)
    return SyncStatusResponse(
        last_sync_timestamp=state.get("last_sync_timestamp"),
        last_sync_objects=state.get("last_sync_objects", 0),
        last_sync_bytes=state.get("last_sync_bytes", 0),
        last_sync_duration=state.get("last_sync_duration", 0.0),
        last_sync_failed=state.get("last_sync_failed", 0),
        is_running=_is_running,
    )


@app.post("/backup/trigger", response_model=TriggerResponse)
def trigger_backup():
    global _is_running

    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "A backup is already in progress")

    try:
        _is_running = True
        cfg = _load_config()
        result = run_sync(prefixes=cfg.prefixes)
        return TriggerResponse(
            message="Backup completed successfully",
            objects_synced=result["objects_synced"],
            objects_failed=result["objects_failed"],
            bytes_transferred=result["bytes_transferred"],
            duration_seconds=result["duration_seconds"],
        )
    except Exception as exc:
        logger.error("Manual backup failed: %s", exc)
        raise HTTPException(500, f"Backup failed: {exc}")
    finally:
        _is_running = False
        _sync_lock.release()


# ── Entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )