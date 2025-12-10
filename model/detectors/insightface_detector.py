from insightface.app import FaceAnalysis

class InsightFaceDetector:
    def __init__(self):
        self.app = FaceAnalysis(name="buffalo_l")
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def detect(self, frame):
        faces = self.app.get(frame)
        return faces
