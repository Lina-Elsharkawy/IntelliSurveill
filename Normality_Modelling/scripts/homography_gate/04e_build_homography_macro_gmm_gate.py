#!/usr/bin/env python3
r"""
04e_build_homography_macro_gmm_gate.py

Build a GMM normality gate for homography-normalized macro-motion features.

Inputs from 04d_extract_homography_macro_features.py:
  homography_macro_features.npy
  homography_macro_metadata.csv
  homography_macro_feature_names.json

Recommended:
  python .\04e_build_homography_macro_gmm_gate.py --input_dir "D:\Embeddings_Distribution\normality_models\homography_macro_50vid_v1_cap3" --output_dir "D:\Embeddings_Distribution\normality_models\homography_macro_gmm_gate_v1" --overwrite

Notes:
- This script intentionally uses a small robust selected feature set by default.
- It avoids spiky max-speed features as primary GMM inputs because they can be affected by bbox jitter/perspective amplification.
- If your homography uses arbitrary 8x6 floor units, report this as homography-normalized floor-unit speed, not true m/s.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import RobustScaler

try:
    from scipy.ndimage import gaussian_filter1d
except Exception:
    gaussian_filter1d = None

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

SCHEMA_VERSION = "homography_macro_gmm_gate_stage3_pose_v1.1"

DEFAULT_SELECTED_FEATURES = [
    "macro_speed_mean_mps",
    "macro_speed_median_mps",
    "macro_speed_p95_mps",
    "macro_accel_p95_mps2",
    "macro_straightness_ratio",
    "macro_direction_change_mean_rad",
    "macro_stationary_step_ratio",
]

RISKY_SPIKY_FEATURES = [
    "macro_speed_max_mps",
    "macro_accel_max_mps2",
    "macro_direction_change_max_rad",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train/evaluate homography macro GMM gate.")
    p.add_argument("--input_dir", required=True)
    p.add_argument("--output_dir", required=True)
    p.add_argument("--features_npy", default=None)
    p.add_argument("--metadata_csv", default=None)
    p.add_argument("--feature_names_json", default=None)
    p.add_argument("--selected_features", nargs="*", default=None)
    p.add_argument("--require_stage3_groundpoints", action="store_true",
                   help="Fail if metadata does not contain Stage-3 groundpoint quality columns from 04a/04a2.")
    p.add_argument("--max_bbox_fallback_ratio", type=float, default=1.0,
                   help="Optional training filter: drop tubelets above this bbox fallback ratio when the column exists.")
    p.add_argument("--max_frozen_ratio", type=float, default=1.0,
                   help="Optional training filter: drop tubelets above this freeze fallback ratio when the column exists.")

    p.add_argument("--train_ratio", type=float, default=0.70)
    p.add_argument("--calibration_ratio", type=float, default=0.15)
    p.add_argument("--normal_test_ratio", type=float, default=0.15)
    p.add_argument("--random_seed", type=int, default=42)

    p.add_argument("--components_to_test", type=int, nargs="*", default=[1, 2, 3, 5, 8, 10])
    p.add_argument("--primary_components", type=int, default=5)
    p.add_argument("--covariance_type", choices=["full", "tied", "diag", "spherical"], default="full")
    p.add_argument("--reg_covar", type=float, default=1e-6)
    p.add_argument("--max_iter", type=int, default=500)
    p.add_argument("--n_init", type=int, default=5)

    p.add_argument("--use_pca", action="store_true")
    p.add_argument("--pca_components", type=int, default=5)

    p.add_argument("--threshold_percentiles", type=float, nargs="*", default=[95, 97.5, 99, 99.5, 99.7, 99.9])
    p.add_argument("--primary_threshold_percentile", type=float, default=99.5)

    p.add_argument("--smoothing_sigma", type=float, default=2.0)
    p.add_argument("--persistence_window", type=int, default=5)
    p.add_argument("--persistence_required_hits", type=int, default=3)
    p.add_argument("--min_event_gap_sec", type=float, default=5.0)

    p.add_argument("--make_plots", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def safe_mkdir_output(output_dir: Path, overwrite: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    protected = [
        output_dir / "09_recommended_macro_gate.json",
        output_dir / "04_macro_thresholds.json",
        output_dir / "05_macro_false_alarm_report.csv",
    ]
    existing = [p for p in protected if p.exists()]
    if existing and not overwrite:
        raise FileExistsError("Output files already exist. Use --overwrite or choose a new --output_dir:\n" + "\n".join(map(str, existing)))
    for sub in ["models", "scores", "plots", "diagnostics"]:
        (output_dir / sub).mkdir(parents=True, exist_ok=True)


def resolve_paths(args: argparse.Namespace) -> Tuple[Path, Path, Path]:
    inp = Path(args.input_dir)
    f = Path(args.features_npy) if args.features_npy else inp / "homography_macro_features.npy"
    m = Path(args.metadata_csv) if args.metadata_csv else inp / "homography_macro_metadata.csv"
    n = Path(args.feature_names_json) if args.feature_names_json else inp / "homography_macro_feature_names.json"
    for p in [f, m, n]:
        if not p.exists():
            raise FileNotFoundError(p)
    return f, m, n


def load_feature_names(path: Path) -> List[str]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    names = obj.get("feature_names")
    if not isinstance(names, list) or not names:
        raise ValueError(f"Invalid feature_names_json: {path}")
    return [str(x) for x in names]


def choose_features(all_names: List[str], requested: Optional[List[str]]) -> List[str]:
    selected = requested if requested else DEFAULT_SELECTED_FEATURES
    missing = [x for x in selected if x not in all_names]
    if missing:
        raise ValueError("Missing selected features: " + ", ".join(missing) + "\nAvailable: " + ", ".join(all_names))
    return selected


def split_by_video(metadata: pd.DataFrame, train_ratio: float, cal_ratio: float, test_ratio: float, seed: int) -> Dict[str, List[str]]:
    if not math.isclose(train_ratio + cal_ratio + test_ratio, 1.0, abs_tol=1e-6):
        raise ValueError("Split ratios must sum to 1.0")
    videos = sorted(metadata["video_id"].astype(str).unique().tolist())
    if len(videos) < 5:
        raise ValueError(f"Need at least 5 videos with tubelets; got {len(videos)}")
    rng = np.random.default_rng(seed)
    arr = np.array(videos, dtype=object)
    rng.shuffle(arr)
    n = len(arr)
    n_train = max(1, int(round(n * train_ratio)))
    n_cal = max(1, int(round(n * cal_ratio)))
    if n_train + n_cal >= n:
        n_train = max(1, n - 2)
        n_cal = 1
    return {
        "train": [str(x) for x in arr[:n_train].tolist()],
        "calibration": [str(x) for x in arr[n_train:n_train + n_cal].tolist()],
        "normal_test": [str(x) for x in arr[n_train + n_cal:].tolist()],
    }


def assign_split(metadata: pd.DataFrame, split: Dict[str, List[str]]) -> pd.Series:
    mapping: Dict[str, str] = {}
    for name, vids in split.items():
        for v in vids:
            mapping[str(v)] = name
    return metadata["video_id"].astype(str).map(mapping).fillna("unknown")


def smooth_grouped(df: pd.DataFrame, score_col: str, sigma: float) -> np.ndarray:
    vals_out = np.full(len(df), np.nan, dtype=np.float64)
    if sigma <= 0 or gaussian_filter1d is None:
        return df[score_col].to_numpy(dtype=np.float64)
    for _, idx in df.groupby(["video_id", "track_id"], sort=False).groups.items():
        idx_list = list(idx)
        sub = df.loc[idx_list].sort_values("start_time_sec")
        vals = sub[score_col].to_numpy(dtype=np.float64)
        if vals.size <= 1:
            sm = vals
        else:
            sm = gaussian_filter1d(vals, sigma=float(sigma), mode="nearest")
        vals_out[sub.index.to_numpy()] = sm
    return vals_out


def score_model(model: GaussianMixture, X: np.ndarray) -> np.ndarray:
    return (-model.score_samples(X)).astype(np.float64)


def count_persistence_events(df: pd.DataFrame, flag_col: str, window: int, required_hits: int, min_gap: float) -> Tuple[int, List[Dict[str, Any]]]:
    events: List[Dict[str, Any]] = []
    for (video_id, track_id), group in df.groupby(["video_id", "track_id"], sort=False):
        g = group.sort_values("start_time_sec").reset_index(drop=False)
        flags = g[flag_col].astype(bool).to_numpy()
        times = g["start_time_sec"].astype(float).to_numpy()
        last_event_t = -1e18
        for i in range(len(g)):
            j0 = max(0, i - int(window) + 1)
            hits = int(flags[j0:i + 1].sum())
            if flags[i] and hits >= int(required_hits):
                t = float(times[i])
                if t - last_event_t >= float(min_gap):
                    row = g.iloc[i]
                    events.append({
                        "video_id": str(video_id),
                        "track_id": str(track_id),
                        "tubelet_id": row.get("tubelet_id", ""),
                        "event_time_sec": t,
                        "start_time_sec": row.get("start_time_sec", ""),
                        "end_time_sec": row.get("end_time_sec", ""),
                        "hits_in_window": hits,
                    })
                    last_event_t = t
    return len(events), events


def build_score_df(meta: pd.DataFrame, selected_df: pd.DataFrame, split_name: str, raw: np.ndarray, smooth: np.ndarray) -> pd.DataFrame:
    cols = ["tubelet_id", "video_id", "track_id", "video_path", "start_frame", "end_frame", "start_time_sec", "end_time_sec", "source_fps", "effective_sample_fps"]
    cols = [c for c in cols if c in meta.columns]
    out = meta[cols].copy()
    out["split"] = split_name
    for c in selected_df.columns:
        out[c] = selected_df[c].to_numpy()
    out["macro_score_raw"] = raw
    out["macro_score_smooth"] = smooth
    return out


def train_gmms(X_train: np.ndarray, components: Sequence[int], args: argparse.Namespace) -> Tuple[Dict[int, GaussianMixture], pd.DataFrame]:
    models: Dict[int, GaussianMixture] = {}
    rows: List[Dict[str, Any]] = []
    for k in components:
        k = int(k)
        if k < 1 or X_train.shape[0] <= k:
            continue
        model = GaussianMixture(
            n_components=k,
            covariance_type=args.covariance_type,
            reg_covar=float(args.reg_covar),
            max_iter=int(args.max_iter),
            n_init=int(args.n_init),
            random_state=int(args.random_seed),
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model.fit(X_train)
        models[k] = model
        rows.append({
            "components": k,
            "train_avg_log_likelihood": float(model.score(X_train)),
            "bic": float(model.bic(X_train)),
            "aic": float(model.aic(X_train)),
            "converged": bool(model.converged_),
            "n_iter": int(model.n_iter_),
            "warnings": " | ".join(str(w.message) for w in caught) if caught else "",
        })
    if not models:
        raise RuntimeError("No GMM candidates were trained")
    return models, pd.DataFrame(rows)


def make_threshold_report(cal_scores: np.ndarray, test_df: pd.DataFrame, percentiles: Sequence[float], args: argparse.Namespace) -> Tuple[Dict[str, Any], pd.DataFrame, Dict[str, List[Dict[str, Any]]]]:
    thresholds: Dict[str, Any] = {}
    rows: List[Dict[str, Any]] = []
    events_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for p in percentiles:
        thr = float(np.percentile(cal_scores, float(p)))
        key = f"p{str(p).replace('.', '_')}"
        thresholds[key] = {"percentile": float(p), "threshold": thr, "score_source": "calibration_macro_score_smooth"}
        tmp = test_df.copy()
        tmp["macro_gate_hit"] = tmp["macro_score_smooth"] > thr
        hits = int(tmp["macro_gate_hit"].sum())
        total = int(len(tmp))
        far = float(hits / total) if total else 0.0
        ev_count, events = count_persistence_events(tmp, "macro_gate_hit", args.persistence_window, args.persistence_required_hits, args.min_event_gap_sec)
        events_by_key[key] = events
        rows.append({
            "threshold_percentile": float(p),
            "threshold": thr,
            "normal_test_tubelets": total,
            "false_alarm_tubelets_before_persistence": hits,
            "false_alarm_rate_before_persistence": far,
            "false_alarm_events_after_persistence": int(ev_count),
            "normal_test_videos": int(tmp["video_id"].astype(str).nunique()) if total else 0,
            "normal_test_tracks": int(tmp[["video_id", "track_id"]].drop_duplicates().shape[0]) if total else 0,
        })
    return thresholds, pd.DataFrame(rows), events_by_key


def save_hist(scores: Dict[str, np.ndarray], threshold: float, path: Path) -> None:
    if plt is None:
        return
    plt.figure(figsize=(10, 6))
    for name, vals in scores.items():
        vals = np.asarray(vals, dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        if vals.size:
            plt.hist(vals, bins=80, density=True, alpha=0.45, label=name)
    plt.axvline(threshold, linestyle="--", label=f"threshold={threshold:.4f}")
    plt.xlabel("Macro anomaly score")
    plt.ylabel("Density")
    plt.title("Homography macro GMM score distribution")
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()


def main() -> int:
    args = parse_args()
    out = Path(args.output_dir)
    safe_mkdir_output(out, args.overwrite)
    features_npy, metadata_csv, feature_names_json = resolve_paths(args)

    all_names = load_feature_names(feature_names_json)
    selected = choose_features(all_names, args.selected_features)

    X_all = np.load(features_npy)
    meta = pd.read_csv(metadata_csv)
    if X_all.ndim != 2 or X_all.shape[1] != len(all_names):
        raise ValueError(f"Feature shape mismatch: {X_all.shape}, names={len(all_names)}")
    if len(meta) != X_all.shape[0]:
        raise ValueError(f"Metadata rows {len(meta)} != features rows {X_all.shape[0]}")
    for req in ["video_id", "track_id", "start_time_sec"]:
        if req not in meta.columns:
            raise ValueError(f"metadata missing required column: {req}")

    # Stage-3 audit columns are useful for diagnostics, but they are not part of
    # the GMM feature vector itself. Some earlier 04d builds consumed ground_points_xy
    # correctly but did not write these audit columns to the metadata CSV. Do not fail
    # training in that case; verify the 04d summary used ground_points_xy instead.
    stage3_cols = ["groundpoint_valid_pose_ratio", "groundpoint_frozen_ratio", "groundpoint_bbox_fallback_ratio"]
    missing_stage3_cols = [c for c in stage3_cols if c not in meta.columns]

    summary_path = Path(args.input_dir) / "homography_macro_extraction_summary.json"
    summary_point_field = None
    if summary_path.exists():
        try:
            summary_obj = json.loads(summary_path.read_text(encoding="utf-8"))
            summary_point_field = str(summary_obj.get("settings", {}).get("point_field", ""))
        except Exception:
            summary_point_field = None

    if args.require_stage3_groundpoints:
        if missing_stage3_cols:
            if summary_point_field == "ground_points_xy":
                print(
                    "[WARN] Stage-3 audit metadata columns are missing from metadata CSV: "
                    + ", ".join(missing_stage3_cols)
                    + ". However, homography_macro_extraction_summary.json confirms 04d used point_field=ground_points_xy, so training will continue."
                )
            else:
                raise ValueError(
                    "Stage-3 groundpoint audit metadata is missing: " + ", ".join(missing_stage3_cols) +
                    ". Also could not confirm point_field=ground_points_xy from homography_macro_extraction_summary.json. " +
                    "Rerun 04d with --point_field ground_points_xy or use the fixed 04d/04e pair."
                )

    # Optional quality filters. Defaults keep all rows, but the arguments are useful
    # when a bad pose run produced too many bbox/freeze fallbacks. If audit columns
    # are absent, these filters are skipped because the Stage-3 features can still
    # train correctly from ground_points_xy.
    quality_mask = np.ones(len(meta), dtype=bool)
    if "groundpoint_bbox_fallback_ratio" in meta.columns and float(args.max_bbox_fallback_ratio) < 1.0:
        quality_mask &= pd.to_numeric(meta["groundpoint_bbox_fallback_ratio"], errors="coerce").fillna(1.0).to_numpy() <= float(args.max_bbox_fallback_ratio)
    elif float(args.max_bbox_fallback_ratio) < 1.0:
        print("[WARN] --max_bbox_fallback_ratio ignored because groundpoint_bbox_fallback_ratio is absent from metadata CSV.")
    if "groundpoint_frozen_ratio" in meta.columns and float(args.max_frozen_ratio) < 1.0:
        quality_mask &= pd.to_numeric(meta["groundpoint_frozen_ratio"], errors="coerce").fillna(1.0).to_numpy() <= float(args.max_frozen_ratio)
    elif float(args.max_frozen_ratio) < 1.0:
        print("[WARN] --max_frozen_ratio ignored because groundpoint_frozen_ratio is absent from metadata CSV.")
    dropped_quality_rows = int((~quality_mask).sum())
    if dropped_quality_rows:
        meta = meta.loc[quality_mask].reset_index(drop=True)
        X_all = X_all[quality_mask]

    fdf = pd.DataFrame(X_all, columns=all_names)
    sdf = fdf[selected].copy()
    finite = np.isfinite(sdf.to_numpy(dtype=np.float64)).all(axis=1)
    dropped = int((~finite).sum())
    if dropped:
        meta = meta.loc[finite].reset_index(drop=True)
        sdf = sdf.loc[finite].reset_index(drop=True)
        X_all = X_all[finite]

    split = split_by_video(meta, args.train_ratio, args.calibration_ratio, args.normal_test_ratio, args.random_seed)
    meta = meta.copy()
    meta["split"] = assign_split(meta, split)
    masks = {name: meta["split"].eq(name).to_numpy() for name in ["train", "calibration", "normal_test"]}

    X_raw = sdf.to_numpy(dtype=np.float64)
    X_train_raw = X_raw[masks["train"]]
    X_cal_raw = X_raw[masks["calibration"]]
    X_test_raw = X_raw[masks["normal_test"]]
    if min(len(X_train_raw), len(X_cal_raw), len(X_test_raw)) == 0:
        raise RuntimeError("One split is empty")

    scaler = RobustScaler(quantile_range=(25, 75))
    X_train = scaler.fit_transform(X_train_raw)
    X_cal = scaler.transform(X_cal_raw)
    X_test = scaler.transform(X_test_raw)

    pca = None
    if args.use_pca:
        n_comp = min(int(args.pca_components), X_train.shape[0], X_train.shape[1])
        pca = PCA(n_components=n_comp, random_state=int(args.random_seed))
        X_train = pca.fit_transform(X_train)
        X_cal = pca.transform(X_cal)
        X_test = pca.transform(X_test)

    models, model_df = train_gmms(X_train, args.components_to_test, args)
    primary_k = int(args.primary_components)
    if primary_k not in models:
        primary_k = int(model_df.sort_values("bic").iloc[0]["components"])
    model = models[primary_k]

    train_raw = score_model(model, X_train)
    cal_raw = score_model(model, X_cal)
    test_raw = score_model(model, X_test)

    meta_train = meta.loc[masks["train"]].reset_index(drop=True)
    meta_cal = meta.loc[masks["calibration"]].reset_index(drop=True)
    meta_test = meta.loc[masks["normal_test"]].reset_index(drop=True)
    sdf_train = sdf.loc[masks["train"]].reset_index(drop=True)
    sdf_cal = sdf.loc[masks["calibration"]].reset_index(drop=True)
    sdf_test = sdf.loc[masks["normal_test"]].reset_index(drop=True)

    tmp_train = meta_train.copy(); tmp_train["macro_score_raw"] = train_raw
    tmp_cal = meta_cal.copy(); tmp_cal["macro_score_raw"] = cal_raw
    tmp_test = meta_test.copy(); tmp_test["macro_score_raw"] = test_raw
    train_smooth = smooth_grouped(tmp_train, "macro_score_raw", args.smoothing_sigma)
    cal_smooth = smooth_grouped(tmp_cal, "macro_score_raw", args.smoothing_sigma)
    test_smooth = smooth_grouped(tmp_test, "macro_score_raw", args.smoothing_sigma)

    train_df = build_score_df(meta_train, sdf_train, "train", train_raw, train_smooth)
    cal_df = build_score_df(meta_cal, sdf_cal, "calibration", cal_raw, cal_smooth)
    test_df = build_score_df(meta_test, sdf_test, "normal_test", test_raw, test_smooth)

    thresholds, fa_df, events_by_key = make_threshold_report(cal_smooth, test_df, args.threshold_percentiles, args)
    pkey = f"p{str(args.primary_threshold_percentile).replace('.', '_')}"
    if pkey not in thresholds:
        pkey = min(thresholds, key=lambda k: abs(float(thresholds[k]["percentile"]) - float(args.primary_threshold_percentile)))
    primary_threshold = float(thresholds[pkey]["threshold"])

    for df in [train_df, cal_df, test_df]:
        df["macro_gate_hit"] = df["macro_score_smooth"] > primary_threshold

    model_df.to_csv(out / "diagnostics" / "macro_gmm_model_selection.csv", index=False, encoding="utf-8-sig")
    train_df.to_csv(out / "scores" / "train_macro_scores.csv", index=False, encoding="utf-8-sig")
    cal_df.to_csv(out / "scores" / "calibration_macro_scores.csv", index=False, encoding="utf-8-sig")
    test_df.to_csv(out / "scores" / "normal_test_macro_scores.csv", index=False, encoding="utf-8-sig")
    fa_df.to_csv(out / "05_macro_false_alarm_report.csv", index=False, encoding="utf-8-sig")
    test_df.sort_values("macro_score_smooth", ascending=False).head(100).to_csv(out / "06_top_abnormal_macro_tubelets.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(events_by_key.get(pkey, [])).to_csv(out / "scores" / "normal_test_macro_events_primary.csv", index=False, encoding="utf-8-sig")

    joblib.dump(scaler, out / "models" / "macro_robust_scaler.joblib")
    if pca is not None:
        joblib.dump(pca, out / "models" / "macro_pca.joblib")
    for k, m in models.items():
        joblib.dump(m, out / "models" / f"macro_gmm_components_{k}.joblib")

    split_counts = {
        name: {"videos": int(meta.loc[mask, "video_id"].astype(str).nunique()), "tubelets": int(mask.sum())}
        for name, mask in masks.items()
    }
    primary_row = fa_df.loc[fa_df["threshold_percentile"].astype(float).sub(float(thresholds[pkey]["percentile"])).abs().idxmin()].to_dict()
    tubelet_far = float(primary_row["false_alarm_rate_before_persistence"])
    event_count = int(primary_row["false_alarm_events_after_persistence"])
    if event_count == 0 and tubelet_far <= 0.01:
        verdict = "promising_low_false_alarm_on_normal_test"
    elif tubelet_far <= 0.05:
        verdict = "usable_but_needs_visual_review"
    else:
        verdict = "too_many_false_alarms_or_threshold_too_low"

    write_json(out / "04_macro_thresholds.json", {
        "schema_version": SCHEMA_VERSION,
        "thresholds": thresholds,
        "primary_threshold_key": pkey,
        "primary_threshold_percentile": thresholds[pkey]["percentile"],
        "primary_threshold": primary_threshold,
        "score_direction": "higher_is_more_anomalous",
        "threshold_source": "calibration_macro_score_smooth",
    })

    write_json(out / "07_macro_suitability_report.json", {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "important_warning": "Normal-only false alarms do not prove anomaly recall. Visually inspect top-scoring normal tubelets and test abnormal clips.",
        "homography_units_warning": "If the homography used arbitrary 8x6 floor units, do not call scores exact m/s.",
        "primary_threshold": primary_threshold,
        "primary_false_alarm_report": primary_row,
        "selected_features": selected,
        "excluded_spiky_features": RISKY_SPIKY_FEATURES,
        "stage3_groundpoint_columns_present": [c for c in stage3_cols if c in meta.columns],
        "missing_stage3_groundpoint_columns": missing_stage3_cols,
        "dropped_quality_rows": dropped_quality_rows,
        "max_bbox_fallback_ratio": float(args.max_bbox_fallback_ratio),
        "max_frozen_ratio": float(args.max_frozen_ratio),
    })

    write_json(out / "09_recommended_macro_gate.json", {
        "schema_version": SCHEMA_VERSION,
        "branch_name": "homography_macro_gate",
        "model_type": "RobustScaler + PCA + GMM" if pca is not None else "RobustScaler + GMM",
        "input_features": selected,
        "expected_point_field": "ground_points_xy",
        "expected_groundpoint_policy": "ankle_midpoint_or_single_ankle_else_freeze_last_valid_else_bbox_bottom",
        "offline_feature_contract": {
            "trajectory_smoothing": "median_savgol",
            "trajectory_smoothing_window": 5,
            "trajectory_smoothing_polyorder": 2,
            "max_plausible_speed_mps": 3.0,
            "max_plausible_accel_mps2": 6.0
        },
        "split_unit": "video_id",
        "split": split,
        "split_counts": split_counts,
        "primary_components": primary_k,
        "covariance_type": args.covariance_type,
        "reg_covar": args.reg_covar,
        "use_pca": bool(pca is not None),
        "pca_components": int(pca.n_components_) if pca is not None else None,
        "smoothing_sigma": float(args.smoothing_sigma),
        "threshold_source": "calibration split only",
        "threshold_percentile": float(thresholds[pkey]["percentile"]),
        "threshold": primary_threshold,
        "persistence_window": int(args.persistence_window),
        "persistence_required_hits": int(args.persistence_required_hits),
        "min_event_gap_sec": float(args.min_event_gap_sec),
        "normal_test_result": primary_row,
        "verdict": verdict,
        "model_paths": {
            "scaler": str(out / "models" / "macro_robust_scaler.joblib"),
            "pca": str(out / "models" / "macro_pca.joblib") if pca is not None else None,
            "gmm": str(out / "models" / f"macro_gmm_components_{primary_k}.joblib"),
        },
    })

    write_json(out / "01_macro_gmm_training_summary.json", {
        "script": Path(__file__).name,
        "schema_version": SCHEMA_VERSION,
        "created_at_unix": time.time(),
        "input_dir": str(args.input_dir),
        "output_dir": str(out),
        "total_rows_after_filtering": int(len(meta)),
        "dropped_nonfinite_rows": dropped,
        "dropped_quality_rows": dropped_quality_rows,
        "all_feature_dim": int(X_all.shape[1]),
        "selected_features": selected,
        "split_counts": split_counts,
        "settings": vars(args),
        "primary_components": primary_k,
        "primary_threshold_key": pkey,
        "primary_threshold": primary_threshold,
        "primary_false_alarm_report": primary_row,
        "verdict": verdict,
    })

    write_json(out / "diagnostics" / "selected_feature_stats.json", sdf.describe().to_dict())
    write_json(out / "diagnostics" / "score_stats.json", {
        "train_smooth": pd.Series(train_smooth).describe().to_dict(),
        "calibration_smooth": pd.Series(cal_smooth).describe().to_dict(),
        "normal_test_smooth": pd.Series(test_smooth).describe().to_dict(),
    })

    if args.make_plots:
        save_hist({"train": train_smooth, "calibration": cal_smooth, "normal_test": test_smooth}, primary_threshold, out / "plots" / "macro_score_histogram.png")

    print("\nDone.")
    print(f"Selected features: {selected}")
    print(f"Split counts: {split_counts}")
    print(f"Primary GMM components: {primary_k}")
    print(f"Primary threshold {pkey}: {primary_threshold:.6f}")
    print("Primary normal-test result:")
    for k, v in primary_row.items():
        print(f"  {k}: {v}")
    print(f"Verdict: {verdict}")
    print(f"Recommended gate: {out / '09_recommended_macro_gate.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
