import numpy as np

class NCMClassifier:
    def __init__(self, threshold=0.9):
        self.threshold = threshold

    def predict(self, embedding, memory):
        embedding = np.array(embedding)

        best_id = None
        best_sim = -1

        for identity in memory.get_identities():
            centroid = memory.get_centroid(identity)
            sim = np.dot(embedding, centroid)

            if sim > best_sim:
                best_sim = sim
                best_id = identity

        if best_sim < self.threshold:
            return "unknown", best_sim
        
        return best_id, best_sim
