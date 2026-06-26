#!/usr/bin/env python3
r"""
04h_plot_and_evaluate_pose_gmm_gate.py

Post-training plots and evaluation for the pose micro-motion GMM gate.

Works with the output folder produced by:
  04g_build_pose_micro_gmm_gate.py

Default expected folder:
  D:\Embeddings_Distribution\normality_models\pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6

What it creates:
  plots/*.png
  reports/pose_score_distribution_stats.csv
  reports/pose_false_alarm_by_video.csv
  reports/pose_false_alarm_by_track.csv
  reports/pose_threshold_operating_points.csv
  reports/pose_component_comparison.csv
  reports/pose_evaluation_summary.json

Important:
  - AUROC / AUPRC require real labels with both normal and abnormal samples.
  - With normal-only calibration/test scores, the script reports false-alarm and stability metrics only.

Optional labelled evaluation:
  Provide a CSV with a score column and label column:
    --labeled_scores_csv path\to\labeled_pose_scores.csv --label_col is_abnormal

The labelled CSV must contain:
  - label column: 0 normal, 1 abnormal
  - score column: default pose_score or pose_score_smooth
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt

try:
    from sklearn.metrics import (
        roc_auc_score,
        average_precision_score,
        precision_recall_fscore_support,
        confusion_matrix,
        balanced_accuracy_score,
        roc_curve,
        precision_recall_curve,
    )
except Exception:
    roc_auc_score = None
    average_precision_score = None
    precision_recall_fscore_support = None
    confusion_matrix = None
    balanced_accuracy_score = None
    roc_curve = None
    precision_recall_curve = None

try:
    from scipy.stats import ks_2samp
except Exception:
    ks_2samp = None


DEFAULT_GATE_DIR = r"D:\Embeddings_Distribution\normality_models\pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6"


def parse_args():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--gate_dir",
        default=DEFAULT_GATE_DIR,
        help="Output folder from 04g_build_pose_micro_gmm_gate.py",
    )
    ap.add_argument(
        "--out_dir",
        default=None,
        help="Optional output folder. Default: <gate_dir>/plots_eval",
    )
    ap.add_argument(
        "--score_col",
        default="pose_score",
        help="Score column for raw score plots/evaluation. Usually pose_score.",
    )
    ap.add_argument(
        "--smooth_score_col",
        default="pose_score_smooth",
        help="Smoothed score column. Usually pose_score_smooth.",
    )
    ap.add_argument(
        "--threshold_json",
        default="04_pose_thresholds.json",
        help="Threshold JSON inside gate_dir.",
    )
    ap.add_argument(
        "--top_k",
        type=int,
        default=50,
        help="How many top abnormal normal-test tubelets to plot.",
    )
    ap.add_argument(
        "--threshold_grid_percentiles",
        default="95,97,98,99,99.5,99.7,99.9",
        help="Calibration percentiles used to simulate operating points.",
    )

    # Optional true supervised metrics, only if labelled data exists.
    ap.add_argument("--labeled_scores_csv", default=None)
    ap.add_argument("--label_col", default="is_abnormal")
    ap.add_argument("--labeled_score_col", default=None)
    ap.add_argument("--positive_label", type=int, default=1)

    return ap.parse_args()


def read_json(path: Path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_dirs(out_dir: Path):
    plots_dir = out_dir / "plots"
    reports_dir = out_dir / "reports"
    plots_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    return plots_dir, reports_dir


def safe_read_csv(path: Path):
    if not path.exists():
        return None
    return pd.read_csv(path)


def get_threshold(gate_dir: Path, threshold_json_name: str):
    payload = read_json(gate_dir / threshold_json_name)
    threshold = payload.get("primary_threshold", None)
    primary_components = payload.get("primary_components", None)
    temporal_config = payload.get("pose_temporal_config", {})
    return threshold, primary_components, payload, temporal_config


def numeric_stats(values):
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {
            "count": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "p50": np.nan,
            "p90": np.nan,
            "p95": np.nan,
            "p99": np.nan,
            "p995": np.nan,
            "max": np.nan,
        }
    return {
        "count": int(arr.size),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "p995": float(np.percentile(arr, 99.5)),
        "max": float(np.max(arr)),
    }


def longest_true_streak(flags):
    best = 0
    cur = 0
    for f in flags:
        if bool(f):
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)


def plot_score_hist(calib_df, test_df, score_col, threshold, plots_dir: Path):
    plt.figure(figsize=(12, 7))
    if calib_df is not None and score_col in calib_df.columns:
        plt.hist(calib_df[score_col].dropna(), bins=80, alpha=0.55, density=True, label="Calibration")
    if test_df is not None and score_col in test_df.columns:
        plt.hist(test_df[score_col].dropna(), bins=80, alpha=0.55, density=True, label="Normal-test")
    if threshold is not None:
        plt.axvline(float(threshold), linestyle="--", linewidth=2, label=f"Threshold = {threshold:.3f}")
    plt.title("Pose GMM score distribution")
    plt.xlabel("Pose score (negative GMM log likelihood; higher = more abnormal)")
    plt.ylabel("Density")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "01_pose_score_hist_calib_vs_normal_test.png", dpi=180)
    plt.close()


def plot_smoothed_hist(test_df, score_col, smooth_col, threshold, plots_dir: Path):
    if test_df is None or score_col not in test_df.columns or smooth_col not in test_df.columns:
        return
    plt.figure(figsize=(12, 7))
    plt.hist(test_df[score_col].dropna(), bins=80, alpha=0.55, density=True, label="Raw pose score")
    plt.hist(test_df[smooth_col].dropna(), bins=80, alpha=0.55, density=True, label="Smoothed pose score")
    if threshold is not None:
        plt.axvline(float(threshold), linestyle="--", linewidth=2, label=f"Threshold = {threshold:.3f}")
    plt.title("Normal-test raw vs smoothed pose scores")
    plt.xlabel("Pose score")
    plt.ylabel("Density")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "02_raw_vs_smoothed_normal_test_hist.png", dpi=180)
    plt.close()


def plot_component_comparison(model_selection, plots_dir: Path):
    if model_selection is None or model_selection.empty:
        return
    if "components" not in model_selection.columns:
        return

    cols = [
        "normal_test_false_alarm_rate_before_persistence",
        "normal_test_false_alarm_rate_after_persistence",
        "normal_test_false_alarm_events_after_persistence",
    ]
    existing = [c for c in cols if c in model_selection.columns]
    if not existing:
        return

    for col in existing:
        plt.figure(figsize=(10, 6))
        plt.plot(model_selection["components"], model_selection[col], marker="o")
        plt.title(f"GMM components vs {col}")
        plt.xlabel("GMM components")
        plt.ylabel(col)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        safe_col = col.replace("/", "_")
        plt.savefig(plots_dir / f"03_components_vs_{safe_col}.png", dpi=180)
        plt.close()

    if "bic_train" in model_selection.columns and "aic_train" in model_selection.columns:
        plt.figure(figsize=(10, 6))
        plt.plot(model_selection["components"], model_selection["bic_train"], marker="o", label="BIC")
        plt.plot(model_selection["components"], model_selection["aic_train"], marker="o", label="AIC")
        plt.title("GMM component selection: BIC / AIC")
        plt.xlabel("GMM components")
        plt.ylabel("Information criterion")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(plots_dir / "04_components_vs_bic_aic.png", dpi=180)
        plt.close()


def plot_false_alarm_stages(test_df, plots_dir: Path):
    if test_df is None or test_df.empty:
        return
    cols = ["pose_hit_raw", "pose_hit_smooth", "pose_persistent_hit"]
    if not all(c in test_df.columns for c in cols):
        return
    counts = [int(test_df[c].sum()) for c in cols]
    labels = ["Raw", "Smoothed", "Persistent"]

    plt.figure(figsize=(9, 6))
    plt.bar(labels, counts)
    plt.title("Normal-test false alarms by post-processing stage")
    plt.ylabel("False-alarm tubelets")
    for i, v in enumerate(counts):
        plt.text(i, v, str(v), ha="center", va="bottom")
    plt.tight_layout()
    plt.savefig(plots_dir / "05_false_alarm_stages.png", dpi=180)
    plt.close()


def plot_top_abnormal(test_df, score_col, top_k, plots_dir: Path):
    if test_df is None or score_col not in test_df.columns or test_df.empty:
        return
    top = test_df.sort_values(score_col, ascending=False).head(top_k).copy()
    if top.empty:
        return
    labels = []
    for _, r in top.iterrows():
        vid = str(r.get("video_id", "video"))
        t = r.get("start_time_sec", np.nan)
        if pd.notna(t):
            labels.append(f"{vid}\n{float(t):.1f}s")
        else:
            labels.append(vid)

    plt.figure(figsize=(max(12, top_k * 0.35), 7))
    plt.bar(np.arange(len(top)), top[score_col].to_numpy(dtype=float))
    plt.xticks(np.arange(len(top)), labels, rotation=90, fontsize=8)
    plt.title(f"Top {len(top)} normal-test pose outliers")
    plt.ylabel(score_col)
    plt.tight_layout()
    plt.savefig(plots_dir / "06_top_normal_test_pose_outliers.png", dpi=180)
    plt.close()


def plot_feature_distributions(test_df, plots_dir: Path):
    if test_df is None or test_df.empty:
        return
    feature_cols = [
        "pose_valid_frame_ratio",
        "pose_mean_keypoint_conf",
        "pose_wrist_speed_p95",
        "pose_limb_speed_p95",
        "pose_limb_accel_p95",
        "pose_body_angle_change_p95",
        "pose_crouch_change_p95",
        "pose_arm_extension_change_p95",
        "pose_asymmetry_motion_p95",
    ]
    existing = [c for c in feature_cols if c in test_df.columns]
    for col in existing:
        vals = pd.to_numeric(test_df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        plt.figure(figsize=(10, 6))
        plt.hist(vals, bins=80)
        plt.title(f"Normal-test feature distribution: {col}")
        plt.xlabel(col)
        plt.ylabel("Count")
        plt.tight_layout()
        plt.savefig(plots_dir / f"07_feature_distribution_{col}.png", dpi=180)
        plt.close()


def plot_score_timeline_by_video(test_df, score_col, smooth_col, threshold, plots_dir: Path, max_videos=12):
    if test_df is None or test_df.empty or "video_id" not in test_df.columns:
        return
    if "start_time_sec" not in test_df.columns:
        return

    # Plot the videos with the highest max score first.
    order = (
        test_df.groupby("video_id")[score_col]
        .max()
        .sort_values(ascending=False)
        .head(max_videos)
        .index
        .tolist()
    )

    for vid in order:
        sub = test_df[test_df["video_id"].astype(str) == str(vid)].copy()
        sub = sub.sort_values("start_time_sec")
        if sub.empty:
            continue

        plt.figure(figsize=(12, 6))
        plt.plot(sub["start_time_sec"], sub[score_col], marker=".", linewidth=1, label="Raw")
        if smooth_col in sub.columns:
            plt.plot(sub["start_time_sec"], sub[smooth_col], linewidth=2, label="Smoothed")
        if threshold is not None:
            plt.axhline(float(threshold), linestyle="--", linewidth=2, label=f"Threshold = {threshold:.3f}")
        plt.title(f"Pose score timeline - {vid}")
        plt.xlabel("Time (seconds)")
        plt.ylabel("Pose score")
        plt.legend()
        plt.tight_layout()
        safe_vid = str(vid).replace("/", "_").replace("\\", "_").replace(":", "_")
        plt.savefig(plots_dir / f"08_score_timeline_{safe_vid}.png", dpi=180)
        plt.close()


def distribution_and_false_alarm_reports(calib_df, test_df, threshold, score_col, smooth_col, reports_dir: Path):
    rows = []
    for name, df in [("calibration", calib_df), ("normal_test", test_df)]:
        if df is None or score_col not in df.columns:
            continue
        stats = numeric_stats(df[score_col])
        stats["split"] = name
        if threshold is not None:
            stats["threshold"] = float(threshold)
            stats["raw_hits"] = int((pd.to_numeric(df[score_col], errors="coerce") > float(threshold)).sum())
            stats["raw_hit_rate"] = float((pd.to_numeric(df[score_col], errors="coerce") > float(threshold)).mean())
        rows.append(stats)

    dist_df = pd.DataFrame(rows)
    if not dist_df.empty:
        cols = ["split"] + [c for c in dist_df.columns if c != "split"]
        dist_df = dist_df[cols]
        dist_df.to_csv(reports_dir / "pose_score_distribution_stats.csv", index=False, encoding="utf-8-sig")

    if test_df is not None and not test_df.empty:
        by_video_rows = []
        for vid, sub in test_df.groupby("video_id", sort=False):
            raw_flags = sub.get("pose_hit_raw", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
            smooth_flags = sub.get("pose_hit_smooth", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
            persist_flags = sub.get("pose_persistent_hit", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
            duration = np.nan
            if "start_time_sec" in sub.columns and "end_time_sec" in sub.columns:
                duration = float(pd.to_numeric(sub["end_time_sec"], errors="coerce").max() - pd.to_numeric(sub["start_time_sec"], errors="coerce").min())
            by_video_rows.append({
                "video_id": vid,
                "tubelets": int(len(sub)),
                "duration_sec_approx": duration,
                "max_score": float(pd.to_numeric(sub[score_col], errors="coerce").max()),
                "raw_hits": int(raw_flags.sum()),
                "raw_hit_rate": float(raw_flags.mean()) if len(raw_flags) else 0.0,
                "smooth_hits": int(smooth_flags.sum()),
                "smooth_hit_rate": float(smooth_flags.mean()) if len(smooth_flags) else 0.0,
                "persistent_hits": int(persist_flags.sum()),
                "persistent_hit_rate": float(persist_flags.mean()) if len(persist_flags) else 0.0,
                "max_raw_hit_streak": longest_true_streak(raw_flags),
                "max_smooth_hit_streak": longest_true_streak(smooth_flags),
                "max_persistent_hit_streak": longest_true_streak(persist_flags),
            })
        pd.DataFrame(by_video_rows).sort_values("max_score", ascending=False).to_csv(
            reports_dir / "pose_false_alarm_by_video.csv", index=False, encoding="utf-8-sig"
        )

        if "track_id" in test_df.columns:
            by_track_rows = []
            for (vid, tid), sub in test_df.groupby(["video_id", "track_id"], sort=False):
                raw_flags = sub.get("pose_hit_raw", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
                smooth_flags = sub.get("pose_hit_smooth", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
                persist_flags = sub.get("pose_persistent_hit", pd.Series(False, index=sub.index)).astype(bool).to_numpy()
                by_track_rows.append({
                    "video_id": vid,
                    "track_id": tid,
                    "tubelets": int(len(sub)),
                    "max_score": float(pd.to_numeric(sub[score_col], errors="coerce").max()),
                    "raw_hits": int(raw_flags.sum()),
                    "smooth_hits": int(smooth_flags.sum()),
                    "persistent_hits": int(persist_flags.sum()),
                    "max_raw_hit_streak": longest_true_streak(raw_flags),
                    "max_smooth_hit_streak": longest_true_streak(smooth_flags),
                    "max_persistent_hit_streak": longest_true_streak(persist_flags),
                })
            pd.DataFrame(by_track_rows).sort_values("max_score", ascending=False).to_csv(
                reports_dir / "pose_false_alarm_by_track.csv", index=False, encoding="utf-8-sig"
            )

    # Calibration-vs-test drift / distribution similarity.
    drift = {}
    if calib_df is not None and test_df is not None and score_col in calib_df.columns and score_col in test_df.columns:
        a = pd.to_numeric(calib_df[score_col], errors="coerce").dropna().to_numpy(dtype=float)
        b = pd.to_numeric(test_df[score_col], errors="coerce").dropna().to_numpy(dtype=float)
        if len(a) and len(b):
            drift["calib_mean"] = float(np.mean(a))
            drift["normal_test_mean"] = float(np.mean(b))
            drift["mean_shift"] = float(np.mean(b) - np.mean(a))
            drift["calib_p995"] = float(np.percentile(a, 99.5))
            drift["normal_test_p995"] = float(np.percentile(b, 99.5))
            drift["p995_shift"] = float(np.percentile(b, 99.5) - np.percentile(a, 99.5))
            if ks_2samp is not None:
                ks = ks_2samp(a, b)
                drift["ks_statistic"] = float(ks.statistic)
                drift["ks_pvalue"] = float(ks.pvalue)

    return dist_df if 'dist_df' in locals() else pd.DataFrame(), drift


def threshold_operating_points(calib_df, test_df, percentiles, score_col, reports_dir: Path):
    if calib_df is None or test_df is None or score_col not in calib_df.columns or score_col not in test_df.columns:
        return pd.DataFrame()
    calib_scores = pd.to_numeric(calib_df[score_col], errors="coerce").dropna().to_numpy(dtype=float)
    if calib_scores.size == 0:
        return pd.DataFrame()

    rows = []
    test_scores = pd.to_numeric(test_df[score_col], errors="coerce")
    for p in percentiles:
        thr = float(np.percentile(calib_scores, p))
        raw_hits = test_scores > thr
        row = {
            "calibration_percentile": float(p),
            "threshold": thr,
            "normal_test_raw_hits": int(raw_hits.sum()),
            "normal_test_raw_hit_rate": float(raw_hits.mean()) if len(raw_hits) else 0.0,
        }
        if "pose_score_smooth" in test_df.columns:
            smooth_hits = pd.to_numeric(test_df["pose_score_smooth"], errors="coerce") > thr
            row["normal_test_smooth_hits"] = int(smooth_hits.sum())
            row["normal_test_smooth_hit_rate"] = float(smooth_hits.mean()) if len(smooth_hits) else 0.0
        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_csv(reports_dir / "pose_threshold_operating_points.csv", index=False, encoding="utf-8-sig")
    return out


def supervised_labelled_evaluation(args, threshold, plots_dir: Path, reports_dir: Path):
    if not args.labeled_scores_csv:
        return {
            "available": False,
            "reason": "No --labeled_scores_csv provided. AUROC/AUPRC require labelled normal and abnormal examples.",
        }

    if roc_auc_score is None:
        return {
            "available": False,
            "reason": "scikit-learn metrics could not be imported.",
        }

    path = Path(args.labeled_scores_csv)
    if not path.exists():
        return {
            "available": False,
            "reason": f"Labelled score CSV not found: {path}",
        }

    df = pd.read_csv(path)
    score_col = args.labeled_score_col or args.score_col
    if score_col not in df.columns:
        return {"available": False, "reason": f"Score column not found in labelled CSV: {score_col}"}
    if args.label_col not in df.columns:
        return {"available": False, "reason": f"Label column not found in labelled CSV: {args.label_col}"}

    y = (pd.to_numeric(df[args.label_col], errors="coerce") == args.positive_label).astype(int).to_numpy()
    s = pd.to_numeric(df[score_col], errors="coerce").to_numpy(dtype=float)
    mask = np.isfinite(s) & np.isfinite(y)
    y = y[mask]
    s = s[mask]

    unique = sorted(set(y.tolist()))
    if unique != [0, 1]:
        return {
            "available": False,
            "reason": f"AUROC/AUPRC require both normal label 0 and abnormal label 1. Found labels: {unique}",
            "samples": int(len(y)),
        }

    auroc = float(roc_auc_score(y, s))
    auprc = float(average_precision_score(y, s))

    if threshold is None:
        threshold = float(np.percentile(s[y == 0], 99.5))

    pred = (s > float(threshold)).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    bal_acc = float(balanced_accuracy_score(y, pred))

    # Curves.
    fpr, tpr, _ = roc_curve(y, s)
    pr, rc, _ = precision_recall_curve(y, s)

    plt.figure(figsize=(7, 7))
    plt.plot(fpr, tpr, linewidth=2, label=f"AUROC = {auroc:.4f}")
    plt.plot([0, 1], [0, 1], linestyle="--", linewidth=1)
    plt.title("ROC curve - labelled pose evaluation")
    plt.xlabel("False positive rate")
    plt.ylabel("True positive rate")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "09_labelled_roc_curve.png", dpi=180)
    plt.close()

    plt.figure(figsize=(7, 7))
    plt.plot(rc, pr, linewidth=2, label=f"AUPRC = {auprc:.4f}")
    plt.title("Precision-recall curve - labelled pose evaluation")
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots_dir / "10_labelled_precision_recall_curve.png", dpi=180)
    plt.close()

    metrics = {
        "available": True,
        "labelled_csv": str(path),
        "score_col": score_col,
        "label_col": args.label_col,
        "samples": int(len(y)),
        "normal_samples": int((y == 0).sum()),
        "abnormal_samples": int((y == 1).sum()),
        "threshold_used": float(threshold),
        "auroc": auroc,
        "auprc_average_precision": auprc,
        "precision_at_threshold": float(precision),
        "recall_tpr_at_threshold": float(recall),
        "specificity_tnr_at_threshold": float(specificity),
        "f1_at_threshold": float(f1),
        "balanced_accuracy_at_threshold": bal_acc,
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
    }

    pd.DataFrame([metrics]).to_csv(reports_dir / "pose_labelled_supervised_metrics.csv", index=False, encoding="utf-8-sig")
    return metrics


def main():
    args = parse_args()

    gate_dir = Path(args.gate_dir)
    out_dir = Path(args.out_dir) if args.out_dir else gate_dir / "plots_eval"
    plots_dir, reports_dir = ensure_dirs(out_dir)

    scores_dir = gate_dir / "scores"

    calib_df = safe_read_csv(scores_dir / "calibration_pose_scores.csv")
    test_df = safe_read_csv(scores_dir / "normal_test_pose_scores.csv")
    events_df = safe_read_csv(scores_dir / "normal_test_pose_events.csv")
    model_selection = safe_read_csv(gate_dir / "pose_gmm_model_selection.csv")
    false_alarm_report = safe_read_csv(gate_dir / "05_pose_false_alarm_report.csv")

    threshold, primary_components, threshold_payload, temporal_config = get_threshold(gate_dir, args.threshold_json)

    if threshold is None:
        raise ValueError(f"Could not find primary_threshold in {gate_dir / args.threshold_json}")

    if calib_df is None:
        raise FileNotFoundError(scores_dir / "calibration_pose_scores.csv")
    if test_df is None:
        raise FileNotFoundError(scores_dir / "normal_test_pose_scores.csv")

    # Plots.
    plot_score_hist(calib_df, test_df, args.score_col, threshold, plots_dir)
    plot_smoothed_hist(test_df, args.score_col, args.smooth_score_col, threshold, plots_dir)
    plot_component_comparison(model_selection, plots_dir)
    plot_false_alarm_stages(test_df, plots_dir)
    plot_top_abnormal(test_df, args.score_col, args.top_k, plots_dir)
    plot_feature_distributions(test_df, plots_dir)
    plot_score_timeline_by_video(test_df, args.score_col, args.smooth_score_col, threshold, plots_dir)

    # Reports.
    dist_df, drift = distribution_and_false_alarm_reports(
        calib_df=calib_df,
        test_df=test_df,
        threshold=threshold,
        score_col=args.score_col,
        smooth_col=args.smooth_score_col,
        reports_dir=reports_dir,
    )

    percentiles = [float(x.strip()) for x in args.threshold_grid_percentiles.split(",") if x.strip()]
    op_points = threshold_operating_points(calib_df, test_df, percentiles, args.score_col, reports_dir)

    if model_selection is not None:
        model_selection.to_csv(reports_dir / "pose_component_comparison.csv", index=False, encoding="utf-8-sig")

    labelled_metrics = supervised_labelled_evaluation(args, threshold, plots_dir, reports_dir)

    summary = {
        "gate_dir": str(gate_dir),
        "out_dir": str(out_dir),
        "primary_components": primary_components,
        "primary_threshold": float(threshold),
        "score_col": args.score_col,
        "smooth_score_col": args.smooth_score_col,
        "temporal_config": temporal_config,
        "calibration_rows": int(len(calib_df)),
        "normal_test_rows": int(len(test_df)),
        "normal_test_events_rows": int(len(events_df)) if events_df is not None else None,
        "normal_only_metrics_note": (
            "Because the default gate outputs are normal-only calibration and normal-test splits, "
            "AUROC/AUPRC are not mathematically meaningful unless labelled abnormal examples are provided."
        ),
        "distribution_drift": drift,
        "supervised_labelled_metrics": labelled_metrics,
        "created_plots_dir": str(plots_dir),
        "created_reports_dir": str(reports_dir),
    }

    (reports_dir / "pose_evaluation_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("=" * 80)
    print("Pose gate plotting/evaluation complete")
    print(f"gate_dir     = {gate_dir}")
    print(f"plots_dir    = {plots_dir}")
    print(f"reports_dir  = {reports_dir}")
    print(f"threshold    = {float(threshold):.6f}")
    print(f"components   = {primary_components}")
    print("=" * 80)
    print("Main plots:")
    for p in sorted(plots_dir.glob("*.png")):
        print(f"- {p}")
    print("\nMain reports:")
    for p in sorted(reports_dir.glob("*.csv")):
        print(f"- {p}")
    print(f"- {reports_dir / 'pose_evaluation_summary.json'}")

    if not labelled_metrics.get("available", False):
        print("\nAUROC/AUPRC not computed:")
        print(labelled_metrics.get("reason"))


if __name__ == "__main__":
    main()
