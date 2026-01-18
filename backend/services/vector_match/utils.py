import math
from typing import List, Optional


def l2_normalize(vec: List[float]) -> List[float]:
    s = 0.0
    for x in vec:
        s += x * x
    norm = math.sqrt(s)
    if norm == 0.0:
        raise ValueError("Zero-norm embedding; cannot normalize.")
    return [x / norm for x in vec]


def to_pgvector_literal(vec: List[float]) -> str:
    # pgvector accepts '[a,b,c]' format
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def interval_from_ms(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return f"{int(ms)} milliseconds"
