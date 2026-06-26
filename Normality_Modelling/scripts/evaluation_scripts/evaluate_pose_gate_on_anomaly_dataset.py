#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
evaluate_pose_gate_on_anomaly_dataset.py

Offline short-clip evaluation for the Pose/Micro GMM gate.

IMPORTANT DESIGN DECISION
-------------------------
Persistence is intentionally REMOVED from this offline anomaly-dataset evaluation.

Why?
- The dataset consists of short pre-segmented clips.
- Each clip is already labeled Normal or Anomaly.
- The fair clip-level question is:
      Did the Pose gate find any strong pose anomaly evidence inside the clip?
- Persistence is more appropriate for continuous live RTSP streams, not for short clip evaluation.

This script evaluates:
  1. Raw score threshold
  2. Smoothed score threshold

It does NOT evaluate:
  - 3/5 persistence
  - persistent rising-edge events

Official primary offline result:
  components = 5
  threshold = frozen normal-calibration p99.5
  postprocess = smooth

Inputs:
  D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_micro_features_5fps_24f_s6
    - pose_micro_features.npy
    - pose_micro_metadata.csv
    - pose_micro_feature_names.json

Models:
  D:\Embeddings_Distribution\normality_models\pose_gate\pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6\models
    - pose_robust_scaler.joblib
    - pose_gmm_components_1.joblib
    - pose_gmm_components_2.joblib
    - pose_gmm_components_3.joblib
    - pose_gmm_components_5.joblib
    - pose_gmm_components_8.joblib
    - pose_gmm_components_10.joblib

Outputs:
  D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_eval_no_persistence
    - pose_eval_tubelet_scores.csv
    - pose_eval_clip_scores.csv
    - pose_eval_metrics_by_config.csv
    - per_clip_score_summary.csv
    - threshold_sweep_diagnostic.csv
    - top_pose_scores.csv
    - pose_eval_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Frozen thresholds from normal-only calibration
# ---------------------------------------------------------------------

THRESHOLDS_BY_COMPONENTS = {
    1: 270.04709013829245,
    2: 118.34844039099255,
    3: 82.17522931844896,
    5: 70.18459395136654,   # PRIMARY / recommended
    8: 67.95033581957631,
    10: 69.77673772337575,
}

COMPONENTS_TO_EVALUATE = [1, 2, 3, 5, 8, 10]
PRIMARY_COMPONENTS = 5
PRIMARY_POSTPROCESS = "smooth"

DIAGNOSTIC_PERCENTILES = [90, 95, 97, 98, 99, 99.5]


# ---------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------

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
    except Exception as e:
        warnings.warn(f"Could not compute AUROC/AUPRC: {e}")
        return {"auroc": None, "auprc": None, "average_precision": None}


# ---------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------

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


def smooth_scores_per_track(
    df: pd.DataFrame,
    score_col: str,
    output_col: str,
    sigma: float,
) -> pd.DataFrame:
    out = sort_timeline(df.copy())
    out[output_col] = np.nan

    kernel = gaussian_kernel1d(sigma)
    group_cols = ["video_id", "track_id"]

    for _, idx in out.groupby(group_cols, dropna=False).groups.items():
        idx = list(idx)
        vals = out.loc[idx, score_col].astype(float).to_numpy()

        if len(vals) <= 1 or sigma <= 0:
            smoothed = vals
        else:
            pad = len(kernel) // 2
            padded = np.pad(vals, pad_width=pad, mode="edge")
            smoothed = np.convolve(padded, kernel, mode="valid")

        out.loc[idx, output_col] = smoothed

    return out


# ---------------------------------------------------------------------
# Labeling and cleaning
# ---------------------------------------------------------------------

def infer_label_from_path_or_id(video_path: str, video_id: str) -> int:
    """
    Safe label inference.

    Do NOT search for 'anomaly' anywhere in the full path, because the root
    folder itself is named anomaly_dataset.
    """
    vid = str(video_id).strip().lower()
    path = str(video_path).replace("\\", "/").strip().lower()

    if vid.startswith("anomaly__"):
        return 1
    if vid.startswith("normal__"):
        return 0

    if "/dataset/anomaly/" in path:
        return 1
    if "/dataset/normal/" in path:
        return 0

    raise ValueError(
        f"Could not infer label:\nvideo_id={video_id}\nvideo_path={video_path}"
    )


def clean_features(
    X: np.ndarray,
    meta: pd.DataFrame,
    feature_names: List[str],
) -> Tuple[np.ndarray, pd.DataFrame, Dict[str, int]]:
    X = np.asarray(X, dtype=np.float64)

    if X.ndim != 2:
        raise ValueError(f"Expected 2D feature matrix, got shape={X.shape}")

    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata/features mismatch: meta={len(meta)} X={X.shape[0]}")

    finite_mask = np.isfinite(X).all(axis=1)
    nonnegative_mask = (X >= 0).all(axis=1)
    all_zero_mask = np.all(np.isclose(X, 0.0), axis=1)

    if "pose_valid_frame_ratio" in feature_names:
        idx = feature_names.index("pose_valid_frame_ratio")
        pose_valid_zero_mask = X[:, idx] <= 0.0
    else:
        pose_valid_zero_mask = np.zeros(X.shape[0], dtype=bool)

    keep_mask = (
        finite_mask
        & nonnegative_mask
        & (~all_zero_mask)
        & (~pose_valid_zero_mask)
    )

    report = {
        "total_rows": int(X.shape[0]),
        "dropped_nonfinite": int(np.sum(~finite_mask)),
        "dropped_negative": int(np.sum(~nonnegative_mask)),
        "dropped_all_zero": int(np.sum(all_zero_mask)),
        "dropped_pose_valid_frame_ratio_zero": int(np.sum(pose_valid_zero_mask)),
        "kept_rows": int(np.sum(keep_mask)),
    }

    X_clean = X[keep_mask].astype(np.float32)
    meta_clean = meta.loc[keep_mask].copy().reset_index(drop=True)

    return X_clean, meta_clean, report


# ---------------------------------------------------------------------
# Clip aggregation and metric rows
# ---------------------------------------------------------------------

def build_clip_scores(
    tubelet_df: pd.DataFrame,
    config_id: str,
    score_col: str,
    pred_col: str,
) -> pd.DataFrame:
    rows = []

    for video_id, g in tubelet_df.groupby("video_id", dropna=False):
        label_values = sorted(set(g["label"].astype(int).tolist()))
        if len(label_values) != 1:
            raise ValueError(f"Mixed labels inside video_id={video_id}: {label_values}")

        label = int(label_values[0])
        video_path = str(g["video_path"].iloc[0]) if "video_path" in g.columns else ""
        num_tubelets = int(len(g))
        num_alarm_tubelets = int(g[pred_col].sum())
        scores = g[score_col].astype(float).to_numpy()

        duration_sec = None
        if "end_time_sec" in g.columns:
            duration_sec = float(pd.to_numeric(g["end_time_sec"], errors="coerce").max())

        rows.append({
            "config_id": config_id,
            "video_id": video_id,
            "video_path": video_path,
            "label": label,
            "clip_pred": int(num_alarm_tubelets >= 1),
            "num_tubelets": num_tubelets,
            "num_alarm_tubelets": num_alarm_tubelets,
            "max_score": float(np.max(scores)),
            "mean_score": float(np.mean(scores)),
            "p95_score": float(np.percentile(scores, 95)),
            "duration_sec": duration_sec,
        })

    return pd.DataFrame(rows)


def add_metric_row(
    metrics_rows: List[Dict[str, Any]],
    *,
    config_id: str,
    role: str,
    components: int,
    threshold: float,
    threshold_source: str,
    threshold_percentile: Optional[float],
    postprocess: str,
    cfg_df: pd.DataFrame,
    score_col: str,
    pred_col: str,
    smoothing_sigma: float,
) -> pd.DataFrame:
    y_true = cfg_df["label"].astype(int).to_numpy()
    y_pred = cfg_df[pred_col].astype(int).to_numpy()
    scores = cfg_df[score_col].astype(float).to_numpy()

    bm = binary_metrics(y_true, y_pred)
    auc = try_auc_metrics(y_true, scores)

    clip_df = build_clip_scores(
        cfg_df,
        config_id=config_id,
        score_col=score_col,
        pred_col=pred_col,
    )

    clip_bm = binary_metrics(
        clip_df["label"].astype(int).to_numpy(),
        clip_df["clip_pred"].astype(int).to_numpy(),
    )

    normal_clip_count = int(np.sum(clip_df["label"] == 0))
    anomaly_clip_count = int(np.sum(clip_df["label"] == 1))

    normal_clip_fp_rate = safe_div(
        int(np.sum((clip_df["label"] == 0) & (clip_df["clip_pred"] == 1))),
        normal_clip_count,
    )

    anomaly_clip_detection_rate = safe_div(
        int(np.sum((clip_df["label"] == 1) & (clip_df["clip_pred"] == 1))),
        anomaly_clip_count,
    )

    metrics_rows.append({
        "config_id": config_id,
        "role": role,
        "components": int(components),
        "threshold": float(threshold),
        "threshold_source": threshold_source,
        "threshold_percentile": threshold_percentile,
        "postprocess": postprocess,
        "smoothing_sigma": float(smoothing_sigma),
        "persistence": "disabled_for_offline_short_clip_evaluation",

        "tubelet_count": int(len(cfg_df)),
        "tubelet_normal_count": int(np.sum(y_true == 0)),
        "tubelet_anomaly_count": int(np.sum(y_true == 1)),
        "tubelet_alarm_count": int(np.sum(y_pred == 1)),

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
        "clip_alarm_count": int(np.sum(clip_df["clip_pred"] == 1)),

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

        "normal_clip_false_positive_rate": normal_clip_fp_rate,
        "anomaly_clip_detection_rate": anomaly_clip_detection_rate,
    })

    return clip_df


# ---------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------

def build_per_clip_score_summary(all_scores_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (components, video_id), g in all_scores_df.groupby(["components", "video_id"], dropna=False):
        label = int(g["label"].iloc[0])
        role = str(g["role"].iloc[0])
        threshold = float(g["threshold"].iloc[0])
        video_path = str(g["video_path"].iloc[0]) if "video_path" in g.columns else ""

        raw = g["raw_score"].astype(float).to_numpy()
        smooth = g["smoothed_score"].astype(float).to_numpy()

        track_count = int(g["track_id"].nunique()) if "track_id" in g.columns else None

        rows.append({
            "components": int(components),
            "role": role,
            "video_id": video_id,
            "video_path": video_path,
            "label": label,
            "threshold": threshold,
            "tubelet_count": int(len(g)),
            "track_count": track_count,

            "max_raw_score": float(np.max(raw)),
            "p95_raw_score": float(np.percentile(raw, 95)),
            "mean_raw_score": float(np.mean(raw)),
            "raw_threshold_crossings": int(np.sum(raw > threshold)),

            "max_smoothed_score": float(np.max(smooth)),
            "p95_smoothed_score": float(np.percentile(smooth, 95)),
            "mean_smoothed_score": float(np.mean(smooth)),
            "smooth_threshold_crossings": int(np.sum(smooth > threshold)),
        })

    return pd.DataFrame(rows).sort_values(
        ["components", "label", "max_smoothed_score"],
        ascending=[True, True, False],
    )


def build_top_pose_scores(all_scores_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    out = all_scores_df.copy()
    out["raw_above_threshold"] = (out["raw_score"] > out["threshold"]).astype(int)
    out["smooth_above_threshold"] = (out["smoothed_score"] > out["threshold"]).astype(int)

    cols = [
        "components", "role", "video_id", "video_path", "label", "track_id",
        "tubelet_id", "start_time_sec", "end_time_sec",
        "threshold", "raw_score", "smoothed_score",
        "raw_above_threshold", "smooth_above_threshold",
    ]
    available = [c for c in cols if c in out.columns]

    return out.sort_values("smoothed_score", ascending=False)[available].head(top_n)


def build_threshold_sweep(all_scores_df: pd.DataFrame) -> pd.DataFrame:
    """
    Diagnostic threshold sweep.

    Thresholds are estimated from the NORMAL subset of the evaluation data.
    This is diagnostic only and must not be presented as frozen final performance.
    """
    rows: List[Dict[str, Any]] = []

    for components, comp_df in all_scores_df.groupby("components", dropna=False):
        role = str(comp_df["role"].iloc[0])
        frozen_threshold = float(comp_df["threshold"].iloc[0])

        for score_col in ["raw_score", "smoothed_score"]:
            normal_scores = comp_df.loc[comp_df["label"] == 0, score_col].astype(float).to_numpy()
            if normal_scores.size == 0:
                continue

            thresholds_to_test: List[Tuple[str, Optional[float], float]] = [
                ("frozen_p99.5_normal_calibration", 99.5, frozen_threshold)
            ]

            for p in DIAGNOSTIC_PERCENTILES:
                thresholds_to_test.append((
                    f"diagnostic_eval_normal_p{p}",
                    float(p),
                    float(np.percentile(normal_scores, p)),
                ))

            for source, percentile, threshold in thresholds_to_test:
                df1 = comp_df.copy()
                df1["diag_pred"] = (df1[score_col].astype(float) > threshold).astype(int)

                clip_df = build_clip_scores(
                    df1,
                    config_id=f"diag_c{components}_{score_col}_{source}",
                    score_col=score_col,
                    pred_col="diag_pred",
                )

                tubelet_bm = binary_metrics(df1["label"].to_numpy(), df1["diag_pred"].to_numpy())
                clip_bm = binary_metrics(clip_df["label"].to_numpy(), clip_df["clip_pred"].to_numpy())

                rows.append({
                    "components": int(components),
                    "role": role,
                    "score_col": score_col,
                    "threshold_source": source,
                    "threshold_percentile": percentile,
                    "threshold": float(threshold),
                    "postprocess": "no_persistence",
                    "tubelet_precision": tubelet_bm["precision"],
                    "tubelet_recall": tubelet_bm["recall"],
                    "tubelet_f1": tubelet_bm["f1"],
                    "tubelet_fpr": tubelet_bm["fpr"],
                    "tubelet_alarm_count": int(df1["diag_pred"].sum()),
                    "clip_precision": clip_bm["precision"],
                    "clip_recall": clip_bm["recall"],
                    "clip_f1": clip_bm["f1"],
                    "clip_fpr": clip_bm["fpr"],
                    "clip_alarm_count": int(clip_df["clip_pred"].sum()),
                    "normal_clip_fp_rate": safe_div(clip_bm["fp"], clip_bm["fp"] + clip_bm["tn"]),
                    "anomaly_clip_detection_rate": safe_div(clip_bm["tp"], clip_bm["tp"] + clip_bm["fn"]),
                    "diagnostic_only": True,
                })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()

    p.add_argument(
        "--pose_features_dir",
        type=Path,
        default=Path(r"D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_micro_features_5fps_24f_s6"),
    )

    p.add_argument(
        "--model_dir",
        type=Path,
        default=Path(r"D:\Embeddings_Distribution\normality_models\pose_gate\pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6\models"),
    )

    p.add_argument(
        "--output_dir",
        type=Path,
        default=Path(r"D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_eval_no_persistence"),
    )

    p.add_argument("--smoothing_sigma", type=float, default=2.0)
    p.add_argument("--top_n_scores", type=int, default=200)
    p.add_argument("--overwrite", action="store_true")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    pose_features_dir = args.pose_features_dir
    model_dir = args.model_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    features_path = pose_features_dir / "pose_micro_features.npy"
    metadata_path = pose_features_dir / "pose_micro_metadata.csv"
    feature_names_path = pose_features_dir / "pose_micro_feature_names.json"
    scaler_path = model_dir / "pose_robust_scaler.joblib"

    out_tubelet_scores = output_dir / "pose_eval_tubelet_scores.csv"
    out_clip_scores = output_dir / "pose_eval_clip_scores.csv"
    out_metrics = output_dir / "pose_eval_metrics_by_config.csv"
    out_summary = output_dir / "pose_eval_summary.json"

    out_per_clip_summary = output_dir / "per_clip_score_summary.csv"
    out_threshold_sweep = output_dir / "threshold_sweep_diagnostic.csv"
    out_top_scores = output_dir / "top_pose_scores.csv"

    if out_metrics.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {out_metrics}. Use --overwrite.")

    print("=" * 80)
    print("Pose gate short-clip evaluation WITHOUT persistence")
    print("=" * 80)
    print(f"pose_features_dir = {pose_features_dir}")
    print(f"model_dir         = {model_dir}")
    print(f"output_dir        = {output_dir}")
    print(f"smoothing_sigma   = {args.smoothing_sigma}")
    print("persistence       = DISABLED")
    print("=" * 80)

    for path in [features_path, metadata_path, feature_names_path, scaler_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    X = np.load(features_path)
    meta = pd.read_csv(metadata_path, encoding="utf-8-sig")
    feature_names = json.loads(feature_names_path.read_text(encoding="utf-8"))

    if X.shape[1] != len(feature_names):
        raise ValueError(
            f"Feature count mismatch: X={X.shape[1]}, feature_names={len(feature_names)}"
        )

    X_clean, meta_clean, cleaning_report = clean_features(X, meta, feature_names)

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
        raise ValueError("pose_micro_metadata.csv must contain track_id.")
    if "video_id" not in meta_clean.columns:
        raise ValueError("pose_micro_metadata.csv must contain video_id.")

    label_counts = meta_clean["label"].value_counts().sort_index().to_dict()
    video_counts = meta_clean.groupby("label")["video_id"].nunique().sort_index().to_dict()

    print("Cleaning report:")
    for k, v in cleaning_report.items():
        print(f"  {k}: {v}")
    print(f"Tubelet label counts: {label_counts}")
    print(f"Video label counts:   {video_counts}")

    scaler = joblib.load(scaler_path)
    X_scaled = scaler.transform(X_clean)

    all_tubelet_frames = []
    all_clip_frames = []
    all_scores_frames = []
    metrics_rows: List[Dict[str, Any]] = []

    for components in COMPONENTS_TO_EVALUATE:
        role = "primary" if components == PRIMARY_COMPONENTS else "comparison"
        threshold = float(THRESHOLDS_BY_COMPONENTS[components])

        gmm_path = model_dir / f"pose_gmm_components_{components}.joblib"
        if not gmm_path.exists():
            raise FileNotFoundError(gmm_path)

        print()
        print("-" * 80)
        print(f"Evaluating components={components} | role={role} | threshold={threshold:.6f}")
        print("-" * 80)

        gmm = joblib.load(gmm_path)
        raw_scores = -gmm.score_samples(X_scaled)

        base_df = meta_clean.copy()
        base_df["components"] = int(components)
        base_df["role"] = role
        base_df["threshold"] = threshold
        base_df["raw_score"] = raw_scores.astype(float)
        base_df = sort_timeline(base_df)

        scored_df = smooth_scores_per_track(
            base_df,
            score_col="raw_score",
            output_col="smoothed_score",
            sigma=float(args.smoothing_sigma),
        )

        scored_df["raw_above_threshold"] = (scored_df["raw_score"] > threshold).astype(int)
        scored_df["smooth_above_threshold"] = (scored_df["smoothed_score"] > threshold).astype(int)

        all_scores_frames.append(scored_df.copy())

        # Raw evaluation
        raw_df = scored_df.copy()
        raw_df["config_id"] = f"pose_c{components}_p995_raw"
        raw_df["postprocess"] = "raw"
        raw_df["eval_score"] = raw_df["raw_score"]
        raw_df["tubelet_pred"] = raw_df["raw_above_threshold"]

        # Smoothed evaluation
        smooth_df = scored_df.copy()
        smooth_df["config_id"] = f"pose_c{components}_p995_smooth"
        smooth_df["postprocess"] = "smooth"
        smooth_df["eval_score"] = smooth_df["smoothed_score"]
        smooth_df["tubelet_pred"] = smooth_df["smooth_above_threshold"]

        for cfg_df, postprocess in [
            (raw_df, "raw"),
            (smooth_df, "smooth"),
        ]:
            config_id = str(cfg_df["config_id"].iloc[0])

            clip_df = add_metric_row(
                metrics_rows,
                config_id=config_id,
                role=role,
                components=components,
                threshold=threshold,
                threshold_source="frozen_normal_calibration_p99.5",
                threshold_percentile=99.5,
                postprocess=postprocess,
                cfg_df=cfg_df,
                score_col="eval_score",
                pred_col="tubelet_pred",
                smoothing_sigma=args.smoothing_sigma if postprocess == "smooth" else 0.0,
            )

            clip_df["components"] = int(components)
            clip_df["role"] = role
            clip_df["threshold"] = threshold
            clip_df["postprocess"] = postprocess
            clip_df["persistence"] = "disabled_for_offline_short_clip_evaluation"

            all_tubelet_frames.append(cfg_df.copy())
            all_clip_frames.append(clip_df.copy())

            last = metrics_rows[-1]
            print(
                f"{config_id}: "
                f"AUROC={last['tubelet_auroc']} | "
                f"AUPRC={last['tubelet_auprc']} | "
                f"tubelet F1={last['tubelet_f1']:.4f} | "
                f"clip recall={last['clip_recall']:.4f} | "
                f"normal clip FP={last['normal_clip_false_positive_rate']:.4f}"
            )

    tubelet_scores_df = pd.concat(all_tubelet_frames, ignore_index=True)
    clip_scores_df = pd.concat(all_clip_frames, ignore_index=True)
    metrics_df = pd.DataFrame(metrics_rows)
    all_scores_df = pd.concat(all_scores_frames, ignore_index=True)

    post_order = {"raw": 0, "smooth": 1}
    comp_order = {c: i for i, c in enumerate(COMPONENTS_TO_EVALUATE)}
    metrics_df["_post_order"] = metrics_df["postprocess"].map(post_order).fillna(99)
    metrics_df["_comp_order"] = metrics_df["components"].map(comp_order).fillna(99)
    metrics_df = metrics_df.sort_values(["_comp_order", "_post_order"]).drop(
        columns=["_comp_order", "_post_order"]
    )

    per_clip_summary_df = build_per_clip_score_summary(all_scores_df)
    top_scores_df = build_top_pose_scores(all_scores_df, top_n=int(args.top_n_scores))
    sweep_df = build_threshold_sweep(all_scores_df)

    tubelet_scores_df.to_csv(out_tubelet_scores, index=False, encoding="utf-8-sig")
    clip_scores_df.to_csv(out_clip_scores, index=False, encoding="utf-8-sig")
    metrics_df.to_csv(out_metrics, index=False, encoding="utf-8-sig")
    per_clip_summary_df.to_csv(out_per_clip_summary, index=False, encoding="utf-8-sig")
    top_scores_df.to_csv(out_top_scores, index=False, encoding="utf-8-sig")
    sweep_df.to_csv(out_threshold_sweep, index=False, encoding="utf-8-sig")

    primary_config_id = f"pose_c{PRIMARY_COMPONENTS}_p995_{PRIMARY_POSTPROCESS}"
    primary_row = metrics_df[metrics_df["config_id"] == primary_config_id]

    summary = {
        "script": "evaluate_pose_gate_on_anomaly_dataset.py",
        "purpose": "offline short-clip pose evaluation without persistence",
        "pose_features_dir": str(pose_features_dir),
        "model_dir": str(model_dir),
        "output_dir": str(output_dir),
        "feature_shape_raw": list(map(int, X.shape)),
        "feature_shape_clean": list(map(int, X_clean.shape)),
        "cleaning_report": cleaning_report,
        "label_counts_tubelets_clean": {str(k): int(v) for k, v in label_counts.items()},
        "video_counts_clean": {str(k): int(v) for k, v in video_counts.items()},
        "components_evaluated": COMPONENTS_TO_EVALUATE,
        "primary_components": PRIMARY_COMPONENTS,
        "primary_config_id": primary_config_id,
        "thresholds_by_components": {str(k): float(v) for k, v in THRESHOLDS_BY_COMPONENTS.items()},
        "score_definition": "negative GMM log likelihood; higher = more abnormal",
        "official_postprocessing": {
            "raw": "threshold applied directly to tubelet score",
            "smooth": f"Gaussian smoothing per video_id+track_id with sigma={float(args.smoothing_sigma)}",
            "persistence": "disabled_for_offline_short_clip_evaluation",
            "reason": (
                "The anomaly dataset consists of short labeled clips. "
                "Clip-level detection is defined as at least one threshold crossing inside the clip. "
                "Persistence is reserved for continuous live RTSP deployment."
            ),
        },
        "official_outputs": {
            "tubelet_scores_csv": str(out_tubelet_scores),
            "clip_scores_csv": str(out_clip_scores),
            "metrics_by_config_csv": str(out_metrics),
            "summary_json": str(out_summary),
        },
        "diagnostic_outputs": {
            "per_clip_score_summary_csv": str(out_per_clip_summary),
            "threshold_sweep_diagnostic_csv": str(out_threshold_sweep),
            "top_pose_scores_csv": str(out_top_scores),
        },
        "primary_result": primary_row.iloc[0].to_dict() if len(primary_row) == 1 else None,
        "important_interpretation": (
            "This evaluation intentionally removes persistence because clips are short and pre-segmented. "
            "The primary offline result is components=5 with frozen p99.5 threshold and smoothed scores. "
            "Threshold-sweep outputs are diagnostic only and should not be reported as frozen final performance."
        ),
    }

    out_summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print("=" * 80)
    print("DONE")
    print("=" * 80)
    print("Outputs:")
    print(f"  Metrics:          {out_metrics}")
    print(f"  Tubelet scores:   {out_tubelet_scores}")
    print(f"  Clip scores:      {out_clip_scores}")
    print(f"  Per-clip summary: {out_per_clip_summary}")
    print(f"  Threshold sweep:  {out_threshold_sweep}")
    print(f"  Top pose scores:  {out_top_scores}")
    print(f"  Summary:          {out_summary}")

    if len(primary_row) == 1:
        pr = primary_row.iloc[0]
        print()
        print("PRIMARY OFFLINE RESULT WITHOUT PERSISTENCE")
        print("------------------------------------------")
        print(f"config_id:             {primary_config_id}")
        print(f"tubelet AUROC:         {pr['tubelet_auroc']}")
        print(f"tubelet AUPRC:         {pr['tubelet_auprc']}")
        print(f"tubelet precision:     {pr['tubelet_precision']:.4f}")
        print(f"tubelet recall:        {pr['tubelet_recall']:.4f}")
        print(f"tubelet F1:            {pr['tubelet_f1']:.4f}")
        print(f"clip precision:        {pr['clip_precision']:.4f}")
        print(f"clip recall:           {pr['clip_recall']:.4f}")
        print(f"clip F1:               {pr['clip_f1']:.4f}")
        print(f"normal clip FP rate:   {pr['normal_clip_false_positive_rate']:.4f}")


if __name__ == "__main__":
    main()