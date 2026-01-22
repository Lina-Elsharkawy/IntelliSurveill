#!/usr/bin/env python3
"""
Plot results from extract_lfw_embeddings.py JSONL output.

Input:  lfw_embeddings_db.jsonl (one JSON object per line)
Output: PNG plots saved to ./plots_lfw/

Plots:
  1) outcomes_bar.png            detected vs no_face vs failed
  2) quality_hist.png            histogram of quality_score for detected faces
  3) processing_time_hist.png    histogram of processing_time_ms for all records (and detected-only overlay)
  4) detection_rate_per_identity.png  detection success rate per identity
"""

import os
import json
from collections import Counter, defaultdict

import matplotlib.pyplot as plt


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

JSONL_PATH = os.path.join(
    SCRIPT_DIR,
    "lfw_subset",
    "lfw_embeddings_db.jsonl"
)

OUT_DIR = os.path.join(SCRIPT_DIR, "plots_lfw")


def read_jsonl(path: str):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Invalid JSON on line {line_no}: {e}") from e
    return records


def classify_outcome(rec: dict) -> str:
    # success record from your script contains embedding_list + embedding_pgvector
    if "embedding_list" in rec and rec.get("error") is None:
        return "detected"
    err = rec.get("error")
    if err == "no_face_detected":
        return "no_face"
    return "failed"


def save_current_fig(filename: str):
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, filename)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    print(f"[SAVED] {out_path}")


def main():
    if not os.path.isfile(JSONL_PATH):
        raise FileNotFoundError(
            f"JSONL file not found: {JSONL_PATH}\n"
            f"Tip: set JSONL_PATH to the full path of lfw_embeddings_db.jsonl"
        )

    records = read_jsonl(JSONL_PATH)
    if not records:
        raise RuntimeError("No records found in JSONL file.")

    # -------------------------
    # 1) Outcomes (detected / no_face / failed)
    # -------------------------
    outcomes = [classify_outcome(r) for r in records]
    counts = Counter(outcomes)

    total = len(records)
    detected = counts.get("detected", 0)
    no_face = counts.get("no_face", 0)
    failed = counts.get("failed", 0)

    detection_rate = detected / total if total else 0.0

    print("\n=== SUMMARY ===")
    print(f"Total records: {total}")
    print(f"Detected:      {detected}")
    print(f"No face:       {no_face}")
    print(f"Failed:        {failed}")
    print(f"Detection rate: {detection_rate:.2%}")

    plt.figure()
    labels = ["detected", "no_face", "failed"]
    values = [counts.get(k, 0) for k in labels]
    plt.bar(labels, values)
    plt.title("LFW Offline Outcomes")
    plt.xlabel("Outcome")
    plt.ylabel("Number of Images")
    save_current_fig("outcomes_bar.png")
    # plt.show()

    # -------------------------
    # 2) Quality score distribution (detected only)
    # -------------------------
    q_detected = []
    for r in records:
        if classify_outcome(r) == "detected":
            qs = r.get("quality_score")
            if qs is not None:
                q_detected.append(float(qs))

    plt.figure()
    if q_detected:
        plt.hist(q_detected, bins=30)
        plt.title("Detection Quality Score Distribution (Detected Only)")
        plt.xlabel("quality_score (detector confidence)")
        plt.ylabel("Count")
    else:
        plt.text(0.5, 0.5, "No detected records with quality_score found.", ha="center", va="center")
        plt.axis("off")
    save_current_fig("quality_hist.png")
    # plt.show()

    # -------------------------
    # 3) Processing time distribution
    #    - all records
    #    - detected-only overlay (optional)
    # -------------------------
    proc_all = []
    proc_detected = []
    for r in records:
        ms = r.get("processing_time_ms")
        if ms is None:
            continue
        ms = float(ms)
        proc_all.append(ms)
        if classify_outcome(r) == "detected":
            proc_detected.append(ms)

    plt.figure()
    if proc_all:
        plt.hist(proc_all, bins=30, alpha=0.7, label="all")
        if proc_detected:
            plt.hist(proc_detected, bins=30, alpha=0.7, label="detected only")
        plt.title("Processing Time Distribution")
        plt.xlabel("processing_time_ms")
        plt.ylabel("Count")
        plt.legend()
    else:
        plt.text(0.5, 0.5, "No processing_time_ms found.", ha="center", va="center")
        plt.axis("off")
    save_current_fig("processing_time_hist.png")
    # plt.show()

    # -------------------------
    # 4) Detection rate per identity
    # -------------------------
    by_identity_total = defaultdict(int)
    by_identity_detected = defaultdict(int)

    for r in records:
        identity = r.get("identity", "UNKNOWN_IDENTITY")
        by_identity_total[identity] += 1
        if classify_outcome(r) == "detected":
            by_identity_detected[identity] += 1

    identities = sorted(by_identity_total.keys())
    rates = []
    for ident in identities:
        t = by_identity_total[ident]
        d = by_identity_detected.get(ident, 0)
        rates.append(d / t if t else 0.0)

    plt.figure(figsize=(max(10, len(identities) * 0.45), 5))
    plt.bar(identities, rates)
    plt.title("Detection Success Rate per Identity")
    plt.xlabel("Identity")
    plt.ylabel("Detection Rate")
    plt.ylim(0.0, 1.0)
    plt.xticks(rotation=60, ha="right")
    save_current_fig("detection_rate_per_identity.png")
    # plt.show()

    print("\nDone. Open the PNGs in:", os.path.abspath(OUT_DIR))


if __name__ == "__main__":
    main()
