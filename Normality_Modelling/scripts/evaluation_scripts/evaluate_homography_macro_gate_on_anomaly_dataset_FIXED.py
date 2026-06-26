#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
evaluate_homography_macro_gate_on_anomaly_dataset.py

Offline short-clip evaluation for the Homography/Macro GMM gate.

Purpose
-------
Evaluate an existing trained homography macro-motion GMM gate, such as:

  D:\Embeddings_Distribution\normality_models\homography_gate\homography_gate_stage3_pose_contract_fixed\homography_macro_gmm_gate_p997

against anomaly-dataset homography macro features.

Inputs
------
features_dir must contain:
  homography_macro_features.npy
  homography_macro_metadata.csv
  homography_macro_feature_names.json

gate_dir must contain:
  09_recommended_macro_gate.json
  04_macro_thresholds.json
  models/macro_robust_scaler.joblib
  models/macro_gmm_components_5.joblib

Design
------
- Loads selected/input features from 09_recommended_macro_gate.json.
- Selects exactly those columns from the feature matrix.
- Applies the trained RobustScaler + GMM.
- Score = negative GMM log likelihood; higher = more anomalous.
- Evaluates raw and Gaussian-smoothed scores per video_id + track_id.
- Clip-level detection = at least one threshold crossing in the clip.
- Persistence is not the primary offline metric because clips are pre-segmented,
  but a diagnostic persistence simulation is included.

Outputs
-------
  homography_eval_tubelet_scores.csv
  homography_eval_clip_scores.csv
  homography_eval_metrics.csv
  homography_per_clip_score_summary.csv
  homography_threshold_sweep_diagnostic.csv
  homography_top_scores.csv
  homography_eval_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate Homography/Macro GMM gate on anomaly dataset features.")

    p.add_argument("--features_dir", required=True, type=Path)
    p.add_argument("--gate_dir", required=True, type=Path)
    p.add_argument("--output_dir", required=True, type=Path)

    p.add_argument("--recommended_json", default="09_recommended_macro_gate.json")
    p.add_argument("--thresholds_json", default="04_macro_thresholds.json")

    p.add_argument("--components", type=int, default=None, help="Override components. Default uses recommended primary_components.")
    p.add_argument("--threshold_key", default=None, help="Override threshold key, e.g. p99_7. Default uses recommended/threshold JSON primary key.")
    p.add_argument("--threshold_value", type=float, default=None, help="Override threshold value directly.")

    p.add_argument("--smoothing_sigma", type=float, default=None, help="Default uses recommended smoothing_sigma or 2.0.")
    p.add_argument("--persistence_window", type=int, default=None, help="Default uses recommended or 5.")
    p.add_argument("--persistence_required_hits", type=int, default=None, help="Default uses recommended or 3.")

    p.add_argument("--top_n_scores", type=int, default=200)
    p.add_argument("--overwrite", action="store_true")

    return p.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def safe_div(num: float, den: float) -> float:
    return float(num / den) if den else 0.0


def binary_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
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


def try_auc_metrics(y_true: np.ndarray, scores: np.ndarray) -> Dict[str, Optional[float]]:
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


def gaussian_kernel1d(sigma: float, radius: Optional[int] = None) -> np.ndarray:
    sigma = float(sigma)
    if sigma <= 0:
        return np.array([1.0], dtype=np.float64)
    if radius is None:
        radius = int(math.ceil(3.0 * sigma))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x ** 2) / (2.0 * sigma ** 2))
    k /= np.sum(k)
    return k


def sort_timeline(df: pd.DataFrame) -> pd.DataFrame:
    sort_cols = ["video_id", "track_id", "start_time_sec", "tubelet_id"]
    available = [c for c in sort_cols if c in df.columns]
    if available:
        return df.sort_values(available).reset_index(drop=True)
    return df.reset_index(drop=True)


def smooth_scores_per_track(df: pd.DataFrame, score_col: str, out_col: str, sigma: float) -> pd.DataFrame:
    out = sort_timeline(df.copy())
    out[out_col] = np.nan
    kernel = gaussian_kernel1d(sigma)
    group_cols = ["video_id", "track_id"] if "track_id" in out.columns else ["video_id"]

    for _, idx in out.groupby(group_cols, dropna=False).groups.items():
        idx = list(idx)
        vals = out.loc[idx, score_col].astype(float).to_numpy()
        if len(vals) <= 1 or sigma <= 0:
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
        persisted = []
        recent: list[int] = []
        for h in hits:
            recent.append(int(h))
            if len(recent) > int(window):
                recent.pop(0)
            persisted.append(int(sum(recent) >= int(required_hits)))
        out.loc[idx, out_col] = persisted

    return out


def infer_label_from_path_or_id(video_path: str, video_id: str) -> int:
    vid = str(video_id).strip().lower()
    path = str(video_path).replace("\\", "/").strip().lower()

    if vid.startswith("anomaly__"):
        return 1
    if vid.startswith("normal__"):
        return 0

    # Avoid checking for "anomaly_dataset" root alone.
    anomaly_markers = [
        "/dataset/anomaly/",
        "/anomaly_dataset/dataset/anomaly/",
        "/anomaly/",
        "\\anomaly\\",
    ]
    normal_markers = [
        "/dataset/normal/",
        "/anomaly_dataset/dataset/normal/",
        "/normal/",
        "\\normal\\",
    ]

    if any(m in path for m in anomaly_markers):
        return 1
    if any(m in path for m in normal_markers):
        return 0

    raise ValueError(f"Could not infer label from video_id={video_id!r}, video_path={video_path!r}")


def find_model_path(gate_dir: Path, preferred: Any, include: list[str], exclude: list[str] | None = None) -> Path:
    exclude = exclude or []

    if preferred:
        p = Path(str(preferred))
        if p.exists():
            return p
        # Windows absolute path may not exist in another environment; search by basename.
        for cand in gate_dir.rglob(p.name):
            if cand.is_file():
                return cand

    hits = []
    for cand in gate_dir.rglob("*.joblib"):
        name = cand.name.lower()
        if all(x.lower() in name for x in include) and not any(x.lower() in name for x in exclude):
            hits.append(cand)

    if hits:
        return sorted(hits, key=lambda x: len(str(x)))[0]

    raise FileNotFoundError(f"Could not find model artifact in {gate_dir}. include={include} exclude={exclude}")


def resolve_threshold(rec: dict[str, Any], thresholds_json: dict[str, Any], args: argparse.Namespace) -> Tuple[str, float, float]:
    if args.threshold_value is not None:
        key = args.threshold_key or "manual"
        return key, float(args.threshold_value), float("nan")

    key = args.threshold_key
    if not key:
        key = str(
            thresholds_json.get("primary_threshold_key")
            or rec.get("primary_threshold_key")
            or rec.get("threshold_key")
            or "p99_7"
        )

    thresholds = thresholds_json.get("thresholds", {}) if isinstance(thresholds_json, dict) else {}
    if key in thresholds and isinstance(thresholds[key], dict):
        return key, float(thresholds[key]["threshold"]), float(thresholds[key].get("percentile", float("nan")))

    if "threshold" in rec:
        return key, float(rec["threshold"]), float(rec.get("threshold_percentile", float("nan")))

    if "primary_threshold" in thresholds_json:
        return key, float(thresholds_json["primary_threshold"]), float(thresholds_json.get("primary_threshold_percentile", float("nan")))

    raise KeyError(f"Could not resolve threshold key={key!r}")


def clean_features(X: np.ndarray, meta: pd.DataFrame, selected_indices: list[int]) -> Tuple[np.ndarray, pd.DataFrame, Dict[str, int]]:
    X = np.asarray(X, dtype=np.float64)
    finite = np.isfinite(X).all(axis=1)
    selected = X[:, selected_indices]
    selected_finite = np.isfinite(selected).all(axis=1)
    nonnegative_selected = (selected >= 0).all(axis=1)
    nonzero_selected = np.abs(selected).sum(axis=1) > 0

    keep = finite & selected_finite & nonnegative_selected & nonzero_selected

    report = {
        "total_rows": int(X.shape[0]),
        "dropped_nonfinite_any_feature": int(np.sum(~finite)),
        "dropped_nonfinite_selected": int(np.sum(~selected_finite)),
        "dropped_negative_selected": int(np.sum(~nonnegative_selected)),
        "dropped_all_zero_selected": int(np.sum(~nonzero_selected)),
        "kept_rows": int(np.sum(keep)),
    }

    return X[keep], meta.loc[keep].copy().reset_index(drop=True), report


def build_clip_scores(df: pd.DataFrame, config_id: str, score_col: str, pred_col: str) -> pd.DataFrame:
    rows = []
    for video_id, g in df.groupby("video_id", dropna=False):
        labels = sorted(set(g["label"].astype(int).tolist()))
        if len(labels) != 1:
            raise ValueError(f"Mixed labels inside video_id={video_id}: {labels}")
        scores = g[score_col].astype(float).to_numpy()
        video_path = str(g["video_path"].iloc[0]) if "video_path" in g.columns else ""
        duration_sec = None
        if "end_time_sec" in g.columns:
            duration_sec = float(pd.to_numeric(g["end_time_sec"], errors="coerce").max())

        rows.append({
            "config_id": config_id,
            "video_id": video_id,
            "video_path": video_path,
            "label": int(labels[0]),
            "clip_pred": int(g[pred_col].astype(int).sum() >= 1),
            "num_tubelets": int(len(g)),
            "num_alarm_tubelets": int(g[pred_col].astype(int).sum()),
            "max_score": float(np.max(scores)),
            "mean_score": float(np.mean(scores)),
            "p95_score": float(np.percentile(scores, 95)),
            "duration_sec": duration_sec,
        })
    return pd.DataFrame(rows)


def add_metric_row(
    rows: list[dict[str, Any]],
    *,
    config_id: str,
    role: str,
    threshold_key: str,
    threshold: float,
    threshold_percentile: float,
    postprocess: str,
    df: pd.DataFrame,
    score_col: str,
    pred_col: str,
    smoothing_sigma: float,
    persistence: str,
) -> pd.DataFrame:
    y = df["label"].astype(int).to_numpy()
    pred = df[pred_col].astype(int).to_numpy()
    scores = df[score_col].astype(float).to_numpy()

    bm = binary_metrics(y, pred)
    auc = try_auc_metrics(y, scores)
    clip_df = build_clip_scores(df, config_id, score_col, pred_col)

    clip_bm = binary_metrics(clip_df["label"].to_numpy(), clip_df["clip_pred"].to_numpy())
    normal_clip_count = int(np.sum(clip_df["label"] == 0))
    anomaly_clip_count = int(np.sum(clip_df["label"] == 1))

    rows.append({
        "config_id": config_id,
        "role": role,
        "threshold_key": threshold_key,
        "threshold": float(threshold),
        "threshold_percentile": None if not np.isfinite(threshold_percentile) else float(threshold_percentile),
        "postprocess": postprocess,
        "smoothing_sigma": float(smoothing_sigma),
        "persistence": persistence,

        "tubelet_count": int(len(df)),
        "tubelet_normal_count": int(np.sum(y == 0)),
        "tubelet_anomaly_count": int(np.sum(y == 1)),
        "tubelet_alarm_count": int(np.sum(pred)),

        "tubelet_auroc": auc["auroc"],
        "tubelet_auprc": auc["auprc"],
        "tubelet_average_precision": auc["average_precision"],

        "tubelet_tp": bm["tp"],
        "tubelet_tn": bm["tn"],
        "tubelet_fp": bm["fp"],
        "tubelet_fn": bm["fn"],
        "tubelet_precision": bm["precision"],
        "tubelet_recall": bm["recall"],
        "tubelet_specificity": bm["specificity"],
        "tubelet_fpr": bm["fpr"],
        "tubelet_fnr": bm["fnr"],
        "tubelet_accuracy": bm["accuracy"],
        "tubelet_f1": bm["f1"],

        "clip_count": int(len(clip_df)),
        "clip_normal_count": normal_clip_count,
        "clip_anomaly_count": anomaly_clip_count,
        "clip_alarm_count": int(np.sum(clip_df["clip_pred"])),

        "clip_tp": clip_bm["tp"],
        "clip_tn": clip_bm["tn"],
        "clip_fp": clip_bm["fp"],
        "clip_fn": clip_bm["fn"],
        "clip_precision": clip_bm["precision"],
        "clip_recall": clip_bm["recall"],
        "clip_specificity": clip_bm["specificity"],
        "clip_fpr": clip_bm["fpr"],
        "clip_fnr": clip_bm["fnr"],
        "clip_accuracy": clip_bm["accuracy"],
        "clip_f1": clip_bm["f1"],
        "normal_clip_false_positive_rate": safe_div(clip_bm["fp"], clip_bm["fp"] + clip_bm["tn"]),
        "anomaly_clip_detection_rate": safe_div(clip_bm["tp"], clip_bm["tp"] + clip_bm["fn"]),
    })

    return clip_df


def build_per_clip_summary(all_scores_df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    rows = []
    for video_id, g in all_scores_df.groupby("video_id", dropna=False):
        label = int(g["label"].iloc[0])
        video_path = str(g["video_path"].iloc[0]) if "video_path" in g.columns else ""
        raw = g["raw_score"].astype(float).to_numpy()
        sm = g["smoothed_score"].astype(float).to_numpy()
        rows.append({
            "video_id": video_id,
            "video_path": video_path,
            "label": label,
            "threshold": float(threshold),
            "tubelet_count": int(len(g)),
            "track_count": int(g["track_id"].nunique()) if "track_id" in g.columns else None,
            "max_raw_score": float(np.max(raw)),
            "p95_raw_score": float(np.percentile(raw, 95)),
            "mean_raw_score": float(np.mean(raw)),
            "raw_threshold_crossings": int(np.sum(raw > threshold)),
            "max_smoothed_score": float(np.max(sm)),
            "p95_smoothed_score": float(np.percentile(sm, 95)),
            "mean_smoothed_score": float(np.mean(sm)),
            "smooth_threshold_crossings": int(np.sum(sm > threshold)),
        })
    return pd.DataFrame(rows).sort_values(["label", "max_smoothed_score"], ascending=[True, False])


def build_threshold_sweep(all_scores_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    percentiles = [90, 95, 97, 98, 99, 99.5, 99.7, 99.9]

    for score_col in ["raw_score", "smoothed_score"]:
        normal_scores = all_scores_df.loc[all_scores_df["label"] == 0, score_col].astype(float).to_numpy()
        if normal_scores.size == 0:
            continue

        for p in percentiles:
            thr = float(np.percentile(normal_scores, p))
            df = all_scores_df.copy()
            df["diag_pred"] = (df[score_col].astype(float) > thr).astype(int)
            clip_df = build_clip_scores(df, f"diag_{score_col}_eval_normal_p{p}", score_col, "diag_pred")

            tbm = binary_metrics(df["label"].to_numpy(), df["diag_pred"].to_numpy())
            cbm = binary_metrics(clip_df["label"].to_numpy(), clip_df["clip_pred"].to_numpy())

            rows.append({
                "score_col": score_col,
                "threshold_source": f"diagnostic_eval_normal_p{p}",
                "threshold_percentile": float(p),
                "threshold": thr,
                "tubelet_precision": tbm["precision"],
                "tubelet_recall": tbm["recall"],
                "tubelet_f1": tbm["f1"],
                "tubelet_fpr": tbm["fpr"],
                "tubelet_alarm_count": int(df["diag_pred"].sum()),
                "clip_precision": cbm["precision"],
                "clip_recall": cbm["recall"],
                "clip_f1": cbm["f1"],
                "clip_fpr": cbm["fpr"],
                "clip_alarm_count": int(clip_df["clip_pred"].sum()),
                "diagnostic_only": True,
            })

    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    out_tubelet_scores = args.output_dir / "homography_eval_tubelet_scores.csv"
    out_clip_scores = args.output_dir / "homography_eval_clip_scores.csv"
    out_metrics = args.output_dir / "homography_eval_metrics.csv"
    out_per_clip = args.output_dir / "homography_per_clip_score_summary.csv"
    out_sweep = args.output_dir / "homography_threshold_sweep_diagnostic.csv"
    out_top = args.output_dir / "homography_top_scores.csv"
    out_summary = args.output_dir / "homography_eval_summary.json"

    if out_metrics.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {out_metrics}. Use --overwrite.")

    features_path = args.features_dir / "homography_macro_features.npy"
    metadata_path = args.features_dir / "homography_macro_metadata.csv"
    feature_names_path = args.features_dir / "homography_macro_feature_names.json"

    rec_path = args.gate_dir / args.recommended_json
    thresholds_path = args.gate_dir / args.thresholds_json

    for p in [features_path, metadata_path, feature_names_path, rec_path]:
        if not p.exists():
            raise FileNotFoundError(p)

    rec = read_json(rec_path)
    thresholds_json = read_json(thresholds_path)

    selected_features = rec.get("input_features") or rec.get("selected_features")
    if not selected_features:
        raise KeyError("Could not find input_features/selected_features in recommended JSON.")
    selected_features = [str(x) for x in selected_features]

    components = int(args.components or rec.get("primary_components", 5))
    threshold_key, threshold, threshold_percentile = resolve_threshold(rec, thresholds_json, args)

    smoothing_sigma = float(args.smoothing_sigma if args.smoothing_sigma is not None else rec.get("smoothing_sigma", 2.0))
    persistence_window = int(args.persistence_window if args.persistence_window is not None else rec.get("persistence_window", 5))
    persistence_required_hits = int(args.persistence_required_hits if args.persistence_required_hits is not None else rec.get("persistence_required_hits", 3))

    artifacts = rec.get("artifacts", {}) if isinstance(rec.get("artifacts"), dict) else {}
    model_paths = rec.get("model_paths", {}) if isinstance(rec.get("model_paths"), dict) else {}

    scaler_preferred = artifacts.get("scaler") or model_paths.get("scaler")
    gmm_preferred = artifacts.get("gmm") or model_paths.get("gmm")
    pca_preferred = artifacts.get("pca") or model_paths.get("pca")

    scaler_path = find_model_path(args.gate_dir, scaler_preferred, include=["scaler"])
    gmm_path = find_model_path(args.gate_dir, gmm_preferred, include=["gmm"], exclude=["pca"])

    pca_path = None
    use_pca = bool(rec.get("use_pca", False))
    if use_pca:
        pca_path = find_model_path(args.gate_dir, pca_preferred, include=["pca"])

    print("=" * 88)
    print("Homography/Macro gate anomaly evaluation")
    print("=" * 88)
    print(f"features_dir       = {args.features_dir}")
    print(f"gate_dir           = {args.gate_dir}")
    print(f"selected_features  = {selected_features}")
    print(f"components         = {components}")
    print(f"threshold          = {threshold_key} = {threshold}")
    print(f"smoothing_sigma    = {smoothing_sigma}")
    print(f"persistence        = {persistence_required_hits}/{persistence_window} diagnostic")
    print(f"scaler             = {scaler_path}")
    print(f"gmm                = {gmm_path}")
    print("=" * 88)

    X = np.load(features_path)
    meta = pd.read_csv(metadata_path, encoding="utf-8-sig")
    feature_names_obj = json.loads(feature_names_path.read_text(encoding="utf-8"))
    if isinstance(feature_names_obj, dict):
        if "feature_names" not in feature_names_obj:
            raise KeyError(f"Feature names JSON is an object but has no 'feature_names' key: {feature_names_path}")
        feature_names = feature_names_obj["feature_names"]
    else:
        feature_names = feature_names_obj
    feature_names = [str(x) for x in feature_names]

    if X.ndim != 2:
        raise ValueError(f"Expected 2D feature matrix, got {X.shape}")
    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata/features mismatch: meta={len(meta)} X={X.shape[0]}")
    if len(feature_names) != X.shape[1]:
        raise ValueError(f"Feature name count mismatch: names={len(feature_names)} X columns={X.shape[1]}")

    missing = [f for f in selected_features if f not in feature_names]
    if missing:
        raise ValueError(f"Selected features missing from feature_names: {missing}")

    selected_indices = [feature_names.index(f) for f in selected_features]
    X_clean, meta_clean, cleaning_report = clean_features(X, meta, selected_indices)

    labels = []
    for _, row in meta_clean.iterrows():
        labels.append(
            infer_label_from_path_or_id(
                video_path=str(row.get("video_path", "")),
                video_id=str(row.get("video_id", "")),
            )
        )
    meta_clean["label"] = labels

    if "track_id" not in meta_clean.columns:
        meta_clean["track_id"] = 0
    if "tubelet_id" not in meta_clean.columns:
        meta_clean["tubelet_id"] = np.arange(len(meta_clean))
    if "start_time_sec" not in meta_clean.columns:
        meta_clean["start_time_sec"] = np.arange(len(meta_clean), dtype=float)
    if "end_time_sec" not in meta_clean.columns:
        meta_clean["end_time_sec"] = meta_clean["start_time_sec"]

    X_sel = X_clean[:, selected_indices].astype(np.float64)

    scaler = joblib.load(scaler_path)
    X_scaled = scaler.transform(X_sel)

    if use_pca:
        pca = joblib.load(pca_path)
        X_model = pca.transform(X_scaled)
    else:
        X_model = X_scaled

    gmm = joblib.load(gmm_path)
    raw_scores = -gmm.score_samples(X_model)

    base_df = meta_clean.copy()
    base_df["components"] = components
    base_df["threshold_key"] = threshold_key
    base_df["threshold"] = float(threshold)
    base_df["raw_score"] = raw_scores.astype(float)
    base_df = sort_timeline(base_df)

    scored = smooth_scores_per_track(base_df, "raw_score", "smoothed_score", smoothing_sigma)
    scored["raw_above_threshold"] = (scored["raw_score"].astype(float) > threshold).astype(int)
    scored["smooth_above_threshold"] = (scored["smoothed_score"].astype(float) > threshold).astype(int)
    scored = add_persistence_per_track(
        scored,
        hit_col="smooth_above_threshold",
        out_col="persistent_above_threshold",
        window=persistence_window,
        required_hits=persistence_required_hits,
    )

    metrics_rows: list[dict[str, Any]] = []
    clip_frames = []
    tubelet_frames = []

    configs = [
        ("homography_macro_raw_no_persistence", "official_comparison", "raw", "raw_score", "raw_above_threshold", "disabled_for_short_clip_eval"),
        ("homography_macro_smooth_no_persistence", "primary_offline", "smooth", "smoothed_score", "smooth_above_threshold", "disabled_for_short_clip_eval"),
        ("homography_macro_smooth_with_persistence_diag", "diagnostic_live_like", "smooth", "smoothed_score", "persistent_above_threshold", f"{persistence_required_hits}/{persistence_window}"),
    ]

    for config_id, role, postprocess, score_col, pred_col, persistence_desc in configs:
        cfg_df = scored.copy()
        cfg_df["config_id"] = config_id
        cfg_df["postprocess"] = postprocess
        cfg_df["eval_score"] = cfg_df[score_col]
        cfg_df["tubelet_pred"] = cfg_df[pred_col].astype(int)

        clip_df = add_metric_row(
            metrics_rows,
            config_id=config_id,
            role=role,
            threshold_key=threshold_key,
            threshold=threshold,
            threshold_percentile=threshold_percentile,
            postprocess=postprocess,
            df=cfg_df,
            score_col="eval_score",
            pred_col="tubelet_pred",
            smoothing_sigma=smoothing_sigma if postprocess == "smooth" else 0.0,
            persistence=persistence_desc,
        )
        clip_df["postprocess"] = postprocess
        clip_df["threshold_key"] = threshold_key
        clip_df["threshold"] = threshold
        clip_df["persistence"] = persistence_desc

        clip_frames.append(clip_df)
        tubelet_frames.append(cfg_df)

    tubelet_scores_df = pd.concat(tubelet_frames, ignore_index=True)
    clip_scores_df = pd.concat(clip_frames, ignore_index=True)
    metrics_df = pd.DataFrame(metrics_rows)
    per_clip_df = build_per_clip_summary(scored, threshold)
    sweep_df = build_threshold_sweep(scored)

    top_cols = [
        "video_id", "video_path", "label", "track_id", "tubelet_id",
        "start_time_sec", "end_time_sec", "threshold",
        "raw_score", "smoothed_score", "raw_above_threshold",
        "smooth_above_threshold", "persistent_above_threshold",
    ]
    top_cols = [c for c in top_cols if c in scored.columns]
    top_df = scored.sort_values("smoothed_score", ascending=False)[top_cols].head(int(args.top_n_scores))

    tubelet_scores_df.to_csv(out_tubelet_scores, index=False, encoding="utf-8-sig")
    clip_scores_df.to_csv(out_clip_scores, index=False, encoding="utf-8-sig")
    metrics_df.to_csv(out_metrics, index=False, encoding="utf-8-sig")
    per_clip_df.to_csv(out_per_clip, index=False, encoding="utf-8-sig")
    sweep_df.to_csv(out_sweep, index=False, encoding="utf-8-sig")
    top_df.to_csv(out_top, index=False, encoding="utf-8-sig")

    primary = metrics_df[metrics_df["config_id"] == "homography_macro_smooth_no_persistence"]
    primary_result = primary.iloc[0].to_dict() if len(primary) == 1 else None

    label_counts = meta_clean["label"].value_counts().sort_index().to_dict()
    video_counts = meta_clean.groupby("label")["video_id"].nunique().sort_index().to_dict()

    summary = {
        "script": Path(__file__).name,
        "purpose": "offline short-clip homography macro gate evaluation",
        "features_dir": str(args.features_dir),
        "gate_dir": str(args.gate_dir),
        "recommended_json": str(rec_path),
        "thresholds_json": str(thresholds_path),
        "feature_shape_raw": list(map(int, X.shape)),
        "feature_shape_clean": list(map(int, X_clean.shape)),
        "all_feature_dim": int(X.shape[1]),
        "selected_feature_dim": int(len(selected_features)),
        "selected_features": selected_features,
        "cleaning_report": cleaning_report,
        "label_counts_tubelets_clean": {str(k): int(v) for k, v in label_counts.items()},
        "video_counts_clean": {str(k): int(v) for k, v in video_counts.items()},
        "model": {
            "components": components,
            "scaler_path": str(scaler_path),
            "pca_path": str(pca_path) if pca_path else None,
            "gmm_path": str(gmm_path),
            "use_pca": bool(use_pca),
        },
        "threshold": {
            "key": threshold_key,
            "value": float(threshold),
            "percentile": None if not np.isfinite(threshold_percentile) else float(threshold_percentile),
            "score_direction": "higher_is_more_anomalous",
        },
        "postprocessing": {
            "smoothing_sigma": float(smoothing_sigma),
            "primary_offline": "smoothed threshold crossing; persistence disabled for short-clip evaluation",
            "diagnostic_live_like": f"{persistence_required_hits}/{persistence_window} persistence on smoothed hits",
        },
        "primary_result": primary_result,
        "outputs": {
            "tubelet_scores_csv": str(out_tubelet_scores),
            "clip_scores_csv": str(out_clip_scores),
            "metrics_csv": str(out_metrics),
            "per_clip_summary_csv": str(out_per_clip),
            "threshold_sweep_diagnostic_csv": str(out_sweep),
            "top_scores_csv": str(out_top),
            "summary_json": str(out_summary),
        },
    }

    out_summary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 88)
    print("DONE")
    print("=" * 88)
    print(f"Metrics: {out_metrics}")
    print(f"Summary: {out_summary}")

    if primary_result:
        print()
        print("PRIMARY OFFLINE RESULT: homography_macro_smooth_no_persistence")
        print("-------------------------------------------------------------")
        print(f"tubelet AUROC:       {primary_result['tubelet_auroc']}")
        print(f"tubelet AUPRC:       {primary_result['tubelet_auprc']}")
        print(f"tubelet precision:   {primary_result['tubelet_precision']:.4f}")
        print(f"tubelet recall:      {primary_result['tubelet_recall']:.4f}")
        print(f"tubelet F1:          {primary_result['tubelet_f1']:.4f}")
        print(f"clip precision:      {primary_result['clip_precision']:.4f}")
        print(f"clip recall:         {primary_result['clip_recall']:.4f}")
        print(f"clip F1:             {primary_result['clip_f1']:.4f}")
        print(f"normal clip FP rate: {primary_result['normal_clip_false_positive_rate']:.4f}")


if __name__ == "__main__":
    main()
