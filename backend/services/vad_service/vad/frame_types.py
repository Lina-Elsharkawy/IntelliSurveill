from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np


@dataclass
class TrackedPerson:
    """One YOLO-tracked person for one decoded frame."""

    tracker_track_id: int
    bbox_xyxy: list[float]
    confidence: float | None
    class_id: int | None = 0
    class_name: str = "person"
    keypoints_xy: list[list[float]] = field(default_factory=list)
    keypoints_conf: list[float] = field(default_factory=list)
    detector_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SampledPerson:
    """One sampled tracked person on the canonical 5 fps VAD timeline."""

    frame_id: int
    detection_id: int | None
    db_track_id: int | None
    tracker_track_id: int
    sample_index: int
    captured_at: datetime
    frame_bgr: np.ndarray
    bbox_xyxy: list[float]
    confidence: float | None
    keypoints_xy: list[list[float]] = field(default_factory=list)
    keypoints_conf: list[float] = field(default_factory=list)


@dataclass
class PerTrackRouteBuffers:
    """In-memory route buffers for one tracked person.

    This is intentionally not a tubelet builder yet. It only proves that the
    backend has a shared sampled timeline and per-track history that all gates
    can consume later.
    """

    tracker_track_id: int
    db_track_id: int | None = None
    last_seen_sample_index: int = -1
    pose_samples: deque[SampledPerson] = field(default_factory=lambda: deque(maxlen=256))
    deep_samples: deque[SampledPerson] = field(default_factory=lambda: deque(maxlen=128))
    homography_macro_samples: deque[SampledPerson] = field(default_factory=lambda: deque(maxlen=128))

    def add(self, person: SampledPerson, *, used_by_pose: bool, used_by_deep: bool, used_by_homography_macro: bool) -> None:
        self.db_track_id = person.db_track_id
        self.last_seen_sample_index = int(person.sample_index)
        if used_by_pose:
            self.pose_samples.append(person)
        if used_by_deep:
            self.deep_samples.append(person)
        if used_by_homography_macro:
            self.homography_macro_samples.append(person)

    def public_status(self) -> dict[str, Any]:
        return {
            "tracker_track_id": self.tracker_track_id,
            "db_track_id": self.db_track_id,
            "last_seen_sample_index": self.last_seen_sample_index,
            "pose_buffer_count": len(self.pose_samples),
            "deep_buffer_count": len(self.deep_samples),
            "homography_macro_buffer_count": len(self.homography_macro_samples),
        }
