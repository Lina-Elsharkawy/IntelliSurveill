import os

DB_DSN = (
    os.getenv("DB_DSN")
    or os.getenv("DATABASE_URL")
    or f"postgresql://{os.getenv('POSTGRES_USER','lina')}:{os.getenv('POSTGRES_PASSWORD','123')}@"
       f"{os.getenv('POSTGRES_HOST','postgres-db')}:{os.getenv('POSTGRES_PORT','5432')}/"
       f"{os.getenv('POSTGRES_DB','lina')}"
)


print("VECTOR_MATCH DB_DSN =", DB_DSN)


# Thresholds (tune later with real data)
T_IDENTIFY = float(os.getenv("T_IDENTIFY", "0.75"))      # accept known if best_sim >= this and margin ok
T_AUTOLEARN = float(os.getenv("T_AUTOLEARN", "0.85"))    # auto-learn only if best_sim >= this (stricter)
M_MARGIN = float(os.getenv("M_MARGIN", "0.05"))          # require best_sim - second_sim >= this
MIN_QUALITY = float(os.getenv("MIN_QUALITY", "0.0"))     # if you provide quality_score, enforce it

# Operational caps
MAX_EMB_PER_PERSON = int(os.getenv("MAX_EMB_PER_PERSON", "100"))

# Search parameters
# IMPORTANT: margin must be computed between identities, not between embeddings.
# We therefore search top-K embeddings then aggregate to best-per-identity.
TOPK = int(os.getenv("TOPK", "30"))

# Continuous learning safety
# - DEDUP_SIM: if the new embedding is too similar to an existing one for the same identity, skip storing it
# - AUTOLEARN_COOLDOWN_SEC: minimum time between auto-learn inserts per identity
DEDUP_SIM = float(os.getenv("DEDUP_SIM", "0.98"))
AUTOLEARN_COOLDOWN_SEC = int(os.getenv("AUTOLEARN_COOLDOWN_SEC", "60"))

# If True: search authoritative first then fallback to all
SEARCH_AUTHORITATIVE_FIRST = os.getenv("SEARCH_AUTHORITATIVE_FIRST", "false").lower() == "true"

# Embedding dimension (your schema uses vector(512))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "512"))
