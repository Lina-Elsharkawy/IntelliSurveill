import numpy as np

class MemoryManager:
    def __init__(self, max_per_identity=20):
        self.memory = {}
        self.max_per_identity = max_per_identity

    def add_embedding(self, identity, emb):
        if identity not in self.memory:
            self.memory[identity] = {
                "embeddings": [],
                "centroid": None
            }

        emb = np.array(emb)

        # Add embedding
        self.memory[identity]["embeddings"].append(emb)

        # Limit memory size
        if len(self.memory[identity]["embeddings"]) > self.max_per_identity:
            self.memory[identity]["embeddings"].pop(0)

        # Update centroid
        self.memory[identity]["centroid"] = np.mean(
            self.memory[identity]["embeddings"], axis=0
        )

    def get_identities(self):
        return list(self.memory.keys())

    def get_centroid(self, identity):
        return self.memory[identity]["centroid"]
