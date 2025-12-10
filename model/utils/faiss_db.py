import faiss
import numpy as np
import torch
import torch.nn.functional as F

class EmbeddingDB:
    def __init__(self, dim):
        self.index = faiss.IndexFlatL2(dim)
        self.embeddings = []
        self.labels = []

    def add(self, emb, label):
        emb = F.normalize(emb, p=2, dim=1).cpu().numpy()
        self.index.add(emb)
        self.labels.extend(label)

    def query(self, emb, k=1):
        emb = F.normalize(emb, p=2, dim=1).cpu().numpy()
        D, I = self.index.search(emb, k)
        return D, [self.labels[i] for i in I[0]]
