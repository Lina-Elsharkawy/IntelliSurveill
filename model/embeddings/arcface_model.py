import torch
import cv2
import numpy as np
from insightface.app import FaceAnalysis

class EmbeddingModel:
    def __init__(self, provider='cpu'):
        self.app = FaceAnalysis(name='buffalo_l')
        self.app.prepare(ctx_id=0 if provider=='cuda' else -1)

    def get_embedding(self, face_image):
        face_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
        data = self.app.get(face_image)

        if len(data) == 0:
            return None

        return data[0].embedding / np.linalg.norm(data[0].embedding)
