from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vad.routers import api_router as vad_router, maybe_autostart_vad, shutdown_vad

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vad_service")

app = FastAPI(title="Backend-Direct VAD Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(vad_router)


@app.on_event("startup")
async def startup() -> None:
    log.info("Starting Backend-Direct VAD Service")
    maybe_autostart_vad()


@app.on_event("shutdown")
async def shutdown() -> None:
    log.info("Shutting down Backend-Direct VAD Service")
    shutdown_vad()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "vad-service",
        "mode": "backend_direct_rtsp",
    }
