from fastapi import APIRouter
from .control import router as control_router, maybe_autostart_vad, shutdown_vad
from .events import router as events_router

api_router = APIRouter()
api_router.include_router(control_router)
api_router.include_router(events_router)

__all__ = ["api_router", "maybe_autostart_vad", "shutdown_vad"]
