import base64
import cv2
import numpy as np
from insightface.app import FaceAnalysis

class InsightFacePipeline:
    def __init__(self, cfg: dict):
        fcfg = cfg["face"]
        self.det_size = tuple(fcfg.get("det_size", [640, 640]))
        self.face_img_size = int(fcfg.get("face_img_size", 160))
        self.jpeg_quality = int(fcfg.get("jpeg_quality", 80))

        model_name = fcfg.get("model_name", "buffalo_l")

        # InsightFace will use CUDA on Jetson if onnxruntime-gpu/TensorRT is configured.
        self.app = FaceAnalysis(name=model_name)
        self.app.prepare(ctx_id=0, det_size=self.det_size)  # ctx_id=0 = GPU when available

    def infer(self, frame_bgr: np.ndarray):
        """Returns list of events: {bbox, embedding, face_jpeg_b64}."""
        faces = self.app.get(frame_bgr)
        out = []

        for f in faces:
            bbox = f.bbox.astype(int).tolist()  # [x1,y1,x2,y2]
            emb = f.embedding  # (512,)

            # Crop face for HITL
            face_b64 = self._crop_face_b64(frame_bgr, bbox)

            out.append({
                "bbox_xyxy": bbox,
                "embedding": emb.astype(float).tolist(),
                "face_jpeg_b64": face_b64,
                "quality_score": float(getattr(f, "det_score", 0.0)),
            })
        return out

    def _crop_face_b64(self, frame_bgr, bbox):
        x1, y1, x2, y2 = bbox
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(x1, w-1)); x2 = max(0, min(x2, w-1))
        y1 = max(0, min(y1, h-1)); y2 = max(0, min(y2, h-1))
        if x2 <= x1 or y2 <= y1:
            return ""

        face = frame_bgr[y1:y2, x1:x2]
        face = cv2.resize(face, (self.face_img_size, self.face_img_size), interpolation=cv2.INTER_AREA)

        ok, buf = cv2.imencode(".jpg", face, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            return ""
        return base64.b64encode(buf.tobytes()).decode("ascii")
