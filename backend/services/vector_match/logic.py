from typing import Optional, Dict, Any, List, Tuple

from .config import T_IDENTIFY, T_AUTOLEARN, M_MARGIN, MIN_QUALITY


def decide(top2: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
    """
    Returns (best_id, best_sim, second_sim, margin)
    """
    if not top2:
        return None, None, None, None

    best_id = int(top2[0]["detected_id"])
    best_sim = float(top2[0]["sim"])

    if len(top2) < 2:
        return best_id, best_sim, None, None

    second_sim = float(top2[1]["sim"])
    margin = best_sim - second_sim
    return best_id, best_sim, second_sim, margin


def is_quality_ok(q: Optional[float]) -> bool:
    if q is None:
        return True
    return q >= MIN_QUALITY


def should_identify(best_sim: float, margin: Optional[float], q: Optional[float]) -> bool:
    if best_sim < T_IDENTIFY:
        return False
    if margin is not None and margin < M_MARGIN:
        return False
    if not is_quality_ok(q):
        return False
    return True


def should_autolearn(best_sim: float, margin: Optional[float], q: Optional[float]) -> bool:
    if best_sim < T_AUTOLEARN:
        return False
    if margin is not None and margin < M_MARGIN:
        return False
    if not is_quality_ok(q):
        return False
    return True
