#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
evaluate_homography_macro_gate_all_components_full_modes.py

Evaluate Homography/Macro GMM gate on anomaly dataset with ALL combinations:

1) raw_no_persistence
   - no smoothing
   - no persistence

2) smooth_no_persistence
   - smoothing enabled
   - no persistence

3) raw_with_persistence
   - no smoothing
   - persistence enabled on raw threshold hits

4) smooth_with_persistence
   - smoothing enabled
   - persistence enabled on smoothed threshold hits

For every GMM component model found under:
    gate_dir/models/macro_gmm_components_*.joblib

For every threshold percentile requested:
    --threshold_percentiles 99.5 99.7

Important design choice
-----------------------
Thresholds are recalibrated per component and per score type:

- raw modes use thresholds from NORMAL calibration RAW scores
- smooth modes use thresholds from NORMAL calibration SMOOTHED scores

Why?
----
Raw and smoothed score distributions are not identical. Reusing a smoothed
threshold for raw scores can make raw/no-smoothing results unfair or misleading.

Inputs
------
--features_dir:
  anomaly/eval feature folder containing:
    homography_macro_features.npy
    homography_macro_metadata.csv
    homography_macro_feature_names.json

--gate_dir:
  trained Homography gate folder containing:
    09_recommended_macro_gate.json
    01_macro_gmm_training_summary.json
    models/macro_robust_scaler.joblib
    models/macro_gmm_components_*.joblib

--normal_features_dir:
  optional. If omitted, read from:
    gate_dir/01_macro_gmm_training_summary.json -> input_dir

Outputs
-------
  homography_full_modes_metrics.csv
  homography_full_modes_clip_scores.csv
  homography_full_modes_tubelet_scores.csv
  homography_full_modes_thresholds.csv
  homography_full_modes_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Args / IO
# ---------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate Homography GMM components with raw/smooth and persistence/no-persistence modes."
    )
    p.add_argument("--features_dir", required=True, type=Path, help="Anomaly/eval Homography features dir.")
    p.add_argument("--gate_dir", required=True, type=Path, help="Trained Homography gate dir.")
    p.add_argument("--output_dir", required=True, type=Path)
    p.add_argument(
        "--normal_features_dir",
        default=None,
        type=Path,
        help="Normal Homography features dir used for training. If omitted, read from training summary input_dir.",
    )
    p.add_argument(
        "--threshold_percentiles",
        type=float,
        nargs="*",
        default=None,
        help="Threshold percentiles to test. Default uses 99.5 and 99.7.",
    )
    p.add_argument("--smoothing_sigma", type=float, default=None, help="Default uses recommended smoothing_sigma or 2.0.")
    p.add_argument("--persistence_window", type=int, default=None, help="Default uses recommended persistence_window or 5.")
    p.add_argument("--persistence_required_hits", type=int, default=None, help="Default uses recommended required hits or 3.")
    p.add_argument("--components", type=int, nargs="*", default=None, help="Optional subset, e.g. --components 5 10")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_feature_names(path: Path) -> list[str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(obj, dict):
        names = obj.get("feature_names")
        if names is None:
            raise KeyError(f"No feature_names key in {path}")
    else:
        names = obj
    return [str(x) for x in names]


def load_features_dir(folder: Path) -> tuple[np.ndarray, pd.DataFrame, list[str]]:
    features_path = folder / "homography_macro_features.npy"
    metadata_path = folder / "homography_macro_metadata.csv"
    feature_names_path = folder / "homography_macro_feature_names.json"

    for p in [features_path, metadata_path, feature_names_path]:
        if not p.exists():
            raise FileNotFoundError(p)

    X = np.load(features_path)
    meta = pd.read_csv(metadata_path, encoding="utf-8-sig")
    names = load_feature_names(feature_names_path)

    if X.ndim != 2:
        raise ValueError(f"Expected 2D feature matrix in {folder}, got {X.shape}")
    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata/features mismatch in {folder}: meta={len(meta)} X={X.shape[0]}")
    if len(names) != X.shape[1]:
        raise ValueError(f"Feature-name mismatch in {folder}: names={len(names)} X={X.shape[1]}")
    return X, meta, names


# ---------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------

def safe_div(a: float, b: float) -> float:
    return float(a / b) if b else 0.0


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)

    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    fpr = safe_div(fp, fp + tn)
    fnr = safe_div(fn, fn + tp)
    accuracy = safe_div(tp + tn, tp + tn + fp + fn)
    f1 = safe_div(2.0 * precision * recall, precision + recall)

    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "fpr": fpr,
        "fnr": fnr,
        "accuracy": accuracy,
        "f1": f1,
    }


def auc_metrics(y_true: np.ndarray, scores: np.ndarray) -> dict[str, Optional[float]]:
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores).astype(float)

    if len(np.unique(y_true)) < 2:
        return {"auroc": None, "auprc": None, "average_precision": None}

    try:
        from sklearn.metrics import roc_auc_score, average_precision_score
        auroc = float(roc_auc_score(y_true, scores))
        ap = float(average_precision_score(y_true, scores))
        return {"auroc": auroc, "auprc": ap, "average_precision": ap}
    except Exception:
        return {"auroc": None, "auprc": None, "average_precision": None}


def gaussian_kernel1d(sigma: float) -> np.ndarray:
    sigma = float(sigma)
    if sigma <= 0:
        return np.array([1.0], dtype=np.float64)
    radius = int(math.ceil(3.0 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x ** 2) / (2.0 * sigma ** 2))
    k /= max(float(k.sum()), 1e-12)
    return k


def sort_timeline(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["video_id", "track_id", "start_time_sec", "tubelet_id"] if c in df.columns]
    return df.sort_values(cols).reset_index(drop=True) if cols else df.reset_index(drop=True)


def smooth_scores_per_track(df: pd.DataFrame, score_col: str, out_col: str, sigma: float) -> pd.DataFrame:
    out = sort_timeline(df.copy())
    out[out_col] = np.nan
    kernel = gaussian_kernel1d(sigma)
    group_cols = ["video_id", "track_id"] if "track_id" in out.columns else ["video_id"]

    for _, idx in out.groupby(group_cols, dropna=False).groups.items():
        idx = list(idx)
        vals = out.loc[idx, score_col].astype(float).to_numpy()
        if sigma <= 0 or len(vals) <= 1:
            smoothed = vals
        else:
            pad = len(kernel) // 2
            padded = np.pad(vals, pad_width=pad, mode="edge")
            smoothed = np.convolve(padded, kernel, mode="valid")
        out.loc[idx, out_col] = smoothed

    return out


def add_persistence_per_track(
    df: pd.DataFrame,
    hit_col: str,
    out_col: str,
    window: int,
    required_hits: int,
) -> pd.DataFrame:
    out = sort_timeline(df.copy())
    out[out_col] = 0
    group_cols = ["video_id", "track_id"] if "track_id" in out.columns else ["video_id"]

    for _, idx in out.groupby(group_cols, dropna=False).groups.items():
        idx = list(idx)
        hits = out.loc[idx, hit_col].astype(int).to_numpy()
        recent: list[int] = []
        persisted: list[int] = []
        for h in hits:
            recent.append(int(h))
            if len(recent) > int(window):
                recent.pop(0)
            persisted.append(int(sum(recent) >= int(required_hits)))
        out.loc[idx, out_col] = persisted

    return out


# ---------------------------------------------------------------------
# Label / feature/model helpers
# ---------------------------------------------------------------------

def infer_label(video_id: str, video_path: str) -> int:
    vid = str(video_id).strip().lower()
    path = str(video_path).replace("\\", "/").strip().lower()

    if vid.startswith("anomaly__"):
        return 1
    if vid.startswith("normal__"):
        return 0

    # Good for D:\...\Dataset\Anomaly\... and D:\...\Dataset\Normal\...
    anomaly_markers = ["/dataset/anomaly/", "/anomaly/"]
    normal_markers = ["/dataset/normal/", "/normal/"]

    if any(m in path for m in anomaly_markers):
        return 1
    if any(m in path for m in normal_markers):
        return 0

    raise ValueError(f"Could not infer label from video_id={video_id!r}, video_path={video_path!r}")


def select_matrix(X: np.ndarray, feature_names: list[str], selected_features: list[str]) -> np.ndarray:
    missing = [f for f in selected_features if f not in feature_names]
    if missing:
        raise ValueError(f"Selected features missing from feature_names: {missing}")

    idx = [feature_names.index(f) for f in selected_features]
    X_sel = np.asarray(X[:, idx], dtype=np.float64)

    keep = np.isfinite(X_sel).all(axis=1) & (np.abs(X_sel).sum(axis=1) > 0)
    if not np.all(keep):
        raise ValueError(
            f"Nonfinite/empty rows found after selecting features. "
            f"This evaluator expects already-clean features. Bad rows={int(np.sum(~keep))}"
        )
    return X_sel


def discover_gmms(gate_dir: Path, requested: Optional[list[int]]) -> dict[int, Path]:
    models_dir = gate_dir / "models"
    hits: dict[int, Path] = {}

    for p in sorted(models_dir.glob("macro_gmm_components_*.joblib")):
        m = re.search(r"components_(\d+)", p.name)
        if not m:
            continue
        k = int(m.group(1))
        if requested is None or k in requested:
            hits[k] = p

    if not hits:
        raise FileNotFoundError(f"No macro_gmm_components_*.joblib files found in {models_dir}")
    return hits


def find_scaler(gate_dir: Path) -> Path:
    preferred = gate_dir / "models" / "macro_robust_scaler.joblib"
    if preferred.exists():
        return preferred

    matches = list(gate_dir.rglob("*scaler*.joblib"))
    if matches:
        return sorted(matches, key=lambda p: len(str(p)))[0]

    raise FileNotFoundError(f"Could not find scaler under {gate_dir}")


# ---------------------------------------------------------------------
# Output tables
# ---------------------------------------------------------------------

def make_clip_scores(
    df: pd.DataFrame,
    *,
    score_col: str,
    pred_col: str,
    components: int,
    threshold_percentile: float,
    threshold: float,
    mode: str,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for video_id, g in df.groupby("video_id", dropna=False):
        labels = sorted(set(g["label"].astype(int).tolist()))
        if len(labels) != 1:
            raise ValueError(f"Mixed labels in video_id={video_id}: {labels}")

        scores = g[score_col].astype(float).to_numpy()
        rows.append({
            "components": int(components),
            "threshold_percentile": float(threshold_percentile),
            "threshold": float(threshold),
            "mode": mode,
            "video_id": video_id,
            "video_path": str(g["video_path"].iloc[0]) if "video_path" in g.columns else "",
            "label": int(labels[0]),
            "clip_pred": int(g[pred_col].astype(int).sum() >= 1),
            "num_tubelets": int(len(g)),
            "num_alarm_tubelets": int(g[pred_col].astype(int).sum()),
            "max_score": float(np.max(scores)),
            "p95_score": float(np.percentile(scores, 95)),
            "mean_score": float(np.mean(scores)),
        })

    return pd.DataFrame(rows)


def add_metric_row(
    rows: list[dict[str, Any]],
    *,
    df: pd.DataFrame,
    clip_df: pd.DataFrame,
    components: int,
    mode: str,
    score_col: str,
    pred_col: str,
    threshold: float,
    threshold_percentile: float,
    threshold_score_type: str,
    smoothing_enabled: bool,
    persistence_enabled: bool,
    smoothing_sigma: float,
    persistence_window: int,
    persistence_required_hits: int,
) -> None:
    y = df["label"].astype(int).to_numpy()
    pred = df[pred_col].astype(int).to_numpy()
    scores = df[score_col].astype(float).to_numpy()

    tbm = binary_metrics(y, pred)
    auc = auc_metrics(y, scores)
    cbm = binary_metrics(clip_df["label"].astype(int).to_numpy(), clip_df["clip_pred"].astype(int).to_numpy())

    rows.append({
        "components": int(components),
        "threshold_percentile": float(threshold_percentile),
        "threshold": float(threshold),
        "threshold_score_type": threshold_score_type,
        "mode": mode,
        "smoothing_enabled": bool(smoothing_enabled),
        "persistence_enabled": bool(persistence_enabled),
        "smoothing_sigma": float(smoothing_sigma) if smoothing_enabled else 0.0,
        "persistence_window": int(persistence_window) if persistence_enabled else 0,
        "persistence_required_hits": int(persistence_required_hits) if persistence_enabled else 0,

        "tubelet_count": int(len(df)),
        "tubelet_normal_count": int(np.sum(y == 0)),
        "tubelet_anomaly_count": int(np.sum(y == 1)),
        "tubelet_alarm_count": int(np.sum(pred)),
        "tubelet_auroc": auc["auroc"],
        "tubelet_auprc": auc["auprc"],
        "tubelet_average_precision": auc["average_precision"],
        "tubelet_tp": tbm["tp"],
        "tubelet_tn": tbm["tn"],
        "tubelet_fp": tbm["fp"],
        "tubelet_fn": tbm["fn"],
        "tubelet_precision": tbm["precision"],
        "tubelet_recall": tbm["recall"],
        "tubelet_specificity": tbm["specificity"],
        "tubelet_fpr": tbm["fpr"],
        "tubelet_fnr": tbm["fnr"],
        "tubelet_accuracy": tbm["accuracy"],
        "tubelet_f1": tbm["f1"],

        "clip_count": int(len(clip_df)),
        "clip_normal_count": int(np.sum(clip_df["label"] == 0)),
        "clip_anomaly_count": int(np.sum(clip_df["label"] == 1)),
        "clip_alarm_count": int(np.sum(clip_df["clip_pred"])),
        "clip_tp": cbm["tp"],
        "clip_tn": cbm["tn"],
        "clip_fp": cbm["fp"],
        "clip_fn": cbm["fn"],
        "clip_precision": cbm["precision"],
        "clip_recall": cbm["recall"],
        "clip_specificity": cbm["specificity"],
        "clip_fpr": cbm["fpr"],
        "clip_fnr": cbm["fnr"],
        "clip_accuracy": cbm["accuracy"],
        "clip_f1": cbm["f1"],
        "normal_clip_false_positive_rate": safe_div(cbm["fp"], cbm["fp"] + cbm["tn"]),
        "anomaly_clip_detection_rate": safe_div(cbm["tp"], cbm["tp"] + cbm["fn"]),
    })


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = args.output_dir / "homography_full_modes_metrics.csv"
    if metrics_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {metrics_path}. Use --overwrite.")

    rec = read_json(args.gate_dir / "09_recommended_macro_gate.json")
    train_summary = read_json(args.gate_dir / "01_macro_gmm_training_summary.json")

    selected_features = (
        rec.get("input_features")
        or rec.get("selected_features")
        or train_summary.get("selected_features")
    )
    if not selected_features:
        raise KeyError("Could not find selected/input features in recommended gate or training summary.")
    selected_features = [str(x) for x in selected_features]

    threshold_percentiles = args.threshold_percentiles
    if not threshold_percentiles:
        threshold_percentiles = [99.5, 99.7]
    threshold_percentiles = [float(x) for x in threshold_percentiles]

    smoothing_sigma = float(args.smoothing_sigma if args.smoothing_sigma is not None else rec.get("smoothing_sigma", 2.0))
    persistence_window = int(args.persistence_window if args.persistence_window is not None else rec.get("persistence_window", 5))
    persistence_required_hits = int(
        args.persistence_required_hits if args.persistence_required_hits is not None else rec.get("persistence_required_hits", 3)
    )

    normal_features_dir = args.normal_features_dir
    if normal_features_dir is None:
        normal_input = train_summary.get("input_dir")
        if not normal_input:
            raise ValueError("Provide --normal_features_dir; could not infer it from 01_macro_gmm_training_summary.json")
        normal_features_dir = Path(str(normal_input))

    split = rec.get("split", {})
    cal_videos = [str(x) for x in split.get("calibration", [])]
    if not cal_videos:
        raise ValueError("No calibration video list found in 09_recommended_macro_gate.json.")

    print("=" * 104)
    print("Homography all-components FULL MODES evaluation")
    print("=" * 104)
    print(f"features_dir              = {args.features_dir}")
    print(f"normal_features_dir       = {normal_features_dir}")
    print(f"gate_dir                  = {args.gate_dir}")
    print(f"selected_features         = {selected_features}")
    print(f"threshold_percentiles     = {threshold_percentiles}")
    print(f"smoothing_sigma           = {smoothing_sigma}")
    print(f"persistence               = {persistence_required_hits}/{persistence_window}")
    print("=" * 104)

    X_eval, meta_eval, names_eval = load_features_dir(args.features_dir)
    X_norm, meta_norm, names_norm = load_features_dir(normal_features_dir)

    X_eval_sel = select_matrix(X_eval, names_eval, selected_features)
    X_norm_sel = select_matrix(X_norm, names_norm, selected_features)

    scaler_path = find_scaler(args.gate_dir)
    scaler = joblib.load(scaler_path)

    X_eval_model = scaler.transform(X_eval_sel)
    X_norm_model = scaler.transform(X_norm_sel)

    # Support PCA if ever enabled; your current contract-fixed gate uses no PCA.
    use_pca = bool(rec.get("use_pca", False))
    pca_path = args.gate_dir / "models" / "macro_pca.joblib"
    if use_pca and pca_path.exists():
        pca = joblib.load(pca_path)
        X_eval_model = pca.transform(X_eval_model)
        X_norm_model = pca.transform(X_norm_model)

    # Labels for eval set
    labels = []
    for _, row in meta_eval.iterrows():
        labels.append(infer_label(str(row.get("video_id", "")), str(row.get("video_path", ""))))
    meta_eval = meta_eval.copy()
    meta_eval["label"] = labels

    for df in [meta_eval, meta_norm]:
        if "track_id" not in df.columns:
            df["track_id"] = 0
        if "tubelet_id" not in df.columns:
            df["tubelet_id"] = np.arange(len(df))
        if "start_time_sec" not in df.columns:
            df["start_time_sec"] = np.arange(len(df), dtype=float)
        if "end_time_sec" not in df.columns:
            df["end_time_sec"] = df["start_time_sec"]

    if "video_id" not in meta_norm.columns:
        raise ValueError("Normal metadata has no video_id column.")

    cal_mask = meta_norm["video_id"].astype(str).isin(cal_videos).to_numpy()
    if not np.any(cal_mask):
        raise ValueError(
            "Calibration split videos from recommended JSON were not found in normal metadata. "
            "Check whether video_id includes .mp4 consistently."
        )

    gmms = discover_gmms(args.gate_dir, args.components)

    all_metrics: list[dict[str, Any]] = []
    all_clip: list[pd.DataFrame] = []
    all_tubelet: list[pd.DataFrame] = []
    threshold_rows: list[dict[str, Any]] = []

    for k, gmm_path in sorted(gmms.items()):
        gmm = joblib.load(gmm_path)

        norm_raw_scores = -gmm.score_samples(X_norm_model)
        norm_df = meta_norm.copy()
        norm_df["raw_score"] = norm_raw_scores.astype(float)
        norm_df = smooth_scores_per_track(norm_df, "raw_score", "smoothed_score", smoothing_sigma)

        eval_raw_scores = -gmm.score_samples(X_eval_model)
        base_eval_df = meta_eval.copy()
        base_eval_df["components"] = int(k)
        base_eval_df["raw_score"] = eval_raw_scores.astype(float)
        base_eval_df = smooth_scores_per_track(base_eval_df, "raw_score", "smoothed_score", smoothing_sigma)

        cal_raw = norm_df.loc[cal_mask, "raw_score"].astype(float).to_numpy()
        cal_smooth = norm_df.loc[cal_mask, "smoothed_score"].astype(float).to_numpy()

        for pct in threshold_percentiles:
            pct = float(pct)
            raw_threshold = float(np.percentile(cal_raw, pct))
            smooth_threshold = float(np.percentile(cal_smooth, pct))

            threshold_rows.append({
                "components": int(k),
                "threshold_percentile": pct,
                "raw_threshold": raw_threshold,
                "smooth_threshold": smooth_threshold,
                "raw_threshold_source": "normal_calibration_split_raw_scores",
                "smooth_threshold_source": "normal_calibration_split_smoothed_scores",
                "calibration_tubelets": int(np.sum(cal_mask)),
                "gmm_path": str(gmm_path),
            })

            df = base_eval_df.copy()
            df["threshold_percentile"] = pct
            df["raw_threshold"] = raw_threshold
            df["smooth_threshold"] = smooth_threshold
            df["raw_hit"] = (df["raw_score"].astype(float) > raw_threshold).astype(int)
            df["smooth_hit"] = (df["smoothed_score"].astype(float) > smooth_threshold).astype(int)

            df = add_persistence_per_track(
                df,
                hit_col="raw_hit",
                out_col="raw_persistent_hit",
                window=persistence_window,
                required_hits=persistence_required_hits,
            )
            df = add_persistence_per_track(
                df,
                hit_col="smooth_hit",
                out_col="smooth_persistent_hit",
                window=persistence_window,
                required_hits=persistence_required_hits,
            )

            mode_specs = [
                {
                    "mode": "raw_no_persistence",
                    "score_col": "raw_score",
                    "pred_col": "raw_hit",
                    "threshold": raw_threshold,
                    "threshold_score_type": "raw",
                    "smoothing_enabled": False,
                    "persistence_enabled": False,
                },
                {
                    "mode": "smooth_no_persistence",
                    "score_col": "smoothed_score",
                    "pred_col": "smooth_hit",
                    "threshold": smooth_threshold,
                    "threshold_score_type": "smooth",
                    "smoothing_enabled": True,
                    "persistence_enabled": False,
                },
                {
                    "mode": "raw_with_persistence",
                    "score_col": "raw_score",
                    "pred_col": "raw_persistent_hit",
                    "threshold": raw_threshold,
                    "threshold_score_type": "raw",
                    "smoothing_enabled": False,
                    "persistence_enabled": True,
                },
                {
                    "mode": "smooth_with_persistence",
                    "score_col": "smoothed_score",
                    "pred_col": "smooth_persistent_hit",
                    "threshold": smooth_threshold,
                    "threshold_score_type": "smooth",
                    "smoothing_enabled": True,
                    "persistence_enabled": True,
                },
            ]

            for spec in mode_specs:
                mode = spec["mode"]
                score_col = spec["score_col"]
                pred_col = spec["pred_col"]
                threshold = float(spec["threshold"])

                tube = df.copy()
                tube["mode"] = mode
                tube["threshold"] = threshold
                tube["threshold_score_type"] = spec["threshold_score_type"]
                tube["smoothing_enabled"] = bool(spec["smoothing_enabled"])
                tube["persistence_enabled"] = bool(spec["persistence_enabled"])
                tube["eval_score"] = tube[score_col]
                tube["tubelet_pred"] = tube[pred_col].astype(int)

                clip = make_clip_scores(
                    tube,
                    score_col="eval_score",
                    pred_col="tubelet_pred",
                    components=k,
                    threshold_percentile=pct,
                    threshold=threshold,
                    mode=mode,
                )

                add_metric_row(
                    all_metrics,
                    df=tube,
                    clip_df=clip,
                    components=k,
                    mode=mode,
                    score_col="eval_score",
                    pred_col="tubelet_pred",
                    threshold=threshold,
                    threshold_percentile=pct,
                    threshold_score_type=spec["threshold_score_type"],
                    smoothing_enabled=bool(spec["smoothing_enabled"]),
                    persistence_enabled=bool(spec["persistence_enabled"]),
                    smoothing_sigma=smoothing_sigma,
                    persistence_window=persistence_window,
                    persistence_required_hits=persistence_required_hits,
                )

                all_clip.append(clip)

                keep_cols = [
                    "components", "threshold_percentile", "mode", "video_id", "video_path", "label",
                    "track_id", "tubelet_id", "start_time_sec", "end_time_sec",
                    "raw_score", "smoothed_score", "raw_threshold", "smooth_threshold",
                    "raw_hit", "smooth_hit", "raw_persistent_hit", "smooth_persistent_hit",
                    "threshold", "threshold_score_type", "smoothing_enabled", "persistence_enabled",
                    "eval_score", "tubelet_pred",
                ]
                keep_cols = [c for c in keep_cols if c in tube.columns]
                all_tubelet.append(tube[keep_cols])

    metrics_df = pd.DataFrame(all_metrics)
    clip_df = pd.concat(all_clip, ignore_index=True)
    tubelet_df = pd.concat(all_tubelet, ignore_index=True)
    thresholds_df = pd.DataFrame(threshold_rows)

    metrics_path = args.output_dir / "homography_full_modes_metrics.csv"
    clip_path = args.output_dir / "homography_full_modes_clip_scores.csv"
    tubelet_path = args.output_dir / "homography_full_modes_tubelet_scores.csv"
    thresholds_path = args.output_dir / "homography_full_modes_thresholds.csv"
    summary_path = args.output_dir / "homography_full_modes_summary.json"

    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    clip_df.to_csv(clip_path, index=False, encoding="utf-8-sig")
    tubelet_df.to_csv(tubelet_path, index=False, encoding="utf-8-sig")
    thresholds_df.to_csv(thresholds_path, index=False, encoding="utf-8-sig")

    summary = {
        "script": Path(__file__).name,
        "features_dir": str(args.features_dir),
        "normal_features_dir": str(normal_features_dir),
        "gate_dir": str(args.gate_dir),
        "selected_features": selected_features,
        "eval_shape": list(map(int, X_eval.shape)),
        "normal_shape": list(map(int, X_norm.shape)),
        "threshold_percentiles": threshold_percentiles,
        "threshold_design": {
            "raw_modes": "threshold from normal calibration raw scores",
            "smooth_modes": "threshold from normal calibration smoothed scores",
        },
        "smoothing_sigma": smoothing_sigma,
        "persistence_window": persistence_window,
        "persistence_required_hits": persistence_required_hits,
        "components_evaluated": sorted([int(k) for k in gmms.keys()]),
        "modes": [
            "raw_no_persistence",
            "smooth_no_persistence",
            "raw_with_persistence",
            "smooth_with_persistence",
        ],
        "outputs": {
            "metrics_csv": str(metrics_path),
            "clip_scores_csv": str(clip_path),
            "tubelet_scores_csv": str(tubelet_path),
            "thresholds_csv": str(thresholds_path),
            "summary_json": str(summary_path),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 104)
    print("DONE - Homography full modes")
    print("=" * 104)
    print(metrics_path)
    print()

    show_cols = [
        "components",
        "threshold_percentile",
        "mode",
        "threshold",
        "tubelet_auroc",
        "tubelet_auprc",
        "tubelet_precision",
        "tubelet_recall",
        "tubelet_f1",
        "clip_precision",
        "clip_recall",
        "clip_f1",
        "normal_clip_false_positive_rate",
    ]
    show_cols = [c for c in show_cols if c in metrics_df.columns]
    print(metrics_df[show_cols].sort_values(["threshold_percentile", "mode", "components"]).to_string(index=False))


if __name__ == "__main__":
    main()
