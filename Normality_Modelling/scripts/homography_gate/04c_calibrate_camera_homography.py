#!/usr/bin/env python3
r"""
04c_calibrate_camera_homography.py

Interactive homography calibration helper for the macro-speed branch.

Purpose
-------
Create a homography matrix that maps image pixel coordinates to real-world
floor coordinates:

    image pixel point: [x_pixel, y_pixel]
        ↓ H
    world floor point: [X_meter, Y_meter]

Outputs
-------
camera_001_homography.npy
camera_001_homography_config.json
camera_001_reference_frame.jpg
camera_001_homography_validation.jpg
camera_001_points.csv

Typical workflow
----------------
1) Extract a reference frame from a video:

python .\04c_calibrate_camera_homography.py --video_path "D:\Embeddings_Distribution\raw_videos\20260315_093203_tp00034.mp4" --output_dir "D:\Embeddings_Distribution\calibration" --camera_id camera_001 --extract_frame_time_sec 30 --mode extract_frame

2) Click floor points and type their real-world coordinates in meters:

python .\04c_calibrate_camera_homography.py --reference_frame "D:\Embeddings_Distribution\calibration\camera_001_reference_frame.jpg" --output_dir "D:\Embeddings_Distribution\calibration" --camera_id camera_001 --mode calibrate

3) Use the saved matrix with 04d:

python .\04d_extract_homography_macro_features.py --tracks_jsonl "D:\Embeddings_Distribution\normality_models\motion_tubelets_v1\motion_tubelet_tracks.jsonl" --output_dir "D:\Embeddings_Distribution\normality_models\homography_macro_50vid_v1" --homography_npy "D:\Embeddings_Distribution\calibration\camera_001_homography.npy" --world_scale_m_per_unit 1.0 --overwrite

How to choose calibration points
--------------------------------
Use points that are on the same flat floor plane, for example:
- floor tile corners,
- lab floor/wall boundary points that touch the ground,
- corners of floor mats,
- marked floor positions,
- known rectangular area corners.

Do NOT use points on walls, tables, chairs, or human bodies.
Use at least 4 points. 6-8 points is better.

Real-world coordinate system
----------------------------
You can choose any origin, but keep it consistent.
Example for a rectangle on the floor:
top-left     = (0.0, 0.0)
top-right    = (4.0, 0.0)
bottom-right = (4.0, 3.0)
bottom-left  = (0.0, 3.0)

The units should preferably be meters.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

WINDOW_NAME = "Homography Calibration - click floor points"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Create a camera homography matrix from clicked image points and real-world floor coordinates."
    )
    p.add_argument("--mode", choices=["extract_frame", "calibrate", "both", "from_points_csv"], required=True)
    p.add_argument("--video_path", type=str, default=None, help="Input video for extracting reference frame")
    p.add_argument("--reference_frame", type=str, default=None, help="Reference frame image path")
    p.add_argument("--output_dir", type=str, required=True, help="Output calibration folder")
    p.add_argument("--camera_id", type=str, default="camera_001")
    p.add_argument("--extract_frame_time_sec", type=float, default=30.0)
    p.add_argument("--extract_frame_index", type=int, default=None)
    p.add_argument("--points_csv", type=str, default=None,
                   help="CSV with columns image_x,image_y,world_x,world_y for non-interactive calibration")
    p.add_argument("--ransac", action="store_true",
                   help="Use cv2.RANSAC. Best with 6+ points if you may have clicking mistakes.")
    p.add_argument("--ransac_reproj_threshold", type=float, default=3.0)
    p.add_argument("--display_width", type=int, default=1280,
                   help="Display width for clicking. Saved image points remain original-resolution.")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def output_paths(output_dir: Path, camera_id: str) -> Dict[str, Path]:
    return {
        "homography_npy": output_dir / f"{camera_id}_homography.npy",
        "config_json": output_dir / f"{camera_id}_homography_config.json",
        "reference_frame": output_dir / f"{camera_id}_reference_frame.jpg",
        "validation_image": output_dir / f"{camera_id}_homography_validation.jpg",
        "points_csv": output_dir / f"{camera_id}_points.csv",
    }


def protect_outputs(paths: Dict[str, Path], overwrite: bool, keys: Optional[List[str]] = None) -> None:
    if overwrite:
        return
    check_keys = keys if keys is not None else list(paths.keys())
    existing = [paths[k] for k in check_keys if paths[k].exists()]
    if existing:
        raise FileExistsError(
            "Output file(s) already exist. Use --overwrite to replace them:\n"
            + "\n".join(str(p) for p in existing)
        )


def extract_reference_frame(video_path: Path, output_path: Path, time_sec: float,
                            frame_index: Optional[int], overwrite: bool) -> Dict[str, Any]:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Reference frame already exists. Use --overwrite: {output_path}")
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_index is None:
        if fps <= 0:
            raise RuntimeError("Video FPS is unavailable; use --extract_frame_index")
        frame_index = int(round(time_sec * fps))

    if frame_count > 0:
        frame_index = max(0, min(frame_index, frame_count - 1))
    else:
        frame_index = max(0, frame_index)

    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read frame_index={frame_index} from {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), frame):
        raise RuntimeError(f"Could not write reference frame: {output_path}")

    return {
        "video_path": str(video_path),
        "fps": fps,
        "frame_count": frame_count,
        "frame_index": int(frame_index),
        "time_sec": float(frame_index / fps) if fps > 0 else None,
        "reference_frame": str(output_path),
        "frame_width": int(frame.shape[1]),
        "frame_height": int(frame.shape[0]),
    }


class ClickCollector:
    def __init__(self, image_bgr: np.ndarray, display_width: int):
        self.image = image_bgr
        self.orig_h, self.orig_w = image_bgr.shape[:2]
        if display_width <= 0 or display_width >= self.orig_w:
            self.scale = 1.0
            self.display = image_bgr.copy()
        else:
            self.scale = display_width / float(self.orig_w)
            disp_h = int(round(self.orig_h * self.scale))
            self.display = cv2.resize(image_bgr, (display_width, disp_h), interpolation=cv2.INTER_AREA)
        self.clicks_display: List[Tuple[int, int]] = []
        self.clicks_original: List[Tuple[float, float]] = []

    def redraw(self) -> np.ndarray:
        canvas = self.display.copy()
        for idx, (x, y) in enumerate(self.clicks_display, start=1):
            cv2.circle(canvas, (x, y), 6, (0, 255, 255), -1)
            cv2.circle(canvas, (x, y), 8, (0, 0, 0), 2)
            cv2.putText(canvas, str(idx), (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX,
                        0.75, (0, 255, 255), 2, cv2.LINE_AA)
        instructions = [
            "Click floor-plane calibration points.",
            "Keys: u=undo | c=clear | q or Enter=finish | ESC=cancel",
            "After finishing, type real-world X,Y meters for each clicked point.",
        ]
        y0 = 28
        for line in instructions:
            cv2.putText(canvas, line, (15, y0), cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, (0, 255, 0), 2, cv2.LINE_AA)
            y0 += 28
        return canvas

    def mouse_cb(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.clicks_display.append((int(x), int(y)))
            self.clicks_original.append((float(x / self.scale), float(y / self.scale)))
            cv2.imshow(WINDOW_NAME, self.redraw())

    def collect(self) -> List[Tuple[float, float]]:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW_NAME, self.mouse_cb)
        cv2.imshow(WINDOW_NAME, self.redraw())
        print("\nClick floor points in the image window.")
        print("  u = undo last point")
        print("  c = clear all points")
        print("  q or Enter = finish")
        print("  ESC = cancel\n")
        while True:
            key = cv2.waitKey(50) & 0xFF
            if key == 27:
                cv2.destroyWindow(WINDOW_NAME)
                raise KeyboardInterrupt("Calibration cancelled by user.")
            if key in (ord("u"), ord("U")):
                if self.clicks_display:
                    self.clicks_display.pop()
                    self.clicks_original.pop()
                    cv2.imshow(WINDOW_NAME, self.redraw())
            elif key in (ord("c"), ord("C")):
                self.clicks_display.clear()
                self.clicks_original.clear()
                cv2.imshow(WINDOW_NAME, self.redraw())
            elif key in (ord("q"), ord("Q"), 13):
                break
        cv2.destroyWindow(WINDOW_NAME)
        return self.clicks_original


def ask_world_points(image_points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    world_points: List[Tuple[float, float]] = []
    print("\nNow enter the real-world floor coordinate for each clicked point.")
    print("Use meters if possible. Example: 0,0 then 4,0 then 4,3 then 0,3\n")
    for i, (ix, iy) in enumerate(image_points, start=1):
        while True:
            raw = input(f"Point {i} image=({ix:.1f}, {iy:.1f}) -> world X,Y meters: ").strip()
            raw = raw.replace(";", ",").replace(" ", ",")
            parts = [p for p in raw.split(",") if p.strip()]
            if len(parts) != 2:
                print("  Please enter exactly two numbers, e.g. 2.5, 1.0")
                continue
            try:
                x = float(parts[0])
                y = float(parts[1])
            except ValueError:
                print("  Invalid number. Try again.")
                continue
            world_points.append((x, y))
            break
    return world_points


def load_points_csv(path: Path) -> Tuple[np.ndarray, np.ndarray]:
    image_pts = []
    world_pts = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"image_x", "image_y", "world_x", "world_y"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"points_csv missing columns: {sorted(missing)}")
        for row in reader:
            image_pts.append([float(row["image_x"]), float(row["image_y"])])
            world_pts.append([float(row["world_x"]), float(row["world_y"])])
    return np.asarray(image_pts, dtype=np.float64), np.asarray(world_pts, dtype=np.float64)


def save_points_csv(path: Path, image_pts: np.ndarray, world_pts: np.ndarray) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["point_id", "image_x", "image_y", "world_x", "world_y"])
        writer.writeheader()
        for i, (ip, wp) in enumerate(zip(image_pts, world_pts), start=1):
            writer.writerow({
                "point_id": i,
                "image_x": float(ip[0]),
                "image_y": float(ip[1]),
                "world_x": float(wp[0]),
                "world_y": float(wp[1]),
            })


def compute_homography(image_pts: np.ndarray, world_pts: np.ndarray,
                       use_ransac: bool, ransac_reproj_threshold: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
    image_pts = np.asarray(image_pts, dtype=np.float64)
    world_pts = np.asarray(world_pts, dtype=np.float64)
    if image_pts.shape != world_pts.shape:
        raise ValueError(f"image/world point shapes differ: {image_pts.shape} vs {world_pts.shape}")
    if image_pts.ndim != 2 or image_pts.shape[1] != 2:
        raise ValueError(f"points must be [N,2], got {image_pts.shape}")
    if image_pts.shape[0] < 4:
        raise ValueError("At least 4 point pairs are required for homography calibration")

    method = cv2.RANSAC if use_ransac else 0
    H, mask = cv2.findHomography(image_pts, world_pts, method=method,
                                  ransacReprojThreshold=float(ransac_reproj_threshold))
    if H is None:
        raise RuntimeError("cv2.findHomography failed. Check your point order and coordinates.")
    H = np.asarray(H, dtype=np.float64)

    ones = np.ones((image_pts.shape[0], 1), dtype=np.float64)
    ph = np.concatenate([image_pts, ones], axis=1)
    wh = ph @ H.T
    denom = wh[:, 2]
    projected = np.full_like(world_pts, np.nan, dtype=np.float64)
    valid = np.isfinite(denom) & (np.abs(denom) > 1e-12)
    projected[valid, 0] = wh[valid, 0] / denom[valid]
    projected[valid, 1] = wh[valid, 1] / denom[valid]

    residuals = np.linalg.norm(projected - world_pts, axis=1)
    inlier_mask = mask.reshape(-1).astype(bool) if mask is not None else np.ones(image_pts.shape[0], dtype=bool)
    diagnostics = {
        "num_points": int(image_pts.shape[0]),
        "method": "RANSAC" if use_ransac else "direct",
        "inliers": int(np.sum(inlier_mask)),
        "mean_world_error_m": float(np.nanmean(residuals)),
        "median_world_error_m": float(np.nanmedian(residuals)),
        "max_world_error_m": float(np.nanmax(residuals)),
        "determinant": float(np.linalg.det(H)),
    }
    return H, projected, residuals, diagnostics


def draw_validation(reference_frame_path: Path, image_pts: np.ndarray, world_pts: np.ndarray,
                    projected_world_pts: np.ndarray, residuals: np.ndarray, output_path: Path) -> None:
    img = cv2.imread(str(reference_frame_path))
    if img is None:
        raise RuntimeError(f"Could not read reference frame: {reference_frame_path}")
    for i, (ip, wp, pp, err) in enumerate(zip(image_pts, world_pts, projected_world_pts, residuals), start=1):
        x, y = int(round(ip[0])), int(round(ip[1]))
        cv2.circle(img, (x, y), 8, (0, 255, 255), -1)
        cv2.circle(img, (x, y), 10, (0, 0, 0), 2)
        label = f"{i}: W=({wp[0]:.2f},{wp[1]:.2f}) err={err:.3f}m"
        cv2.putText(img, label, (x + 12, y - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 255, 255), 2, cv2.LINE_AA)
    if image_pts.shape[0] >= 4:
        poly = np.round(image_pts).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(img, [poly], isClosed=True, color=(255, 0, 255), thickness=2)
    if not cv2.imwrite(str(output_path), img):
        raise RuntimeError(f"Could not write validation image: {output_path}")


def calibrate_from_reference(reference_frame: Path, paths: Dict[str, Path], camera_id: str,
                             display_width: int, use_ransac: bool, ransac_reproj_threshold: float,
                             overwrite: bool, points_csv: Optional[Path] = None) -> Dict[str, Any]:
    protect_outputs(paths, overwrite, keys=["homography_npy", "config_json", "validation_image", "points_csv"])
    if not reference_frame.exists():
        raise FileNotFoundError(reference_frame)

    if points_csv is not None:
        image_pts, world_pts = load_points_csv(points_csv)
    else:
        frame = cv2.imread(str(reference_frame))
        if frame is None:
            raise RuntimeError(f"Could not read reference frame: {reference_frame}")
        collector = ClickCollector(frame, display_width=display_width)
        image_points_list = collector.collect()
        if len(image_points_list) < 4:
            raise ValueError(f"Need at least 4 clicked points, got {len(image_points_list)}")
        world_points_list = ask_world_points(image_points_list)
        image_pts = np.asarray(image_points_list, dtype=np.float64)
        world_pts = np.asarray(world_points_list, dtype=np.float64)

    H, projected, residuals, diag = compute_homography(image_pts, world_pts, use_ransac, ransac_reproj_threshold)
    np.save(paths["homography_npy"], H)
    save_points_csv(paths["points_csv"], image_pts, world_pts)
    draw_validation(reference_frame, image_pts, world_pts, projected, residuals, paths["validation_image"])

    config = {
        "schema_version": "camera_homography_calibration_v1.0",
        "created_at_unix": time.time(),
        "camera_id": camera_id,
        "description": "Homography maps image pixel coordinates to world/floor coordinates. Coordinates should be meters if entered as meters.",
        "homography_npy": str(paths["homography_npy"]),
        "reference_frame": str(reference_frame),
        "validation_image": str(paths["validation_image"]),
        "points_csv": str(paths["points_csv"]),
        "world_scale_m_per_unit": 1.0,
        "H": H.tolist(),
        "diagnostics": diag,
        "points": [
            {
                "point_id": int(i),
                "image_x": float(ip[0]),
                "image_y": float(ip[1]),
                "world_x": float(wp[0]),
                "world_y": float(wp[1]),
                "projected_world_x": float(pp[0]),
                "projected_world_y": float(pp[1]),
                "world_error_m": float(err),
            }
            for i, (ip, wp, pp, err) in enumerate(zip(image_pts, world_pts, projected, residuals), start=1)
        ],
        "usage": {
            "single_homography_command": (
                f'python .\\04d_extract_homography_macro_features.py '
                f'--tracks_jsonl "D:\\Embeddings_Distribution\\normality_models\\motion_tubelets_v1\\motion_tubelet_tracks.jsonl" '
                f'--output_dir "D:\\Embeddings_Distribution\\normality_models\\homography_macro_50vid_v1" '
                f'--homography_npy "{paths["homography_npy"]}" --world_scale_m_per_unit 1.0 --overwrite'
            )
        },
    }
    write_json(paths["config_json"], config)
    return config


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)
    paths = output_paths(output_dir, args.camera_id)

    if args.mode in ("extract_frame", "both"):
        if not args.video_path:
            raise SystemExit("--video_path is required for --mode extract_frame or --mode both")
        info = extract_reference_frame(Path(args.video_path), paths["reference_frame"],
                                       float(args.extract_frame_time_sec), args.extract_frame_index,
                                       bool(args.overwrite))
        print("\nReference frame saved:")
        print(f"  {paths['reference_frame']}")
        print(f"  frame_index={info['frame_index']} time_sec={info['time_sec']} size={info['frame_width']}x{info['frame_height']}")
        if args.mode == "extract_frame":
            return 0

    if args.mode in ("calibrate", "both"):
        reference_frame = Path(args.reference_frame) if args.reference_frame else paths["reference_frame"]
        config = calibrate_from_reference(reference_frame, paths, args.camera_id,
                                          int(args.display_width), bool(args.ransac),
                                          float(args.ransac_reproj_threshold), bool(args.overwrite), None)
        print("\nHomography calibration saved:")
        print(f"  H npy:       {paths['homography_npy']}")
        print(f"  config json: {paths['config_json']}")
        print(f"  points csv:  {paths['points_csv']}")
        print(f"  validation:  {paths['validation_image']}")
        print("\nDiagnostics:")
        for k, v in config["diagnostics"].items():
            print(f"  {k}: {v}")
        return 0

    if args.mode == "from_points_csv":
        if not args.reference_frame:
            raise SystemExit("--reference_frame is required for --mode from_points_csv")
        if not args.points_csv:
            raise SystemExit("--points_csv is required for --mode from_points_csv")
        config = calibrate_from_reference(Path(args.reference_frame), paths, args.camera_id,
                                          int(args.display_width), bool(args.ransac),
                                          float(args.ransac_reproj_threshold), bool(args.overwrite),
                                          Path(args.points_csv))
        print("\nHomography calibration saved from CSV:")
        print(f"  H npy:       {paths['homography_npy']}")
        print(f"  config json: {paths['config_json']}")
        print(f"  validation:  {paths['validation_image']}")
        print("\nDiagnostics:")
        for k, v in config["diagnostics"].items():
            print(f"  {k}: {v}")
        return 0

    raise SystemExit(f"Unsupported mode: {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
