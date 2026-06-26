#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import pandas as pd

INPUT_CSV = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_eval_no_persistence\pose_eval_tubelet_scores.csv"
)

OUTPUT_DIR = Path(
    r"D:\Embeddings_Distribution\anomaly_dataset\outputs\pose_eval_no_persistence\component5_inspection"
)

THRESHOLD_C5 = 70.18459395136654


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

    # Keep only component 5 smoothed config. This still contains raw_score and smoothed_score.
    c5 = df[
        (df["components"] == 5)
        & (df["postprocess"] == "smooth")
    ].copy()

    anomaly = c5[c5["label"] == 1].copy()
    normal = c5[c5["label"] == 0].copy()

    anomaly["raw_cross"] = anomaly["raw_score"] > THRESHOLD_C5
    anomaly["smooth_cross"] = anomaly["smoothed_score"] > THRESHOLD_C5
    normal["raw_cross"] = normal["raw_score"] > THRESHOLD_C5
    normal["smooth_cross"] = normal["smoothed_score"] > THRESHOLD_C5

    keep_cols = [
        "video_id",
        "video_path",
        "track_id",
        "tubelet_id",
        "start_time_sec",
        "end_time_sec",
        "threshold",
        "raw_score",
        "smoothed_score",
        "raw_cross",
        "smooth_cross",
        "pose_valid_frame_ratio",
        "pose_mean_keypoint_conf",
        "pose_valid_keypoint_ratio_mean",
        "mean_conf",
        "min_conf",
        "mean_iou",
        "max_center_jump_ratio",
        "mean_bbox_area_ratio",
    ]
    keep_cols = [c for c in keep_cols if c in anomaly.columns]

    # 1) Full component-5 anomaly tubelet table.
    anomaly_sorted = anomaly.sort_values(
        ["video_id", "track_id", "start_time_sec", "tubelet_id"]
    )
    anomaly_sorted[keep_cols].to_csv(
        OUTPUT_DIR / "component5_anomaly_tubelets_all.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 2) Top component-5 anomaly tubelets by smoothed score.
    anomaly.sort_values("smoothed_score", ascending=False)[keep_cols].head(300).to_csv(
        OUTPUT_DIR / "component5_top_anomaly_tubelets_by_smoothed_score.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 3) Top component-5 anomaly tubelets by raw score.
    anomaly.sort_values("raw_score", ascending=False)[keep_cols].head(300).to_csv(
        OUTPUT_DIR / "component5_top_anomaly_tubelets_by_raw_score.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 4) Per-video summary.
    rows = []
    for video_id, g in anomaly.groupby("video_id", dropna=False):
        rows.append({
            "video_id": video_id,
            "video_path": str(g["video_path"].iloc[0]) if "video_path" in g.columns else "",
            "tubelet_count": int(len(g)),
            "track_count": int(g["track_id"].nunique()),
            "negative_raw_count": int((g["raw_score"] < 0).sum()),
            "negative_raw_pct": float((g["raw_score"] < 0).mean()),
            "negative_smoothed_count": int((g["smoothed_score"] < 0).sum()),
            "negative_smoothed_pct": float((g["smoothed_score"] < 0).mean()),
            "raw_min": float(g["raw_score"].min()),
            "raw_median": float(g["raw_score"].median()),
            "raw_p95": float(g["raw_score"].quantile(0.95)),
            "raw_max": float(g["raw_score"].max()),
            "smoothed_min": float(g["smoothed_score"].min()),
            "smoothed_median": float(g["smoothed_score"].median()),
            "smoothed_p95": float(g["smoothed_score"].quantile(0.95)),
            "smoothed_max": float(g["smoothed_score"].max()),
            "raw_threshold_crossings": int((g["raw_score"] > THRESHOLD_C5).sum()),
            "smoothed_threshold_crossings": int((g["smoothed_score"] > THRESHOLD_C5).sum()),
            "first_raw_cross_time_sec": (
                float(g.loc[g["raw_score"] > THRESHOLD_C5, "start_time_sec"].min())
                if (g["raw_score"] > THRESHOLD_C5).any() and "start_time_sec" in g.columns
                else None
            ),
            "first_smoothed_cross_time_sec": (
                float(g.loc[g["smoothed_score"] > THRESHOLD_C5, "start_time_sec"].min())
                if (g["smoothed_score"] > THRESHOLD_C5).any() and "start_time_sec" in g.columns
                else None
            ),
        })

    per_video = pd.DataFrame(rows).sort_values("smoothed_max", ascending=False)
    per_video.to_csv(
        OUTPUT_DIR / "component5_anomaly_per_video_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 5) Compare anomaly vs normal score distributions.
    dist_rows = []
    for name, sub in [("normal", normal), ("anomaly", anomaly)]:
        for score_col in ["raw_score", "smoothed_score"]:
            dist_rows.append({
                "class": name,
                "score_col": score_col,
                "count": int(len(sub)),
                "negative_count": int((sub[score_col] < 0).sum()),
                "negative_pct": float((sub[score_col] < 0).mean()),
                "min": float(sub[score_col].min()),
                "p01": float(sub[score_col].quantile(0.01)),
                "p05": float(sub[score_col].quantile(0.05)),
                "p25": float(sub[score_col].quantile(0.25)),
                "median": float(sub[score_col].median()),
                "p75": float(sub[score_col].quantile(0.75)),
                "p90": float(sub[score_col].quantile(0.90)),
                "p95": float(sub[score_col].quantile(0.95)),
                "p99": float(sub[score_col].quantile(0.99)),
                "p995": float(sub[score_col].quantile(0.995)),
                "max": float(sub[score_col].max()),
                "threshold": THRESHOLD_C5,
                "threshold_crossings": int((sub[score_col] > THRESHOLD_C5).sum()),
            })

    pd.DataFrame(dist_rows).to_csv(
        OUTPUT_DIR / "component5_score_distribution_normal_vs_anomaly.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print("Done. Files written to:")
    print(OUTPUT_DIR)


if __name__ == "__main__":
    main()