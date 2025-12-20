import torch
import torch.nn.functional as F

def msfd_loss(student_feats, teacher_feats):
    loss = 0
    for s, t in zip(student_feats, teacher_feats):
        loss += F.mse_loss(s, t)
    return loss

def gpkd_loss(student_emb, teacher_emb):
    return 1 - F.cosine_similarity(student_emb, teacher_emb).mean()

def ckd_loss(student_emb, teacher_emb, temperature=0.1):
    sim_matrix = torch.matmul(student_emb, teacher_emb.T) / temperature
    labels = torch.arange(sim_matrix.size(0)).to(sim_matrix.device)
    return F.cross_entropy(sim_matrix, labels)
