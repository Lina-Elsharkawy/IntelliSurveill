"""
insightface_loader.py
Single place to load InsightFace FaceAnalysis.

We keep this separate so later you can switch providers / optimization
without touching the face recognition logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple
from insightface.app import FaceAnalysis


@dataclass
class InsightFaceConfig:
    model_name: str = "buffalo_l"
    det_size: int = 320          # 320/480/640
    ctx_id: int = -1             # -1 CPU, 0 GPU (if available)


def load_face_analyzer(cfg: dict) -> FaceAnalysis:
    ic = InsightFaceConfig(**cfg)
    app = FaceAnalysis(name=ic.model_name)
    app.prepare(ctx_id=ic.ctx_id, det_size=(ic.det_size, ic.det_size))
    return app
