from dataclasses import dataclass
from insightface.app import FaceAnalysis


@dataclass
class InsightFaceConfig:
    model_name: str = "buffalo_l"
    det_size: int = 640
    ctx_id: int = -1


def load_face_analyzer(cfg: dict) -> FaceAnalysis:
    ic = InsightFaceConfig(**cfg)
    app = FaceAnalysis(name=ic.model_name)
    app.prepare(ctx_id=ic.ctx_id, det_size=(ic.det_size, ic.det_size))
    return app
