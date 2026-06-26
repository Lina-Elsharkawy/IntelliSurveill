from pathlib import Path
import csv
import re


# =========================
# Paths
# =========================

DATASET_ROOT = Path(r"D:\Embeddings_Distribution\anomaly_dataset\Dataset")

OUTPUT_CSV = Path(r"D:\Embeddings_Distribution\anomaly_dataset\dataset_labels.csv")


# =========================
# Class folders and labels
# =========================
# Normal  = 0
# Anomaly = 1

CLASSES = {
    "Normal": 0,
    "Anomaly": 1,
}


# =========================
# Supported video formats
# =========================

VIDEO_EXTENSIONS = {
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wmv",
    ".m4v",
}


# =========================
# Natural sorting helper
# =========================
# This makes video2 come before video10.

def natural_key(path: Path):
    return [
        int(text) if text.isdigit() else text.lower()
        for text in re.split(r"(\d+)", path.stem)
    ]


# =========================
# Build CSV rows
# =========================

rows = []

for folder_name, label in CLASSES.items():
    folder_path = DATASET_ROOT / folder_name

    if not folder_path.exists():
        print(f"WARNING: Folder not found: {folder_path}")
        continue

    video_files = sorted(
        (
            p for p in folder_path.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=natural_key
    )

    print(f"Found {len(video_files)} videos in {folder_path}")

    for video_path in video_files:
        # Unique ID to avoid duplicate video1 in Normal and Anomaly
        video_id = f"{folder_name.lower()}_{video_path.stem}"

        rows.append({
            "video_id": video_id,
            "video_path": str(video_path),
            "label": label,
        })


# =========================
# Write CSV
# =========================

OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["video_id", "video_path", "label"]
    )
    writer.writeheader()
    writer.writerows(rows)


# =========================
# Summary
# =========================

normal_count = sum(1 for r in rows if r["label"] == 0)
anomaly_count = sum(1 for r in rows if r["label"] == 1)

print()
print("Done. CSV created at:")
print(OUTPUT_CSV)
print()
print(f"Total videos:   {len(rows)}")
print(f"Normal videos:  {normal_count}")
print(f"Anomaly videos: {anomaly_count}")