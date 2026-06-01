from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class TrackTubeletBuffer(Generic[T]):
    """Per-track fixed-length tubelet emitter with stride.

    A tubelet is emitted when at least `tubelet_frames` samples exist and the
    newest sample index is at least `stride` newer than the previous emission.
    """

    tubelet_frames: int
    stride: int
    max_samples: int = 256
    samples: deque[T] = field(default_factory=deque)
    last_emit_sample_index: Optional[int] = None

    def __post_init__(self) -> None:
        self.tubelet_frames = int(self.tubelet_frames)
        self.stride = int(self.stride)
        self.samples = deque(maxlen=max(self.max_samples, self.tubelet_frames * 4))

    def add(self, sample: T, *, sample_index: int) -> list[T] | None:
        self.samples.append(sample)
        if len(self.samples) < self.tubelet_frames:
            return None
        latest = int(sample_index)
        if self.last_emit_sample_index is not None and latest - self.last_emit_sample_index < self.stride:
            return None
        self.last_emit_sample_index = latest
        return list(self.samples)[-self.tubelet_frames:]
