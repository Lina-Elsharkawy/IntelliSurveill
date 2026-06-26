#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
06b_evaluate_deep_gate_on_labeled_tubelet_embeddings.py

Evaluate a trained Deep VideoMAE+kNN gate on labeled normal/anomaly tubelet embeddings.

MATCHED-THRESHOLD VERSION: raw scores use raw thresholds; smoothed scores use matching causal-smoothed thresholds.

Expected flow:
  1) Convert live-parity motion_tubelet_tracks.jsonl to VideoMAE embeddings using
     05a_build_deep_embeddings_from_motion_tubelets_jsonl.py.
  2) Run this evaluator against the trained normal Deep artifacts:
       - models/03_knn_index.joblib
       - 04_thresholds.json

The evaluator:
  - loads embeddings + metadata
  - L2-normalizes embeddings exactly like the builder/deployment
  - scores using the saved kNN memory bank
  - applies causal Gaussian smoothing exactly like OnlineGateState
  - applies N-of-M persistence exactly like deployment
  - infers labels from video_path/video_id by default:
      anomaly if path contains "\Anomaly\" or "/Anomaly/" or "anomaly"
      normal  if path contains "\Normal\"  or "/Normal/"  or "normal"
    You can override/confirm labels with --labels_csv if needed.
  - writes clip/tubelet-level and video-level reports.

This script does NOT train anything.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd


def percentile_key(p: float) -> str:
    s = ("%g" % float(p)).replace(".", "_")
    return f"p{s}"


def parse_ints(text: str) -> List[int]:
    vals = []
    for item in str(text).split(","):
        item = item.strip()
        if item:
            vals.append(int(item))
    return sorted(set(vals))


def parse_floats(text: str) -> List[float]:
    vals = []
    for item in str(text).split(","):
        item = item.strip()
        if item:
            vals.append(float(item))
    return sorted(set(vals))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return (x / np.maximum(norms, eps)).astype(np.float32)


def extract_knn_object(artifact: Any) -> Any:
    if hasattr(artifact, "kneighbors"):
        return artifact
    if isinstance(artifact, dict):
        for key in ("knn", "knn_index", "index", "nearest_neighbors", "nn", "model", "estimator"):
            obj = artifact.get(key)
            if hasattr(obj, "kneighbors"):
                return obj
    raise TypeError("Could not find sklearn-like kNN object with .kneighbors()")


def load_threshold(thresholds: dict, k: int, threshold_key: str, score_mode: str = "raw") -> float:
    """Load threshold for a k/percentile.

    Supports both:
      1) legacy raw format: {"k5": {"p99_5": ...}}
      2) new grouped format:
         {
           "raw": {"k5": {"p99_5": ...}},
           "gaussian_sigma_2": {"k5": {"p99_5": ...}}
         }
      3) combined 04_thresholds.json format with "thresholds_by_score_mode".
    """
    # New combined artifact: 04_thresholds.json
    grouped = thresholds.get("thresholds_by_score_mode")
    if isinstance(grouped, dict) and score_mode in grouped:
        block = grouped[score_mode]
        kd = block.get(f"k{k}") or block.get(str(k)) or block.get(f"deep_k_{k}")
        if isinstance(kd, dict) and threshold_key in kd:
            return float(kd[threshold_key])

    # Direct grouped artifact: 04_thresholds_by_score_mode.json
    if score_mode in thresholds and isinstance(thresholds[score_mode], dict):
        block = thresholds[score_mode]
        kd = block.get(f"k{k}") or block.get(str(k)) or block.get(f"deep_k_{k}")
        if isinstance(kd, dict) and threshold_key in kd:
            return float(kd[threshold_key])

    # Legacy/raw fallback.
    candidates = [thresholds]
    for nested_key in ("thresholds", "deep_thresholds", "knn_thresholds", "scores", "raw"):
        if isinstance(thresholds.get(nested_key), dict):
            candidates.append(thresholds[nested_key])

    for d in candidates:
        if not isinstance(d, dict):
            continue
        for k_name in (f"k{k}", str(k), f"deep_k_{k}"):
            kd = d.get(k_name)
            if isinstance(kd, dict) and threshold_key in kd:
                return float(kd[threshold_key])

    for d in candidates:
        if isinstance(d, dict) and threshold_key in d:
            return float(d[threshold_key])

    raise KeyError(f"Threshold key={threshold_key!r} for k={k}, score_mode={score_mode!r} not found")


def score_knn(nbrs: Any, x: np.ndarray, k_values: Sequence[int], batch_size: int) -> Dict[int, np.ndarray]:
    max_k = int(max(k_values))
    out = {int(k): np.empty((x.shape[0],), dtype=np.float32) for k in k_values}
    for start in range(0, x.shape[0], int(batch_size)):
        end = min(start + int(batch_size), x.shape[0])
        distances, _ = nbrs.kneighbors(x[start:end], n_neighbors=max_k, return_distance=True)
        distances = distances.astype(np.float32, copy=False)
        for k in k_values:
            out[int(k)][start:end] = distances[:, :int(k)].mean(axis=1)
    return out


def causal_smooth_values(vals: np.ndarray, sigma: float) -> np.ndarray:
    vals = np.asarray(vals, dtype=np.float64)
    if sigma <= 0 or len(vals) <= 1:
        return vals.astype(np.float64)
    radius = int(max(1, math.ceil(3.0 * float(sigma))))
    smoothed = np.zeros_like(vals, dtype=np.float64)
    for i in range(len(vals)):
        start_idx = max(0, i - radius)
        recent = vals[start_idx:i + 1]
        d = np.arange(len(recent) - 1, -1, -1, dtype=np.float64)
        w = np.exp(-(d ** 2) / (2.0 * float(sigma) * float(sigma)))
        w /= max(float(w.sum()), 1e-12)
        smoothed[i] = float(np.sum(recent * w))
    return smoothed


def add_causal_smoothing(df: pd.DataFrame, score_col: str, sigma: float, out_col: str) -> pd.DataFrame:
    out = df.copy()
    out[out_col] = np.nan
    for _, g in out.groupby("video_id", sort=False):
        sort_col = "start_time_sec" if "start_time_sec" in g.columns else "start_frame" if "start_frame" in g.columns else None
        g_sorted = g.sort_values(sort_col) if sort_col else g
        vals = pd.to_numeric(g_sorted[score_col], errors="coerce").ffill().bfill().fillna(0).values.astype(float)
        out.loc[g_sorted.index, out_col] = causal_smooth_values(vals, sigma)
    return out


def infer_label_from_text(text: str) -> int | None:
    s = str(text).replace("\\", "/").lower()
    parts = [p for p in s.split("/") if p]
    if "anomaly" in parts or "anomalous" in parts:
        return 1
    if "normal" in parts:
        return 0
    # fallback for names that include the token
    if "anomaly" in s or "anomalous" in s:
        return 1
    if "normal" in s:
        return 0
    return None


def attach_labels(meta: pd.DataFrame, labels_csv: Path | None = None) -> pd.DataFrame:
    out = meta.copy()
    label_map: Dict[str, int] = {}

    if labels_csv is not None and labels_csv.exists():
        labels = pd.read_csv(labels_csv)
        lower_cols = {c.lower().strip(): c for c in labels.columns}
        video_col = lower_cols.get("video_id") or lower_cols.get("video") or lower_cols.get("filename") or lower_cols.get("file") or lower_cols.get("video_path")
        label_col = lower_cols.get("label") or lower_cols.get("class") or lower_cols.get("target") or lower_cols.get("is_anomaly")
        if video_col and label_col:
            for _, row in labels.iterrows():
                key = str(row[video_col])
                raw = str(row[label_col]).strip().lower()
                if raw in {"1", "true", "yes", "y", "anomaly", "anomalous", "abnormal"}:
                    label_map[key] = 1
                    label_map[Path(key).name] = 1
                    label_map[Path(key).stem] = 1
                elif raw in {"0", "false", "no", "n", "normal"}:
                    label_map[key] = 0
                    label_map[Path(key).name] = 0
                    label_map[Path(key).stem] = 0

    labels_out = []
    label_source = []
    for _, row in out.iterrows():
        candidates = [
            str(row.get("video_id", "")),
            str(Path(str(row.get("video_id", ""))).name),
            str(Path(str(row.get("video_id", ""))).stem),
            str(row.get("video_path", "")),
            str(Path(str(row.get("video_path", ""))).name),
            str(Path(str(row.get("video_path", ""))).stem),
        ]

        lab = None
        for c in candidates:
            if c in label_map:
                lab = int(label_map[c])
                label_source.append("labels_csv")
                break

        if lab is None:
            joined = " ".join(candidates)
            lab = infer_label_from_text(joined)
            label_source.append("path_inference" if lab is not None else "unknown")

        labels_out.append(lab if lab is not None else -1)

    out["label"] = labels_out
    out["label_name"] = out["label"].map({0: "normal", 1: "anomaly"}).fillna("unknown")
    out["label_source"] = label_source
    return out


def safe_auc_metrics(y_true: np.ndarray, scores: np.ndarray) -> dict:
    y_true = np.asarray(y_true)
    scores = np.asarray(scores, dtype=float)
    mask = np.isfinite(scores) & np.isin(y_true, [0, 1])
    y = y_true[mask].astype(int)
    s = scores[mask].astype(float)

    out = {"rows_used": int(len(y)), "positive_rows": int((y == 1).sum()), "negative_rows": int((y == 0).sum())}
    if len(np.unique(y)) < 2:
        out.update({"auroc": None, "auprc": None, "note": "Need both normal and anomaly labels for AUROC/AUPRC."})
        return out

    try:
        from sklearn.metrics import roc_auc_score, average_precision_score
        out["auroc"] = float(roc_auc_score(y, s))
        out["auprc"] = float(average_precision_score(y, s))
    except Exception as exc:
        out["auroc"] = None
        out["auprc"] = None
        out["note"] = f"Could not compute sklearn metrics: {exc!r}"
    return out


def apply_persistence(df: pd.DataFrame, score_col: str, threshold: float, window: int, required_hits: int) -> pd.DataFrame:
    out = df.copy()
    out[f"{score_col}_hit"] = False
    out[f"{score_col}_persistence_hits"] = 0
    out[f"{score_col}_persistent"] = False

    for _, g in out.groupby("video_id", sort=False):
        sort_col = "start_time_sec" if "start_time_sec" in g.columns else "start_frame" if "start_frame" in g.columns else None
        g_sorted = g.sort_values(sort_col) if sort_col else g
        hits_deque: deque[bool] = deque(maxlen=int(window))

        for idx, row in g_sorted.iterrows():
            score = float(row[score_col]) if pd.notna(row[score_col]) else 0.0
            hit = bool(score > threshold)
            hits_deque.append(hit)
            persistence_hits = int(sum(hits_deque))
            persistent = bool(persistence_hits >= int(required_hits))
            out.at[idx, f"{score_col}_hit"] = hit
            out.at[idx, f"{score_col}_persistence_hits"] = persistence_hits
            out.at[idx, f"{score_col}_persistent"] = persistent

    return out


def summarize_by_video(df: pd.DataFrame, score_col: str, threshold: float) -> pd.DataFrame:
    rows = []
    for video_id, g in df.groupby("video_id", sort=True):
        label_vals = g["label"].dropna().unique().tolist() if "label" in g.columns else []
        label = int(label_vals[0]) if label_vals else -1
        hit_col = f"{score_col}_hit"
        persistent_col = f"{score_col}_persistent"
        rows.append({
            "video_id": video_id,
            "video_path": g["video_path"].iloc[0] if "video_path" in g.columns and len(g) else "",
            "label": label,
            "label_name": {0: "normal", 1: "anomaly"}.get(label, "unknown"),
            "tubelets": int(len(g)),
            "max_score": float(pd.to_numeric(g[score_col], errors="coerce").max()),
            "mean_score": float(pd.to_numeric(g[score_col], errors="coerce").mean()),
            "threshold": float(threshold),
            "hit_tubelets": int(g[hit_col].sum()) if hit_col in g.columns else 0,
            "persistent_tubelets": int(g[persistent_col].sum()) if persistent_col in g.columns else 0,
            "video_pred_any_hit": int(g[hit_col].any()) if hit_col in g.columns else 0,
            "video_pred_any_persistent": int(g[persistent_col].any()) if persistent_col in g.columns else 0,
        })
    return pd.DataFrame(rows)


def binary_metrics_from_video(video_df: pd.DataFrame, pred_col: str) -> dict:
    d = video_df[video_df["label"].isin([0, 1])].copy()
    if len(d) == 0:
        return {}
    y = d["label"].astype(int).values
    p = d[pred_col].astype(int).values
    tp = int(((y == 1) & (p == 1)).sum())
    fp = int(((y == 0) & (p == 1)).sum())
    tn = int(((y == 0) & (p == 0)).sum())
    fn = int(((y == 1) & (p == 0)).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    specificity = tn / max(1, tn + fp)
    return {
        "videos": int(len(d)),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "specificity": float(specificity),
        "normal_video_false_positive_rate": float(fp / max(1, fp + tn)),
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate trained Deep kNN gate on labeled normal/anomaly embeddings.")
    p.add_argument("--artifact_dir", required=True, type=Path)
    p.add_argument("--thresholds_path", default=None, type=Path, help="Optional thresholds JSON. Use 04_thresholds_by_score_mode.json or combined 04_thresholds.json.")
    p.add_argument("--embeddings_path", required=True, type=Path)
    p.add_argument("--metadata_path", required=True, type=Path)
    p.add_argument("--output_dir", required=True, type=Path)
    p.add_argument("--labels_csv", default=None, type=Path)

    p.add_argument("--k_values", default="1,3,5,10,20")
    p.add_argument("--selected_k", type=int, default=5)
    p.add_argument("--threshold_key", default="p99_5")
    p.add_argument("--gaussian_sigmas", default="1,2,3")
    p.add_argument("--selected_gaussian_sigma", type=float, default=2.0)
    p.add_argument("--persistence_window", type=int, default=5)
    p.add_argument("--persistence_required_hits", type=int, default=3)
    p.add_argument("--batch_size", type=int, default=4096)
    p.add_argument("--l2_epsilon", type=float, default=1e-12)
    p.add_argument("--top_n", type=int, default=200)
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    out_dir: Path = args.output_dir
    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite:
        raise SystemExit(f"Output folder exists and is not empty:\n{out_dir}\nPass --overwrite or choose a new output_dir.")
    ensure_dir(out_dir)
    ensure_dir(out_dir / "scores")
    ensure_dir(out_dir / "reports")

    k_values = parse_ints(args.k_values)
    gaussian_sigmas = parse_floats(args.gaussian_sigmas)
    if args.selected_k not in k_values:
        raise SystemExit(f"--selected_k {args.selected_k} must be included in --k_values {k_values}")
    if args.selected_gaussian_sigma not in gaussian_sigmas:
        gaussian_sigmas.append(float(args.selected_gaussian_sigma))
        gaussian_sigmas = sorted(set(gaussian_sigmas))

    knn_path = args.artifact_dir / "models" / "03_knn_index.joblib"
    thresholds_path = args.thresholds_path or (args.artifact_dir / "04_thresholds.json")
    if not knn_path.exists():
        raise SystemExit(f"kNN artifact not found: {knn_path}")
    if not thresholds_path.exists():
        raise SystemExit(f"Thresholds JSON not found: {thresholds_path}")
    if not args.embeddings_path.exists():
        raise SystemExit(f"Embeddings not found: {args.embeddings_path}")
    if not args.metadata_path.exists():
        raise SystemExit(f"Metadata CSV not found: {args.metadata_path}")

    print(f"[1/7] Loading trained kNN: {knn_path}")
    nbrs = extract_knn_object(joblib.load(knn_path))
    thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))

    print(f"[2/7] Loading eval embeddings: {args.embeddings_path}")
    emb = np.load(args.embeddings_path)
    meta = pd.read_csv(args.metadata_path)
    if len(meta) != emb.shape[0]:
        if "person_embedding_index" in meta.columns:
            idx = pd.to_numeric(meta["person_embedding_index"], errors="coerce")
            valid = idx.notna() & (idx >= 0) & (idx < emb.shape[0])
            meta = meta.loc[valid].copy()
            emb = emb[idx.loc[valid].astype(int).values]
        else:
            raise SystemExit(f"Metadata rows ({len(meta)}) != embeddings rows ({emb.shape[0]})")

    print("[3/7] Attaching labels...")
    meta = attach_labels(meta, args.labels_csv)
    label_counts = meta["label_name"].value_counts(dropna=False).to_dict()
    print(f"Label counts: {label_counts}")

    print("[4/7] L2-normalizing + scoring kNN...")
    x = l2_normalize(emb.astype(np.float32, copy=False), args.l2_epsilon)
    scores_by_k = score_knn(nbrs, x, k_values, args.batch_size)

    scores_df = meta.copy()
    for k, scores in scores_by_k.items():
        scores_df[f"deep_knn_score_k{k}"] = scores.astype(float)

    print("[5/7] Applying causal Gaussian smoothing...")
    for k in k_values:
        raw_col = f"deep_knn_score_k{k}"
        for sigma in gaussian_sigmas:
            out_col = f"deep_knn_score_k{k}_gauss_s{str(float(sigma)).replace('.', '_')}"
            scores_df = add_causal_smoothing(scores_df, raw_col, float(sigma), out_col)

    selected_suffix = str(float(args.selected_gaussian_sigma)).replace(".", "_")
    selected_score_col = f"deep_knn_score_k{args.selected_k}_gauss_s{selected_suffix}"
    selected_score_mode = f"gaussian_sigma_{float(args.selected_gaussian_sigma):g}"
    selected_threshold = load_threshold(thresholds, args.selected_k, args.threshold_key, selected_score_mode)

    print("[6/7] Applying selected threshold + persistence...")
    scores_df = apply_persistence(
        scores_df,
        selected_score_col,
        selected_threshold,
        args.persistence_window,
        args.persistence_required_hits,
    )

    scores_path = out_dir / "scores" / "06_deep_eval_tubelet_scores.csv"
    scores_df.to_csv(scores_path, index=False, encoding="utf-8-sig")

    top_df = scores_df.sort_values(selected_score_col, ascending=False).head(args.top_n)
    top_df.to_csv(out_dir / "reports" / "06_top_scoring_eval_tubelets.csv", index=False, encoding="utf-8-sig")

    print("[7/7] Building metrics reports...")
    sweep_rows = []
    for k in k_values:
        score_cols = [f"deep_knn_score_k{k}"] + [f"deep_knn_score_k{k}_gauss_s{str(float(s)).replace('.', '_')}" for s in gaussian_sigmas]
        for score_col in score_cols:
            if score_col not in scores_df.columns:
                continue
            auc = safe_auc_metrics(scores_df["label"].values, pd.to_numeric(scores_df[score_col], errors="coerce").values)
            if "_gauss_s" in score_col:
                sigma_part = score_col.split("_gauss_s", 1)[1].replace("_", ".")
                score_mode = f"gaussian_sigma_{float(sigma_part):g}"
            else:
                score_mode = "raw"

            # Prefer matching threshold keys from this score mode.
            if isinstance(thresholds.get("thresholds_by_score_mode"), dict):
                mode_block = thresholds["thresholds_by_score_mode"].get(score_mode, {})
            else:
                mode_block = thresholds.get(score_mode, {}) if isinstance(thresholds.get(score_mode), dict) else thresholds.get("raw", thresholds)
            k_block = mode_block.get(f"k{k}", {}) if isinstance(mode_block, dict) else {}
            threshold_keys = sorted(k_block.keys()) if isinstance(k_block, dict) and k_block else ["p95", "p97_5", "p99", "p99_5", "p99_7", "p99_9"]

            for threshold_key in threshold_keys:
                th = load_threshold(thresholds, k, threshold_key, score_mode)
                tmp = apply_persistence(scores_df, score_col, th, args.persistence_window, args.persistence_required_hits)
                video_df = summarize_by_video(tmp, score_col, th)
                vm = binary_metrics_from_video(video_df, f"video_pred_any_persistent")
                sweep_rows.append({
                    "k": int(k),
                    "score_col": score_col,
                    "score_mode": score_mode,
                    "threshold_source_mode": score_mode,
                    "threshold_key": threshold_key,
                    "threshold_value": float(th),
                    "tubelet_auroc": auc.get("auroc"),
                    "tubelet_auprc": auc.get("auprc"),
                    "tubelet_rows_used": auc.get("rows_used"),
                    **{f"video_{kk}": vv for kk, vv in vm.items()},
                })

    sweep_df = pd.DataFrame(sweep_rows)
    sweep_df.to_csv(out_dir / "reports" / "06_deep_eval_config_sweep.csv", index=False, encoding="utf-8-sig")

    video_df = summarize_by_video(scores_df, selected_score_col, selected_threshold)
    video_df.to_csv(out_dir / "reports" / "06_deep_eval_video_summary_selected.csv", index=False, encoding="utf-8-sig")

    selected_auc = safe_auc_metrics(scores_df["label"].values, pd.to_numeric(scores_df[selected_score_col], errors="coerce").values)
    selected_video_metrics = binary_metrics_from_video(video_df, "video_pred_any_persistent")

    summary = {
        "status": "done",
        "artifact_dir": str(args.artifact_dir),
        "embeddings_path": str(args.embeddings_path),
        "metadata_path": str(args.metadata_path),
        "output_dir": str(out_dir),
        "label_counts": label_counts,
        "selected": {
            "k": int(args.selected_k),
            "threshold_key": args.threshold_key,
            "threshold_value": float(selected_threshold),
            "score_col": selected_score_col,
            "score_mode": selected_score_mode,
            "threshold_source_mode": selected_score_mode,
            "gaussian_sigma": float(args.selected_gaussian_sigma),
            "persistence_window": int(args.persistence_window),
            "persistence_required_hits": int(args.persistence_required_hits),
        },
        "selected_tubelet_auc": selected_auc,
        "selected_video_metrics_any_persistent": selected_video_metrics,
        "outputs": {
            "tubelet_scores_csv": str(scores_path),
            "top_scoring_tubelets_csv": str(out_dir / "reports" / "06_top_scoring_eval_tubelets.csv"),
            "config_sweep_csv": str(out_dir / "reports" / "06_deep_eval_config_sweep.csv"),
            "video_summary_selected_csv": str(out_dir / "reports" / "06_deep_eval_video_summary_selected.csv"),
        },
        "important_note": "Video-level metrics assume each video folder/path label is correct. If only part of an anomaly video contains abnormal behavior, video-level recall may be easier than time-localized recall."
    }
    save_json(out_dir / "reports" / "06_deep_eval_summary.json", summary)

    print("\nDONE.")
    print(f"Selected score: {selected_score_col}")
    print(f"Selected threshold: {args.threshold_key} ({selected_score_mode}) = {selected_threshold:.8f}")
    print(f"Tubelet AUROC: {selected_auc.get('auroc')}")
    print(f"Tubelet AUPRC: {selected_auc.get('auprc')}")
    print(f"Video metrics: {selected_video_metrics}")
    print(f"Outputs: {out_dir}")


if __name__ == "__main__":
    main()
