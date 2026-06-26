#!/usr/bin/env python3
r"""
Deep Branch V2 Distribution Builder for PERSON-ONLY VideoMAE embeddings.

CAUSAL-SMOOTHED-THRESHOLDS VERSION: computes raw and matching causal-smoothed calibration thresholds.

CAUSAL-FIXED VERSION: offline Gaussian smoothing now matches backend OnlineGateState.

This script intentionally implements ONLY the deep branch:
  - NO pose branch
  - NO velocity branch
  - NO PCA/Mahalanobis branch yet
  - NO k-means/prototype branch yet

Input expected from your extraction folder:
  processed_dataset_direct_2p5fps_6sec_person_only_stride8/
    embeddings/
      person_embeddings.npy
      direct_embedding_metadata.csv
      direct_extraction_summary.json   optional

Main logic:
  1) Load person_embeddings.npy + direct_embedding_metadata.csv
  2) Validate alignment and remove invalid rows
  3) Split by video_id into train / calibration / normal-test
  4) L2-normalize embeddings
  5) Fit kNN memory bank on TRAIN only
  6) Score CALIBRATION and NORMAL-TEST splits
  7) Build thresholds from CALIBRATION only
  8) Evaluate raw scores, Gaussian-smoothed scores, and Gaussian-smoothed+persistence events on NORMAL-TEST only
  9) Save artifacts, reports, score CSVs, top abnormal normal tubelets, and a VideoMAE suitability report

Example:
  python scripts\03b_build_deep_branch_distribution_v2_gaussian.py ^
    --processed_dir "D:\Embeddings_Distribution\processed_dataset_direct_2p5fps_6sec_person_only_stride8" ^
    --output_dir "D:\Embeddings_Distribution\processed_dataset_direct_2p5fps_6sec_person_only_stride8\deep_branch_artifacts_v2_gaussian" ^
    --primary_k 5 ^
    --primary_threshold_percentile 99.5
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    from sklearn.neighbors import NearestNeighbors
except Exception as exc:  # pragma: no cover
    raise SystemExit("scikit-learn is required. Install with: pip install scikit-learn") from exc

try:
    import joblib
except Exception:  # pragma: no cover
    joblib = None

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None


DEFAULT_PROCESSED_DIR = Path(r"D:\Embeddings_Distribution\processed_dataset_direct_2p5fps_6sec_person_only_stride8")
DEFAULT_OUTPUT_NAME = "deep_branch_artifacts_v2_gaussian"


@dataclass
class RunConfig:
    expected_embedding_dim: int
    split_unit: str
    train_ratio: float
    calibration_ratio: float
    normal_test_ratio: float
    random_seed: int
    normalization: str
    l2_epsilon: float
    k_values: List[int]
    primary_k: int
    distance_metric: str
    score_method: str
    threshold_percentiles: List[float]
    primary_threshold_percentile: float
    persistence_window: int
    persistence_required_hits: int
    min_event_gap_sec: float
    gaussian_sigmas: List[float]
    selected_gaussian_sigma: float
    scoring_batch_size: int
    top_n_abnormal_normal: int


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_pickle(path: Path, obj) -> None:
    ensure_dir(path.parent)
    if joblib is not None:
        joblib.dump(obj, path)
    else:
        with path.open("wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def percentile_key(p: float) -> str:
    # 99.5 -> p99_5, 99 -> p99
    s = ("%g" % float(p)).replace(".", "_")
    return f"p{s}"


def parse_percentiles(text: str) -> List[float]:
    vals = []
    for item in text.split(","):
        item = item.strip()
        if item:
            vals.append(float(item))
    if not vals:
        raise ValueError("At least one percentile is required")
    return vals


def parse_k_values(text: str) -> List[int]:
    vals = []
    for item in text.split(","):
        item = item.strip()
        if item:
            vals.append(int(item))
    vals = sorted(set(vals))
    if not vals:
        raise ValueError("At least one k value is required")
    return vals



def parse_float_values(text: str) -> List[float]:
    vals: List[float] = []
    for item in text.split(","):
        item = item.strip()
        if item:
            vals.append(float(item))
    vals = sorted(set(vals))
    if not vals:
        raise ValueError("At least one float value is required")
    return vals

def l2_normalize(x: np.ndarray, eps: float) -> Tuple[np.ndarray, np.ndarray]:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    safe = np.maximum(norms, eps)
    return (x / safe).astype(np.float32), norms.reshape(-1)


def validate_and_align(emb: np.ndarray, meta: pd.DataFrame, expected_dim: int) -> Tuple[np.ndarray, pd.DataFrame, dict]:
    report: Dict[str, object] = {}
    report["raw_embedding_shape"] = list(emb.shape)
    report["raw_metadata_rows"] = int(len(meta))

    if emb.ndim != 2:
        raise ValueError(f"Expected embeddings to be 2-D, got shape {emb.shape}")
    if emb.shape[1] != expected_dim:
        raise ValueError(f"Expected embedding dim={expected_dim}, got {emb.shape[1]}")

    if "person_embedding_index" in meta.columns:
        idx = pd.to_numeric(meta["person_embedding_index"], errors="coerce")
        valid_idx = idx.notna() & (idx >= 0) & (idx < emb.shape[0])
        report["metadata_rows_with_valid_person_embedding_index"] = int(valid_idx.sum())
        meta = meta.loc[valid_idx].copy()
        meta["person_embedding_index"] = idx.loc[valid_idx].astype(int).values
        emb = emb[meta["person_embedding_index"].values]
        # After alignment, make local row index explicit for downstream use.
        meta["aligned_embedding_index"] = np.arange(len(meta), dtype=int)
    else:
        if len(meta) != emb.shape[0]:
            raise ValueError(
                "Metadata has no person_embedding_index and row count does not match embeddings: "
                f"metadata={len(meta)}, embeddings={emb.shape[0]}"
            )
        meta = meta.copy()
        meta["person_embedding_index"] = np.arange(len(meta), dtype=int)
        meta["aligned_embedding_index"] = np.arange(len(meta), dtype=int)

    if len(meta) != emb.shape[0]:
        raise ValueError(f"Alignment failed: metadata={len(meta)}, embeddings={emb.shape[0]}")

    finite_mask = np.isfinite(emb).all(axis=1)
    norms = np.linalg.norm(emb, axis=1)
    stds = np.std(emb, axis=1)
    norm_mask = norms > 1e-8
    std_mask = stds > 1e-10

    person_valid_mask = np.ones(len(meta), dtype=bool)
    if "person_valid" in meta.columns:
        vals = meta["person_valid"].astype(str).str.lower().str.strip()
        person_valid_mask = vals.isin(["true", "1", "yes", "y"]).values

    valid_mask = finite_mask & norm_mask & std_mask & person_valid_mask

    report["aligned_rows_before_cleaning"] = int(len(meta))
    report["removed_non_finite"] = int((~finite_mask).sum())
    report["removed_near_zero_norm"] = int((~norm_mask).sum())
    report["removed_near_zero_std"] = int((~std_mask).sum())
    report["removed_person_valid_false"] = int((~person_valid_mask).sum())
    report["rows_after_cleaning"] = int(valid_mask.sum())

    emb_clean = emb[valid_mask].astype(np.float32, copy=False)
    meta_clean = meta.loc[valid_mask].copy().reset_index(drop=True)
    meta_clean["clean_embedding_index"] = np.arange(len(meta_clean), dtype=int)

    clean_norms = np.linalg.norm(emb_clean, axis=1)
    report["embedding_norm_min"] = float(np.min(clean_norms)) if len(clean_norms) else None
    report["embedding_norm_max"] = float(np.max(clean_norms)) if len(clean_norms) else None
    report["embedding_norm_mean"] = float(np.mean(clean_norms)) if len(clean_norms) else None
    report["embedding_norm_median"] = float(np.median(clean_norms)) if len(clean_norms) else None
    report["embedding_norm_std"] = float(np.std(clean_norms)) if len(clean_norms) else None

    required = ["video_id", "track_id", "start_frame", "end_frame"]
    missing = [c for c in required if c not in meta_clean.columns]
    report["missing_recommended_metadata_columns"] = missing
    if "video_id" not in meta_clean.columns:
        raise ValueError("direct_embedding_metadata.csv must contain video_id for leakage-safe splitting")

    return emb_clean, meta_clean, report


def split_by_video(
    meta: pd.DataFrame,
    train_ratio: float,
    calibration_ratio: float,
    normal_test_ratio: float,
    seed: int,
) -> Tuple[pd.DataFrame, dict]:
    ratios_sum = train_ratio + calibration_ratio + normal_test_ratio
    if not math.isclose(ratios_sum, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError(f"Ratios must sum to 1.0, got {ratios_sum}")

    videos = sorted(meta["video_id"].astype(str).unique().tolist())
    if len(videos) < 3:
        raise ValueError(f"Need at least 3 unique video_id values for train/calibration/normal-test split. Found {len(videos)}")

    rng = np.random.default_rng(seed)
    videos_arr = np.array(videos, dtype=object)
    rng.shuffle(videos_arr)
    n = len(videos_arr)

    n_train = max(1, int(round(n * train_ratio)))
    n_cal = max(1, int(round(n * calibration_ratio)))
    # guarantee at least one test video
    if n_train + n_cal >= n:
        n_train = max(1, n - 2)
        n_cal = 1
    n_test = n - n_train - n_cal
    if n_test < 1:
        raise ValueError("Split failed to allocate at least one normal-test video")

    train_videos = set(videos_arr[:n_train].tolist())
    cal_videos = set(videos_arr[n_train:n_train + n_cal].tolist())
    test_videos = set(videos_arr[n_train + n_cal:].tolist())

    split = []
    for vid in meta["video_id"].astype(str):
        if vid in train_videos:
            split.append("train")
        elif vid in cal_videos:
            split.append("calibration")
        elif vid in test_videos:
            split.append("normal_test")
        else:
            raise RuntimeError(f"Unassigned video_id: {vid}")

    meta_out = meta.copy()
    meta_out["split"] = split

    report = {
        "split_unit": "video_id",
        "random_seed": int(seed),
        "total_videos": int(n),
        "train_videos": sorted(train_videos),
        "calibration_videos": sorted(cal_videos),
        "normal_test_videos": sorted(test_videos),
        "train_video_count": len(train_videos),
        "calibration_video_count": len(cal_videos),
        "normal_test_video_count": len(test_videos),
        "train_rows": int((meta_out["split"] == "train").sum()),
        "calibration_rows": int((meta_out["split"] == "calibration").sum()),
        "normal_test_rows": int((meta_out["split"] == "normal_test").sum()),
    }
    return meta_out, report


def score_knn_in_batches(
    nbrs: NearestNeighbors,
    x: np.ndarray,
    k_values: Sequence[int],
    batch_size: int,
) -> Dict[int, np.ndarray]:
    max_k = int(max(k_values))
    scores = {int(k): np.empty((x.shape[0],), dtype=np.float32) for k in k_values}

    for start in range(0, x.shape[0], batch_size):
        end = min(start + batch_size, x.shape[0])
        distances, _ = nbrs.kneighbors(x[start:end], n_neighbors=max_k, return_distance=True)
        distances = distances.astype(np.float32, copy=False)
        for k in k_values:
            scores[int(k)][start:end] = distances[:, :int(k)].mean(axis=1)
    return scores


def make_scores_frame(meta: pd.DataFrame, scores_by_k: Dict[int, np.ndarray]) -> pd.DataFrame:
    cols = [
        "tubelet_id", "video_path", "video_id", "track_id", "start_frame", "end_frame",
        "start_time_sec", "end_time_sec", "clip_span_sec", "clip_duration_sec",
        "mean_conf", "min_conf", "mean_bbox_area_ratio", "mean_iou", "max_center_jump_ratio",
        "split",
    ]
    existing_cols = [c for c in cols if c in meta.columns]
    out = meta[existing_cols].copy()
    for k, scores in scores_by_k.items():
        out[f"deep_knn_score_k{k}"] = scores.astype(float)
    return out


def compute_thresholds(cal_scores_by_k: Dict[int, np.ndarray], percentiles: Sequence[float]) -> dict:
    thresholds: Dict[str, Dict[str, float]] = {}
    for k, scores in cal_scores_by_k.items():
        finite = scores[np.isfinite(scores)]
        if finite.size == 0:
            raise ValueError(f"No finite calibration scores for k={k}")
        thresholds[f"k{k}"] = {percentile_key(p): float(np.percentile(finite, p)) for p in percentiles}
    return thresholds


def compute_thresholds_from_scores_frame(
    scores_df: pd.DataFrame,
    k_values: Sequence[int],
    percentiles: Sequence[float],
    *,
    mode_name: str,
    column_suffix: str = "",
) -> dict:
    """Compute thresholds from score columns in a DataFrame.

    mode_name examples:
      - raw
      - gaussian_sigma_1
      - gaussian_sigma_2
    column_suffix examples:
      - "" for raw columns: deep_knn_score_k5
      - "_gauss_s2_0" for smoothed columns: deep_knn_score_k5_gauss_s2_0
    """
    thresholds: Dict[str, Dict[str, float]] = {}
    for k in k_values:
        col = f"deep_knn_score_k{int(k)}{column_suffix}"
        if col not in scores_df.columns:
            raise KeyError(f"Missing score column for threshold computation: {col}")
        scores = pd.to_numeric(scores_df[col], errors="coerce").values.astype(float)
        finite = scores[np.isfinite(scores)]
        if finite.size == 0:
            raise ValueError(f"No finite {mode_name} calibration scores for k={k}")
        thresholds[f"k{int(k)}"] = {percentile_key(p): float(np.percentile(finite, p)) for p in percentiles}
    return thresholds


def get_threshold_for_mode(threshold_groups: dict, mode_key: str, k: int, pkey: str) -> float:
    """Read a threshold from threshold_groups[mode_key][kX][pYY]."""
    if mode_key not in threshold_groups:
        raise KeyError(f"Threshold mode not found: {mode_key}")
    mode_block = threshold_groups[mode_key]
    k_block = mode_block.get(f"k{int(k)}")
    if not isinstance(k_block, dict):
        raise KeyError(f"Threshold k block not found: mode={mode_key} k={k}")
    if pkey not in k_block:
        raise KeyError(f"Threshold percentile not found: mode={mode_key} k={k} key={pkey}")
    return float(k_block[pkey])



def _extract_order_times(g: pd.DataFrame) -> np.ndarray:
    if "start_time_sec" in g.columns:
        series = pd.to_numeric(g["start_time_sec"], errors="coerce").ffill().fillna(0)
        return series.values.astype(float)
    if "start_frame" in g.columns:
        series = pd.to_numeric(g["start_frame"], errors="coerce").ffill().fillna(0)
        return series.values.astype(float)
    return np.arange(len(g), dtype=float)


def gaussian_kernel1d(sigma: float, truncate: float = 3.0) -> np.ndarray:
    sigma = float(sigma)
    if sigma <= 0:
        return np.array([1.0], dtype=np.float64)
    radius = max(1, int(round(truncate * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x ** 2) / (2.0 * sigma ** 2))
    kernel /= kernel.sum()
    return kernel


def smooth_scores_per_video(
    scores_df: pd.DataFrame,
    score_col: str,
    sigma: float,
    out_col: str,
) -> pd.DataFrame:
    """Apply strictly CAUSAL Gaussian smoothing per video.

    This mirrors backend OnlineGateState._causal_gaussian_latest():
    - uses only past + current scores
    - radius = ceil(3 * sigma)
    - d=0 is the current score, older scores receive smaller weights
    """
    out = scores_df.copy()
    out[out_col] = np.nan

    for _, g in out.groupby("video_id", sort=False):
        sort_col = "start_time_sec" if "start_time_sec" in g.columns else "start_frame" if "start_frame" in g.columns else None
        if sort_col:
            g_sorted = g.sort_values(sort_col)
        else:
            g_sorted = g

        vals = pd.to_numeric(g_sorted[score_col], errors="coerce").ffill().bfill().fillna(0).values.astype(float)
        if len(vals) == 0:
            continue

        if sigma <= 0 or len(vals) == 1:
            smoothed = vals
        else:
            radius = int(max(1, math.ceil(3.0 * float(sigma))))
            smoothed = np.zeros_like(vals, dtype=np.float64)

            for i in range(len(vals)):
                start_idx = max(0, i - radius)
                recent = vals[start_idx : i + 1]

                d = np.arange(len(recent) - 1, -1, -1, dtype=np.float64)
                w = np.exp(-(d ** 2) / (2.0 * float(sigma) * float(sigma)))
                w /= max(float(w.sum()), 1e-12)
                smoothed[i] = float(np.sum(recent * w))

        out.loc[g_sorted.index, out_col] = smoothed.astype(float)

    return out



def count_persistence_events_for_hits(
    df: pd.DataFrame,
    hits_col: str,
    persistence_window: int,
    persistence_required_hits: int,
    min_event_gap_sec: float,
) -> Tuple[int, int, Dict[str, int]]:
    event_count = 0
    max_streak = 0
    video_event_counts: Dict[str, int] = {}

    for video_id, g in df.groupby("video_id", sort=True):
        sort_col = "start_time_sec" if "start_time_sec" in g.columns else "start_frame" if "start_frame" in g.columns else None
        if sort_col:
            g = g.sort_values(sort_col)
        h = g[hits_col].astype(bool).values

        cur = 0
        local_max = 0
        for val in h:
            if val:
                cur += 1
                local_max = max(local_max, cur)
            else:
                cur = 0
        max_streak = max(max_streak, local_max)

        times = _extract_order_times(g)
        last_event_time = -1e18
        local_events = 0
        for i in range(len(h)):
            start = max(0, i - persistence_window + 1)
            if int(h[start:i + 1].sum()) >= persistence_required_hits:
                t = float(times[i])
                if t - last_event_time >= min_event_gap_sec:
                    local_events += 1
                    last_event_time = t
        video_event_counts[str(video_id)] = int(local_events)
        event_count += int(local_events)

    return int(event_count), int(max_streak), video_event_counts


def evaluate_thresholds_v2(
    test_scores_df: pd.DataFrame,
    threshold_groups: dict,
    k_values: Sequence[int],
    percentiles: Sequence[float],
    gaussian_sigmas: Sequence[float],
    persistence_window: int,
    persistence_required_hits: int,
    min_event_gap_sec: float,
) -> Tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Evaluate raw and causal-Gaussian score modes against MATCHING thresholds.

    This version is intentionally different from the old builder:
      - raw scores are evaluated against raw calibration thresholds
      - gaussian_sigma_X scores are evaluated against gaussian_sigma_X calibration thresholds

    This avoids comparing flattened smoothed scores to higher raw thresholds.
    """
    work_df = test_scores_df.copy()

    # Add causal Gaussian-smoothed score columns per k/sigma.
    for k in k_values:
        raw_col = f"deep_knn_score_k{k}"
        for sigma in gaussian_sigmas:
            suffix = str(float(sigma)).replace('.', '_')
            out_col = f"deep_knn_score_k{k}_gauss_s{suffix}"
            work_df = smooth_scores_per_video(work_df, raw_col, float(sigma), out_col)

    rows = []
    detailed = {}
    total = len(work_df)

    modes = [("raw", None)] + [(f"gaussian_sigma_{float(s):g}", float(s)) for s in gaussian_sigmas]

    for k in k_values:
        detailed[f"k{k}"] = {}
        for mode_key, sigma in modes:
            score_col = f"deep_knn_score_k{k}" if mode_key == "raw" else f"deep_knn_score_k{k}_gauss_s{str(float(sigma)).replace('.', '_')}"
            if score_col not in work_df.columns:
                continue
            scores = pd.to_numeric(work_df[score_col], errors="coerce").values.astype(float)
            detailed[f"k{k}"][mode_key] = {}

            for p in percentiles:
                pkey = percentile_key(p)
                th = get_threshold_for_mode(threshold_groups, mode_key, int(k), pkey)
                hits = np.isfinite(scores) & (scores > th)
                false_alarm_tubelets = int(hits.sum())
                false_alarm_rate = 100.0 * false_alarm_tubelets / max(1, total)

                hit_col = f"_hit_k{k}_{mode_key}_{pkey}"
                eval_df = work_df.copy()
                eval_df[hit_col] = hits
                event_count, max_streak, video_event_counts = count_persistence_events_for_hits(
                    eval_df,
                    hit_col,
                    persistence_window,
                    persistence_required_hits,
                    min_event_gap_sec,
                )

                row = {
                    "k": int(k),
                    "score_mode": mode_key,
                    "threshold_source_mode": mode_key,
                    "gaussian_sigma_tubelets": "" if sigma is None else float(sigma),
                    "threshold_percentile": float(p),
                    "threshold_key": pkey,
                    "threshold_value": th,
                    "normal_test_tubelets": int(total),
                    "false_alarm_tubelets_before_persistence": false_alarm_tubelets,
                    "false_alarm_rate_percent_before_persistence": false_alarm_rate,
                    "max_false_alarm_streak_before_persistence": int(max_streak),
                    "persistence_window": int(persistence_window),
                    "persistence_required_hits": int(persistence_required_hits),
                    "min_event_gap_sec": float(min_event_gap_sec),
                    "false_alarm_events_after_persistence": int(event_count),
                }
                rows.append(row)
                detailed[f"k{k}"][mode_key][pkey] = {**row, "video_event_counts": video_event_counts}

    return pd.DataFrame(rows), detailed, work_df



def ks_2sample_np(a: np.ndarray, b: np.ndarray) -> float:
    """Small dependency-free two-sample KS statistic."""
    a = np.sort(a[np.isfinite(a)])
    b = np.sort(b[np.isfinite(b)])
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    vals = np.sort(np.concatenate([a, b]))
    cdf_a = np.searchsorted(a, vals, side="right") / len(a)
    cdf_b = np.searchsorted(b, vals, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


def pearson_abs(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 3:
        return float("nan")
    x = x[m]
    y = y[m]
    sx = float(np.std(x))
    sy = float(np.std(y))
    if sx < 1e-12 or sy < 1e-12:
        return float("nan")
    return float(abs(np.corrcoef(x, y)[0, 1]))


def build_videomae_suitability_report(
    validation_report: dict,
    split_report: dict,
    cal_scores_df: pd.DataFrame,
    normal_test_scores_df: pd.DataFrame,
    false_alarm_df: pd.DataFrame,
    primary_k: int,
    primary_threshold_key: str,
    selected_gaussian_sigma: float,
    top_n: int = 100,
) -> dict:
    """Heuristic evidence report: are the embeddings useful or mostly artifacts?"""
    raw_col = f"deep_knn_score_k{primary_k}"
    smooth_col = f"deep_knn_score_k{primary_k}_gauss_s{str(float(selected_gaussian_sigma)).replace('.', '_')}"
    score_col = smooth_col if smooth_col in normal_test_scores_df.columns else raw_col

    cal = pd.to_numeric(cal_scores_df[raw_col], errors="coerce").values.astype(float)
    test_raw = pd.to_numeric(normal_test_scores_df[raw_col], errors="coerce").values.astype(float)
    test_sel = pd.to_numeric(normal_test_scores_df[score_col], errors="coerce").values.astype(float)

    cal_med = float(np.nanmedian(cal))
    test_med = float(np.nanmedian(test_raw))
    cal_p99 = float(np.nanpercentile(cal, 99))
    test_p99 = float(np.nanpercentile(test_raw, 99))
    ks = ks_2sample_np(cal, test_raw)

    selected_rows = false_alarm_df[
        (false_alarm_df["k"] == primary_k) &
        (false_alarm_df["threshold_key"] == primary_threshold_key) &
        (false_alarm_df["score_mode"] == f"gaussian_sigma_{selected_gaussian_sigma:g}")
    ]
    if len(selected_rows) == 0:
        selected_rows = false_alarm_df[
            (false_alarm_df["k"] == primary_k) &
            (false_alarm_df["threshold_key"] == primary_threshold_key) &
            (false_alarm_df["score_mode"] == "raw")
        ]
    selected_eval = selected_rows.iloc[0].to_dict() if len(selected_rows) else {}

    quality_cols = [
        "mean_conf", "min_conf", "mean_bbox_area_ratio", "mean_iou", "max_center_jump_ratio", "clip_span_sec", "clip_duration_sec"
    ]
    artifact_corr = {}
    for c in quality_cols:
        if c in normal_test_scores_df.columns:
            artifact_corr[c] = pearson_abs(test_sel, pd.to_numeric(normal_test_scores_df[c], errors="coerce").values)
    finite_corr = {k: v for k, v in artifact_corr.items() if np.isfinite(v)}
    max_artifact_corr = max(finite_corr.values()) if finite_corr else float("nan")

    top = normal_test_scores_df.sort_values(score_col, ascending=False).head(top_n)
    top_video_counts = top["video_id"].astype(str).value_counts().head(10).to_dict() if "video_id" in top.columns else {}
    top_track_counts = top[["video_id", "track_id"]].astype(str).agg("|".join, axis=1).value_counts().head(10).to_dict() if {"video_id", "track_id"}.issubset(top.columns) else {}
    top_video_concentration = float(max(top_video_counts.values()) / max(1, len(top))) if top_video_counts else float("nan")

    passed = []
    warnings = []
    failed = []

    valid_rows = validation_report.get("rows_after_cleaning", 0)
    removed_total = validation_report.get("aligned_rows_before_cleaning", valid_rows) - valid_rows
    removal_rate = removed_total / max(1, validation_report.get("aligned_rows_before_cleaning", valid_rows))
    if removal_rate <= 0.01:
        passed.append("Embedding validity is clean: less than or equal to 1% removed during validation.")
    elif removal_rate <= 0.05:
        warnings.append("Some embeddings were removed during validation; inspect 00_input_validation.json.")
    else:
        failed.append("Too many embeddings were invalid/removed; extraction may be unreliable.")

    if np.isfinite(ks) and ks <= 0.15:
        passed.append("Calibration and normal-test score distributions are similar; threshold transfer looks stable.")
    elif np.isfinite(ks) and ks <= 0.30:
        warnings.append("Calibration and normal-test score distributions differ moderately; threshold may be scene-sensitive.")
    else:
        failed.append("Calibration and normal-test score distributions differ strongly; VideoMAE scores may be scene/camera biased.")

    events = selected_eval.get("false_alarm_events_after_persistence", None)
    rate = selected_eval.get("false_alarm_rate_percent_before_persistence", selected_eval.get("raw_false_alarm_rate_percent", None))
    if events is not None and int(events) == 0:
        passed.append("Selected threshold produced zero persistent false-alarm events on held-out normal videos.")
    elif events is not None and int(events) <= 2:
        warnings.append("Selected threshold produced a small number of persistent false-alarm events; may still be usable after preview inspection.")
    else:
        failed.append("Selected threshold produced too many persistent false-alarm events on held-out normal videos.")

    if np.isfinite(max_artifact_corr) and max_artifact_corr < 0.25:
        passed.append("Deep scores are not strongly correlated with obvious detection-quality metadata.")
    elif np.isfinite(max_artifact_corr) and max_artifact_corr < 0.40:
        warnings.append("Deep scores have moderate correlation with detection-quality metadata; inspect top abnormal clips for crop/tracking artifacts.")
    else:
        failed.append("Deep scores correlate strongly with detection-quality metadata; VideoMAE may be reacting to detector/tracker artifacts.")

    if np.isfinite(top_video_concentration) and top_video_concentration <= 0.50:
        passed.append("Top abnormal-normal tubelets are not dominated by one video.")
    elif np.isfinite(top_video_concentration) and top_video_concentration <= 0.80:
        warnings.append("Top abnormal-normal tubelets are concentrated in a few videos; inspect whether these videos contain unusual normal behavior or scene bias.")
    else:
        failed.append("Top abnormal-normal tubelets are heavily dominated by one video; threshold may be scene-specific or that video may contain unusual normal behavior.")

    # Conservative overall verdict. Visual inspection remains mandatory because there are no labeled anomalies here.
    if failed:
        verdict = "not_proven_or_problematic"
    elif len(warnings) >= 2:
        verdict = "promising_but_requires_visual_preview"
    else:
        verdict = "promising_for_deep_branch"

    return {
        "verdict": verdict,
        "important_limit": "This is normal-only validation. It can prove stability and low false alarms, but it cannot prove anomaly recall without abnormal test clips or visual inspection of top outliers.",
        "primary_k": int(primary_k),
        "selected_score_column": score_col,
        "selected_gaussian_sigma_tubelets": float(selected_gaussian_sigma),
        "calibration_vs_normal_test": {
            "calibration_median_raw": cal_med,
            "normal_test_median_raw": test_med,
            "median_ratio_test_over_calibration": float(test_med / cal_med) if abs(cal_med) > 1e-12 else None,
            "calibration_p99_raw": cal_p99,
            "normal_test_p99_raw": test_p99,
            "p99_ratio_test_over_calibration": float(test_p99 / cal_p99) if abs(cal_p99) > 1e-12 else None,
            "ks_statistic_raw": ks,
        },
        "selected_false_alarm_evaluation": selected_eval,
        "artifact_correlation_abs_pearson": artifact_corr,
        "max_artifact_correlation_abs_pearson": max_artifact_corr,
        "top_abnormal_normal_concentration": {
            "top_n": int(len(top)),
            "top_video_counts": top_video_counts,
            "top_track_counts": top_track_counts,
            "top_video_concentration": top_video_concentration,
        },
        "passed_checks": passed,
        "warnings": warnings,
        "failed_checks": failed,
        "how_to_decide_if_videomae_is_right": [
            "Held-out normal videos should have low persistent false alarms.",
            "Calibration and normal-test score distributions should be similar, not shifted by scene/camera.",
            "High scores should not be strongly explained by low confidence, tiny boxes, bad IoU, or track jumps.",
            "Top abnormal-normal tubelets must look visually unusual or semantically difficult, not merely broken crops.",
            "When abnormal test clips are available, their smoothed scores should rise clearly above the calibrated normal threshold before deployment."
        ],
    }

def plot_hist(path: Path, scores: np.ndarray, title: str, threshold_values: Optional[Dict[str, float]] = None) -> None:
    if plt is None:
        return
    ensure_dir(path.parent)
    finite = scores[np.isfinite(scores)]
    if finite.size == 0:
        return
    plt.figure(figsize=(10, 6))
    plt.hist(finite, bins=80)
    if threshold_values:
        for label, val in threshold_values.items():
            plt.axvline(float(val), linestyle="--", linewidth=1)
            ymax = plt.ylim()[1]
            plt.text(float(val), ymax * 0.90, label, rotation=90, va="top", fontsize=8)
    plt.title(title)
    plt.xlabel("Deep kNN score")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Deep Branch V2 kNN + Gaussian smoothing distribution from person-only VideoMAE embeddings")
    parser.add_argument("--processed_dir", type=Path, default=DEFAULT_PROCESSED_DIR,
                        help="Processed dataset folder containing embeddings/person_embeddings.npy and embeddings/direct_embedding_metadata.csv")
    parser.add_argument("--embeddings_path", type=Path, default=None,
                        help="Optional explicit person_embeddings.npy path")
    parser.add_argument("--metadata_path", type=Path, default=None,
                        help="Optional explicit direct_embedding_metadata.csv path")
    parser.add_argument("--output_dir", type=Path, default=None,
                        help="Output artifact folder. Default: processed_dir/deep_branch_artifacts_v2_gaussian")

    parser.add_argument("--expected_embedding_dim", type=int, default=768)
    parser.add_argument("--train_ratio", type=float, default=0.70)
    parser.add_argument("--calibration_ratio", type=float, default=0.15)
    parser.add_argument("--normal_test_ratio", type=float, default=0.15)
    parser.add_argument("--random_seed", type=int, default=42)

    parser.add_argument("--l2_epsilon", type=float, default=1e-12)
    parser.add_argument("--k_values", type=str, default="1,3,5,10,20",
                        help="Comma-separated k values to evaluate")
    parser.add_argument("--primary_k", type=int, default=1)
    parser.add_argument("--distance_metric", type=str, default="euclidean", choices=["euclidean", "cosine"],
                        help="Use euclidean by default because embeddings are L2-normalized")
    parser.add_argument("--scoring_batch_size", type=int, default=4096)
    parser.add_argument("--n_jobs", type=int, default=-1)

    parser.add_argument("--threshold_percentiles", type=str, default="95,97.5,99,99.5,99.7,99.9")
    parser.add_argument("--primary_threshold_percentile", type=float, default=99.5)

    parser.add_argument("--persistence_window", type=int, default=5)
    parser.add_argument("--persistence_required_hits", type=int, default=3)
    parser.add_argument("--min_event_gap_sec", type=float, default=5.0)
    parser.add_argument("--gaussian_sigmas", type=str, default="1,2,3",
                        help="Comma-separated Gaussian smoothing sigma values in tubelet units")
    parser.add_argument("--selected_gaussian_sigma", type=float, default=2.0,
                        help="Sigma used for the recommended paper-style smoothed score")
    parser.add_argument("--top_n_abnormal_normal", type=int, default=100)

    parser.add_argument("--save_train_embeddings", action="store_true",
                        help="Save normalized train embeddings. Can be large, but useful for deployment/debugging.")
    parser.add_argument("--overwrite", action="store_true", help="Allow writing into a non-empty output folder")

    args = parser.parse_args()

    processed_dir: Path = args.processed_dir
    emb_path = args.embeddings_path or (processed_dir / "embeddings" / "person_embeddings.npy")
    meta_path = args.metadata_path or (processed_dir / "embeddings" / "direct_embedding_metadata.csv")
    out_dir = args.output_dir or (processed_dir / DEFAULT_OUTPUT_NAME)

    if out_dir.exists() and any(out_dir.iterdir()) and not args.overwrite:
        raise SystemExit(
            f"Output folder already exists and is not empty:\n{out_dir}\n\n"
            "Pass --overwrite or choose a new --output_dir."
        )
    ensure_dir(out_dir)
    ensure_dir(out_dir / "plots")
    ensure_dir(out_dir / "scores")
    ensure_dir(out_dir / "models")
    ensure_dir(out_dir / "splits")

    k_values = parse_k_values(args.k_values)
    gaussian_sigmas = parse_float_values(args.gaussian_sigmas)
    if args.selected_gaussian_sigma not in gaussian_sigmas:
        gaussian_sigmas.append(float(args.selected_gaussian_sigma))
        gaussian_sigmas = sorted(set(gaussian_sigmas))
    if args.primary_k not in k_values:
        raise SystemExit(f"primary_k={args.primary_k} must be included in --k_values {k_values}")
    percentiles = parse_percentiles(args.threshold_percentiles)

    config = RunConfig(
        expected_embedding_dim=args.expected_embedding_dim,
        split_unit="video_id",
        train_ratio=args.train_ratio,
        calibration_ratio=args.calibration_ratio,
        normal_test_ratio=args.normal_test_ratio,
        random_seed=args.random_seed,
        normalization="l2",
        l2_epsilon=args.l2_epsilon,
        k_values=k_values,
        primary_k=args.primary_k,
        distance_metric=args.distance_metric,
        score_method="mean_distance_to_k_neighbors",
        threshold_percentiles=percentiles,
        primary_threshold_percentile=args.primary_threshold_percentile,
        persistence_window=args.persistence_window,
        persistence_required_hits=args.persistence_required_hits,
        min_event_gap_sec=args.min_event_gap_sec,
        gaussian_sigmas=gaussian_sigmas,
        selected_gaussian_sigma=float(args.selected_gaussian_sigma),
        scoring_batch_size=args.scoring_batch_size,
        top_n_abnormal_normal=args.top_n_abnormal_normal,
    )
    save_json(out_dir / "run_config.json", asdict(config))

    print(f"[1/8] Loading embeddings: {emb_path}")
    if not emb_path.exists():
        raise SystemExit(f"Embeddings file not found: {emb_path}")
    if not meta_path.exists():
        raise SystemExit(f"Metadata CSV not found: {meta_path}")

    emb_raw = np.load(emb_path, mmap_mode=None)
    meta_raw = pd.read_csv(meta_path)

    print("[2/8] Validating and aligning metadata with embeddings...")
    emb_clean, meta_clean, validation_report = validate_and_align(emb_raw, meta_raw, args.expected_embedding_dim)
    save_json(out_dir / "00_input_validation.json", validation_report)
    meta_clean.to_csv(out_dir / "00_clean_metadata.csv", index=False, encoding="utf-8-sig")

    if len(meta_clean) < 10:
        raise SystemExit(f"Too few valid embeddings after cleaning: {len(meta_clean)}")

    raw_norms = np.linalg.norm(emb_clean, axis=1)
    pd.DataFrame({"embedding_norm": raw_norms}).describe().to_csv(out_dir / "00_embedding_basic_stats.csv", encoding="utf-8-sig")
    plot_hist(out_dir / "plots" / "00_embedding_norm_histogram.png", raw_norms, "Raw VideoMAE embedding norms")

    print("[3/8] Splitting by video_id into train / calibration / normal-test...")
    meta_split, split_report = split_by_video(meta_clean, args.train_ratio, args.calibration_ratio, args.normal_test_ratio, args.random_seed)
    save_json(out_dir / "01_split_manifest.json", split_report)
    meta_split.to_csv(out_dir / "splits" / "01_all_metadata_with_split.csv", index=False, encoding="utf-8-sig")
    for split_name in ["train", "calibration", "normal_test"]:
        meta_split.loc[meta_split["split"] == split_name].to_csv(
            out_dir / "splits" / f"01_{split_name}_metadata.csv",
            index=False,
            encoding="utf-8-sig",
        )

    print("[4/8] L2-normalizing embeddings...")
    emb_l2, l2_norms = l2_normalize(emb_clean, args.l2_epsilon)
    save_json(out_dir / "02_normalization_config.json", {
        "normalization": "l2",
        "epsilon": args.l2_epsilon,
        "post_l2_norm_min": float(np.min(np.linalg.norm(emb_l2, axis=1))),
        "post_l2_norm_max": float(np.max(np.linalg.norm(emb_l2, axis=1))),
        "post_l2_norm_mean": float(np.mean(np.linalg.norm(emb_l2, axis=1))),
    })

    train_mask = (meta_split["split"] == "train").values
    cal_mask = (meta_split["split"] == "calibration").values
    test_mask = (meta_split["split"] == "normal_test").values

    x_train = emb_l2[train_mask]
    x_cal = emb_l2[cal_mask]
    x_test = emb_l2[test_mask]
    meta_train = meta_split.loc[train_mask].reset_index(drop=True)
    meta_cal = meta_split.loc[cal_mask].reset_index(drop=True)
    meta_test = meta_split.loc[test_mask].reset_index(drop=True)

    if len(x_train) <= max(k_values):
        raise SystemExit(f"Train split has only {len(x_train)} rows, but max_k={max(k_values)}")

    print(f"[5/8] Fitting kNN memory bank on train only: train_rows={len(x_train)}, max_k={max(k_values)}")
    nbrs = NearestNeighbors(
        n_neighbors=max(k_values),
        metric=args.distance_metric,
        algorithm="auto",
        n_jobs=args.n_jobs,
    )
    nbrs.fit(x_train)

    knn_config = {
        "model_name": "deep_knn_l2",
        "train_rows": int(len(x_train)),
        "embedding_dim": int(x_train.shape[1]),
        "normalization": "l2",
        "distance_metric": args.distance_metric,
        "k_values": k_values,
        "primary_k": args.primary_k,
        "score_method": "mean_distance_to_k_neighbors",
        "note": "Thresholds are calibrated on calibration videos only, not train rows.",
    }
    save_json(out_dir / "03_model_A_knn_config.json", knn_config)
    save_pickle(out_dir / "models" / "03_knn_index.joblib", nbrs)
    if args.save_train_embeddings:
        np.save(out_dir / "models" / "03_train_embeddings_l2.npy", x_train.astype(np.float32))
        meta_train.to_csv(out_dir / "models" / "03_train_metadata.csv", index=False, encoding="utf-8-sig")

    print(f"[6/8] Scoring calibration split: rows={len(x_cal)}")
    cal_scores_by_k = score_knn_in_batches(nbrs, x_cal, k_values, args.scoring_batch_size)
    cal_scores_df = make_scores_frame(meta_cal, cal_scores_by_k)
    cal_scores_df.to_csv(out_dir / "scores" / "04_calibration_scores.csv", index=False, encoding="utf-8-sig")
    np.save(out_dir / "scores" / "04_calibration_scores_primary_k.npy", cal_scores_by_k[args.primary_k])

    # Build raw calibration scores first.
    raw_thresholds = compute_thresholds(cal_scores_by_k, percentiles)

    # Build causal-smoothed calibration scores and matching thresholds per smoothing mode.
    cal_scores_smoothed_df = cal_scores_df.copy()
    threshold_groups = {"raw": raw_thresholds}
    for k in k_values:
        raw_col = f"deep_knn_score_k{k}"
        for sigma in gaussian_sigmas:
            suffix = str(float(sigma)).replace('.', '_')
            out_col = f"deep_knn_score_k{k}_gauss_s{suffix}"
            cal_scores_smoothed_df = smooth_scores_per_video(cal_scores_smoothed_df, raw_col, float(sigma), out_col)

    for sigma in gaussian_sigmas:
        suffix = str(float(sigma)).replace('.', '_')
        mode_key = f"gaussian_sigma_{float(sigma):g}"
        threshold_groups[mode_key] = compute_thresholds_from_scores_frame(
            cal_scores_smoothed_df,
            k_values,
            percentiles,
            mode_name=mode_key,
            column_suffix=f"_gauss_s{suffix}",
        )

    # Backward-compatible threshold artifact:
    # - top-level k1/k3/k5... are RAW thresholds for old loaders
    # - thresholds_by_score_mode contains the new consistent raw/smoothed thresholds
    thresholds = dict(raw_thresholds)
    thresholds["threshold_format_version"] = "deep_thresholds_v2_raw_and_causal_smoothed"
    thresholds["legacy_top_level_thresholds_are"] = "raw_calibration_scores"
    thresholds["thresholds_by_score_mode"] = threshold_groups
    thresholds["score_mode_notes"] = {
        "raw": "Thresholds computed from raw calibration kNN scores.",
        "gaussian_sigma_X": "Thresholds computed from causal-smoothed calibration kNN scores using the same sigma X.",
    }
    save_json(out_dir / "04_thresholds.json", thresholds)
    save_json(out_dir / "04_thresholds_raw_legacy.json", raw_thresholds)
    save_json(out_dir / "04_thresholds_by_score_mode.json", threshold_groups)
    cal_scores_smoothed_df.to_csv(out_dir / "scores" / "04_calibration_scores_with_gaussian.csv", index=False, encoding="utf-8-sig")

    for k in k_values:
        plot_hist(
            out_dir / "plots" / f"04_calibration_score_histogram_k{k}.png",
            cal_scores_by_k[k],
            title=f"Calibration deep kNN raw scores | k={k}",
            threshold_values=raw_thresholds[f"k{k}"],
        )
        for sigma in gaussian_sigmas:
            suffix = str(float(sigma)).replace('.', '_')
            mode_key = f"gaussian_sigma_{float(sigma):g}"
            col = f"deep_knn_score_k{k}_gauss_s{suffix}"
            plot_hist(
                out_dir / "plots" / f"04_calibration_score_histogram_k{k}_{mode_key}.png",
                pd.to_numeric(cal_scores_smoothed_df[col], errors="coerce").values.astype(float),
                title=f"Calibration causal-smoothed deep kNN scores | k={k} | sigma={float(sigma):g}",
                threshold_values=threshold_groups[mode_key][f"k{k}"],
            )

    print(f"[7/8] Scoring normal-test split: rows={len(x_test)}")
    test_scores_by_k = score_knn_in_batches(nbrs, x_test, k_values, args.scoring_batch_size)
    test_scores_df = make_scores_frame(meta_test, test_scores_by_k)
    test_scores_df.to_csv(out_dir / "scores" / "05_normal_test_scores.csv", index=False, encoding="utf-8-sig")
    np.save(out_dir / "scores" / "05_normal_test_scores_primary_k.npy", test_scores_by_k[args.primary_k])

    for k in k_values:
        plot_hist(
            out_dir / "plots" / f"05_normal_test_score_histogram_k{k}.png",
            test_scores_by_k[k],
            title=f"Normal-test deep kNN scores | k={k}",
            threshold_values=thresholds[f"k{k}"],
        )

    print("[8/9] Evaluating raw, Gaussian, and Gaussian+persistence false alarms...")
    false_alarm_df, false_alarm_detail, test_scores_smoothed_df = evaluate_thresholds_v2(
        test_scores_df=test_scores_df,
        threshold_groups=threshold_groups,
        k_values=k_values,
        percentiles=percentiles,
        gaussian_sigmas=gaussian_sigmas,
        persistence_window=args.persistence_window,
        persistence_required_hits=args.persistence_required_hits,
        min_event_gap_sec=args.min_event_gap_sec,
    )
    false_alarm_df.to_csv(out_dir / "05_false_alarm_report.csv", index=False, encoding="utf-8-sig")
    save_json(out_dir / "05_false_alarm_detail.json", false_alarm_detail)
    test_scores_smoothed_df.to_csv(out_dir / "scores" / "05_normal_test_scores_with_gaussian.csv", index=False, encoding="utf-8-sig")


    for k in k_values:
        for sigma in gaussian_sigmas:
            col = f"deep_knn_score_k{k}_gauss_s{str(float(sigma)).replace('.', '_')}"
            plot_hist(
                out_dir / "plots" / f"05_normal_test_score_histogram_k{k}_gaussian_sigma_{sigma:g}.png",
                pd.to_numeric(test_scores_smoothed_df[col], errors="coerce").values.astype(float),
                title=f"Normal-test Gaussian-smoothed deep kNN scores | k={k} | sigma={sigma:g}",
                threshold_values=thresholds[f"k{k}"],
            )

    primary_pkey = percentile_key(args.primary_threshold_percentile)
    primary_raw_score_col = f"deep_knn_score_k{args.primary_k}"
    selected_smooth_suffix = str(float(args.selected_gaussian_sigma)).replace('.', '_')
    primary_score_col = f"deep_knn_score_k{args.primary_k}_gauss_s{selected_smooth_suffix}"
    if primary_score_col not in test_scores_smoothed_df.columns:
        primary_score_col = primary_raw_score_col
    if primary_score_col not in test_scores_smoothed_df.columns:
        raise RuntimeError(f"Missing primary score column: {primary_score_col}")

    top_df = test_scores_smoothed_df.sort_values(primary_score_col, ascending=False).head(args.top_n_abnormal_normal)
    top_df.to_csv(out_dir / "06_top_abnormal_normal_tubelets.csv", index=False, encoding="utf-8-sig")
    top_raw_df = test_scores_smoothed_df.sort_values(primary_raw_score_col, ascending=False).head(args.top_n_abnormal_normal)
    top_raw_df.to_csv(out_dir / "06_top_abnormal_normal_tubelets_raw_score.csv", index=False, encoding="utf-8-sig")

    # Also provide a calibration+test combined top list for broader inspection.
    combined_scores_df = pd.concat([cal_scores_smoothed_df, test_scores_smoothed_df], ignore_index=True)
    combined_top_df = combined_scores_df.sort_values(primary_score_col, ascending=False).head(args.top_n_abnormal_normal)
    combined_top_df.to_csv(out_dir / "06_top_abnormal_calibration_and_test_tubelets.csv", index=False, encoding="utf-8-sig")

    selected_mode = f"gaussian_sigma_{args.selected_gaussian_sigma:g}"
    selected_rows = false_alarm_df[
        (false_alarm_df["k"] == args.primary_k) &
        (false_alarm_df["threshold_key"] == primary_pkey) &
        (false_alarm_df["score_mode"] == selected_mode)
    ]
    selected_eval = selected_rows.iloc[0].to_dict() if len(selected_rows) else {}
    selected_threshold_value = get_threshold_for_mode(
        threshold_groups,
        selected_mode,
        int(args.primary_k),
        primary_pkey,
    )

    print("[9/9] Building VideoMAE suitability diagnostics...")
    suitability_report = build_videomae_suitability_report(
        validation_report=validation_report,
        split_report=split_report,
        cal_scores_df=cal_scores_smoothed_df,
        normal_test_scores_df=test_scores_smoothed_df,
        false_alarm_df=false_alarm_df,
        primary_k=args.primary_k,
        primary_threshold_key=primary_pkey,
        selected_gaussian_sigma=float(args.selected_gaussian_sigma),
        top_n=args.top_n_abnormal_normal,
    )
    save_json(out_dir / "07_videomae_suitability_report.json", suitability_report)
    recommended = {
        "selected_model": "deep_knn_l2",
        "selected_k": int(args.primary_k),
        "selected_threshold_percentile": float(args.primary_threshold_percentile),
        "selected_threshold_key": primary_pkey,
        "selected_threshold_value": float(selected_threshold_value),
        "selected_threshold_source_mode": selected_mode,
        "normalization": "l2",
        "distance_metric": args.distance_metric,
        "score_method": "mean_distance_to_k_neighbors",
        "smoothing_or_event_logic": {
            "method": "gaussian_then_persistence",
            "gaussian_sigma_tubelets": float(args.selected_gaussian_sigma),
            "persistence_window": int(args.persistence_window),
            "persistence_required_hits": int(args.persistence_required_hits),
            "min_event_gap_sec": float(args.min_event_gap_sec),
        },
        "normal_test_evaluation_for_selected_threshold": selected_eval,
        "artifacts": {
            "knn_index": str(out_dir / "models" / "03_knn_index.joblib"),
            "thresholds": str(out_dir / "04_thresholds.json"),
            "calibration_scores": str(out_dir / "scores" / "04_calibration_scores.csv"),
            "normal_test_scores_raw": str(out_dir / "scores" / "05_normal_test_scores.csv"),
            "normal_test_scores_with_gaussian": str(out_dir / "scores" / "05_normal_test_scores_with_gaussian.csv"),
            "top_abnormal_normal_tubelets": str(out_dir / "06_top_abnormal_normal_tubelets.csv"),
            "videomae_suitability_report": str(out_dir / "07_videomae_suitability_report.json"),
        },
    }
    save_json(out_dir / "09_recommended_deep_branch.json", recommended)

    summary = {
        "status": "done",
        "processed_dir": str(processed_dir),
        "output_dir": str(out_dir),
        "embeddings_path": str(emb_path),
        "metadata_path": str(meta_path),
        "validation": validation_report,
        "split": split_report,
        "selected": recommended,
        "videomae_suitability": suitability_report,
    }
    save_json(out_dir / "10_run_summary.json", summary)

    print("\nDONE.")
    print(f"Artifacts saved to: {out_dir}")
    print(f"Selected model: deep_knn_l2 | k={args.primary_k} | gaussian_sigma={args.selected_gaussian_sigma:g} | threshold={primary_pkey} ({selected_mode}) = {selected_threshold_value:.8f}")
    print(f"VideoMAE suitability verdict: {suitability_report.get('verdict', 'NA')}")
    if selected_eval:
        print(
            "Normal-test selected threshold: "
            f"raw_false_alarm_rate={selected_eval.get('false_alarm_rate_percent_before_persistence', 'NA'):.4f}% | "
            f"events_after_persistence={selected_eval.get('false_alarm_events_after_persistence', 'NA')}"
        )


if __name__ == "__main__":
    main()
