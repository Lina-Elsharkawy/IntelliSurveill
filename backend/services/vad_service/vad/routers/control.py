from __future__ import annotations
import logging
from typing import Any
from fastapi import APIRouter, HTTPException

from .deps import cfg, sampler

log = logging.getLogger("vad.routers.control")

router = APIRouter(prefix="/vad", tags=["VAD Control"])

@router.get("/rtsp/config")
def get_vad_config() -> dict[str, Any]:
    return cfg.public_dict()

@router.post("/rtsp/start")
def start_rtsp_sampler() -> dict[str, Any]:
    try:
        return sampler.start()
    except Exception as e:
        log.exception("Could not start VAD RTSP sampler")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rtsp/stop")
def stop_rtsp_sampler() -> dict[str, Any]:
    try:
        return sampler.stop()
    except Exception as e:
        log.exception("Could not stop VAD RTSP sampler")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/rtsp/status")
def get_rtsp_status() -> dict[str, Any]:
    return sampler.status()

@router.post("/rtsp/debug/save-latest")
def save_latest_debug_frame() -> dict[str, Any]:
    try:
        return sampler.save_latest_debug_frame()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

def maybe_autostart_vad() -> None:
    if not cfg.backend_direct_enabled:
        log.info("VAD backend-direct path disabled; not autostarting")
        return

    if not cfg.autostart:
        log.info("VAD_AUTOSTART=0; manual RTSP start mode enabled")
        return

    try:
        log.info("VAD_AUTOSTART=1; starting RTSP sampler")
        sampler.start()
    except Exception:
        log.exception("VAD autostart failed")

def shutdown_vad() -> None:
    try:
        if sampler.is_running:
            log.info("Stopping VAD RTSP sampler")
            sampler.stop()
    except Exception:
        log.exception("VAD shutdown failed")
