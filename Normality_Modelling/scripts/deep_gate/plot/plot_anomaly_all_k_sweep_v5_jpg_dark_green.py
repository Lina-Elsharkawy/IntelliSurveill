#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Deep Gate v5 — anomaly dataset FULL all-k hyperparameter-sweep plots and LaTeX tables

This version fixes:
    1. ALL k values are plotted.
    2. No selected configuration is highlighted.
    3. Plot titles no longer overlap with legends.
    4. The empty sixth subplot is used for the legend in all-k line plots.
    5. Dataset tubelet counts can be supplied manually if the summary JSON is not found.
    6. Output image files are saved as JPG instead of PNG.
    7. Output filenames and figure/table labels use v5 instead of v4.

Important interpretation:
    - Tubelet AUROC/AUPRC are threshold-independent ranking metrics.
      They are computed before deployment thresholding and before persistence.
    - video_recall, video_f1, video_normal_video_false_positive_rate,
      video_tp, video_fp, video_tn, and video_fn are video-level metrics
      after applying thresholding and persistence/event logic.

Example PowerShell command:
python "D:\Embeddings_Distribution\scripts\deep_gate\plot_anomaly_all_k_sweep_v5_jpg.py" --csv "D:\Embeddings_Distribution\anomaly_dataset\outputs\deep_eval_v5_matched_thresholds_2p5fps_16f_s8\reports\06_deep_eval_config_sweep.csv" --summary-json "D:\Embeddings_Distribution\anomaly_dataset\outputs\deep_eval_v5_matched_thresholds_2p5fps_16f_s8\reports\06_deep_eval_summary.json" --outdir "D:\Embeddings_Distribution\anomaly_dataset\outputs\deep_eval_v5_matched_thresholds_2p5fps_16f_s8\plots\all_k_anomaly_eval" --heatmaps
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from cycler import cycler


# ---------------------------------------------------------------------------
# DARK + GREEN THEME
# (theme-only block; no plotting logic below this point is modified)
# ---------------------------------------------------------------------------
_BG = "#0e1410"
_PANEL_BG = "#0e1410"
_GRID = "#2a3530"
_TEXT = "#e8f5e9"
_SUBTEXT = "#cfe8d3"

# Raw -> gray, then progressively brighter greens for sigma=1,2,3.
# This becomes the default color cycle, so every plt.bar()/ax.scatter()/"C{idx}"
# reference in the script below picks these up automatically.
_GREEN_CYCLE = ["#7d8c86", "#4caf50", "#21c97a", "#9be564"]

plt.rcParams.update({
    "figure.facecolor": _BG,
    "savefig.facecolor": _BG,
    "axes.facecolor": _PANEL_BG,
    "axes.edgecolor": _GRID,
    "axes.labelcolor": _TEXT,
    "text.color": _TEXT,
    "xtick.color": _SUBTEXT,
    "ytick.color": _SUBTEXT,
    "grid.color": _GRID,
    "grid.alpha": 0.5,
    "legend.facecolor": "#142019",
    "legend.edgecolor": _GRID,
    "legend.labelcolor": _TEXT,
    "axes.prop_cycle": cycler(color=_GREEN_CYCLE),
})


DEFAULT_CSV = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs"
    r"\deep_eval_v5_matched_thresholds_2p5fps_16f_s8"
    r"\reports\06_deep_eval_config_sweep.csv"
)

DEFAULT_SUMMARY_JSON = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs"
    r"\deep_eval_v5_matched_thresholds_2p5fps_16f_s8"
    r"\reports\06_deep_eval_summary.json"
)

DEFAULT_EMBEDDING_SUMMARY_JSON = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs"
    r"\deep_from_motion_tubelets_liveparity_2p5fps_16f_s8"
    r"\embeddings\deep_from_motion_tubelets_summary.json"
)

DEFAULT_OUTDIR = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs"
    r"\deep_eval_v5_matched_thresholds_2p5fps_16f_s8"
    r"\plots\all_k_anomaly_eval_DARK_GREEN"
)


REQUIRED_COLUMNS = {
    "k",
    "score_col",
    "threshold_key",
    "threshold_value",
    "tubelet_auroc",
    "tubelet_auprc",
    "tubelet_rows_used",
    "video_videos",
    "video_tp",
    "video_fp",
    "video_tn",
    "video_fn",
    "video_precision",
    "video_recall",
    "video_f1",
    "video_specificity",
    "video_normal_video_false_positive_rate",
}


MODE_ORDER = ["raw", "gaussian_sigma_1", "gaussian_sigma_2", "gaussian_sigma_3"]

MODE_LABELS = {
    "raw": "Raw",
    "gaussian_sigma_1": r"Gaussian $\sigma$=1",
    "gaussian_sigma_2": r"Gaussian $\sigma$=2",
    "gaussian_sigma_3": r"Gaussian $\sigma$=3",
}

MODE_LABELS_PLAIN = {
    "raw": "Raw",
    "gaussian_sigma_1": "Gaussian sigma=1",
    "gaussian_sigma_2": "Gaussian sigma=2",
    "gaussian_sigma_3": "Gaussian sigma=3",
}

THRESHOLD_ORDER = ["p95", "p97_5", "p99", "p99_5", "p99_7", "p99_9"]

THRESHOLD_LABELS = {
    "p95": "p95",
    "p97_5": "p97.5",
    "p99": "p99",
    "p99_5": "p99.5",
    "p99_7": "p99.7",
    "p99_9": "p99.9",
}


IMAGE_EXT = ".jpg"


def load_json_if_exists(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    if not path.exists():
        print(f"Warning: JSON file not found, continuing without it:\n  {path}")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def score_mode_from_col(score_col: str) -> str:
    score_col = str(score_col)
    if "gauss_s1" in score_col:
        return "gaussian_sigma_1"
    if "gauss_s2" in score_col:
        return "gaussian_sigma_2"
    if "gauss_s3" in score_col:
        return "gaussian_sigma_3"
    return "raw"


def threshold_label(threshold_key: str) -> str:
    return THRESHOLD_LABELS.get(str(threshold_key), str(threshold_key))


def read_sweep(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found:\n{csv_path}")

    df = pd.read_csv(csv_path)

    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(
            "The CSV is missing these required columns:\n"
            + "\n".join(f"- {col}" for col in sorted(missing))
        )

    df = df.copy()

    numeric_cols = [
        "k",
        "threshold_value",
        "tubelet_auroc",
        "tubelet_auprc",
        "tubelet_rows_used",
        "video_videos",
        "video_tp",
        "video_fp",
        "video_tn",
        "video_fn",
        "video_precision",
        "video_recall",
        "video_f1",
        "video_specificity",
        "video_normal_video_false_positive_rate",
    ]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="raise")

    df["score_mode"] = df["score_col"].apply(score_mode_from_col)

    known_modes = [m for m in MODE_ORDER if m in set(df["score_mode"])]
    extra_modes = sorted(set(df["score_mode"]) - set(known_modes))
    df.attrs["mode_order"] = known_modes + extra_modes

    known_thresholds = [t for t in THRESHOLD_ORDER if t in set(df["threshold_key"])]
    extra_thresholds = sorted(set(df["threshold_key"]) - set(known_thresholds))
    df.attrs["threshold_order"] = known_thresholds + extra_thresholds

    df["score_mode_label"] = df["score_mode"].map(MODE_LABELS_PLAIN).fillna(df["score_mode"])
    df["threshold_label"] = df["threshold_key"].map(THRESHOLD_LABELS).fillna(df["threshold_key"])

    return df


def get_dataset_counts(
    summary: dict,
    df: pd.DataFrame,
    normal_tubelets_arg: Optional[int],
    anomaly_tubelets_arg: Optional[int],
) -> Tuple[int, int, int, int]:
    label_counts = summary.get("label_counts", {})

    normal_tubelets = int(label_counts.get("normal", 0))
    anomaly_tubelets = int(label_counts.get("anomaly", 0))

    if normal_tubelets_arg is not None:
        normal_tubelets = int(normal_tubelets_arg)
    if anomaly_tubelets_arg is not None:
        anomaly_tubelets = int(anomaly_tubelets_arg)

    first = df.iloc[0]
    normal_videos = int(first["video_tn"] + first["video_fp"])
    anomaly_videos = int(first["video_tp"] + first["video_fn"])

    return normal_tubelets, anomaly_tubelets, normal_videos, anomaly_videos


def save_figure(fig, outpath: Path, show: bool = False) -> None:
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300, bbox_inches="tight", format="jpg", pil_kwargs={"quality": 95})
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_dataset_composition(
    summary: dict,
    embedding_summary: dict,
    df: pd.DataFrame,
    outpath: Path,
    normal_tubelets_arg: Optional[int],
    anomaly_tubelets_arg: Optional[int],
    show: bool = False,
) -> None:
    normal_tubelets, anomaly_tubelets, normal_videos, anomaly_videos = get_dataset_counts(
        summary, df, normal_tubelets_arg, anomaly_tubelets_arg
    )

    fig, axes = plt.subplots(1, 2, figsize=(9, 5), constrained_layout=True)

    panels = [
        ("Tubelets", ["Normal", "Anomaly"], [normal_tubelets, anomaly_tubelets]),
        ("Videos", ["Normal", "Anomaly"], [normal_videos, anomaly_videos]),
    ]

    for ax, (title, labels, values) in zip(axes, panels):
        bars = ax.bar(labels, values, width=0.55, edgecolor="white", linewidth=1.0)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.set_ylabel("Count")
        ax.grid(axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)

        ymax = max(values) if max(values) > 0 else 1
        ax.set_ylim(0, ymax * 1.20)

        total = sum(values)
        for bar, value in zip(bars, values):
            pct = 100 * value / total if total > 0 else 0
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + ymax * 0.03,
                f"{int(value)}\n({pct:.1f}%)",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    subtitle = ""
    saved = embedding_summary.get("saved_embeddings") or embedding_summary.get("final_saved_embeddings")
    invalid = embedding_summary.get("invalid_embeddings")
    if saved is not None and invalid is not None:
        subtitle = f"\n{saved} saved embeddings · {invalid} invalid"

    fig.suptitle(
        f"Deep Gate v5 anomaly-evaluation dataset composition{subtitle}",
        fontsize=13,
        fontweight="bold",
    )

    save_figure(fig, outpath, show)


def plot_auc_auprc_grouped(
    df: pd.DataFrame,
    outpath: Path,
    show: bool = False,
) -> None:
    unique_scores = (
        df[["k", "score_mode", "tubelet_auroc", "tubelet_auprc"]]
        .drop_duplicates()
        .copy()
    )

    mode_order = df.attrs["mode_order"]
    k_values = sorted(unique_scores["k"].unique())

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)

    width = 0.18
    x = np.arange(len(k_values))

    for metric, ax, ylabel, panel_title in [
        ("tubelet_auroc", axes[0], "AUROC", "Tubelet AUROC"),
        ("tubelet_auprc", axes[1], "AUPRC", "Tubelet AUPRC"),
    ]:
        for mode_idx, mode in enumerate(mode_order):
            sub = (
                unique_scores[unique_scores["score_mode"] == mode]
                .set_index("k")
                .reindex(k_values)
            )
            offset = (mode_idx - (len(mode_order) - 1) / 2) * width

            bars = ax.bar(
                x + offset,
                sub[metric],
                width=width,
                label=MODE_LABELS.get(mode, mode),
                edgecolor="white",
                linewidth=0.6,
            )

            for bar in bars:
                h = bar.get_height()
                if np.isfinite(h):
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        h + 0.004,
                        f"{h:.2f}",
                        ha="center",
                        va="bottom",
                        fontsize=6,
                        rotation=90,
                    )

        ax.set_title(panel_title, fontsize=11, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.set_xlabel("k")
        ax.set_xticks(x)
        ax.set_xticklabels([str(int(k)) for k in k_values])
        ax.set_ylim(0.0, 1.0)
        ax.grid(True, axis="y", alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(title="Score mode", fontsize=8)

    fig.suptitle(
        "Deep Gate v5 tubelet-level ranking performance before thresholding and persistence",
        fontsize=13,
        fontweight="bold",
    )
    save_figure(fig, outpath, show)


def plot_metric_vs_threshold_all_k(
    df: pd.DataFrame,
    outpath: Path,
    metric: str,
    metric_label: str,
    title: str,
    y_max: Optional[float] = None,
    show: bool = False,
) -> None:
    k_values = sorted(df["k"].unique())
    mode_order = df.attrs["mode_order"]
    threshold_order = df.attrs["threshold_order"]

    ncols = 3
    nrows = 2

    fig, axes = plt.subplots(nrows, ncols, figsize=(15.5, 8.5), constrained_layout=False)
    axes_flat = np.array(axes).ravel()

    x = np.arange(len(threshold_order))
    x_labels = [threshold_label(t) for t in threshold_order]

    handles = None
    labels = None

    for ax, k in zip(axes_flat, k_values):
        sub_k = df[df["k"] == k].copy()

        for mode in mode_order:
            group = (
                sub_k[sub_k["score_mode"] == mode]
                .set_index("threshold_key")
                .reindex(threshold_order)
            )
            if group.empty:
                continue

            ax.plot(
                x,
                group[metric],
                marker="o",
                linewidth=1.8,
                label=MODE_LABELS.get(mode, mode),
            )

        ax.set_title(f"k = {int(k)}", fontsize=11, fontweight="bold")
        ax.set_xlabel("Threshold percentile")
        ax.set_ylabel(metric_label)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, rotation=35, ha="right")
        ax.grid(True, alpha=0.3)
        ax.spines[["top", "right"]].set_visible(False)

        if y_max is not None:
            ax.set_ylim(-0.02, y_max)
        else:
            ymax = max(0.1, float(df[metric].max()) + 0.05)
            ax.set_ylim(-0.02, ymax)

        if handles is None:
            handles, labels = ax.get_legend_handles_labels()

    legend_ax = axes_flat[len(k_values)]
    legend_ax.axis("off")
    if handles and labels:
        legend_ax.legend(
            handles,
            labels,
            title="Score mode",
            loc="center",
            fontsize=10,
            frameon=True,
        )

    fig.suptitle(title, fontsize=14, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.94])

    save_figure(fig, outpath, show)


def plot_counts_vs_threshold_all_k(
    df: pd.DataFrame,
    outpath: Path,
    show: bool = False,
) -> None:
    k_values = sorted(df["k"].unique())
    mode_order = df.attrs["mode_order"]
    threshold_order = df.attrs["threshold_order"]

    count_metrics = [
        ("video_tp", "TP"),
        ("video_fp", "FP"),
        ("video_tn", "TN"),
        ("video_fn", "FN"),
    ]

    nrows = len(k_values)
    ncols = len(count_metrics)

    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(17, 3.0 * nrows),
        constrained_layout=False,
        sharex=True,
    )

    x = np.arange(len(threshold_order))
    x_labels = [threshold_label(t) for t in threshold_order]

    handles = None
    labels = None

    for row_idx, k in enumerate(k_values):
        sub_k = df[df["k"] == k].copy()

        for col_idx, (metric, metric_name) in enumerate(count_metrics):
            ax = axes[row_idx, col_idx]

            for mode in mode_order:
                group = (
                    sub_k[sub_k["score_mode"] == mode]
                    .set_index("threshold_key")
                    .reindex(threshold_order)
                )
                if group.empty:
                    continue

                ax.plot(
                    x,
                    group[metric],
                    marker="o",
                    linewidth=1.5,
                    label=MODE_LABELS.get(mode, mode),
                )

            ax.set_title(f"k={int(k)} | {metric_name}", fontsize=10, fontweight="bold")
            ax.set_xticks(x)
            ax.set_xticklabels(x_labels, rotation=35, ha="right")
            ax.set_ylabel("Video count")
            ax.grid(True, alpha=0.3)
            ax.spines[["top", "right"]].set_visible(False)

            if handles is None:
                handles, labels = ax.get_legend_handles_labels()

    fig.suptitle(
        "Deep Gate v5 video-level TP/FP/TN/FN counts after thresholding and persistence",
        fontsize=14,
        fontweight="bold",
        y=0.995,
    )

    if handles and labels:
        fig.legend(
            handles,
            labels,
            title="Score mode",
            loc="upper center",
            bbox_to_anchor=(0.5, 0.975),
            ncol=4,
            fontsize=9,
            frameon=True,
        )

    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.95])

    save_figure(fig, outpath, show)


def plot_operating_point_scatter(
    df: pd.DataFrame,
    outpath: Path,
    show: bool = False,
) -> None:
    k_values = sorted(df["k"].unique())
    markers = ["o", "s", "^", "D", "P", "X", "v"]
    marker_by_k = {k: markers[i % len(markers)] for i, k in enumerate(k_values)}

    fig, ax = plt.subplots(figsize=(10.5, 6), constrained_layout=True)

    mode_handles = []
    k_handles = []

    mode_colours = {}
    for idx, mode in enumerate(df.attrs["mode_order"]):
        mode_colours[mode] = f"C{idx}"

    for mode in df.attrs["mode_order"]:
        for k in k_values:
            sub = df[(df["score_mode"] == mode) & (df["k"] == k)].copy()
            if sub.empty:
                continue

            sizes = 55 + 420 * sub["video_f1"].fillna(0.0).clip(lower=0.0)

            ax.scatter(
                sub["video_normal_video_false_positive_rate"],
                sub["video_recall"],
                s=sizes,
                marker=marker_by_k[k],
                alpha=0.72,
                edgecolors="white",
                linewidths=0.5,
                color=mode_colours[mode],
            )

    from matplotlib.lines import Line2D

    for mode in df.attrs["mode_order"]:
        mode_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                markerfacecolor=mode_colours[mode],
                markersize=9,
                label=MODE_LABELS.get(mode, mode),
            )
        )

    for k in k_values:
        k_handles.append(
            Line2D(
                [0],
                [0],
                marker=marker_by_k[k],
                color="w",
                markerfacecolor="#666666",
                markersize=9,
                label=f"k={int(k)}",
            )
        )

    handles = mode_handles + [Line2D([0], [0], color="none", label="")] + k_handles

    ax.legend(
        handles=handles,
        title="Colour = score mode; marker = k",
        fontsize=8,
        loc="upper right",
        frameon=True,
    )

    ax.set_title(
        "Deep Gate v5 operating-point trade-off after thresholding and persistence",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_xlabel("Normal-video false-positive rate")
    ax.set_ylabel("Video recall")
    ax.set_xlim(-0.02, max(0.05, float(df["video_normal_video_false_positive_rate"].max()) + 0.04))
    ax.set_ylim(-0.02, max(0.5, float(df["video_recall"].max()) + 0.08))
    ax.grid(True, alpha=0.3)
    ax.spines[["top", "right"]].set_visible(False)

    save_figure(fig, outpath, show)


def make_pivot(df: pd.DataFrame, mode: str, metric: str) -> pd.DataFrame:
    sub = df[df["score_mode"] == mode].copy()
    ks = sorted(sub["k"].unique())
    thresholds = [t for t in df.attrs["threshold_order"] if t in set(sub["threshold_key"])]

    pivot = sub.pivot_table(
        index="k",
        columns="threshold_key",
        values=metric,
        aggfunc="mean",
    )

    return pivot.loc[ks, thresholds]


def annotate_heatmap(ax, values: np.ndarray, fmt: str) -> None:
    vmax = np.nanmax(values) if np.isfinite(values).any() else 1.0
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            value = values[i, j]
            if np.isfinite(value):
                color = "white" if vmax > 0 and value > 0.55 * vmax else "black"
                ax.text(
                    j,
                    i,
                    format(value, fmt),
                    ha="center",
                    va="center",
                    fontsize=7,
                    fontweight="bold",
                    color=color,
                )


def plot_metric_heatmap_grid(
    df: pd.DataFrame,
    metric: str,
    label: str,
    outpath: Path,
    fmt: str = ".2f",
    show: bool = False,
) -> None:
    mode_order = df.attrs["mode_order"]
    pivots: Dict[str, pd.DataFrame] = {}
    all_values = []

    for mode in mode_order:
        pivot = make_pivot(df, mode, metric)
        pivots[mode] = pivot
        all_values.extend(pivot.values.ravel().tolist())

    vals = np.array([v for v in all_values if np.isfinite(v)], dtype=float)
    vmin = float(vals.min()) if vals.size else 0.0
    vmax = float(vals.max()) if vals.size else 1.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=False)
    axes_flat = axes.ravel()
    last_image = None

    for ax, mode in zip(axes_flat, mode_order):
        pivot = pivots[mode]
        image = ax.imshow(pivot.values, aspect="auto", norm=norm)
        last_image = image

        ax.set_title(MODE_LABELS.get(mode, mode))
        ax.set_xlabel("Threshold")
        ax.set_ylabel("k")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([threshold_label(t) for t in pivot.columns], rotation=45, ha="right")
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(int(k)) for k in pivot.index])
        annotate_heatmap(ax, pivot.values, fmt)

    fig.suptitle(f"Deep Gate v5 {label} after thresholding and persistence", fontsize=14, fontweight="bold")
    fig.colorbar(last_image, ax=axes_flat.tolist(), label=label, shrink=0.85)
    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.94])

    save_figure(fig, outpath, show)


def format_float(x: float, digits: int = 3) -> str:
    if pd.isna(x):
        return ""
    return f"{float(x):.{digits}f}"


def build_table_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    table = df.copy()
    table["threshold_order_idx"] = table["threshold_key"].apply(
        lambda x: THRESHOLD_ORDER.index(x) if x in THRESHOLD_ORDER else 999
    )
    table["score_mode_order_idx"] = table["score_mode"].apply(
        lambda x: MODE_ORDER.index(x) if x in MODE_ORDER else 999
    )
    table = table.sort_values(["k", "score_mode_order_idx", "threshold_order_idx"])

    out = pd.DataFrame({
        "k": table["k"].astype(int),
        "Mode": table["score_mode"].map(MODE_LABELS_PLAIN).fillna(table["score_mode"]),
        "Thr.": table["threshold_key"].map(THRESHOLD_LABELS).fillna(table["threshold_key"]),
        "AUROC": table["tubelet_auroc"].map(lambda x: format_float(x, 3)),
        "AUPRC": table["tubelet_auprc"].map(lambda x: format_float(x, 3)),
        "TP": table["video_tp"].astype(int),
        "FP": table["video_fp"].astype(int),
        "TN": table["video_tn"].astype(int),
        "FN": table["video_fn"].astype(int),
        "Prec.": table["video_precision"].map(lambda x: format_float(x, 3)),
        "Rec.": table["video_recall"].map(lambda x: format_float(x, 3)),
        "F1": table["video_f1"].map(lambda x: format_float(x, 3)),
        "Spec.": table["video_specificity"].map(lambda x: format_float(x, 3)),
        "NV-FPR": table["video_normal_video_false_positive_rate"].map(lambda x: format_float(x, 3)),
    })
    return out


def latex_escape(text: object) -> str:
    s = str(text)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s


def dataframe_to_latex_longtable(
    df: pd.DataFrame,
    caption: str,
    label: str,
    outpath: Path,
) -> None:
    cols = list(df.columns)
    alignment = "rllrrrrrrrrrrr"
    header = " & ".join(latex_escape(c) for c in cols) + r" \\" 

    lines = []
    lines.append(r"% Requires: \usepackage{booktabs,longtable}")
    lines.append(r"\begin{longtable}{" + alignment + "}")
    lines.append(r"\caption{" + latex_escape(caption) + r"}")
    lines.append(r"\label{" + latex_escape(label) + r"}\\")
    lines.append(r"\toprule")
    lines.append(header)
    lines.append(r"\midrule")
    lines.append(r"\endfirsthead")
    lines.append(r"\toprule")
    lines.append(header)
    lines.append(r"\midrule")
    lines.append(r"\endhead")
    lines.append(r"\midrule")
    lines.append(r"\multicolumn{" + str(len(cols)) + r"}{r}{Continued on next page}\\")
    lines.append(r"\midrule")
    lines.append(r"\endfoot")
    lines.append(r"\bottomrule")
    lines.append(r"\endlastfoot")

    for _, row in df.iterrows():
        values = [latex_escape(row[c]) for c in cols]
        lines.append(" & ".join(values) + r" \\")

    lines.append(r"\end{longtable}")
    outpath.write_text("\n".join(lines), encoding="utf-8")


def dataframe_to_latex_table(
    df: pd.DataFrame,
    caption: str,
    label: str,
    outpath: Path,
) -> None:
    cols = list(df.columns)
    alignment = "rllrrrrrrrrrrr"
    lines = []
    lines.append(r"% Requires: \usepackage{booktabs,graphicx,float}")
    lines.append(r"\begin{table}[H]")
    lines.append(r"\centering")
    lines.append(r"\scriptsize")
    lines.append(r"\caption{" + latex_escape(caption) + r"}")
    lines.append(r"\label{" + latex_escape(label) + r"}")
    lines.append(r"\resizebox{\textwidth}{!}{%")
    lines.append(r"\begin{tabular}{" + alignment + "}")
    lines.append(r"\toprule")
    lines.append(" & ".join(latex_escape(c) for c in cols) + r" \\")
    lines.append(r"\midrule")
    for _, row in df.iterrows():
        lines.append(" & ".join(latex_escape(row[c]) for c in cols) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}%")
    lines.append(r"}")
    lines.append(r"\end{table}")
    outpath.write_text("\n".join(lines), encoding="utf-8")


def write_summary_tables(df: pd.DataFrame, outdir: Path) -> None:
    tables_dir = outdir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    table_df = build_table_dataframe(df)

    table_df.to_csv(tables_dir / "v5_anomaly_all_configurations_metrics.csv", index=False)

    dataframe_to_latex_longtable(
        table_df,
        caption=(
            "Deep Gate v5 anomaly-dataset evaluation across all hyperparameter "
            "configurations. Video-level metrics are computed after thresholding "
            "and persistence."
        ),
        label="tab:deep_v5_anomaly_all_configs",
        outpath=tables_dir / "v5_anomaly_all_configurations_metrics_longtable.tex",
    )

    for k in sorted(df["k"].unique()):
        k_table = table_df[table_df["k"] == int(k)].copy()
        dataframe_to_latex_table(
            k_table,
            caption=(
                f"Deep Gate v5 anomaly-dataset evaluation for k={int(k)} "
                "across all score modes and thresholds. Video-level metrics are "
                "computed after thresholding and persistence."
            ),
            label=f"tab:deep_v5_anomaly_k{int(k)}",
            outpath=tables_dir / f"v5_anomaly_metrics_k{int(k)}.tex",
        )

    compact_cols = [
        "k",
        "score_mode_label",
        "threshold_label",
        "threshold_value",
        "tubelet_auroc",
        "tubelet_auprc",
        "video_tp",
        "video_fp",
        "video_tn",
        "video_fn",
        "video_precision",
        "video_recall",
        "video_f1",
        "video_specificity",
        "video_normal_video_false_positive_rate",
    ]

    ranked = df[compact_cols].sort_values(
        ["video_f1", "video_recall", "video_normal_video_false_positive_rate"],
        ascending=[False, False, True],
    )
    ranked.to_csv(tables_dir / "v5_anomaly_configurations_ranked_by_f1.csv", index=False)

    zero_fp = df[df["video_fp"] == 0].copy()
    zero_fp[compact_cols].sort_values(
        ["video_recall", "video_f1"], ascending=False
    ).to_csv(tables_dir / "v5_anomaly_zero_fp_configurations.csv", index=False)

    print(f"  Tables written to: {tables_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Deep Gate v5 anomaly-dataset FULL all-k hyperparameter sweep "
            "plots and LaTeX tables."
        )
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to 06_deep_eval_config_sweep.csv.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_SUMMARY_JSON,
        help="Optional path to 06_deep_eval_summary.json.",
    )
    parser.add_argument(
        "--embedding-summary-json",
        type=Path,
        default=DEFAULT_EMBEDDING_SUMMARY_JSON,
        help="Optional path to deep_from_motion_tubelets_summary.json.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help="Output folder for plots and tables.",
    )
    parser.add_argument(
        "--normal-tubelets",
        type=int,
        default=None,
        help="Optional manual normal tubelet count if summary JSON is unavailable.",
    )
    parser.add_argument(
        "--anomaly-tubelets",
        type=int,
        default=None,
        help="Optional manual anomaly tubelet count if summary JSON is unavailable.",
    )
    parser.add_argument(
        "--heatmaps",
        action="store_true",
        help="Also generate heatmap grids for recall, F1, FPR, TP, FP, TN, FN.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display plots interactively as they are generated.",
    )
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("Deep Gate v5 anomaly ALL-K hyperparameter-sweep plotting")
    print("=" * 80)
    print(f"CSV                  : {args.csv}")
    print(f"Summary JSON         : {args.summary_json}")
    print(f"Embedding summary    : {args.embedding_summary_json}")
    print(f"Output directory     : {args.outdir}")
    print(f"Manual tubelets      : normal={args.normal_tubelets}, anomaly={args.anomaly_tubelets}")
    print(f"Heatmaps             : {args.heatmaps}")
    print()

    df = read_sweep(args.csv)
    summary = load_json_if_exists(args.summary_json)
    embedding_summary = load_json_if_exists(args.embedding_summary_json)

    print(f"Loaded {len(df)} sweep rows.")
    print(f"k values             : {sorted(df['k'].unique())}")
    print(f"thresholds           : {df.attrs['threshold_order']}")
    print(f"score modes          : {df.attrs['mode_order']}")
    print()

    print("Writing tables...")
    write_summary_tables(df, args.outdir)

    print("Generating plots...")

    plot_dataset_composition(
        summary=summary,
        embedding_summary=embedding_summary,
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_01_dataset_composition{IMAGE_EXT}",
        normal_tubelets_arg=args.normal_tubelets,
        anomaly_tubelets_arg=args.anomaly_tubelets,
        show=args.show,
    )

    plot_auc_auprc_grouped(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_02_tubelet_auroc_auprc_all_k{IMAGE_EXT}",
        show=args.show,
    )

    plot_metric_vs_threshold_all_k(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_03_video_recall_vs_threshold_ALL_K{IMAGE_EXT}",
        metric="video_recall",
        metric_label="Video recall",
        title="Deep Gate v5 video recall after thresholding and persistence for ALL k values",
        y_max=0.55,
        show=args.show,
    )

    plot_metric_vs_threshold_all_k(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_04_video_f1_vs_threshold_ALL_K{IMAGE_EXT}",
        metric="video_f1",
        metric_label="Video F1",
        title="Deep Gate v5 video F1 after thresholding and persistence for ALL k values",
        y_max=0.65,
        show=args.show,
    )

    plot_metric_vs_threshold_all_k(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_05_normal_video_fpr_vs_threshold_ALL_K{IMAGE_EXT}",
        metric="video_normal_video_false_positive_rate",
        metric_label="Normal-video false-positive rate",
        title="Deep Gate v5 normal-video FPR after thresholding and persistence for ALL k values",
        y_max=0.30,
        show=args.show,
    )

    plot_counts_vs_threshold_all_k(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_06_tp_fp_tn_fn_counts_vs_threshold_ALL_K{IMAGE_EXT}",
        show=args.show,
    )

    plot_operating_point_scatter(
        df=df,
        outpath=args.outdir / f"FIG_v5_anomaly_07_operating_point_tradeoff_ALL_CONFIGS{IMAGE_EXT}",
        show=args.show,
    )

    if args.heatmaps:
        heatmap_specs = [
            ("video_recall", "video recall", ".2f"),
            ("video_f1", "video F1", ".2f"),
            ("video_precision", "video precision", ".2f"),
            ("video_specificity", "video specificity", ".2f"),
            ("video_normal_video_false_positive_rate", "normal-video FPR", ".2f"),
            ("video_tp", "TP", ".0f"),
            ("video_fp", "FP", ".0f"),
            ("video_tn", "TN", ".0f"),
            ("video_fn", "FN", ".0f"),
        ]
        heatmap_dir = args.outdir / "heatmaps"
        heatmap_dir.mkdir(parents=True, exist_ok=True)

        for metric, label, fmt in heatmap_specs:
            plot_metric_heatmap_grid(
                df=df,
                metric=metric,
                label=label,
                outpath=heatmap_dir / f"FIG_v5_anomaly_heatmap_{metric}_ALL_K{IMAGE_EXT}",
                fmt=fmt,
                show=args.show,
            )

    print()
    print("Created main plots:")
    for f in sorted(args.outdir.glob("FIG_v5_anomaly_*" + IMAGE_EXT)):
        print(f"  {f}")

    if args.heatmaps:
        print()
        print("Created heatmaps:")
        for f in sorted((args.outdir / "heatmaps").glob("FIG_v5_anomaly_heatmap_*" + IMAGE_EXT)):
            print(f"  {f}")

    print()
    print("Created tables:")
    for f in sorted((args.outdir / "tables").glob("*")):
        print(f"  {f}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
