import cv2
from detectors.insightface_detector import InsightFaceDetector
from embeddings.arcface_model import EmbeddingModel
from memory.memory_manager import MemoryManager
from classifier.ncm_classifier import NCMClassifier

class RealTimeRecognizer:
    def __init__(self):
        # InsightFace detector + ArcFace embeddings
        self.detector = InsightFaceDetector()
        self.embedder = EmbeddingModel()
        self.memory = MemoryManager()
        self.classifier = NCMClassifier()

    def run(self):
        cap = cv2.VideoCapture(0)

        if not cap.isOpened():
            print("Error: Cannot open webcam")
            return

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Cannot read frame")
                break

            # Detect faces with InsightFace
            faces = self.detector.detect(frame)

            for face in faces:
                # Bounding box
                x1, y1, x2, y2 = face.bbox.astype(int)

                # Embedding from InsightFace (already normalized)
                emb = face.embedding
                if emb is None:
                    continue

                # Predict identity with NCM
                identity, score = self.classifier.predict(emb, self.memory)

                # Add unknown user to memory
                if identity == "unknown":
                    identity = "user_" + str(len(self.memory.get_identities()))
                    self.memory.add_embedding(identity, emb)

                # Draw bounding box & label
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{identity} ({score:.2f})",
                            (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 255, 0), 2)

            cv2.imshow("CLFace - Continual Learning Face Recognition", frame)

            # Quit on 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    app = RealTimeRecognizer()
    app.run()
