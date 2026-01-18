from typing import Optional, Dict, Any, List, Tuple

from .config import T_IDENTIFY, T_AUTOLEARN, M_MARGIN, MIN_QUALITY


def decide_identity(topk: List[Dict[str, Any]]) -> Tuple[Optional[int], Optional[float], Optional[float], Optional[float]]:
    """Identity-level decision.

    Why: In a continuous-learning system you store *multiple embeddings per identity*.
    A naive top-2 nearest-neighbor over embeddings often returns two embeddings
    from the *same identity*, making the margin artificially small and causing
    false "unknown" decisions.

    Input: a list of rows like {detected_id, sim, ...} from a top-K embedding search.
    Output: (best_id, best_sim, second_best_sim, margin) where second_best_sim is
    from a *different identity*.
    """
    if not topk:
        return None, None, None, None

    # Best similarity per identity
    best_by_id: Dict[int, float] = {}
    for r in topk:
        did = int(r["detected_id"])
        sim = float(r["sim"])
        prev = best_by_id.get(did)
        if prev is None or sim > prev:
            best_by_id[did] = sim

    ranked = sorted(best_by_id.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_sim = ranked[0][0], ranked[0][1]

    if len(ranked) < 2:
        return best_id, best_sim, None, None

    second_sim = ranked[1][1]
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
