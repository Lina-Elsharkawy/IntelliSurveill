#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
Deep Gate v4 — false-alarm hyperparameter plotting script

Place this file here:
    D:\Embeddings_Distribution\scripts\deep_gate\plot_v4_false_alarm_hyperparams.py

Default input CSV:
    D:\Embeddings_Distribution\normality_models\deep_gate\
    deep_branch_artifacts_v4_liveparity_2p5fps_16f_s8_gaussian\
    05_false_alarm_report.csv

Default output directory:
    D:\Embeddings_Distribution\normality_models\deep_gate\
    deep_branch_artifacts_v4_liveparity_2p5fps_16f_s8_gaussian\
    plots\v4_false_alarm_hyperparam_summary

Main use:
    python plot_v4_false_alarm_hyperparams.py ^
      --csv "D:\...\05_false_alarm_report.csv" ^
      --outdir "D:\...\plots\v4_false_alarm_hyperparam_summary"

Optional:
    --show
        Display plots interactively.

    --all
        Generate individual heatmaps for every metric and score mode.

    --linear
        Use linear colour scaling instead of log-normalised heatmaps.

    --k 5
        Focal k for the two-panel threshold/smoothing line plot.

    --ksens-mode gaussian_sigma_2
        Score mode used for the k-sensitivity figure.

    --ksens-percentile 99.5
        Threshold percentile used for the k-sensitivity figure.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


DEFAULT_CSV = Path(
    r"D:\Embeddings_Distribution\normality_models\deep_gate"
    r"\deep_branch_artifacts_v4_liveparity_2p5fps_16f_s8_gaussian"
    r"\05_false_alarm_report.csv"
)

DEFAULT_OUTDIR = Path(
    r"D:\Embeddings_Distribution\normality_models\deep_gate"
    r"\deep_branch_artifacts_v4_liveparity_2p5fps_16f_s8_gaussian"
    r"\plots\v4_false_alarm_hyperparam_summary"
)

REQUIRED_COLUMNS = {
    "k",
    "score_mode",
    "threshold_percentile",
    "threshold_value",
    "false_alarm_tubelets_before_persistence",
    "false_alarm_rate_percent_before_persistence",
    "max_false_alarm_streak_before_persistence",
    "false_alarm_events_after_persistence",
}

MODE_ORDER = [
    "raw",
    "gaussian_sigma_1",
    "gaussian_sigma_2",
    "gaussian_sigma_3",
]

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


def fmt_percentile(value: float) -> str:
    """Format 95.0 as 95 and 99.5 as 99.5."""
    return f"{float(value):g}"


def read_false_alarm_report(csv_path: Path) -> pd.DataFrame:
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
    df["k"] = pd.to_numeric(df["k"], errors="raise")
    df["threshold_percentile"] = pd.to_numeric(
        df["threshold_percentile"], errors="raise"
    )
    df["threshold_value"] = pd.to_numeric(df["threshold_value"], errors="raise")

    for metric in METRICS:
        df[metric] = pd.to_numeric(df[metric], errors="raise")

    known_modes = [m for m in MODE_ORDER if m in set(df["score_mode"])]
    extra_modes = sorted(set(df["score_mode"]) - set(known_modes))
    df.attrs["mode_order"] = known_modes + extra_modes

    return df


def make_pivot(df: pd.DataFrame, mode: str, metric: str) -> pd.DataFrame:
    sub = df[df["score_mode"] == mode].copy()
    if sub.empty:
        raise ValueError(f"No rows found for score_mode={mode}")

    ks = sorted(sub["k"].unique())
    percentiles = sorted(sub["threshold_percentile"].unique())

    pivot = sub.pivot_table(
        index="k",
        columns="threshold_percentile",
        values=metric,
        aggfunc="mean",
    )

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
    """Replace non-positive values only for LogNorm display. Annotations keep true values."""
    display = values.astype(float).copy()
    if use_lognorm:
        floor = positive_floor(display.ravel())
        display[~np.isfinite(display)] = np.nan
        display[display <= 0] = floor
    return display


def annotation_colour(value: float, norm: mcolors.Normalize) -> str:
    """Use white text on high-intensity cells and black text on low-intensity cells."""
    try:
        scaled = float(norm(value if value > 0 else getattr(norm, "vmin", 0.0)))
    except Exception:
        scaled = 0.0
    return "white" if scaled > 0.55 else "black"


def annotate_heatmap(
    ax,
    true_values: np.ndarray,
    display_values: np.ndarray,
    norm: mcolors.Normalize,
    fmt: str,
) -> None:
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

    fig, axes = plt.subplots(2, 2, figsize=(14, 8), constrained_layout=True)
    axes_flat = axes.ravel()

    last_image = None
    for ax, mode in zip(axes_flat, mode_order):
        pivot = pivots[mode]
        true_values = pivot.values.astype(float)
        display_values = values_for_display(true_values, use_lognorm=use_lognorm)

        image = ax.imshow(
            display_values,
            aspect="auto",
            norm=norm,
            cmap="YlOrRd",
        )
        last_image = image

        ax.set_title(MODE_LABELS.get(mode, mode), fontsize=11)
        ax.set_xlabel("Threshold percentile")
        ax.set_ylabel("k")
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(
            [fmt_percentile(x) for x in pivot.columns],
            rotation=45,
            ha="right",
        )
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(int(x)) for x in pivot.index])

        if annotate:
            annotate_heatmap(ax, true_values, display_values, norm, spec["fmt"])

    for ax in axes_flat[len(mode_order):]:
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
    k_value: int = 5,
    show: bool = False,
) -> None:
    mode_order = df.attrs["mode_order"]
    sub = df[df["k"] == k_value].copy()

    if sub.empty:
        raise ValueError(f"No rows found for k={k_value}")

    percentiles_sorted = sorted(sub["threshold_percentile"].unique())
    x_labels = [fmt_percentile(p) for p in percentiles_sorted]
    x_pos = list(range(len(percentiles_sorted)))

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)

    metric_left = "false_alarm_rate_percent_before_persistence"
    metric_right = "false_alarm_events_after_persistence"

    for mode in mode_order:
        group = (
            sub[sub["score_mode"] == mode]
            .sort_values("threshold_percentile")
            .set_index("threshold_percentile")
        )
        if group.empty:
            continue

        label = MODE_LABELS.get(mode, mode)
        y_left = [group.loc[p, metric_left] for p in percentiles_sorted]
        y_right = [group.loc[p, metric_right] for p in percentiles_sorted]

        axes[0].plot(x_pos, y_left, marker="o", label=label, linewidth=1.8)
        axes[1].plot(x_pos, y_right, marker="o", label=label, linewidth=1.8)

    for ax, ylabel, panel_title in zip(
        axes,
        [
            "False-alarm rate before persistence (%)",
            "Events after persistence",
        ],
        [
            f"Tubelet-level false-alarm rate (k={k_value})",
            f"Persistent false-alarm events (k={k_value})",
        ],
    ):
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_xlabel("Threshold percentile")
        ax.set_ylabel(ylabel)
        ax.set_title(panel_title)
        ax.grid(True, alpha=0.3)
        ax.legend(title="Score mode", fontsize=9)

    fig.suptitle(
        "Deep Gate v4 — normal-validation sensitivity at the focal k value",
        fontsize=13,
        fontweight="bold",
    )
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_k_sensitivity(
    df: pd.DataFrame,
    outpath: Path,
    selected_mode: str = "gaussian_sigma_2",
    selected_percentile: float = 99.5,
    show: bool = False,
) -> None:
    sub = df[
        (df["score_mode"] == selected_mode)
        & (df["threshold_percentile"] == selected_percentile)
    ].sort_values("k").copy()

    if sub.empty:
        raise ValueError(
            f"No rows found for score_mode={selected_mode}, "
            f"threshold_percentile={selected_percentile}"
        )

    k_vals = sub["k"].tolist()
    fa_rate = sub["false_alarm_rate_percent_before_persistence"].tolist()
    fa_events = sub["false_alarm_events_after_persistence"].tolist()

    mode_label = MODE_LABELS.get(selected_mode, selected_mode)
    percentile_label = fmt_percentile(selected_percentile)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), constrained_layout=True)

    axes[0].plot(k_vals, fa_rate, marker="o", linewidth=2)
    axes[0].set_title(
        f"Tubelet-level false-alarm rate\n({mode_label}, p{percentile_label})"
    )
    axes[0].set_xlabel("k (number of nearest neighbours)")
    axes[0].set_ylabel("False-alarm rate before persistence (%)")
    axes[0].set_xticks(k_vals)
    axes[0].grid(True, alpha=0.3)
    for kv, yr in zip(k_vals, fa_rate):
        axes[0].annotate(
            f"{yr:.3f}%",
            xy=(kv, yr),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    axes[1].plot(k_vals, fa_events, marker="s", linewidth=2)
    axes[1].set_title(
        f"Persistent false-alarm events\n({mode_label}, p{percentile_label})"
    )
    axes[1].set_xlabel("k (number of nearest neighbours)")
    axes[1].set_ylabel("Events after persistence")
    axes[1].set_xticks(k_vals)
    axes[1].grid(True, alpha=0.3)
    for kv, ye in zip(k_vals, fa_events):
        axes[1].annotate(
            str(int(ye)),
            xy=(kv, ye),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    fig.suptitle(
        f"Deep Gate v4 — k sensitivity at the selected configuration "
        f"({mode_label}, p{percentile_label})",
        fontsize=13,
        fontweight="bold",
    )
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    if show:
        plt.show()
    plt.close(fig)
    print(f"  Saved: {outpath.name}")


def plot_individual_heatmaps(
    df: pd.DataFrame,
    outdir: Path,
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
            ax.set_title(
                f"{MODE_LABELS.get(mode, mode)} — {spec['label']} ({scale_note})"
            )
            ax.set_xlabel("Threshold percentile")
            ax.set_ylabel("k")
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels(
                [fmt_percentile(x) for x in pivot.columns],
                rotation=45,
                ha="right",
            )
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels([str(int(x)) for x in pivot.index])
            annotate_heatmap(ax, true_values, display_values, norm, spec["fmt"])
            fig.colorbar(image, ax=ax, label=spec["label"])

            outpath = individual_dir / f"heatmap_{spec['short']}_{mode}.png"
            fig.savefig(outpath, dpi=300, bbox_inches="tight")
            if show:
                plt.show()
            plt.close(fig)


def write_summary_tables(df: pd.DataFrame, outdir: Path) -> None:
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
    compact.to_csv(outdir / "v4_full_false_alarm_sweep_compact.csv", index=False)

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
    range_summary.to_csv(
        outdir / "v4_false_alarm_range_summary_across_k.csv",
        index=False,
    )

    for metric, spec in METRICS.items():
        table_rows = []
        for mode in df.attrs["mode_order"]:
            row = {"score_mode": MODE_LABELS.get(mode, mode)}
            mode_df = df[df["score_mode"] == mode]
            for percentile in sorted(mode_df["threshold_percentile"].unique()):
                group = mode_df[mode_df["threshold_percentile"] == percentile]
                min_value = group[metric].min()
                max_value = group[metric].max()

                if spec["fmt"] == ".0f":
                    cell = f"{int(min_value)}–{int(max_value)}"
                else:
                    cell = f"{min_value:.3f}–{max_value:.3f}"

                row[f"p{fmt_percentile(percentile)}"] = cell

            table_rows.append(row)

        thesis_table = pd.DataFrame(table_rows)
        thesis_table.to_csv(
            outdir / f"v4_thesis_range_table_{spec['short']}.csv",
            index=False,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Deep Gate v4 false-alarm hyperparameter plots."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Path to 05_false_alarm_report.csv.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_OUTDIR,
        help="Output directory for plots and CSV summaries.",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=5,
        help="Focal k value for the threshold/smoothing line plot. Default: 5.",
    )
    parser.add_argument(
        "--ksens-mode",
        type=str,
        default="gaussian_sigma_2",
        help="Score mode for the k-sensitivity plot. Default: gaussian_sigma_2.",
    )
    parser.add_argument(
        "--ksens-percentile",
        type=float,
        default=99.5,
        help="Threshold percentile for the k-sensitivity plot. Default: 99.5.",
    )
    parser.add_argument(
        "--linear",
        action="store_true",
        help="Use linear colour scale instead of log-normalised heatmaps.",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display plots interactively as they are generated.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also generate individual heatmaps for every metric and score mode.",
    )
    args = parser.parse_args()

    args.outdir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("Deep Gate v4 false-alarm hyperparameter plotting")
    print("=" * 80)
    print(f"Input CSV : {args.csv}")
    print(f"Output dir: {args.outdir}")
    print(f"Focal k   : {args.k}")
    print(
        f"k-sens    : score_mode={args.ksens_mode}, "
        f"threshold_percentile={args.ksens_percentile}"
    )
    print(f"Heatmaps  : {'linear' if args.linear else 'log-normalised'}")
    print()

    df = read_false_alarm_report(args.csv)
    print(f"Loaded {len(df)} rows.")
    print(f"k values             : {sorted(df['k'].unique())}")
    print(f"threshold percentiles: {sorted(df['threshold_percentile'].unique())}")
    print(f"score modes          : {df.attrs['mode_order']}")
    print()

    write_summary_tables(df, args.outdir)
    print("CSV summaries written.")
    print()

    use_lognorm = not args.linear

    print("Generating plots...")

    plot_metric_heatmap_grid(
        df=df,
        metric="false_alarm_rate_percent_before_persistence",
        outpath=args.outdir / "FIG_v4_heatmap_grid_false_alarm_rate_before_persistence.png",
        title="Deep Gate v4: false-alarm rate before persistence across hyperparameters",
        annotate=True,
        use_lognorm=use_lognorm,
        show=args.show,
    )

    plot_metric_heatmap_grid(
        df=df,
        metric="false_alarm_events_after_persistence",
        outpath=args.outdir / "FIG_v4_heatmap_grid_persistent_false_alarm_events.png",
        title="Deep Gate v4: persistent false-alarm events across hyperparameters",
        annotate=True,
        use_lognorm=use_lognorm,
        show=args.show,
    )

    plot_k_fixed_two_panel_summary(
        df=df,
        outpath=args.outdir / f"FIG_v4_k{args.k}_line_summary_false_alarm_rate_and_events.png",
        k_value=args.k,
        show=args.show,
    )

    ksens_suffix = (
        f"{args.ksens_mode}_p{fmt_percentile(args.ksens_percentile).replace('.', '_')}"
    )

    plot_k_sensitivity(
        df=df,
        outpath=args.outdir / f"FIG_v4_k_sensitivity_{ksens_suffix}.png",
        selected_mode=args.ksens_mode,
        selected_percentile=args.ksens_percentile,
        show=args.show,
    )

    if args.all:
        plot_individual_heatmaps(
            df,
            args.outdir,
            show=args.show,
            use_lognorm=use_lognorm,
        )
        print("  Individual heatmaps written.")

    print()
    print("All done. Output files:")
    for f in sorted(args.outdir.glob("FIG_*.png")):
        print(f"  {f}")
    print()
    for f in sorted(args.outdir.glob("v4_*.csv")):
        print(f"  {f}")


if __name__ == "__main__":
    main()
