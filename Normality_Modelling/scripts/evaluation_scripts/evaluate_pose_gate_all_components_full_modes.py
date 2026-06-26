#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
evaluate_pose_gate_all_components_full_modes.py

Evaluate the NEW backend-parity Pose/Micro GMM gate on the anomaly dataset.

This script is designed for the new gate built by:
  04g_build_pose_micro_gmm_gate_ALLK_ALLP.py

It reads:
  - pose_micro_features.npy
  - pose_micro_metadata.csv
  - pose_micro_feature_names.json
from --features_dir

and reads:
  - models/pose_robust_scaler.joblib
  - models/pose_gmm_components_*.joblib
  - 04_pose_thresholds.json
from --gate_dir

It evaluates all available:
  - GMM components
  - threshold percentiles
  - postprocessing modes

Modes:
  raw_no_persistence
  smooth_no_persistence
  raw_with_persistence
  smooth_with_persistence

Important:
  For thesis/offline short-clip metrics, usually prefer no-persistence modes.
  Persistence is included only as a deployment-like diagnostic.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from sklearn.metrics import average_precision_score, roc_auc_score


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features_dir", required=True)
    ap.add_argument("--gate_dir", required=True)
    ap.add_argument("--output_dir", required=True)
    ap.add_argument("--threshold_percentiles", type=float, nargs="*", default=None)
    ap.add_argument("--components", type=int, nargs="*", default=None)
    ap.add_argument("--smoothing_sigma", type=float, default=2.0)
    ap.add_argument("--persistence_window", type=int, default=5)
    ap.add_argument("--persistence_required_hits", type=int, default=3)
    ap.add_argument("--overwrite", action="store_true")
    return ap.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_feature_names(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    obj = load_json(path)
    if isinstance(obj, dict):
        names = obj.get("feature_names")
    else:
        names = obj
    return [str(x) for x in names] if names is not None else None


def clean_features(X: np.ndarray, meta: pd.DataFrame, feature_names: list[str] | None):
    finite_mask = np.isfinite(X).all(axis=1)
    nonnegative_mask = (X >= 0).all(axis=1)
    nonzero_mask = np.abs(X).sum(axis=1) > 0

    pose_valid_mask = np.ones(len(X), dtype=bool)
    if feature_names and "pose_valid_frame_ratio" in feature_names:
        idx = feature_names.index("pose_valid_frame_ratio")
        pose_valid_mask = X[:, idx] > 0

    keep = finite_mask & nonnegative_mask & nonzero_mask & pose_valid_mask

    report = {
        "total_rows": int(len(X)),
        "dropped_nonfinite": int((~finite_mask).sum()),
        "dropped_negative": int((~nonnegative_mask).sum()),
        "dropped_all_zero": int((~nonzero_mask).sum()),
        "dropped_pose_valid_frame_ratio_zero": int((~pose_valid_mask).sum()),
        "kept_rows": int(keep.sum()),
    }

    return X[keep], meta.loc[keep].copy().reset_index(drop=True), report


def infer_label(row: pd.Series) -> int:
    text = " ".join(
        str(row.get(c, ""))
        for c in ["video_id", "video_path", "source_video", "path", "file"]
    ).lower().replace("\\", "/")

    # Put anomaly first so paths like ".../anomaly/..." are correctly caught.
    if any(tok in text for tok in ["anomaly", "abnormal", "anomalous", "fall", "fight", "run"]):
        return 1
    if any(tok in text for tok in ["normal", "negative", "/0/", "\\0\\"]):
        return 0

    # If labels are already stored numerically in metadata.
    for c in ["label", "target", "y_true", "class"]:
        if c in row.index:
            try:
                val = int(row[c])
                if val in (0, 1):
                    return val
            except Exception:
                pass

    return 0


def safe_auc(y_true: np.ndarray, scores: np.ndarray) -> float:
    try:
        if len(np.unique(y_true)) < 2:
            return float("nan")
        return float(roc_auc_score(y_true, scores))
    except Exception:
        return float("nan")


def safe_auprc(y_true: np.ndarray, scores: np.ndarray) -> float:
    try:
        if len(np.unique(y_true)) < 2:
            return float("nan")
        return float(average_precision_score(y_true, scores))
    except Exception:
        return float("nan")


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "normal_false_positive_rate": float(fp / (fp + tn)) if (fp + tn) else 0.0,
    }


def gaussian_smooth_1d(values: np.ndarray, sigma: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if sigma <= 0 or len(values) <= 2:
        return values.copy()
    radius = int(max(1, round(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(x ** 2) / (2 * sigma ** 2))
    kernel /= max(float(kernel.sum()), 1e-12)
    padded = np.pad(values, (radius, radius), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def sort_timeline(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = [c for c in ["video_id", "track_id", "start_time_sec", "tubelet_id"] if c in df.columns]
    return df.sort_values(sort_cols).reset_index(drop=True)


def add_smooth_and_persistence(df: pd.DataFrame, threshold: float, sigma: float, required_hits: int, window: int) -> pd.DataFrame:
    df = sort_timeline(df.copy())
    if "track_id" not in df.columns:
        df["track_id"] = 0
    if "start_time_sec" not in df.columns:
        df["start_time_sec"] = np.arange(len(df), dtype=float)

    df["smooth_score"] = np.nan
    df["raw_hit"] = df["raw_score"] > threshold
    df["smooth_hit"] = False
    df["raw_persistent_hit"] = False
    df["smooth_persistent_hit"] = False

    for _, idx in df.groupby(["video_id", "track_id"], sort=False).groups.items():
        idx = list(idx)
        sub = df.loc[idx].sort_values("start_time_sec")
        order_idx = list(sub.index)

        raw = sub["raw_score"].to_numpy(dtype=float)
        smooth = gaussian_smooth_1d(raw, sigma)

        raw_hits = raw > threshold
        smooth_hits = smooth > threshold

        raw_p = np.zeros(len(raw_hits), dtype=bool)
        smooth_p = np.zeros(len(smooth_hits), dtype=bool)

        for i in range(len(raw_hits)):
            lo = max(0, i - window + 1)
            raw_p[i] = int(raw_hits[lo:i + 1].sum()) >= required_hits
            smooth_p[i] = int(smooth_hits[lo:i + 1].sum()) >= required_hits

        df.loc[order_idx, "smooth_score"] = smooth
        df.loc[order_idx, "smooth_hit"] = smooth_hits
        df.loc[order_idx, "raw_persistent_hit"] = raw_p
        df.loc[order_idx, "smooth_persistent_hit"] = smooth_p

    return df


def thresholds_from_payload(gate_dir: Path) -> dict[int, dict[float, float]]:
    path = gate_dir / "04_pose_thresholds.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing thresholds file: {path}")

    payload = load_json(path)
    out: dict[int, dict[float, float]] = {}

    # New enhanced layout.
    by_kp = payload.get("thresholds_by_components_and_percentiles")
    if isinstance(by_kp, dict):
        for k_str, pmap in by_kp.items():
            k = int(k_str)
            out[k] = {}
            for _, item in pmap.items():
                if isinstance(item, dict):
                    p = float(item["percentile"])
                    thr = float(item["threshold"])
                    out[k][p] = thr
        return out

    # Old fallback layout: only one threshold per k.
    by_k = payload.get("thresholds_by_components")
    one_p = float(payload.get("threshold_percentile", payload.get("primary_threshold_percentile", 99.5)))
    if isinstance(by_k, dict):
        for k_str, thr in by_k.items():
            out[int(k_str)] = {one_p: float(thr)}
        return out

    raise ValueError(f"Could not parse thresholds from {path}")


def label_percentile(p: float) -> str:
    return ("%g" % float(p)).replace(".", "p")


def build_clip_scores(df: pd.DataFrame, mode: str, score_col: str, pred_col: str) -> pd.DataFrame:
    rows = []
    for video_id, sub in df.groupby("video_id", sort=False):
        label = int(sub["label"].max())
        rows.append({
            "video_id": video_id,
            "label": label,
            "mode": mode,
            "clip_score": float(sub[score_col].max()) if len(sub) else float("nan"),
            "clip_pred": int(sub[pred_col].astype(bool).any()),
            "tubelets": int(len(sub)),
            "tracks": int(sub["track_id"].nunique()) if "track_id" in sub.columns else 1,
        })
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()

    features_dir = Path(args.features_dir)
    gate_dir = Path(args.gate_dir)
    output_dir = Path(args.output_dir)

    if output_dir.exists() and not args.overwrite:
        raise FileExistsError(f"Output folder exists: {output_dir}. Use --overwrite.")
    output_dir.mkdir(parents=True, exist_ok=True)

    X = np.load(features_dir / "pose_micro_features.npy")
    meta = pd.read_csv(features_dir / "pose_micro_metadata.csv", encoding="utf-8-sig")
    feature_names = load_feature_names(features_dir / "pose_micro_feature_names.json")

    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata rows do not match feature rows: {len(meta)} vs {X.shape[0]}")
    if feature_names is not None and len(feature_names) != X.shape[1]:
        raise ValueError(f"Feature names count mismatch: {len(feature_names)} vs {X.shape[1]}")

    X_clean, meta_clean, cleaning_report = clean_features(X, meta, feature_names)

    if "video_id" not in meta_clean.columns:
        raise ValueError("pose_micro_metadata.csv must contain video_id")
    if "track_id" not in meta_clean.columns:
        meta_clean["track_id"] = 0
    if "tubelet_id" not in meta_clean.columns:
        meta_clean["tubelet_id"] = np.arange(len(meta_clean))
    if "start_time_sec" not in meta_clean.columns:
        meta_clean["start_time_sec"] = np.arange(len(meta_clean), dtype=float)

    meta_clean["label"] = meta_clean.apply(infer_label, axis=1).astype(int)

    thresholds = thresholds_from_payload(gate_dir)
    available_components = sorted(thresholds.keys())
    components = args.components if args.components else available_components

    if args.threshold_percentiles:
        wanted_percentiles = [float(p) for p in args.threshold_percentiles]
    else:
        wanted_percentiles = sorted({p for pmap in thresholds.values() for p in pmap.keys()})

    scaler_path = gate_dir / "models" / "pose_robust_scaler.joblib"
    if not scaler_path.exists():
        raise FileNotFoundError(scaler_path)

    scaler = joblib.load(scaler_path)
    X_scaled = scaler.transform(X_clean)

    print("=" * 90)
    print("Evaluating Pose gate on anomaly dataset - all k / all percentiles / full modes")
    print(f"features_dir = {features_dir}")
    print(f"gate_dir     = {gate_dir}")
    print(f"output_dir   = {output_dir}")
    print(f"feature_shape_raw   = {list(X.shape)}")
    print(f"feature_shape_clean = {list(X_clean.shape)}")
    print(f"label_counts = {meta_clean['label'].value_counts().sort_index().to_dict()}")
    print(f"video_counts = {meta_clean.groupby('label')['video_id'].nunique().sort_index().to_dict()}")
    print(f"components   = {components}")
    print(f"percentiles  = {wanted_percentiles}")
    print("=" * 90)

    all_tubelet_frames = []
    all_clip_frames = []
    metric_rows = []

    for k in components:
        k = int(k)
        gmm_path = gate_dir / "models" / f"pose_gmm_components_{k}.joblib"
        if not gmm_path.exists():
            print(f"[WARN] Missing model for k={k}: {gmm_path}; skipping")
            continue

        if k not in thresholds:
            print(f"[WARN] No thresholds for k={k}; skipping")
            continue

        gmm = joblib.load(gmm_path)
        raw_scores = -gmm.score_samples(X_scaled)

        base = meta_clean.copy()
        base["components"] = k
        base["raw_score"] = raw_scores.astype(float)
        base = sort_timeline(base)

        for p in wanted_percentiles:
            p = float(p)
            if p not in thresholds[k]:
                print(f"[WARN] Missing threshold for k={k}, p={p}; skipping")
                continue

            threshold = float(thresholds[k][p])
            scored = add_smooth_and_persistence(
                base,
                threshold=threshold,
                sigma=float(args.smoothing_sigma),
                required_hits=int(args.persistence_required_hits),
                window=int(args.persistence_window),
            )

            mode_defs = [
                ("raw_no_persistence", "raw_score", "raw_hit"),
                ("smooth_no_persistence", "smooth_score", "smooth_hit"),
                ("raw_with_persistence", "raw_score", "raw_persistent_hit"),
                ("smooth_with_persistence", "smooth_score", "smooth_persistent_hit"),
            ]

            for mode, score_col, pred_col in mode_defs:
                cfg = scored.copy()
                cfg["threshold_percentile"] = p
                cfg["threshold"] = threshold
                cfg["mode"] = mode
                cfg["config_id"] = f"pose_c{k}_p{label_percentile(p)}_{mode}"
                cfg["eval_score"] = cfg[score_col].astype(float)
                cfg["tubelet_pred"] = cfg[pred_col].astype(int)

                clip_df = build_clip_scores(cfg, mode=mode, score_col="eval_score", pred_col="tubelet_pred")
                clip_df["components"] = k
                clip_df["threshold_percentile"] = p
                clip_df["threshold"] = threshold
                clip_df["config_id"] = cfg["config_id"].iloc[0]

                y_t = cfg["label"].to_numpy(dtype=int)
                y_p = cfg["tubelet_pred"].to_numpy(dtype=int)
                y_s = cfg["eval_score"].to_numpy(dtype=float)

                tube_m = binary_metrics(y_t, y_p)
                clip_m = binary_metrics(
                    clip_df["label"].to_numpy(dtype=int),
                    clip_df["clip_pred"].to_numpy(dtype=int),
                )

                row = {
                    "config_id": cfg["config_id"].iloc[0],
                    "components": k,
                    "threshold_percentile": p,
                    "threshold": threshold,
                    "mode": mode,
                    "tubelet_auroc": safe_auc(y_t, y_s),
                    "tubelet_auprc": safe_auprc(y_t, y_s),
                    "tubelet_precision": tube_m["precision"],
                    "tubelet_recall": tube_m["recall"],
                    "tubelet_f1": tube_m["f1"],
                    "tubelet_tp": tube_m["tp"],
                    "tubelet_tn": tube_m["tn"],
                    "tubelet_fp": tube_m["fp"],
                    "tubelet_fn": tube_m["fn"],
                    "clip_precision": clip_m["precision"],
                    "clip_recall": clip_m["recall"],
                    "clip_f1": clip_m["f1"],
                    "clip_tp": clip_m["tp"],
                    "clip_tn": clip_m["tn"],
                    "clip_fp": clip_m["fp"],
                    "clip_fn": clip_m["fn"],
                    "normal_clip_false_positive_rate": clip_m["normal_false_positive_rate"],
                    "num_clips": int(len(clip_df)),
                    "num_normal_clips": int((clip_df["label"] == 0).sum()),
                    "num_anomaly_clips": int((clip_df["label"] == 1).sum()),
                }
                metric_rows.append(row)

                all_tubelet_frames.append(cfg[[
                    c for c in [
                        "config_id", "components", "threshold_percentile", "threshold", "mode",
                        "video_id", "video_path", "track_id", "tubelet_id", "start_time_sec", "label",
                        "raw_score", "smooth_score", "eval_score",
                        "raw_hit", "smooth_hit", "raw_persistent_hit", "smooth_persistent_hit", "tubelet_pred",
                    ] if c in cfg.columns
                ]].copy())
                all_clip_frames.append(clip_df.copy())

                print(
                    f"{row['config_id']}: "
                    f"AUROC={row['tubelet_auroc']:.4f} | "
                    f"AUPRC={row['tubelet_auprc']:.4f} | "
                    f"clip P/R/F1={row['clip_precision']:.3f}/{row['clip_recall']:.3f}/{row['clip_f1']:.3f} | "
                    f"normal FP={row['normal_clip_false_positive_rate']:.3f}"
                )

    metrics_df = pd.DataFrame(metric_rows)
    tubelet_df = pd.concat(all_tubelet_frames, ignore_index=True) if all_tubelet_frames else pd.DataFrame()
    clip_df = pd.concat(all_clip_frames, ignore_index=True) if all_clip_frames else pd.DataFrame()

    if not metrics_df.empty:
        mode_order = {
            "raw_no_persistence": 0,
            "smooth_no_persistence": 1,
            "raw_with_persistence": 2,
            "smooth_with_persistence": 3,
        }
        metrics_df["_mode_order"] = metrics_df["mode"].map(mode_order).fillna(99)
        metrics_df = metrics_df.sort_values(
            ["components", "threshold_percentile", "_mode_order"]
        ).drop(columns=["_mode_order"])

    out_metrics = output_dir / "pose_full_modes_metrics.csv"
    out_tubelets = output_dir / "pose_full_modes_tubelet_scores.csv"
    out_clips = output_dir / "pose_full_modes_clip_scores.csv"
    out_summary = output_dir / "pose_full_modes_summary.json"

    metrics_df.to_csv(out_metrics, index=False, encoding="utf-8-sig")
    tubelet_df.to_csv(out_tubelets, index=False, encoding="utf-8-sig")
    clip_df.to_csv(out_clips, index=False, encoding="utf-8-sig")

    summary = {
        "script": Path(__file__).name,
        "features_dir": str(features_dir),
        "gate_dir": str(gate_dir),
        "output_dir": str(output_dir),
        "feature_shape_raw": list(map(int, X.shape)),
        "feature_shape_clean": list(map(int, X_clean.shape)),
        "cleaning_report": cleaning_report,
        "label_counts_tubelets_clean": {str(k): int(v) for k, v in meta_clean["label"].value_counts().sort_index().to_dict().items()},
        "video_counts_clean": {str(k): int(v) for k, v in meta_clean.groupby("label")["video_id"].nunique().sort_index().to_dict().items()},
        "components_evaluated": [int(x) for x in components],
        "threshold_percentiles_evaluated": [float(x) for x in wanted_percentiles],
        "modes": ["raw_no_persistence", "smooth_no_persistence", "raw_with_persistence", "smooth_with_persistence"],
        "important_interpretation": (
            "For offline short-clip reporting, raw_no_persistence and smooth_no_persistence are usually the fair metrics. "
            "Persistence modes are included as deployment-like diagnostics because persistence is primarily for continuous RTSP streams."
        ),
        "outputs": {
            "metrics_csv": str(out_metrics),
            "tubelet_scores_csv": str(out_tubelets),
            "clip_scores_csv": str(out_clips),
            "summary_json": str(out_summary),
        },
    }
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + "=" * 90)
    print("DONE")
    print("=" * 90)
    print(f"Metrics:        {out_metrics}")
    print(f"Clip scores:    {out_clips}")
    print(f"Tubelet scores: {out_tubelets}")
    print(f"Summary:        {out_summary}")

    if not metrics_df.empty:
        print("\nTop by clip_f1, with normal FP <= 0.50:")
        subset = metrics_df[metrics_df["normal_clip_false_positive_rate"] <= 0.50].copy()
        if len(subset):
            print(subset.sort_values(["clip_f1", "clip_precision", "clip_recall"], ascending=False).head(15)[[
                "components", "threshold_percentile", "mode", "threshold",
                "clip_precision", "clip_recall", "clip_f1", "normal_clip_false_positive_rate",
                "tubelet_auroc", "tubelet_auprc",
            ]].to_string(index=False))


if __name__ == "__main__":
    main()
