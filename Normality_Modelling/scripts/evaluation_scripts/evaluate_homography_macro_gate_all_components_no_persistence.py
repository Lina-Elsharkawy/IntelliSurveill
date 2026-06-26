#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
evaluate_homography_macro_gate_all_components_no_persistence.py

Evaluate all Homography/Macro GMM component models with NO persistence.

What it does
------------
- Loads anomaly/eval Homography features:
    homography_macro_features.npy
    homography_macro_metadata.csv
    homography_macro_feature_names.json

- Loads the trained RobustScaler and every:
    models/macro_gmm_components_*.joblib

- For each component count:
    1) recalibrates that component's threshold from the NORMAL calibration split
       using the same selected features and same scaler;
    2) evaluates anomaly_dataset clips/tubelets using:
       - raw scores, no persistence
       - smoothed scores, no persistence

Why recalibrate per component?
------------------------------
A GMM with 1 component and a GMM with 10 components do not share the same
score scale. Therefore the p99_7 threshold from components=5 must NOT be reused
for other components. This script recalculates p99_7 per component from the
original normal calibration videos.

Required folders
----------------
--features_dir:
  anomaly/eval features folder

--gate_dir:
  trained gate folder containing:
    09_recommended_macro_gate.json
    01_macro_gmm_training_summary.json
    models/macro_robust_scaler.joblib
    models/macro_gmm_components_*.joblib

--normal_features_dir:
  optional. If omitted, the script tries to read it from:
    gate_dir/01_macro_gmm_training_summary.json -> input_dir

Outputs
-------
  homography_all_components_no_persistence_metrics.csv
  homography_all_components_no_persistence_clip_scores.csv
  homography_all_components_no_persistence_tubelet_scores.csv
  homography_all_components_no_persistence_thresholds.csv
  homography_all_components_no_persistence_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate all Homography GMM components with no persistence.")
    p.add_argument("--features_dir", required=True, type=Path, help="Anomaly/eval Homography features dir.")
    p.add_argument("--gate_dir", required=True, type=Path, help="Trained Homography gate dir.")
    p.add_argument("--output_dir", required=True, type=Path)
    p.add_argument("--normal_features_dir", default=None, type=Path,
                   help="Normal Homography features dir used for original training. If omitted, read from training summary.")
    p.add_argument("--threshold_percentile", type=float, default=None,
                   help="Default uses recommended threshold_percentile/primary_threshold_percentile, usually 99.7.")
    p.add_argument("--smoothing_sigma", type=float, default=None,
                   help="Default uses recommended smoothing_sigma, usually 2.0.")
    p.add_argument("--components", type=int, nargs="*", default=None,
                   help="Optional subset, e.g. --components 1 2 3 5 8 10")
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
    X = np.load(folder / "homography_macro_features.npy")
    meta = pd.read_csv(folder / "homography_macro_metadata.csv", encoding="utf-8-sig")
    names = load_feature_names(folder / "homography_macro_feature_names.json")
    if X.ndim != 2:
        raise ValueError(f"Expected 2D feature matrix in {folder}, got {X.shape}")
    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata/features mismatch in {folder}: meta={len(meta)} X={X.shape[0]}")
    if len(names) != X.shape[1]:
        raise ValueError(f"Feature-name mismatch in {folder}: names={len(names)} X={X.shape[1]}")
    return X, meta, names


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
    f1 = safe_div(2 * precision * recall, precision + recall)
    return {
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "specificity": specificity,
        "fpr": fpr, "fnr": fnr, "accuracy": accuracy, "f1": f1,
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
    k /= k.sum()
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
            sm = vals
        else:
            pad = len(kernel) // 2
            sm = np.convolve(np.pad(vals, pad, mode="edge"), kernel, mode="valid")
        out.loc[idx, out_col] = sm
    return out


def infer_label(video_id: str, video_path: str) -> int:
    vid = str(video_id).strip().lower()
    path = str(video_path).replace("\\", "/").strip().lower()

    if vid.startswith("anomaly__"):
        return 1
    if vid.startswith("normal__"):
        return 0

    normal_markers = ["/dataset/normal/", "/normal/"]
    anomaly_markers = ["/dataset/anomaly/", "/anomaly/"]

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
        raise ValueError(f"Nonfinite/empty rows found after selecting features: dropped would be {int(np.sum(~keep))}. Clean upstream first.")
    return X_sel


def discover_gmms(gate_dir: Path, requested: Optional[list[int]]) -> dict[int, Path]:
    hits: dict[int, Path] = {}
    for p in sorted((gate_dir / "models").glob("macro_gmm_components_*.joblib")):
        m = re.search(r"components_(\d+)", p.name)
        if not m:
            continue
        k = int(m.group(1))
        if requested is None or k in requested:
            hits[k] = p
    if not hits:
        raise FileNotFoundError(f"No macro_gmm_components_*.joblib files found in {gate_dir / 'models'}")
    return hits


def make_clip_scores(df: pd.DataFrame, score_col: str, pred_col: str, component: int, mode: str) -> pd.DataFrame:
    rows = []
    for video_id, g in df.groupby("video_id", dropna=False):
        labels = sorted(set(g["label"].astype(int).tolist()))
        if len(labels) != 1:
            raise ValueError(f"Mixed labels in video_id={video_id}: {labels}")
        rows.append({
            "components": int(component),
            "mode": mode,
            "video_id": video_id,
            "video_path": str(g["video_path"].iloc[0]) if "video_path" in g.columns else "",
            "label": int(labels[0]),
            "clip_pred": int(g[pred_col].astype(int).sum() >= 1),
            "num_tubelets": int(len(g)),
            "num_alarm_tubelets": int(g[pred_col].astype(int).sum()),
            "max_score": float(g[score_col].astype(float).max()),
            "p95_score": float(np.percentile(g[score_col].astype(float), 95)),
            "mean_score": float(g[score_col].astype(float).mean()),
        })
    return pd.DataFrame(rows)


def add_metric_row(
    rows: list[dict[str, Any]],
    df: pd.DataFrame,
    clip_df: pd.DataFrame,
    *,
    component: int,
    mode: str,
    threshold: float,
    threshold_percentile: float,
    score_col: str,
    pred_col: str,
    smoothing_sigma: float,
) -> None:
    y = df["label"].astype(int).to_numpy()
    pred = df[pred_col].astype(int).to_numpy()
    scores = df[score_col].astype(float).to_numpy()
    bm = binary_metrics(y, pred)
    auc = auc_metrics(y, scores)
    cbm = binary_metrics(clip_df["label"].to_numpy(), clip_df["clip_pred"].to_numpy())

    rows.append({
        "components": int(component),
        "mode": mode,
        "persistence": "disabled",
        "threshold_percentile": float(threshold_percentile),
        "threshold": float(threshold),
        "smoothing_sigma": float(smoothing_sigma),

        "tubelet_count": int(len(df)),
        "tubelet_normal_count": int(np.sum(y == 0)),
        "tubelet_anomaly_count": int(np.sum(y == 1)),
        "tubelet_alarm_count": int(np.sum(pred)),
        "tubelet_auroc": auc["auroc"],
        "tubelet_auprc": auc["auprc"],
        "tubelet_average_precision": auc["average_precision"],
        "tubelet_tp": bm["tp"], "tubelet_tn": bm["tn"], "tubelet_fp": bm["fp"], "tubelet_fn": bm["fn"],
        "tubelet_precision": bm["precision"], "tubelet_recall": bm["recall"],
        "tubelet_specificity": bm["specificity"], "tubelet_fpr": bm["fpr"],
        "tubelet_accuracy": bm["accuracy"], "tubelet_f1": bm["f1"],

        "clip_count": int(len(clip_df)),
        "clip_normal_count": int(np.sum(clip_df["label"] == 0)),
        "clip_anomaly_count": int(np.sum(clip_df["label"] == 1)),
        "clip_alarm_count": int(np.sum(clip_df["clip_pred"])),
        "clip_tp": cbm["tp"], "clip_tn": cbm["tn"], "clip_fp": cbm["fp"], "clip_fn": cbm["fn"],
        "clip_precision": cbm["precision"], "clip_recall": cbm["recall"],
        "clip_specificity": cbm["specificity"], "clip_fpr": cbm["fpr"],
        "clip_accuracy": cbm["accuracy"], "clip_f1": cbm["f1"],
        "normal_clip_false_positive_rate": safe_div(cbm["fp"], cbm["fp"] + cbm["tn"]),
        "anomaly_clip_detection_rate": safe_div(cbm["tp"], cbm["tp"] + cbm["fn"]),
    })


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "homography_all_components_no_persistence_metrics.csv"
    if metrics_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists: {metrics_path}. Use --overwrite.")

    rec = read_json(args.gate_dir / "09_recommended_macro_gate.json")
    train_summary = read_json(args.gate_dir / "01_macro_gmm_training_summary.json")

    selected_features = rec.get("input_features") or rec.get("selected_features") or train_summary.get("selected_features")
    if not selected_features:
        raise KeyError("Could not find selected/input features in recommended gate or training summary.")
    selected_features = [str(x) for x in selected_features]

    threshold_percentile = float(
        args.threshold_percentile
        if args.threshold_percentile is not None
        else rec.get("threshold_percentile", train_summary.get("settings", {}).get("primary_threshold_percentile", 99.7))
    )
    smoothing_sigma = float(args.smoothing_sigma if args.smoothing_sigma is not None else rec.get("smoothing_sigma", 2.0))

    normal_features_dir = args.normal_features_dir
    if normal_features_dir is None:
        normal_input = train_summary.get("input_dir")
        if not normal_input:
            raise ValueError("Provide --normal_features_dir; could not infer it from 01_macro_gmm_training_summary.json")
        normal_features_dir = Path(str(normal_input))

    split = rec.get("split", {})
    cal_videos = [str(x) for x in split.get("calibration", [])]
    if not cal_videos:
        raise ValueError("No calibration video list found in 09_recommended_macro_gate.json. Cannot fairly threshold other components.")

    print("=" * 96)
    print("Homography all-components evaluation - NO PERSISTENCE")
    print("=" * 96)
    print(f"features_dir           = {args.features_dir}")
    print(f"normal_features_dir    = {normal_features_dir}")
    print(f"gate_dir               = {args.gate_dir}")
    print(f"selected_features      = {selected_features}")
    print(f"threshold_percentile   = {threshold_percentile}")
    print(f"smoothing_sigma        = {smoothing_sigma}")
    print("persistence            = disabled")
    print("=" * 96)

    X_eval, meta_eval, names_eval = load_features_dir(args.features_dir)
    X_norm, meta_norm, names_norm = load_features_dir(normal_features_dir)

    X_eval_sel = select_matrix(X_eval, names_eval, selected_features)
    X_norm_sel = select_matrix(X_norm, names_norm, selected_features)

    scaler_path = args.gate_dir / "models" / "macro_robust_scaler.joblib"
    if not scaler_path.exists():
        matches = list(args.gate_dir.rglob("*scaler*.joblib"))
        if not matches:
            raise FileNotFoundError(f"Could not find scaler under {args.gate_dir}")
        scaler_path = matches[0]
    scaler = joblib.load(scaler_path)

    X_eval_model = scaler.transform(X_eval_sel)
    X_norm_model = scaler.transform(X_norm_sel)

    # No PCA in your contract-fixed model, but support it safely if present.
    pca_path = args.gate_dir / "models" / "macro_pca.joblib"
    use_pca = bool(rec.get("use_pca", False))
    if use_pca and pca_path.exists():
        pca = joblib.load(pca_path)
        X_eval_model = pca.transform(X_eval_model)
        X_norm_model = pca.transform(X_norm_model)

    labels = []
    for _, row in meta_eval.iterrows():
        labels.append(infer_label(str(row.get("video_id", "")), str(row.get("video_path", ""))))
    meta_eval = meta_eval.copy()
    meta_eval["label"] = labels
    if "track_id" not in meta_eval.columns:
        meta_eval["track_id"] = 0
    if "tubelet_id" not in meta_eval.columns:
        meta_eval["tubelet_id"] = np.arange(len(meta_eval))
    if "start_time_sec" not in meta_eval.columns:
        meta_eval["start_time_sec"] = np.arange(len(meta_eval), dtype=float)

    if "video_id" not in meta_norm.columns:
        raise ValueError("Normal metadata has no video_id column.")
    cal_mask = meta_norm["video_id"].astype(str).isin(cal_videos).to_numpy()
    if not np.any(cal_mask):
        raise ValueError("Calibration split videos from recommended JSON were not found in normal metadata.")

    gmms = discover_gmms(args.gate_dir, args.components)

    all_metrics = []
    all_clip = []
    all_tubelet = []
    thresholds_rows = []

    for k, gmm_path in sorted(gmms.items()):
        gmm = joblib.load(gmm_path)

        norm_scores_raw = -gmm.score_samples(X_norm_model)
        norm_df = meta_norm.copy()
        norm_df["raw_score"] = norm_scores_raw
        norm_df = smooth_scores_per_track(norm_df, "raw_score", "smoothed_score", smoothing_sigma)
        cal_scores = norm_df.loc[cal_mask, "smoothed_score"].astype(float).to_numpy()
        threshold = float(np.percentile(cal_scores, threshold_percentile))

        eval_scores_raw = -gmm.score_samples(X_eval_model)
        df = meta_eval.copy()
        df["components"] = int(k)
        df["raw_score"] = eval_scores_raw.astype(float)
        df = smooth_scores_per_track(df, "raw_score", "smoothed_score", smoothing_sigma)
        df["raw_pred"] = (df["raw_score"].astype(float) > threshold).astype(int)
        df["smooth_pred"] = (df["smoothed_score"].astype(float) > threshold).astype(int)
        df["threshold"] = threshold
        df["threshold_percentile"] = threshold_percentile

        thresholds_rows.append({
            "components": int(k),
            "threshold_percentile": threshold_percentile,
            "threshold": threshold,
            "threshold_source": "normal_calibration_split_smoothed_scores",
            "calibration_tubelets": int(np.sum(cal_mask)),
            "gmm_path": str(gmm_path),
        })

        for mode, score_col, pred_col, sigma in [
            ("raw_no_persistence", "raw_score", "raw_pred", 0.0),
            ("smooth_no_persistence", "smoothed_score", "smooth_pred", smoothing_sigma),
        ]:
            tube = df.copy()
            tube["mode"] = mode
            tube["eval_score"] = tube[score_col]
            tube["tubelet_pred"] = tube[pred_col]
            clip = make_clip_scores(tube, "eval_score", "tubelet_pred", k, mode)

            add_metric_row(
                all_metrics,
                tube,
                clip,
                component=k,
                mode=mode,
                threshold=threshold,
                threshold_percentile=threshold_percentile,
                score_col="eval_score",
                pred_col="tubelet_pred",
                smoothing_sigma=sigma,
            )

            all_clip.append(clip)
            keep_cols = [c for c in [
                "components", "mode", "video_id", "video_path", "label", "track_id", "tubelet_id",
                "start_time_sec", "end_time_sec", "raw_score", "smoothed_score",
                "threshold", "raw_pred", "smooth_pred", "eval_score", "tubelet_pred"
            ] if c in tube.columns]
            all_tubelet.append(tube[keep_cols])

    metrics_df = pd.DataFrame(all_metrics)
    clip_df = pd.concat(all_clip, ignore_index=True)
    tubelet_df = pd.concat(all_tubelet, ignore_index=True)
    thresholds_df = pd.DataFrame(thresholds_rows)

    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    clip_df.to_csv(args.output_dir / "homography_all_components_no_persistence_clip_scores.csv", index=False, encoding="utf-8-sig")
    tubelet_df.to_csv(args.output_dir / "homography_all_components_no_persistence_tubelet_scores.csv", index=False, encoding="utf-8-sig")
    thresholds_df.to_csv(args.output_dir / "homography_all_components_no_persistence_thresholds.csv", index=False, encoding="utf-8-sig")

    summary = {
        "script": Path(__file__).name,
        "features_dir": str(args.features_dir),
        "normal_features_dir": str(normal_features_dir),
        "gate_dir": str(args.gate_dir),
        "selected_features": selected_features,
        "eval_shape": list(map(int, X_eval.shape)),
        "normal_shape": list(map(int, X_norm.shape)),
        "threshold_percentile": threshold_percentile,
        "threshold_source": "normal calibration split smoothed scores per component",
        "smoothing_sigma": smoothing_sigma,
        "persistence": "disabled",
        "components_evaluated": sorted([int(k) for k in gmms.keys()]),
        "outputs": {
            "metrics_csv": str(metrics_path),
            "clip_scores_csv": str(args.output_dir / "homography_all_components_no_persistence_clip_scores.csv"),
            "tubelet_scores_csv": str(args.output_dir / "homography_all_components_no_persistence_tubelet_scores.csv"),
            "thresholds_csv": str(args.output_dir / "homography_all_components_no_persistence_thresholds.csv"),
        },
    }
    (args.output_dir / "homography_all_components_no_persistence_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print()
    print("=" * 96)
    print("DONE - no persistence, all components")
    print("=" * 96)
    print(metrics_path)
    print()
    show_cols = [
        "components", "mode", "threshold",
        "tubelet_auroc", "tubelet_auprc", "tubelet_precision", "tubelet_recall", "tubelet_f1",
        "clip_precision", "clip_recall", "clip_f1", "normal_clip_false_positive_rate",
    ]
    print(metrics_df[show_cols].sort_values(["mode", "components"]).to_string(index=False))


if __name__ == "__main__":
    main()
