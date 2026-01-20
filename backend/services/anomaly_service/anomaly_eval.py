from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import psycopg
import pandas as pd


# -------------------------
# Config
# -------------------------
DEFAULT_DSN = os.getenv("DB_DSN", "postgresql://lina:123@127.0.0.1:5432/lina")

# Your exported JSON (from the COPY ... > anomaly_vlm_results.json)
DEFAULT_JOBS_JSON = Path("anomaly_vlm_results.jsonl")

OUT_DIR = Path("analysis_out")
OUT_DIR.mkdir(parents=True, exist_ok=True)


DECISION_RE = re.compile(
    r"ALERT:\s*(YES|NO)\s*[\r\n]+SEVERITY:\s*(LOW|MEDIUM|HIGH)\s*[\r\n]+REASON:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


def parse_llm_decision(text: str) -> Tuple[str, str, str]:
    """
    Returns (alert_yes_no_unknown, severity, reason).
    Expected format is enforced by your worker prompt. :contentReference[oaicite:2]{index=2}
    """
    if not text:
        return "UNKNOWN", "UNKNOWN", ""

    m = DECISION_RE.search(text.strip())
    if not m:
        # Sometimes the model slightly deviates; do a weak fallback:
        t = text.upper()
        alert = "YES" if "ALERT:" in t and "YES" in t.split("ALERT:", 1)[1][:20] else (
            "NO" if "ALERT:" in t and "NO" in t.split("ALERT:", 1)[1][:20] else "UNKNOWN"
        )
        sev = "HIGH" if "SEVERITY:" in t and "HIGH" in t else (
            "MEDIUM" if "SEVERITY:" in t and "MEDIUM" in t else (
                "LOW" if "SEVERITY:" in t and "LOW" in t else "UNKNOWN"
            )
        )
        return alert, sev, ""

    alert = m.group(1).upper()
    severity = m.group(2).upper()
    reason = (m.group(3) or "").strip()
    return alert, severity, reason


def load_llm_decisions_from_export(jobs_json_path: Path) -> Dict[int, Dict[str, Any]]:
    """
    Build: anomaly_candidate_id -> LLM decision data
    Robust to:
      - valid JSON array
      - COPY output that includes noise / blank lines
      - NULL output
    """
    if not jobs_json_path.exists():
        raise FileNotFoundError(f"Jobs JSON not found: {jobs_json_path.resolve()}")

    raw = jobs_json_path.read_text(encoding="utf-8", errors="ignore")
    s = raw.strip()

    if not s or s.upper() == "NULL":
        items = []
    else:
        # If COPY produced some noise, try to locate the first JSON bracket
        first_json_pos = None
        for ch in ("[", "{"):
            pos = s.find(ch)
            if pos != -1:
                first_json_pos = pos if first_json_pos is None else min(first_json_pos, pos)

        if first_json_pos is not None and first_json_pos > 0:
            s = s[first_json_pos:].strip()

        # If it ends with COPY row count or other trailing junk, try to cut after last ] or }
        last_bracket = max(s.rfind("]"), s.rfind("}"))
        if last_bracket != -1 and last_bracket < len(s) - 1:
            s = s[: last_bracket + 1].strip()

        items = []
        for line in s.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            items.append(json.loads(line))


    # Normalize: items should be a list
    if isinstance(items, dict):
        items = [items]
    elif not isinstance(items, list):
        items = []

    by_candidate: Dict[int, Dict[str, Any]] = {}

    for it in items:
        if not isinstance(it, dict):
            continue
        cand_id = it.get("anomaly_candidate_id")
        if cand_id is None:
            continue

        rj = it.get("response_json") or {}
        job_type = (rj.get("job_type") or "").strip()

        if job_type != "llm_reason":
            continue

        decision_text = (rj.get("decision") or it.get("response_text") or "").strip()
        alert, severity, reason = parse_llm_decision(decision_text)

        by_candidate[int(cand_id)] = {
            "llm_job_id": it.get("job_id"),
            "llm_model": it.get("model_name"),
            "llm_alert": alert,
            "llm_severity": severity,
            "llm_reason": reason,
            "llm_decision_text": decision_text,
        }

    return by_candidate



def fetch_baseline_windows(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    """
    Pull baseline results from scene_window_embeddings plus anomaly_candidates link.
    scene_window_embeddings stores is_normal, cosine_distance, radius_threshold, score. 
    anomaly_candidates links each anomaly window to an id used by ollama_jobs. 
    """
    # NOTE: We LEFT JOIN anomaly_candidates because normal windows won't have a candidate.
    rows = conn.execute(
        """
        SELECT
            swe.id AS scene_window_embedding_id,
            swe.event_key,
            swe.window_start_ts,
            swe.is_normal,
            swe.cosine_distance,
            swe.radius_threshold,
            swe.score,
            swe.nearest_cluster_index,
            ac.id AS anomaly_candidate_id
        FROM scene_window_embeddings swe
        LEFT JOIN anomaly_candidates ac
          ON ac.scene_window_embedding_id = swe.id
        ORDER BY swe.window_start_ts, swe.id
        """
    ).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "scene_window_embedding_id": r[0],
                "event_key": r[1],
                "window_start_ts": str(r[2]) if r[2] is not None else None,
                "is_normal": r[3],
                "cosine_distance": r[4],
                "radius_threshold": r[5],
                "score": r[6],
                "nearest_cluster_index": r[7],
                "anomaly_candidate_id": r[8],
            }
        )
    return out


def derive_fight_and_window(event_key: Optional[str]) -> Tuple[str, Optional[int]]:
    """
    Your test used event_key like: Fight1-win-7
    We'll extract:
      fight = "Fight1"
      window_index = 7
    """
    if not event_key:
        return "UNKNOWN", None

    # Split by "-win-"
    if "-win-" in event_key:
        fight, idx = event_key.split("-win-", 1)
        try:
            return fight, int(idx)
        except Exception:
            return fight, None

    return event_key, None


def main():
    jobs_json_path = DEFAULT_JOBS_JSON

    print(f"[eval] DB_DSN={DEFAULT_DSN}")
    print(f"[eval] Jobs JSON={jobs_json_path.resolve()}")
    print(f"[eval] Output dir={OUT_DIR.resolve()}")

    # Load LLM decisions from your exported JSON file
    llm_by_candidate = load_llm_decisions_from_export(jobs_json_path)

    # Pull baseline from DB
    with psycopg.connect(DEFAULT_DSN) as conn:
        baseline = fetch_baseline_windows(conn)

    # Build tidy rows
    rows_out: List[Dict[str, Any]] = []

    for b in baseline:
        fight, win_idx = derive_fight_and_window(b.get("event_key"))

        is_normal = b.get("is_normal")
        baseline_is_anomaly = (is_normal is False)  # None treated as unknown

        cand_id = b.get("anomaly_candidate_id")
        llm = llm_by_candidate.get(int(cand_id)) if cand_id is not None else None

        llm_alert = (llm or {}).get("llm_alert", "N/A")  # N/A if no candidate
        llm_severity = (llm or {}).get("llm_severity", "N/A")

        rows_out.append(
            {
                "fight": fight,
                "window_index": win_idx,
                "event_key": b.get("event_key"),
                "scene_window_embedding_id": b.get("scene_window_embedding_id"),
                "anomaly_candidate_id": cand_id,

                "baseline_is_normal": is_normal,
                "baseline_is_anomaly": baseline_is_anomaly,
                "cosine_distance": b.get("cosine_distance"),
                "radius_threshold": b.get("radius_threshold"),
                "score": b.get("score"),
                "nearest_cluster_index": b.get("nearest_cluster_index"),

                "llm_alert": llm_alert,        # YES / NO / UNKNOWN / N/A
                "llm_severity": llm_severity,  # LOW / MEDIUM / HIGH / UNKNOWN / N/A
            }
        )

    df = pd.DataFrame(rows_out)

    # -------------------------
    # Metrics (your ground truth: ALL windows are anomalies)
    # -------------------------
    total = len(df)

    # Before: anomalies flagged by clustering
    before_detected = int(df["baseline_is_anomaly"].fillna(False).sum())

    # After: LLM alerts YES among candidates (exclude N/A rows)
    llm_yes = int((df["llm_alert"] == "YES").sum())
    llm_no = int((df["llm_alert"] == "NO").sum())
    llm_unknown = int((df["llm_alert"] == "UNKNOWN").sum())

    # How many rows had no candidate (i.e., baseline normal)
    no_candidate = int((df["anomaly_candidate_id"].isna()).sum())

    summary = {
        "total_windows": total,
        "ground_truth_anomalies": total,  # your assumption for this experiment
        "baseline_detected_anomalies_before_llm": before_detected,
        "baseline_missed_before_llm": total - before_detected,

        "llm_alert_yes_after": llm_yes,
        "llm_alert_no_after": llm_no,
        "llm_alert_unknown_after": llm_unknown,

        "baseline_normals_no_candidate": no_candidate,
        "notes": {
            "baseline_is_anomaly": "baseline_is_anomaly = (scene_window_embeddings.is_normal == false)",
            "llm_alert": "parsed from exported ollama_jobs JSON for job_type=llm_reason decision text",
        },
    }

    # Save outputs
    out_csv = OUT_DIR / "windows.csv"
    out_summary = OUT_DIR / "summary.json"

    df.to_csv(out_csv, index=False, encoding="utf-8")
    out_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for k, v in summary.items():
        if k != "notes":
            print(f"{k}: {v}")

    print(f"\nSaved:\n- {out_csv.resolve()}\n- {out_summary.resolve()}")


if __name__ == "__main__":
    main()
