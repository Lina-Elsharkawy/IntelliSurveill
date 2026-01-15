import os

DB_DSN="postgresql://lina:123@127.0.0.1:5432/lina"

print("VECTOR_MATCH DB_DSN =", DB_DSN)


# Thresholds (tune later with real data)
T_IDENTIFY = float(os.getenv("T_IDENTIFY", "0.75"))      # accept known if best_sim >= this and margin ok
T_AUTOLEARN = float(os.getenv("T_AUTOLEARN", "0.85"))    # auto-learn only if best_sim >= this (stricter)
M_MARGIN = float(os.getenv("M_MARGIN", "0.05"))          # require best_sim - second_sim >= this
MIN_QUALITY = float(os.getenv("MIN_QUALITY", "0.0"))     # if you provide quality_score, enforce it

# Operational caps
MAX_EMB_PER_PERSON = int(os.getenv("MAX_EMB_PER_PERSON", "100"))

# If True: search authoritative first then fallback to all
SEARCH_AUTHORITATIVE_FIRST = os.getenv("SEARCH_AUTHORITATIVE_FIRST", "false").lower() == "true"

# Embedding dimension (your schema uses vector(512))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
