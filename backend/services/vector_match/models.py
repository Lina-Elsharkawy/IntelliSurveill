from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

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


class CreateIdentityFromUnknownRequest(BaseModel):
    unknown_face_event_id: int
    name: Optional[str] = None
    additional_info: Optional[str] = None
    promote_to_authoritative: bool = True
    notes: Optional[str] = None


class PendingUnknownItem(BaseModel):
    id: int
    entry_log_id: int
    embedding_model: str
    status: str
    assigned_detected_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime

    camera_id: Optional[int] = None
    location: Optional[str] = None
    event_type: Optional[str] = None
    image_video_ref: Optional[str] = None


class EntryLogItem(BaseModel):
    id: int
    timestamp: str
    detected_id: Optional[int] = None
    camera_id: Optional[int] = None
    authorized: Optional[bool] = None
    event_type: Optional[str] = None
    location: Optional[str] = None
    device_status: Optional[str] = None
    image_video_ref: Optional[str] = None
    processing_time: Optional[str] = None
    model_version: Optional[str] = None


class IdentityItem(BaseModel):
    id: int
    name: Optional[str] = None
    additional_info: Optional[str] = None
    employee_id: Optional[int] = None
    visitor: Optional[bool] = None
    visitor_id: Optional[int] = None
    embeddings_count: int
    authoritative_count: int
