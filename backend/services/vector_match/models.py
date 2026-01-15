from typing import List, Optional
from pydantic import BaseModel, Field


class EdgeEvent(BaseModel):
    event_id: str
    camera_id: int
    ts: Optional[str] = None

    embedding: List[float] = Field(..., min_items=2)

    event_type: Optional[str] = "face_detected"
    location: Optional[str] = None
    device_status: Optional[str] = None
    image_video_ref: Optional[str] = None
    processing_time_ms: Optional[int] = None
    model_version: Optional[str] = None

    quality_score: Optional[float] = None


class MatchResponse(BaseModel):
    event_id: str
    status: str
    entry_log_id: int
    detected_id: Optional[int] = None

    best_similarity: Optional[float] = None
    second_similarity: Optional[float] = None
    margin: Optional[float] = None

    auto_learned: bool = False
    unknown_face_event_id: Optional[int] = None


class AssignUnknownRequest(BaseModel):
    unknown_face_event_id: int
    detected_id: int
    promote_to_authoritative: bool = False
    notes: Optional[str] = None
