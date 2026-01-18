from insightface.app import FaceAnalysis

class InsightFaceDetector:
    def __init__(self):
        # Use a ViT model trained with ArcFace
        self.app = FaceAnalysis(name="buffalo_l_vit")  # ← ViT model
        self.app.prepare(ctx_id=0, det_size=(640, 640))  # GPU: 0, CPU: -1

        rec_model = self.app.models['recognition']
        print("Recognition model file:", rec_model.model_file)

    def detect(self, frame):
        faces = self.app.get(frame)
        return faces

# Test
if __name__ == "__main__":
    detector = InsightFaceDetector()
