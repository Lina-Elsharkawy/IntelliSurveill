from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class GateUpdate:
    raw_score: float
    smoothed_score: float
    threshold: float
    hit_raw: bool
    hit_smooth: bool
    persistent: bool
    persistence_hits: int
    persistence_window: int
    persistence_required_hits: int

    @property
    def above_threshold(self) -> bool:
        """Backward-compatible alias used by gate wrappers; persistence uses smoothed hits."""
        return bool(self.hit_smooth)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "raw_score": self.raw_score,
            "smoothed_score": self.smoothed_score,
            "threshold": self.threshold,
            "hit_raw": self.hit_raw,
            "hit_smooth": self.hit_smooth,
            "persistent": self.persistent,
            "persistence_hits": self.persistence_hits,
            "persistence_window": self.persistence_window,
            "persistence_required_hits": self.persistence_required_hits,
        }


@dataclass
class OnlineGateState:
    """Causal Gaussian smoothing + N-of-M persistence.

    This matches the live tester behavior: scores are smoothed only from past and
    current values, then persistence is computed on smoothed threshold hits.
    """

    threshold: float
    sigma: float = 2.0
    persistence_required_hits: int = 3
    persistence_window: int = 5
    max_history: int = 128
    scores: deque[float] = field(default_factory=deque)
    smooth_hits: deque[bool] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.threshold = float(self.threshold)
        self.sigma = float(self.sigma)
        self.persistence_required_hits = int(self.persistence_required_hits)
        self.persistence_window = int(self.persistence_window)
        self.scores = deque(maxlen=max(self.max_history, int(6 * max(self.sigma, 1.0)) + self.persistence_window + 8))
        self.smooth_hits = deque(maxlen=self.persistence_window)

    def _causal_gaussian_latest(self) -> float:
        if not self.scores:
            return 0.0
        vals = np.asarray(list(self.scores), dtype=np.float64)
        if self.sigma <= 0 or len(vals) == 1:
            return float(vals[-1])
        radius = int(max(1, math.ceil(3.0 * self.sigma)))
        recent = vals[-(radius + 1):]
        d = np.arange(len(recent) - 1, -1, -1, dtype=np.float64)
        w = np.exp(-(d ** 2) / (2.0 * self.sigma * self.sigma))
        w /= max(float(w.sum()), 1e-12)
        return float(np.sum(recent * w))

    def update(self, score: float) -> GateUpdate:
        try:
            raw = float(score)
        except Exception:
            raw = 0.0
        if not math.isfinite(raw):
            raw = 0.0

        self.scores.append(raw)
        smooth = self._causal_gaussian_latest()
        hit_raw = raw > self.threshold
        hit_smooth = smooth > self.threshold
        self.smooth_hits.append(bool(hit_smooth))
        hits = int(sum(self.smooth_hits))
        persistent = hits >= self.persistence_required_hits
        return GateUpdate(
            raw_score=raw,
            smoothed_score=smooth,
            threshold=self.threshold,
            hit_raw=hit_raw,
            hit_smooth=hit_smooth,
            persistent=persistent,
            persistence_hits=hits,
            persistence_window=self.persistence_window,
            persistence_required_hits=self.persistence_required_hits,
        )
