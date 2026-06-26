#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Robust multi-version Deep Gate false-alarm plotting script.

Use this for Deep Gate v1, v2, v3, v4, or later versions.

Why this script exists
----------------------
Older Deep Gate versions may have different CSV column names.
For example:
    - v1 may not have score_mode because it only used raw scores.
    - v1 may not have false_alarm_rate_percent_before_persistence.
    - some reports may use threshold instead of threshold_value.
    - some reports may use false_alarm_rate or raw_false_alarm_rate.

This script tries to normalize older/newer CSV formats into a common schema.

Required minimum columns
------------------------
The CSV must contain at least:
    - k
    - threshold_percentile or threshold key/percentile equivalent
    - at least one false-alarm metric

Best expected CSV:
    05_false_alarm_report.csv

Example PowerShell commands
---------------------------
python "D:\Embeddings_Distribution\scripts\deep_gate\plot_false_alarm_hyperparams_multi_version_robust.py" --version "Deep Gate v1" --csv "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v1\05_false_alarm_report.csv" --outdir "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v1\plots\false_alarm_hyperparam_summary"

python "D:\Embeddings_Distribution\scripts\deep_gate\plot_false_alarm_hyperparams_multi_version_robust.py" --version "Deep Gate v2 Gaussian" --csv "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v2_gaussian\05_false_alarm_report.csv" --outdir "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v2_gaussian\plots\false_alarm_hyperparam_summary"

python "D:\Embeddings_Distribution\scripts\deep_gate\plot_false_alarm_hyperparams_multi_version_robust.py" --version "Deep Gate v3 Gaussian" --csv "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v3_gaussian\05_false_alarm_report.csv" --outdir "D:\Embeddings_Distribution\normality_models\deep_gate\deep_branch_artifacts_v3_gaussian\plots\false_alarm_hyperparam_summary"
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


CANONICAL_COLUMNS = {
    "k",
    "score_mode",
    "threshold_percentile",
    "threshold_value",
    "false_alarm_tubelets_before_persistence",
    "false_alarm_rate_percent_before_persistence",
    "max_false_alarm_streak_before_persistence",
    "false_alarm_events_after_persistence",
}

COLUMN_ALIASES = {
    "k": [
        "k",
        "knn_k",
        "n_neighbors",
        "neighbors",
    ],
    "score_mode": [
        "score_mode",
        "mode",
        "smoothing_mode",
        "score_col",
        "score_column",
    ],
    "threshold_percentile": [
        "threshold_percentile",
        "percentile",
        "threshold_pct",
        "threshold_p",
        "calibration_percentile",
        "threshold_key",
    ],
    "threshold_value": [
        "threshold_value",
        "threshold",
        "score_threshold",
        "calibrated_threshold",
        "threshold_score",
    ],
    "false_alarm_tubelets_before_persistence": [
        "false_alarm_tubelets_before_persistence",
        "false_alarm_tubelets",
        "fa_tubelets",
        "false_alarms_before_persistence",
        "false_alarm_count_before_persistence",
        "false_alarm_count",
        "num_false_alarms",
        "false_alarms",
        "raw_false_alarms",
        "raw_false_alarm_count",
        "false_alarm_rows",
    ],
    "false_alarm_rate_percent_before_persistence": [
        "false_alarm_rate_percent_before_persistence",
        "false_alarm_rate_before_persistence",
        "fa_rate_percent",
        "false_alarm_rate_percent",
        "raw_false_alarm_rate_percent",
        "false_alarm_rate",
        "raw_false_alarm_rate",
        "fa_rate",
        "normal_false_positive_rate_percent",
        "normal_clip_false_positive_rate_percent",
    ],
    "max_false_alarm_streak_before_persistence": [
        "max_false_alarm_streak_before_persistence",
        "max_false_alarm_streak",
        "max_fa_streak",
        "max_consecutive_false_alarms",
        "max_raw_false_alarm_streak",
    ],
    "false_alarm_events_after_persistence": [
        "false_alarm_events_after_persistence",
        "persistent_false_alarm_events",
        "false_alarm_events",
        "fa_events_after_persistence",
        "events_after_persistence",
        "persistent_events",
        "normal_false_alarm_events",
    ],
}

DENOMINATOR_ALIASES = [
    "normal_test_tubelets",
    "test_tubelets",
    "n_test_tubelets",
    "num_test_tubelets",
    "total_tubelets",
    "tubelets",
    "rows_used",
    "normal_rows",
    "normal_test_rows",
]


MODE_ORDER = ["raw", "gaussian_sigma_1", "gaussian_sigma_2", "gaussian_sigma_3"]

MODE_LABELS = {
    "raw": "Raw",
    "gaussian_sigma_1": r"Gaussian $\sigma$=1",
    "gaussian_sigma_2": r"Gaussian $\sigma$=2",
    "gaussian_sigma_3": r"Gaussian $\sigma$=3",
}

METRICS = {
    "false_alarm_rate_percent_before_persistence": {
        "label": "False-alarm tubelet rate before persistence (%)",
        "short": "fa_rate_before_persistence",
        "fmt": ".3f",
    },
    "false_alarm_tubelets_before_persistence": {
        "label": "False-alarm tubelets before persistence",
        "short": "fa_tubelets_before_persistence",
        "fmt": ".0f",
    },
    "max_false_alarm_streak_before_persistence": {
        "label": "Maximum false-alarm streak before persistence",
        "short": "max_fa_streak",
        "fmt": ".0f",
    },
    "false_alarm_events_after_persistence": {
        "label": "Persistent false-alarm events after persistence",
        "short": "persistent_fa_events",
        "fmt": ".0f",
    },
}


def safe_name(text: str) -> str:
    return (
        text.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )


def fmt_percentile(value: float) -> str:
    return f"{float(value):g}"


def normalize_score_mode(value: object) -> str:
    s = str(value).strip().lower()

    if not s or s == "nan":
        return "raw"

    # Convert possible score-column names into score modes.
    if "gauss_s1" in s or "sigma_1" in s or "sigma=1" in s or "gaussian1" in s:
        return "gaussian_sigma_1"
    if "gauss_s2" in s or "sigma_2" in s or "sigma=2" in s or "gaussian2" in s:
        return "gaussian_sigma_2"
    if "gauss_s3" in s or "sigma_3" in s or "sigma=3" in s or "gaussian3" in s:
        return "gaussian_sigma_3"
    if "raw" in s:
        return "raw"

    return s


def parse_threshold_percentile(value: object) -> float:
    if pd.isna(value):
        return np.nan

    s = str(value).strip().lower()

    mapping = {
        "p95": 95.0,
        "95": 95.0,
        "p97_5": 97.5,
        "p97.5": 97.5,
        "97.5": 97.5,
        "p99": 99.0,
        "99": 99.0,
        "p99_5": 99.5,
        "p99.5": 99.5,
        "99.5": 99.5,
        "p99_7": 99.7,
        "p99.7": 99.7,
        "99.7": 99.7,
        "p99_9": 99.9,
        "p99.9": 99.9,
        "99.9": 99.9,
    }

    if s in mapping:
        return mapping[s]

    s = s.replace("p", "").replace("_", ".")
    try:
        return float(s)
    except ValueError:
        return np.nan


def find_first_existing_column(df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    lower_to_original = {c.lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in lower_to_original:
            return lower_to_original[alias.lower()]
    return None


def copy_or_create_column(
    src: pd.DataFrame,
    dst: pd.DataFrame,
    canonical: str,
    default_value: object = np.nan,
) -> Tuple[pd.DataFrame, Optional[str]]:
    col = find_first_existing_column(src, COLUMN_ALIASES[canonical])
    if col is None:
        dst[canonical] = default_value
        return dst, None
    dst[canonical] = src[col]
    return dst, col


def normalize_report(raw: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    mapping: Dict[str, Optional[str]] = {}
    df = pd.DataFrame()

    for canonical in CANONICAL_COLUMNS:
        default = "raw" if canonical == "score_mode" else np.nan
        df, source_col = copy_or_create_column(raw, df, canonical, default)
        mapping[canonical] = source_col

    # Required basics.
    if df["k"].isna().all():
        raise ValueError(
            "Could not find a k column. Available columns are:\n"
            + "\n".join(f"- {c}" for c in raw.columns)
        )

    if df["threshold_percentile"].isna().all():
        raise ValueError(
            "Could not find a threshold percentile column. Available columns are:\n"
            + "\n".join(f"- {c}" for c in raw.columns)
        )

    # Normalize values.
    df["k"] = pd.to_numeric(df["k"], errors="raise")
    df["score_mode"] = df["score_mode"].apply(normalize_score_mode)
    df["threshold_percentile"] = df["threshold_percentile"].apply(parse_threshold_percentile)

    if df["threshold_percentile"].isna().any():
        bad = df[df["threshold_percentile"].isna()].head()
        raise ValueError(
            "Some threshold percentiles could not be parsed. First bad rows:\n"
            + bad.to_string(index=False)
        )

    df["threshold_value"] = pd.to_numeric(df["threshold_value"], errors="coerce")

    # Convert metrics to numeric if present.
    for metric in METRICS:
        df[metric] = pd.to_numeric(df[metric], errors="coerce")

    # If missing false-alarm rate, try to derive it from false-alarm tubelet count and a denominator.
    if df["false_alarm_rate_percent_before_persistence"].isna().all():
        denom_col = find_first_existing_column(raw, DENOMINATOR_ALIASES)
        if denom_col is not None and not df["false_alarm_tubelets_before_persistence"].isna().all():
            denom = pd.to_numeric(raw[denom_col], errors="coerce")
            df["false_alarm_rate_percent_before_persistence"] = (
                df["false_alarm_tubelets_before_persistence"] / denom * 100.0
            )
            mapping["derived_false_alarm_rate_denominator"] = denom_col
        else:
            mapping["derived_false_alarm_rate_denominator"] = None

    # If rate exists but appears as fraction, convert to percent.
    rate = df["false_alarm_rate_percent_before_persistence"]
    if not rate.isna().all() and float(rate.max()) <= 1.0:
        df["false_alarm_rate_percent_before_persistence"] = rate * 100.0

    # If missing tubelet count, try to derive from percent and denominator.
    if df["false_alarm_tubelets_before_persistence"].isna().all():
        denom_col = find_first_existing_column(raw, DENOMINATOR_ALIASES)
        if denom_col is not None and not df["false_alarm_rate_percent_before_persistence"].isna().all():
            denom = pd.to_numeric(raw[denom_col], errors="coerce")
            df["false_alarm_tubelets_before_persistence"] = (
                df["false_alarm_rate_percent_before_persistence"] / 100.0 * denom
            ).round()
            mapping["derived_false_alarm_tubelets_denominator"] = denom_col
        else:
            mapping["derived_false_alarm_tubelets_denominator"] = None

    # Defaults if old CSV cannot provide them.
    if df["max_false_alarm_streak_before_persistence"].isna().all():
        df["max_false_alarm_streak_before_persistence"] = 0.0
        mapping["max_false_alarm_streak_before_persistence"] = "defaulted_to_0"

    if df["false_alarm_events_after_persistence"].isna().all():
        df["false_alarm_events_after_persistence"] = 0.0
        mapping["false_alarm_events_after_persistence"] = "defaulted_to_0"

    # If no rate is available, keep it as zero only to allow the script to run,
    # but report this clearly. The count/event plots will still be meaningful.
    if df["false_alarm_rate_percent_before_persistence"].isna().all():
        df["false_alarm_rate_percent_before_persistence"] = 0.0
        mapping["false_alarm_rate_percent_before_persistence"] = "defaulted_to_0_missing_in_csv"

    if df["false_alarm_tubelets_before_persistence"].isna().all():
        df["false_alarm_tubelets_before_persistence"] = 0.0
        mapping["false_alarm_tubelets_before_persistence"] = "defaulted_to_0_missing_in_csv"

    # Mode order.
    known_modes = [m for m in MODE_ORDER if m in set(df["score_mode"])]
    extra_modes = sorted(set(df["score_mode"]) - set(known_modes))
    df.attrs["mode_order"] = known_modes + extra_modes

    return df, mapping


def read_false_alarm_report(csv_path: Path) -> Tuple[pd.DataFrame, Dict[str, Optional[str]], pd.DataFrame]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found:\n{csv_path}")

    raw = pd.read_csv(csv_path)
    df, mapping = normalize_report(raw)
    return df, mapping, raw


def choose_available_k(df: pd.DataFrame, requested_k: int) -> int:
    k_values = sorted(int(k) for k in df["k"].unique())
    if requested_k in k_values:
        return requested_k
    return min(k_values, key=lambda k: abs(k - requested_k))


def choose_available_mode(df: pd.DataFrame, requested_mode: str) -> str:
    modes = df.attrs["mode_order"]
    if requested_mode in modes:
        return requested_mode
    if "gaussian_sigma_2" in modes:
        return "gaussian_sigma_2"
    if "raw" in modes:
        return "raw"
    return modes[0]


def choose_available_percentile(df: pd.DataFrame, requested_percentile: float) -> float:
    percentiles = sorted(float(p) for p in df["threshold_percentile"].unique())
    if requested_percentile in percentiles:
        return requested_percentile
    return min(percentiles, key=lambda p: abs(p - requested_percentile))


def make_pivot(df: pd.DataFrame, mode: str, metric: str) -> pd.DataFrame:
    sub = df[df["score_mode"] == mode].copy()
    if sub.empty:
        raise ValueError(f"No rows found for score_mode={mode}")

    ks = sorted(sub["k"].unique())
    percentiles = sorted(sub["threshold_percentile"].unique())

    pivot = sub.pivot_table(index="k", columns="threshold_percentile", values=metric, aggfunc="mean")
    return pivot.loc[ks, percentiles]


def positive_floor(values: Iterable[float]) -> float:
    arr = np.array(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    positives = arr[arr > 0]
    if positives.size == 0:
        return 1e-6
    return max(float(positives.min()) * 0.5, 1e-6)


def make_norm(values: Iterable[float], use_lognorm: bool) -> mcolors.Normalize:
    arr = np.array(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]

    if arr.size == 0:
        return mcolors.Normalize(vmin=0.0, vmax=1.0)

    vmax = float(arr.max())

    if not use_lognorm:
        vmin = float(arr.min())
        if vmax <= vmin:
            vmax = vmin + 1.0
        return mcolors.Normalize(vmin=vmin, vmax=vmax)

    floor = positive_floor(arr)
    if vmax <= floor:
        return mcolors.Normalize(vmin=0.0, vmax=max(vmax, 1.0))

    return mcolors.LogNorm(vmin=floor, vmax=vmax)


def values_for_display(values: np.ndarray, use_lognorm: bool) -> np.ndarray:
    display = values.astype(float).copy()
    if use_lognorm:
        floor = positive_floor(display.ravel())
        display[~np.isfinite(display)] = np.nan
        display[display <= 0] = floor
    return display


def annotation_colour(value: float, norm: mcolors.Normalize) -> str:
    try:
        scaled = float(norm(value if value > 0 else getattr(norm, "vmin", 0.0)))
    except Exception:
        scaled = 0.0
    return "white" if scaled > 0.55 else "black"


def annotate_heatmap(ax, true_values: np.ndarray, display_values: np.ndarray, norm: mcolors.Normalize, fmt: str) -> None:
    for i in range(true_values.shape[0]):
        for j in range(true_values.shape[1]):
            true_value = true_values[i, j]
            display_value = display_values[i, j]
            if pd.notna(true_value):
                ax.text(
                    j,
                    i,
                    format(true_value, fmt),
                    ha="center",
                    va="center",
                    fontsize=7,
                    color=annotation_colour(display_value, norm),
                    fontweight="bold",
                )


def plot_metric_heatmap_grid(
    df: pd.DataFrame,
    metric: str,
    outpath: Path,
    title: str,
    annotate: bool = True,
    use_lognorm: bool = True,
    show: bool = False,
) -> None:
    spec = METRICS[metric]
    mode_order = df.attrs["mode_order"]

    pivots: Dict[str, pd.DataFrame] = {}
    all_values = []

    for mode in mode_order:
        pivot = make_pivot(df, mode, metric)
        pivots[mode] = pivot
        all_values.extend(pivot.values.ravel().tolist())

    norm = make_norm(all_values, use_lognorm=use_lognorm)

    n_modes = len(mode_order)
    ncols = min(2, n_modes)
    nrows = int(np.ceil(n_modes / ncols))

    fig, axes = plt.subplots(nrows, ncols, figsize=(7 * ncols, 4.5 * nrows), constrained_layout=True)
    axes_flat = np.array(axes).ravel() if n_modes > 1 else np.array([axes])

    last_image = None
    for ax, mode in zip(axes_flat, mode_order):
        pivot = pivots[mode]
        true_values = pivot.values.astype(float)
        display_values = values_for_display(true_values, use_lognorm=use_lognorm)

        image = ax.imshow(display_values, aspect="auto", norm=norm, cmap="YlOrRd")
        last_image = image

        ax.set_title(MODE_LABELS.get(mode, mode), fontsize=11)
        ax.set_xlabel("Threshold percentile")
        ax.set_ylabel("k")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([fmt_percentile(x) for x in pivot.columns], rotation=45, ha="right")
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(int(x)) for x in pivot.index])

        if annotate:
            annotate_heatmap(ax, true_values, display_values, norm, spec["fmt"])

    for ax in axes_flat[n_modes:]:
        ax.axis("off")

    scale_note = "log scale" if use_lognorm else "linear scale"
    fig.suptitle(f"{title} ({scale_note})", fontsize=14, fontweight="bold")
    cb = fig.colorbar(last_image, ax=axes_flat.tolist(), shrink=0.85)
    cb.ax.set_ylabel(spec["label"], rotation=270, labelpad=18)

    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_k_fixed_two_panel_summary(
    df: pd.DataFrame,
    outpath: Path,
    version: str,
    k_value: int = 5,
    show: bool = False,
) -> None:
    mode_order = df.attrs["mode_order"]
    sub = df[df["k"] == k_value].copy()

    if sub.empty:
        print(f"  Skipped focal-k line plot: no rows found for k={k_value}.")
        return

    percentiles_sorted = sorted(sub["threshold_percentile"].unique())
    x_labels = [fmt_percentile(p) for p in percentiles_sorted]
    x_pos = list(range(len(percentiles_sorted)))

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)

    metric_left = "false_alarm_rate_percent_before_persistence"
    metric_right = "false_alarm_events_after_persistence"

    for mode in mode_order:
        group = sub[sub["score_mode"] == mode].sort_values("threshold_percentile").set_index("threshold_percentile")
        if group.empty:
            continue

        label = MODE_LABELS.get(mode, mode)
        y_left = [group.loc[p, metric_left] for p in percentiles_sorted]
        y_right = [group.loc[p, metric_right] for p in percentiles_sorted]

        axes[0].plot(x_pos, y_left, marker="o", label=label, linewidth=1.8)
        axes[1].plot(x_pos, y_right, marker="o", label=label, linewidth=1.8)

    for ax, ylabel, panel_title in zip(
        axes,
        ["False-alarm rate before persistence (%)", "Events after persistence"],
        [f"Tubelet-level false-alarm rate (k={k_value})", f"Persistent false-alarm events (k={k_value})"],
    ):
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_xlabel("Threshold percentile")
        ax.set_ylabel(ylabel)
        ax.set_title(panel_title)
        ax.grid(True, alpha=0.3)
        ax.legend(title="Score mode", fontsize=9)

    fig.suptitle(f"{version} normal-validation sensitivity at k={k_value}", fontsize=13, fontweight="bold")
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_k_sensitivity(
    df: pd.DataFrame,
    outpath: Path,
    version: str,
    requested_mode: str = "gaussian_sigma_2",
    requested_percentile: float = 99.5,
    show: bool = False,
) -> None:
    selected_mode = choose_available_mode(df, requested_mode)
    selected_percentile = choose_available_percentile(df, requested_percentile)

    sub = df[(df["score_mode"] == selected_mode) & (df["threshold_percentile"] == selected_percentile)].sort_values("k").copy()

    if sub.empty:
        print("  Skipped k-sensitivity plot: no matching rows.")
        return

    k_vals = sub["k"].tolist()
    fa_rate = sub["false_alarm_rate_percent_before_persistence"].tolist()
    fa_events = sub["false_alarm_events_after_persistence"].tolist()

    mode_label = MODE_LABELS.get(selected_mode, selected_mode)
    percentile_label = fmt_percentile(selected_percentile)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)

    axes[0].plot(k_vals, fa_rate, marker="o", linewidth=2)
    axes[0].set_title(f"Tubelet-level false-alarm rate\n({mode_label}, p{percentile_label})")
    axes[0].set_xlabel("k")
    axes[0].set_ylabel("False-alarm rate before persistence (%)")
    axes[0].set_xticks(k_vals)
    axes[0].grid(True, alpha=0.3)

    for kv, yr in zip(k_vals, fa_rate):
        axes[0].annotate(f"{yr:.3f}%", xy=(kv, yr), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8)

    axes[1].plot(k_vals, fa_events, marker="s", linewidth=2)
    axes[1].set_title(f"Persistent false-alarm events\n({mode_label}, p{percentile_label})")
    axes[1].set_xlabel("k")
    axes[1].set_ylabel("Events after persistence")
    axes[1].set_xticks(k_vals)
    axes[1].grid(True, alpha=0.3)

    for kv, ye in zip(k_vals, fa_events):
        axes[1].annotate(str(int(ye)), xy=(kv, ye), xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8)

    fig.suptitle(f"{version} k-sensitivity at {mode_label}, p{percentile_label}", fontsize=13, fontweight="bold")
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_individual_heatmaps(
    df: pd.DataFrame,
    outdir: Path,
    version_prefix: str,
    show: bool = False,
    use_lognorm: bool = True,
) -> None:
    individual_dir = outdir / "individual_heatmaps"
    individual_dir.mkdir(parents=True, exist_ok=True)

    for metric, spec in METRICS.items():
        for mode in df.attrs["mode_order"]:
            pivot = make_pivot(df, mode, metric)
            true_values = pivot.values.astype(float)
            display_values = values_for_display(true_values, use_lognorm=use_lognorm)
            norm = make_norm(true_values.ravel().tolist(), use_lognorm=use_lognorm)

            fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
            image = ax.imshow(display_values, aspect="auto", norm=norm, cmap="YlOrRd")
            scale_note = "log scale" if use_lognorm else "linear scale"
            ax.set_title(f"{MODE_LABELS.get(mode, mode)} — {spec['label']} ({scale_note})")
            ax.set_xlabel("Threshold percentile")
            ax.set_ylabel("k")
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels([fmt_percentile(x) for x in pivot.columns], rotation=45, ha="right")
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels([str(int(x)) for x in pivot.index])
            annotate_heatmap(ax, true_values, display_values, norm, spec["fmt"])
            fig.colorbar(image, ax=ax, label=spec["label"])

            outpath = individual_dir / f"{version_prefix}_heatmap_{spec['short']}_{mode}.png"
            fig.savefig(outpath, dpi=300, bbox_inches="tight")
            if show:
                plt.show()
            plt.close(fig)


def write_summary_tables(df: pd.DataFrame, raw: pd.DataFrame, mapping: Dict[str, Optional[str]], outdir: Path, version_prefix: str) -> None:
    compact_cols = [
        "k",
        "score_mode",
        "threshold_percentile",
        "threshold_value",
        "false_alarm_tubelets_before_persistence",
        "false_alarm_rate_percent_before_persistence",
        "max_false_alarm_streak_before_persistence",
        "false_alarm_events_after_persistence",
    ]

    compact = df[compact_cols].sort_values(["score_mode", "k", "threshold_percentile"])
    compact.to_csv(outdir / f"{version_prefix}_full_false_alarm_sweep_compact.csv", index=False)

    raw.to_csv(outdir / f"{version_prefix}_original_report_copy.csv", index=False)

    mapping_df = pd.DataFrame(
        [{"canonical_column": k, "source_or_derivation": v} for k, v in mapping.items()]
    )
    mapping_df.to_csv(outdir / f"{version_prefix}_column_mapping_used.csv", index=False)

    rows = []
    for (mode, percentile), group in df.groupby(["score_mode", "threshold_percentile"]):
        row = {
            "score_mode": mode,
            "threshold_percentile": percentile,
            "k_min": int(group["k"].min()),
            "k_max": int(group["k"].max()),
        }
        for metric, spec in METRICS.items():
            row[f"{spec['short']}_min_across_k"] = group[metric].min()
            row[f"{spec['short']}_max_across_k"] = group[metric].max()
        rows.append(row)

    range_summary = pd.DataFrame(rows).sort_values(["score_mode", "threshold_percentile"])
    range_summary.to_csv(outdir / f"{version_prefix}_false_alarm_range_summary_across_k.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate robust generic Deep Gate false-alarm hyperparameter plots.")
    parser.add_argument("--version", required=True, help='Figure title version, e.g. "Deep Gate v1".')
    parser.add_argument("--csv", type=Path, required=True, help="Path to 05_false_alarm_report.csv.")
    parser.add_argument("--outdir", type=Path, required=True, help="Output directory for plots and CSV summaries.")
    parser.add_argument("--k", type=int, default=5, help="Focal k for two-panel threshold plot. Default: 5.")
    parser.add_argument("--ksens-mode", type=str, default="gaussian_sigma_2", help="Score mode for k-sensitivity plot.")
    parser.add_argument("--ksens-percentile", type=float, default=99.5, help="Threshold percentile for k-sensitivity plot.")
    parser.add_argument("--linear", action="store_true", help="Use linear colour scale instead of log-normalised heatmaps.")
    parser.add_argument("--show", action="store_true", help="Display plots interactively as they are generated.")
    parser.add_argument("--all", action="store_true", help="Also generate individual heatmaps for every metric and score mode.")
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    df, mapping, raw = read_false_alarm_report(args.csv)
    version_prefix = safe_name(args.version)
    use_lognorm = not args.linear
    actual_k = choose_available_k(df, args.k)

    print("=" * 80)
    print(f"{args.version} false-alarm hyperparameter plotting")
    print("=" * 80)
    print(f"Input CSV : {args.csv}")
    print(f"Output dir: {args.outdir}")
    print(f"k values  : {sorted(df['k'].unique())}")
    print(f"modes     : {df.attrs['mode_order']}")
    print(f"thresholds: {sorted(df['threshold_percentile'].unique())}")
    print(f"Focal k   : requested={args.k}, used={actual_k}")
    print()
    print("Column mapping / derivation:")
    for canonical, source in mapping.items():
        print(f"  {canonical}: {source}")
    print()

    write_summary_tables(df, raw, mapping, args.outdir, version_prefix)

    plot_metric_heatmap_grid(
        df=df,
        metric="false_alarm_rate_percent_before_persistence",
        outpath=args.outdir / f"{version_prefix}_heatmap_grid_false_alarm_rate_before_persistence.png",
        title=f"{args.version}: false-alarm rate before persistence across hyperparameters",
        annotate=True,
        use_lognorm=use_lognorm,
        show=args.show,
    )

    plot_metric_heatmap_grid(
        df=df,
        metric="false_alarm_events_after_persistence",
        outpath=args.outdir / f"{version_prefix}_heatmap_grid_persistent_false_alarm_events.png",
        title=f"{args.version}: persistent false-alarm events across hyperparameters",
        annotate=True,
        use_lognorm=use_lognorm,
        show=args.show,
    )

    plot_k_fixed_two_panel_summary(
        df=df,
        outpath=args.outdir / f"{version_prefix}_k{actual_k}_line_summary_false_alarm_rate_and_events.png",
        version=args.version,
        k_value=actual_k,
        show=args.show,
    )

    plot_k_sensitivity(
        df=df,
        outpath=args.outdir / f"{version_prefix}_k_sensitivity.png",
        version=args.version,
        requested_mode=args.ksens_mode,
        requested_percentile=args.ksens_percentile,
        show=args.show,
    )

    if args.all:
        plot_individual_heatmaps(
            df=df,
            outdir=args.outdir,
            version_prefix=version_prefix,
            show=args.show,
            use_lognorm=use_lognorm,
        )
        print("  Individual heatmaps written.")

    print()
    print("Done. Output files:")
    for f in sorted(args.outdir.glob("*")):
        if f.is_file():
            print(f"  {f}")


if __name__ == "__main__":
    main()
