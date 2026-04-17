import base64
import cv2
import numpy as np

from models.insightface_loader import load_face_analyzer


class InsightFacePipeline:
    def __init__(self, cfg: dict):
        fcfg = cfg["face"]
        self.det_size = tuple(fcfg.get("det_size", [640, 640]))
        self.face_img_size = int(fcfg.get("face_img_size", 160))
        self.jpeg_quality = int(fcfg.get("jpeg_quality", 80))
        self.min_face_size = int(fcfg.get("min_face_size", 40))
        self.min_det_score = float(fcfg.get("min_det_score", 0.45))

        ctx_id = int(fcfg.get("ctx_id", -1))
        model_name = fcfg.get("model_name", "buffalo_l")
        det_size_scalar = int(self.det_size[0])

        self.app = load_face_analyzer(
            {
                "model_name": model_name,
                "det_size": det_size_scalar,
                "ctx_id": ctx_id,
            }
        )

    def infer(self, frame_bgr: np.ndarray):
        faces = self.app.get(frame_bgr)
        out = []

        for f in faces:
            bbox = f.bbox.astype(int).tolist()
            x1, y1, x2, y2 = bbox
            box_w = max(0, x2 - x1)
            box_h = max(0, y2 - y1)
            face_size = min(box_w, box_h)
            det_score = float(getattr(f, "det_score", 0.0))

            if face_size < self.min_face_size:
                continue
            if det_score < self.min_det_score:
                continue

            emb = getattr(f, "embedding", None)
            if emb is None:
                continue

            face_b64 = self._crop_face_b64(frame_bgr, bbox)
            if not face_b64:
                continue

            out.append(
                {
                    "bbox_xyxy": bbox,
                    "embedding": np.asarray(emb, dtype=np.float32).tolist(),
                    "face_jpeg_b64": face_b64,
                    "quality_score": det_score,
                    "face_size": face_size,
                }
            )

        return out

    def _crop_face_b64(self, frame_bgr, bbox):
        x1, y1, x2, y2 = bbox
        h, w = frame_bgr.shape[:2]

        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        if x2 <= x1 or y2 <= y1:
            return ""

        face = frame_bgr[y1:y2, x1:x2]
        if face.size == 0:
            return ""

        face = cv2.resize(
            face,
            (self.face_img_size, self.face_img_size),
            interpolation=cv2.INTER_AREA,
        )

        ok, buf = cv2.imencode(
            ".jpg",
            face,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            return ""

        return base64.b64encode(buf.tobytes()).decode("ascii")
