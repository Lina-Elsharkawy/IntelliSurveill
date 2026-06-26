#!/usr/bin/env python3
r"""
04g_build_pose_micro_gmm_gate.py

Builds the pose / micro-motion normality gate for the multi-branch VAD pipeline.

Input:
  pose_micro_features.npy      shape [N, 30]
  pose_micro_metadata.csv      N rows
  pose_micro_feature_names.json

Recommended input folder:
  D:\Embeddings_Distribution\normality_models\pose_micro_50vid_v1_yolov8s

Outputs:
  models/pose_robust_scaler.joblib
  models/pose_gmm_components_*.joblib
  scores/calibration_pose_scores.csv
  scores/normal_test_pose_scores.csv
  scores/normal_test_pose_events.csv
  pose_gmm_model_selection.csv
  04_pose_thresholds.json
  05_pose_false_alarm_report.csv
  06_top_abnormal_pose_tubelets.csv
  07_pose_suitability_report.json
  09_recommended_pose_gate.json

Design:
  - No PCA.
  - RobustScaler.
  - GMM on 30-D YOLOv8s-pose micro-motion features.
  - Split by video_id to avoid leakage.
  - Threshold selected from calibration split only.
  - Normal-test is held out.
  - Higher score = more abnormal.
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler


def parse_args():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--input_dir",
        default=r"D:\Embeddings_Distribution\normality_models\pose_micro_50vid_v2_yolov8s_5fps_24f_s6",
        help="Folder containing pose_micro_features.npy and pose_micro_metadata.csv",
    )
    ap.add_argument(
        "--output_dir",
        default=r"D:\Embeddings_Distribution\normality_models\pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6",
        help="Output folder for models, scores, and reports",
    )

    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--train_ratio", type=float, default=0.70)
    ap.add_argument("--calib_ratio", type=float, default=0.15)

    ap.add_argument("--components", type=str, default="1,2,3,5,8,10")
    ap.add_argument("--components_to_test", type=int, nargs="*", default=None, help="Space-separated GMM component counts, e.g. --components_to_test 1 2 3 5 8 10")
    ap.add_argument("--primary_components", type=int, default=5)

    ap.add_argument("--covariance_type", type=str, default="full")
    ap.add_argument("--reg_covar", type=float, default=1e-6)
    ap.add_argument("--max_iter", type=int, default=500)

    ap.add_argument("--threshold_percentile", type=float, default=99.5)
    ap.add_argument("--threshold_percentiles", type=float, nargs="*", default=None, help="Evaluate multiple calibration percentiles in one run")
    ap.add_argument("--primary_threshold_percentile", type=float, default=None, help="Which percentile to write as recommended/default")

    ap.add_argument("--smoothing_sigma", type=float, default=2.0)
    ap.add_argument("--persistence_hits", type=int, default=3)
    ap.add_argument("--persistence_required_hits", type=int, default=None, help="Alias for --persistence_hits")
    ap.add_argument("--persistence_window", type=int, default=5)
    ap.add_argument("--min_event_gap_sec", type=float, default=5.0)

    ap.add_argument("--top_k", type=int, default=200)

    # Safety metadata checks for the 5fps / 24-frame / stride-6 pose gate.
    ap.add_argument("--expected_sample_fps", type=float, default=5.0)
    ap.add_argument("--expected_tubelet_frames", type=int, default=24)
    ap.add_argument("--expected_stride", type=int, default=6)
    ap.add_argument("--skip_extraction_config_check", action="store_true")
    ap.add_argument("--overwrite", action="store_true")

    return ap.parse_args()


def ensure_dirs(out_dir: Path, overwrite: bool = False):
    if out_dir.exists() and overwrite:
        import shutil
        for name in ["models", "scores", "pose_gmm_model_selection.csv", "05_pose_false_alarm_report.csv", "06_top_abnormal_pose_tubelets.csv", "07_pose_suitability_report.json", "09_recommended_pose_gate.json", "04_pose_thresholds.json", "01_pose_gmm_training_summary.json"]:
            q = out_dir / name
            if q.is_dir():
                shutil.rmtree(q)
            elif q.exists():
                q.unlink()
    (out_dir / "models").mkdir(parents=True, exist_ok=True)
    (out_dir / "scores").mkdir(parents=True, exist_ok=True)


def load_inputs(input_dir: Path):
    features_path = input_dir / "pose_micro_features.npy"
    meta_path = input_dir / "pose_micro_metadata.csv"
    feature_names_path = input_dir / "pose_micro_feature_names.json"
    failed_path = input_dir / "pose_micro_failed.csv"
    summary_path = input_dir / "pose_micro_extraction_summary.json"

    if not features_path.exists():
        raise FileNotFoundError(f"Missing features file: {features_path}")
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing metadata file: {meta_path}")

    X = np.load(features_path)
    meta = pd.read_csv(meta_path)

    if X.ndim != 2:
        raise ValueError(f"Expected 2D feature array, got shape {X.shape}")

    if len(meta) != X.shape[0]:
        raise ValueError(f"Metadata rows do not match features: rows={len(meta)} features={X.shape[0]}")

    feature_names = None
    if feature_names_path.exists():
        _obj = json.loads(feature_names_path.read_text(encoding="utf-8"))
        feature_names = _obj.get("feature_names") if isinstance(_obj, dict) else _obj

    if feature_names is not None and len(feature_names) != X.shape[1]:
        raise ValueError(
            f"Feature names count does not match feature columns: "
            f"names={len(feature_names)} cols={X.shape[1]}"
        )

    failed_count = None
    if failed_path.exists():
        try:
            failed_df = pd.read_csv(failed_path)
            failed_count = int(len(failed_df))
        except Exception:
            failed_count = None

    extraction_summary = {}
    if summary_path.exists():
        try:
            extraction_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            extraction_summary = {}

    return X.astype(np.float64), meta, feature_names, failed_count, extraction_summary



def validate_extraction_config(extraction_summary, args):
    """Best-effort safety check to avoid training the v2 gate on old v1 features."""
    if getattr(args, "skip_extraction_config_check", False):
        return

    if not extraction_summary:
        print("[WARN] No pose_micro_extraction_summary.json found; cannot verify extraction config.")
        return

    expected_frames = int(args.expected_tubelet_frames)
    expected_stride = int(args.expected_stride)
    expected_fps = float(args.expected_sample_fps)

    got_frames = extraction_summary.get("expected_tubelet_frames", extraction_summary.get("tubelet_frames", None))
    got_stride = extraction_summary.get("expected_stride", extraction_summary.get("stride", None))
    got_fps = extraction_summary.get("expected_sample_fps", extraction_summary.get("sample_fps", None))

    problems = []

    if got_frames is not None and int(got_frames) != expected_frames:
        problems.append(f"tubelet_frames got={got_frames}, expected={expected_frames}")

    if got_stride is not None and int(got_stride) != expected_stride:
        problems.append(f"stride got={got_stride}, expected={expected_stride}")

    if got_fps is not None and abs(float(got_fps) - expected_fps) > 1e-6:
        problems.append(f"sample_fps got={got_fps}, expected={expected_fps}")

    if problems:
        raise ValueError(
            "Pose extraction config mismatch. Refusing to train this gate on mismatched features: "
            + "; ".join(problems)
            + ". Use --skip_extraction_config_check only if you are absolutely sure."
        )

def infer_required_columns(meta):
    if "video_id" not in meta.columns:
        raise ValueError("Metadata must contain video_id")

    if "track_id" not in meta.columns:
        meta["track_id"] = 0

    if "tubelet_id" not in meta.columns:
        meta["tubelet_id"] = np.arange(len(meta))

    if "start_time_sec" not in meta.columns:
        if "start_frame" in meta.columns and "source_fps" in meta.columns:
            fps = meta["source_fps"].replace(0, np.nan)
            meta["start_time_sec"] = (meta["start_frame"] / fps).fillna(0.0)
        else:
            meta["start_time_sec"] = np.arange(len(meta), dtype=float)

    if "end_time_sec" not in meta.columns:
        meta["end_time_sec"] = meta["start_time_sec"]

    return meta


def clean_inputs(X, meta, feature_names):
    finite_mask = np.isfinite(X).all(axis=1)
    nonnegative_mask = (X >= 0).all(axis=1)
    nonzero_mask = np.abs(X).sum(axis=1) > 0

    # For pose specifically, also keep rows with some valid pose information.
    pose_valid_mask = np.ones(len(X), dtype=bool)
    if feature_names and "pose_valid_frame_ratio" in feature_names:
        idx = feature_names.index("pose_valid_frame_ratio")
        pose_valid_mask = X[:, idx] > 0

    keep = finite_mask & nonnegative_mask & nonzero_mask & pose_valid_mask

    dropped = {
        "total_rows": int(len(X)),
        "dropped_nonfinite": int((~finite_mask).sum()),
        "dropped_negative": int((~nonnegative_mask).sum()),
        "dropped_all_zero": int((~nonzero_mask).sum()),
        "dropped_pose_valid_frame_ratio_zero": int((~pose_valid_mask).sum()),
        "kept_rows": int(keep.sum()),
    }

    X2 = X[keep]
    meta2 = meta.loc[keep].copy().reset_index(drop=True)

    if len(X2) == 0:
        raise ValueError("No valid pose features remain after cleaning.")

    return X2, meta2, dropped


def split_by_video(meta, seed, train_ratio, calib_ratio):
    rng = np.random.default_rng(seed)

    videos = np.array(sorted(meta["video_id"].astype(str).unique()))
    rng.shuffle(videos)

    n = len(videos)
    n_train = max(1, int(round(n * train_ratio)))
    n_calib = max(1, int(round(n * calib_ratio)))

    if n_train + n_calib >= n:
        n_train = max(1, n - 2)
        n_calib = 1

    train_videos = set(videos[:n_train])
    calib_videos = set(videos[n_train:n_train + n_calib])
    test_videos = set(videos[n_train + n_calib:])

    split = []
    for vid in meta["video_id"].astype(str):
        if vid in train_videos:
            split.append("train")
        elif vid in calib_videos:
            split.append("calibration")
        elif vid in test_videos:
            split.append("normal_test")
        else:
            raise RuntimeError("Unexpected split assignment failure")

    meta = meta.copy()
    meta["split"] = split

    split_info = {
        "seed": int(seed),
        "split_unit": "video_id",
        "num_videos_total": int(n),
        "num_train_videos": int(len(train_videos)),
        "num_calibration_videos": int(len(calib_videos)),
        "num_normal_test_videos": int(len(test_videos)),
        "train_videos": sorted(list(train_videos)),
        "calibration_videos": sorted(list(calib_videos)),
        "normal_test_videos": sorted(list(test_videos)),
        "tubelets_by_split": {k: int(v) for k, v in meta["split"].value_counts().to_dict().items()},
    }

    return meta, split_info


def gaussian_smooth_1d(values, sigma):
    values = np.asarray(values, dtype=float)

    if sigma <= 0 or len(values) <= 2:
        return values.copy()

    radius = int(max(1, round(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-(x ** 2) / (2 * sigma ** 2))
    kernel /= kernel.sum()

    padded = np.pad(values, (radius, radius), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def add_smoothed_and_persistence(df, threshold, sigma, hits, window):
    df = df.copy()
    df["pose_score_smooth"] = np.nan
    df["pose_hit_raw"] = df["pose_score"] > threshold
    df["pose_hit_smooth"] = False
    df["pose_persistent_hit"] = False

    for _, idx in df.groupby(["video_id", "track_id"], sort=False).groups.items():
        idx = list(idx)
        sub = df.loc[idx].sort_values("start_time_sec")
        order_idx = list(sub.index)

        scores = sub["pose_score"].to_numpy(dtype=float)
        smooth = gaussian_smooth_1d(scores, sigma)
        hit_smooth = smooth > threshold

        persistent = np.zeros(len(hit_smooth), dtype=bool)
        for i in range(len(hit_smooth)):
            lo = max(0, i - window + 1)
            if int(hit_smooth[lo:i + 1].sum()) >= hits:
                persistent[i] = True

        df.loc[order_idx, "pose_score_smooth"] = smooth
        df.loc[order_idx, "pose_hit_smooth"] = hit_smooth
        df.loc[order_idx, "pose_persistent_hit"] = persistent

    return df


def make_event(video_id, track_id, rows):
    scores = [float(r["pose_score"]) for r in rows]
    smooth = [float(r["pose_score_smooth"]) for r in rows]
    starts = [float(r["start_time_sec"]) for r in rows]
    ends = [float(r["end_time_sec"]) for r in rows]

    return {
        "video_id": video_id,
        "track_id": track_id,
        "event_start_time_sec": min(starts),
        "event_end_time_sec": max(ends),
        "num_tubelets": len(rows),
        "max_pose_score": max(scores),
        "mean_pose_score": float(np.mean(scores)),
        "max_pose_score_smooth": max(smooth),
        "reason": "rare_pose_articulation",
    }


def build_events(df, min_event_gap_sec):
    events = []

    for (video_id, track_id), sub in df.groupby(["video_id", "track_id"], sort=False):
        sub = sub.sort_values("start_time_sec").reset_index(drop=False)
        hits = sub[sub["pose_persistent_hit"]].copy()

        if hits.empty:
            continue

        current = []
        last_t = None

        for _, row in hits.iterrows():
            t = float(row["start_time_sec"])

            if last_t is None or (t - last_t) <= min_event_gap_sec:
                current.append(row)
            else:
                events.append(make_event(video_id, track_id, current))
                current = [row]

            last_t = t

        if current:
            events.append(make_event(video_id, track_id, current))

    if not events:
        return pd.DataFrame(columns=[
            "video_id", "track_id", "event_start_time_sec", "event_end_time_sec",
            "num_tubelets", "max_pose_score", "mean_pose_score",
            "max_pose_score_smooth", "reason"
        ])

    return pd.DataFrame(events)


def evaluate_scores(df, threshold, sigma, hits, window, min_event_gap_sec):
    scored = add_smoothed_and_persistence(
        df=df,
        threshold=threshold,
        sigma=sigma,
        hits=hits,
        window=window,
    )

    events = build_events(scored, min_event_gap_sec=min_event_gap_sec)

    report = {
        "tubelets": int(len(scored)),
        "threshold": float(threshold),
        "false_alarm_tubelets_before_persistence": int(scored["pose_hit_raw"].sum()),
        "false_alarm_rate_before_persistence": float(scored["pose_hit_raw"].mean()) if len(scored) else 0.0,
        "false_alarm_tubelets_after_smoothing": int(scored["pose_hit_smooth"].sum()),
        "false_alarm_rate_after_smoothing": float(scored["pose_hit_smooth"].mean()) if len(scored) else 0.0,
        "false_alarm_tubelets_after_persistence": int(scored["pose_persistent_hit"].sum()),
        "false_alarm_rate_after_persistence": float(scored["pose_persistent_hit"].mean()) if len(scored) else 0.0,
        "false_alarm_events_after_persistence": int(len(events)),
        "videos": int(scored["video_id"].astype(str).nunique()) if len(scored) else 0,
        "tracks": int(scored[["video_id", "track_id"]].drop_duplicates().shape[0]) if len(scored) else 0,
    }

    return scored, events, report


def add_feature_columns(df, X, feature_names):
    if feature_names is None:
        return df

    out = df.copy()
    for i, name in enumerate(feature_names):
        if i < X.shape[1]:
            out[name] = X[:, i]
    return out


def main():
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    ensure_dirs(output_dir, overwrite=bool(args.overwrite))

    if args.components_to_test:
        components = [int(x) for x in args.components_to_test]
    else:
        components = [int(x.strip()) for x in args.components.split(",") if x.strip()]
    if args.primary_components not in components:
        components.append(args.primary_components)
    components = sorted(set(components))

    if args.threshold_percentiles:
        threshold_percentiles = sorted(set(float(x) for x in args.threshold_percentiles))
    else:
        threshold_percentiles = [float(args.threshold_percentile)]
    primary_threshold_percentile = float(args.primary_threshold_percentile if args.primary_threshold_percentile is not None else args.threshold_percentile)
    if primary_threshold_percentile not in threshold_percentiles:
        threshold_percentiles.append(primary_threshold_percentile)
        threshold_percentiles = sorted(set(threshold_percentiles))

    persistence_hits = int(args.persistence_required_hits if args.persistence_required_hits is not None else args.persistence_hits)

    print("=" * 80)
    print("Building pose micro-motion GMM gate")
    print(f"input_dir  = {input_dir}")
    print(f"output_dir = {output_dir}")
    print(f"target_pose= {args.expected_sample_fps}fps | {args.expected_tubelet_frames} frames | stride {args.expected_stride}")
    print(f"components = {components}")
    print(f"threshold_percentiles = {threshold_percentiles}")
    print(f"primary = k={args.primary_components}, p={primary_threshold_percentile}")
    print("=" * 80)

    X, meta, feature_names, failed_count, extraction_summary = load_inputs(input_dir)
    validate_extraction_config(extraction_summary, args)

    print(f"Loaded features shape: {X.shape}")
    print(f"Loaded metadata rows : {len(meta)}")
    print(f"Extraction failed rows: {failed_count}")

    meta = infer_required_columns(meta)
    X, meta, cleaning_report = clean_inputs(X, meta, feature_names)

    print("Cleaning report:")
    print(json.dumps(cleaning_report, indent=2))

    meta, split_info = split_by_video(
        meta=meta,
        seed=args.seed,
        train_ratio=args.train_ratio,
        calib_ratio=args.calib_ratio,
    )

    print("Split info:")
    print(json.dumps({
        "num_videos_total": split_info["num_videos_total"],
        "num_train_videos": split_info["num_train_videos"],
        "num_calibration_videos": split_info["num_calibration_videos"],
        "num_normal_test_videos": split_info["num_normal_test_videos"],
        "tubelets_by_split": split_info["tubelets_by_split"],
    }, indent=2))

    train_mask = meta["split"].eq("train").to_numpy()
    calib_mask = meta["split"].eq("calibration").to_numpy()
    test_mask = meta["split"].eq("normal_test").to_numpy()

    X_train = X[train_mask]
    X_calib = X[calib_mask]
    X_test = X[test_mask]

    if len(X_train) == 0 or len(X_calib) == 0 or len(X_test) == 0:
        raise ValueError("One of train/calibration/normal_test splits is empty. Cannot proceed.")

    scaler = RobustScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_calib_s = scaler.transform(X_calib)
    X_test_s = scaler.transform(X_test)

    joblib.dump(scaler, output_dir / "models" / "pose_robust_scaler.joblib")

    model_rows = []
    thresholds = {}
    primary_payload = None
    primary_calib_scored = None
    primary_test_scored = None
    primary_test_events = None

    for k in components:
        print(f"\nTraining pose GMM components={k}")

        gmm = GaussianMixture(
            n_components=k,
            covariance_type=args.covariance_type,
            reg_covar=args.reg_covar,
            max_iter=args.max_iter,
            random_state=args.seed,
            n_init=3,
        )

        gmm.fit(X_train_s)
        joblib.dump(gmm, output_dir / "models" / f"pose_gmm_components_{k}.joblib")

        train_scores = -gmm.score_samples(X_train_s)
        calib_scores = -gmm.score_samples(X_calib_s)
        test_scores = -gmm.score_samples(X_test_s)

        calib_df = meta.loc[calib_mask].copy().reset_index(drop=True)
        calib_df["pose_score"] = calib_scores
        calib_df = add_feature_columns(calib_df, X_calib, feature_names)

        test_df = meta.loc[test_mask].copy().reset_index(drop=True)
        test_df["pose_score"] = test_scores
        test_df = add_feature_columns(test_df, X_test, feature_names)

        thresholds[str(k)] = {}

        for pctl in threshold_percentiles:
            threshold = float(np.percentile(calib_scores, pctl))
            pkey = ("p" + ("%g" % float(pctl)).replace(".", "_"))
            thresholds[str(k)][pkey] = {
                "percentile": float(pctl),
                "threshold": float(threshold),
                "score_source": "calibration_pose_score_raw",
            }

            calib_scored, calib_events, calib_report = evaluate_scores(
                calib_df,
                threshold=threshold,
                sigma=args.smoothing_sigma,
                hits=persistence_hits,
                window=args.persistence_window,
                min_event_gap_sec=args.min_event_gap_sec,
            )

            test_scored, test_events, test_report = evaluate_scores(
                test_df,
                threshold=threshold,
                sigma=args.smoothing_sigma,
                hits=persistence_hits,
                window=args.persistence_window,
                min_event_gap_sec=args.min_event_gap_sec,
            )

            row = {
                "components": int(k),
                "converged": bool(gmm.converged_),
                "n_iter": int(gmm.n_iter_),
                "bic_train": float(gmm.bic(X_train_s)),
                "aic_train": float(gmm.aic(X_train_s)),
                "threshold_percentile": float(pctl),
                "threshold": float(threshold),

                "train_score_mean": float(np.mean(train_scores)),
                "train_score_p95": float(np.percentile(train_scores, 95)),
                "train_score_p995": float(np.percentile(train_scores, 99.5)),

                "calib_score_mean": float(np.mean(calib_scores)),
                "calib_score_p95": float(np.percentile(calib_scores, 95)),
                "calib_score_p995": float(np.percentile(calib_scores, 99.5)),

                "normal_test_score_mean": float(np.mean(test_scores)),
                "normal_test_score_p95": float(np.percentile(test_scores, 95)),
                "normal_test_score_p995": float(np.percentile(test_scores, 99.5)),

                "calib_false_alarm_tubelets_before_persistence": calib_report["false_alarm_tubelets_before_persistence"],
                "calib_false_alarm_rate_before_persistence": calib_report["false_alarm_rate_before_persistence"],
                "calib_false_alarm_tubelets_after_smoothing": calib_report["false_alarm_tubelets_after_smoothing"],
                "calib_false_alarm_rate_after_smoothing": calib_report["false_alarm_rate_after_smoothing"],
                "calib_false_alarm_tubelets_after_persistence": calib_report["false_alarm_tubelets_after_persistence"],
                "calib_false_alarm_rate_after_persistence": calib_report["false_alarm_rate_after_persistence"],
                "calib_false_alarm_events_after_persistence": calib_report["false_alarm_events_after_persistence"],

                "normal_test_tubelets": test_report["tubelets"],
                "normal_test_videos": test_report["videos"],
                "normal_test_tracks": test_report["tracks"],
                "normal_test_false_alarm_tubelets_before_persistence": test_report["false_alarm_tubelets_before_persistence"],
                "normal_test_false_alarm_rate_before_persistence": test_report["false_alarm_rate_before_persistence"],
                "normal_test_false_alarm_tubelets_after_smoothing": test_report["false_alarm_tubelets_after_smoothing"],
                "normal_test_false_alarm_rate_after_smoothing": test_report["false_alarm_rate_after_smoothing"],
                "normal_test_false_alarm_tubelets_after_persistence": test_report["false_alarm_tubelets_after_persistence"],
                "normal_test_false_alarm_rate_after_persistence": test_report["false_alarm_rate_after_persistence"],
                "normal_test_false_alarm_events_after_persistence": test_report["false_alarm_events_after_persistence"],
            }

            if test_report["false_alarm_events_after_persistence"] == 0:
                row["verdict"] = "excellent_on_held_out_normal"
            elif test_report["false_alarm_rate_before_persistence"] <= 0.01 and test_report["false_alarm_events_after_persistence"] <= 10:
                row["verdict"] = "usable_but_needs_visual_review"
            else:
                row["verdict"] = "needs_tuning_or_visual_review"

            model_rows.append(row)

            if k == args.primary_components and abs(float(pctl) - primary_threshold_percentile) < 1e-9:
                primary_payload = {
                    "components": int(k),
                    "threshold_percentile": float(pctl),
                    "threshold": float(threshold),
                    "calib_scored": calib_scored,
                    "calib_events": calib_events,
                    "calib_report": calib_report,
                    "test_scored": test_scored,
                    "test_events": test_events,
                    "test_report": test_report,
                    "train_scores": train_scores,
                    "calib_scores": calib_scores,
                    "test_scores": test_scores,
                    "gmm": gmm,
                }
                primary_calib_scored = calib_scored
                primary_test_scored = test_scored
                primary_test_events = test_events

        primary_rows_for_k = [r for r in model_rows if int(r["components"]) == int(k) and abs(float(r["threshold_percentile"]) - primary_threshold_percentile) < 1e-9]
        if primary_rows_for_k:
            print(json.dumps(primary_rows_for_k[-1], indent=2))

    if primary_payload is None:
        raise RuntimeError("Primary GMM payload was not created.")

    model_selection = pd.DataFrame(model_rows).sort_values(["threshold_percentile", "components"])
    model_selection.to_csv(output_dir / "pose_gmm_model_selection.csv", index=False, encoding="utf-8-sig")

    primary_k = args.primary_components
    threshold = primary_payload["threshold"]
    primary_threshold_percentile = float(primary_payload["threshold_percentile"])

    calib_scored = primary_payload["calib_scored"]
    test_scored = primary_payload["test_scored"]
    test_events = primary_payload["test_events"]

    calib_scored.to_csv(output_dir / "scores" / "calibration_pose_scores_primary.csv", index=False, encoding="utf-8-sig")
    test_scored.to_csv(output_dir / "scores" / "normal_test_pose_scores_primary.csv", index=False, encoding="utf-8-sig")
    test_events.to_csv(output_dir / "scores" / "normal_test_pose_events_primary.csv", index=False, encoding="utf-8-sig")

    # Full normal-test result table for ALL k and ALL percentiles.
    false_alarm_report = model_selection.copy()
    false_alarm_report.to_csv(output_dir / "05_pose_false_alarm_report.csv", index=False, encoding="utf-8-sig")

    top_cols = [
        "tubelet_id", "video_id", "track_id",
        "start_time_sec", "end_time_sec",
        "pose_score", "pose_score_smooth",
        "pose_hit_raw", "pose_hit_smooth", "pose_persistent_hit",
        "pose_valid_frame_ratio",
        "pose_mean_keypoint_conf",
        "pose_valid_keypoint_ratio_mean",
        "pose_wrist_speed_p95",
        "pose_ankle_speed_p95",
        "pose_limb_speed_p95",
        "pose_limb_accel_p95",
        "pose_body_angle_change_p95",
        "pose_crouch_change_p95",
        "pose_arm_extension_change_p95",
        "pose_asymmetry_motion_p95",
    ]

    existing_top_cols = [c for c in top_cols if c in test_scored.columns]
    top_abnormal = test_scored.sort_values("pose_score", ascending=False).head(args.top_k)
    top_abnormal[existing_top_cols].to_csv(
        output_dir / "06_top_abnormal_pose_tubelets.csv",
        index=False,
        encoding="utf-8-sig",
    )

    thresholds_payload = {
        "model": "pose_micro_gmm",
        "feature_source": str(input_dir),
        "threshold_source": "calibration split only",
        "threshold_percentiles": [float(x) for x in threshold_percentiles],
        "primary_components": int(primary_k),
        "primary_threshold_percentile": float(primary_threshold_percentile),
        "primary_threshold": float(threshold),
        "thresholds_by_components_and_percentiles": thresholds,
        "thresholds_by_components": {str(k): thresholds[str(k)].get(("p" + ("%g" % float(primary_threshold_percentile)).replace(".", "_")), {}).get("threshold") for k in components},
        "score_definition": "negative GMM log likelihood; higher = more abnormal",
        "split_info": split_info,
        "cleaning_report": cleaning_report,
        "feature_names": feature_names,
        "pose_temporal_config": {
            "target_sample_fps": float(args.expected_sample_fps),
            "tubelet_frames": int(args.expected_tubelet_frames),
            "stride": int(args.expected_stride),
            "target_window_duration_sec": float(args.expected_tubelet_frames / args.expected_sample_fps),
            "extraction_summary_expected_sample_fps": extraction_summary.get("expected_sample_fps"),
            "extraction_summary_expected_tubelet_frames": extraction_summary.get("expected_tubelet_frames"),
            "extraction_summary_expected_stride": extraction_summary.get("expected_stride"),
            "extraction_summary_fps_tolerance": extraction_summary.get("fps_tolerance"),
            "extraction_summary_allow_sample_gaps": extraction_summary.get("allow_sample_gaps"),
        },
    }

    (output_dir / "04_pose_thresholds.json").write_text(
        json.dumps(thresholds_payload, indent=2),
        encoding="utf-8",
    )

    training_summary = {
        "script": Path(__file__).name,
        "schema_version": "pose_micro_gmm_gate_allk_allp_v1",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "total_rows_after_filtering": int(X.shape[0]),
        "feature_dim": int(X.shape[1]),
        "components_to_test": components,
        "threshold_percentiles": [float(x) for x in threshold_percentiles],
        "primary_components": int(primary_k),
        "primary_threshold_percentile": float(primary_threshold_percentile),
        "primary_threshold": float(threshold),
        "settings": {
            "train_ratio": float(args.train_ratio),
            "calib_ratio": float(args.calib_ratio),
            "random_seed": int(args.seed),
            "covariance_type": str(args.covariance_type),
            "reg_covar": float(args.reg_covar),
            "max_iter": int(args.max_iter),
            "smoothing_sigma": float(args.smoothing_sigma),
            "persistence_hits": int(persistence_hits),
            "persistence_window": int(args.persistence_window),
            "min_event_gap_sec": float(args.min_event_gap_sec),
        },
        "split_info": split_info,
        "cleaning_report": cleaning_report,
    }
    (output_dir / "01_pose_gmm_training_summary.json").write_text(json.dumps(training_summary, indent=2), encoding="utf-8")

    test_report = primary_payload["test_report"]

    if test_report["false_alarm_events_after_persistence"] == 0:
        verdict = "excellent_on_held_out_normal"
    elif test_report["false_alarm_rate_before_persistence"] <= 0.01 and test_report["false_alarm_events_after_persistence"] <= 10:
        verdict = "usable_but_needs_visual_review"
    else:
        verdict = "needs_tuning_or_visual_review"

    suitability = {
        "verdict": verdict,
        "important_interpretation": (
            "This only proves behavior on held-out normal videos. "
            "It does not prove abnormal detection yet. "
            "Next step is visual review of top normal-test pose outliers and abnormal-video testing."
        ),
        "feature_shape": list(X.shape),
        "metadata_rows": int(len(meta)),
        "extraction_failed_rows": failed_count,
        "primary_components": int(primary_k),
        "primary_threshold": float(threshold),
        "pose_temporal_config": {
            "target_sample_fps": float(args.expected_sample_fps),
            "tubelet_frames": int(args.expected_tubelet_frames),
            "stride": int(args.expected_stride),
            "target_window_duration_sec": float(args.expected_tubelet_frames / args.expected_sample_fps),
        },
        "normal_test_report": test_report,
        "calibration_report": primary_payload["calib_report"],
        "speed_note": (
            f"Pose extraction completed with model={extraction_summary.get('pose_model', 'unknown')}, "
            f"tubelets_per_sec={extraction_summary.get('tubelets_per_sec', 'unknown')}."
        ),
        "pose_quality_note": (
            "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. "
            "Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."
        ),
    }

    (output_dir / "07_pose_suitability_report.json").write_text(
        json.dumps(suitability, indent=2),
        encoding="utf-8",
    )

    recommended_gate = {
        "gate_name": "pose_micro_gmm_gate",
        "reason_when_fired": "rare_pose_articulation",
        "feature_extractor": {
            "model": extraction_summary.get("pose_model", "yolov8s-pose.pt"),
            "device_used_for_extraction": extraction_summary.get("device", "cuda"),
            "imgsz": extraction_summary.get("imgsz", 256),
            "conf": extraction_summary.get("conf", 0.25),
            "kpt_conf": extraction_summary.get("kpt_conf", 0.30),
            "crop_pad_ratio": extraction_summary.get("crop_pad_ratio", 0.25),
            "min_crop_size": extraction_summary.get("min_crop_size", 192),
            "target_sample_fps": float(args.expected_sample_fps),
            "tubelet_frames": int(args.expected_tubelet_frames),
            "stride": int(args.expected_stride),
            "target_window_duration_sec": float(args.expected_tubelet_frames / args.expected_sample_fps),
            "feature_dim": int(X.shape[1]),
            "feature_names": feature_names,
            "important": (
                "Production inference must use the same pose model and feature extraction settings used for calibration."
            ),
        },
        "normality_model": {
            "scaler": str(output_dir / "models" / "pose_robust_scaler.joblib"),
            "gmm": str(output_dir / "models" / f"pose_gmm_components_{primary_k}.joblib"),
            "components": int(primary_k),
            "covariance_type": args.covariance_type,
            "reg_covar": float(args.reg_covar),
            "score_definition": "negative GMM log likelihood; higher = more abnormal",
            "threshold": float(threshold),
            "threshold_percentile": float(primary_threshold_percentile),
        },
        "postprocessing": {
            "smoothing_sigma": float(args.smoothing_sigma),
            "persistence_hits": int(persistence_hits),
            "persistence_window": int(args.persistence_window),
            "min_event_gap_sec": float(args.min_event_gap_sec),
        },
        "decision": {
            "gate_fires_if": "smoothed pose score exceeds threshold persistently",
            "final_pipeline_logic": "Independent gate. Do not fuse raw score with deep or velocity branches yet.",
        },
        "validation_status": suitability,
    }

    (output_dir / "09_recommended_pose_gate.json").write_text(
        json.dumps(recommended_gate, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 80)
    print("DONE")
    print("=" * 80)
    print(f"Output folder: {output_dir}")
    print(f"Primary components: {primary_k}")
    print(f"Primary threshold: {threshold:.6f}")
    print("Normal-test report:")
    print(json.dumps(test_report, indent=2))
    print(f"Verdict: {verdict}")

    print("\nImportant files:")
    print(f"- {output_dir / '05_pose_false_alarm_report.csv'}")
    print(f"- {output_dir / '06_top_abnormal_pose_tubelets.csv'}")
    print(f"- {output_dir / '07_pose_suitability_report.json'}")
    print(f"- {output_dir / '09_recommended_pose_gate.json'}")

    print("\nCompact result table:")
    show_cols = [
        "components", "threshold_percentile", "threshold",
        "normal_test_false_alarm_rate_before_persistence",
        "normal_test_false_alarm_rate_after_smoothing",
        "normal_test_false_alarm_rate_after_persistence",
        "normal_test_false_alarm_events_after_persistence",
        "verdict",
    ]
    print(model_selection[show_cols].to_string(index=False))


if __name__ == "__main__":
    main()