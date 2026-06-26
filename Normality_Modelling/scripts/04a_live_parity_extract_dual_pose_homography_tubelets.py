#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
04a_live_parity_extract_dual_pose_homography_tubelets.py

One-pass live-parity motion tubelet extraction for BOTH:
  1) Pose micro-motion gate:       5 FPS, 24 frames, stride 6, no sample gaps
  2) Homography macro-motion gate: 2.5 FPS, 16 frames, stride 8, sample gaps allowed

Why this exists
---------------
The normal 04a_live_parity extractor is correct, but it extracts only one
tubelet configuration per run. Running Pose and Homography separately repeats
YOLO.track() twice. This script runs YOLO.track() ONCE on every decoded frame
and feeds two separate gate-specific tubelet buffers.

Important:
- Tracking is shared.
- Sampling/tubelet emission is gate-specific.
- Output folders are separate.
- JSONL schema is the same as the original live-parity extractor.

Expected files:
Place this script in the same folder as:
  04a_live_parity_extract_motion_tubelet_tracks_from_raw_videos.py

It imports helper functions/classes from that existing script.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import math
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from tqdm import tqdm

try:
    import torch
except ImportError:
    torch = None

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise SystemExit(
        "ERROR: ultralytics is not installed. Install it with:\n"
        "  pip install ultralytics\n"
    ) from exc


VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".m4v", ".wmv", ".mpg", ".mpeg", ".webm"
}


def load_base_module():
    base_path = Path(__file__).with_name("04a_live_parity_extract_motion_tubelet_tracks_from_raw_videos.py")
    if not base_path.exists():
        raise SystemExit(
            f"ERROR: Could not find base extractor next to this script:\n  {base_path}\n\n"
            "Place this dual script in the same folder as "
            "04a_live_parity_extract_motion_tubelet_tracks_from_raw_videos.py"
        )

    spec = importlib.util.spec_from_file_location("live_parity_base_extractor", str(base_path))
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: Could not import base extractor: {base_path}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


base = load_base_module()


@dataclass
class GateSpec:
    name: str
    output_dir: Path
    sample_fps: float
    tubelet_frames: int
    stride: int
    max_track_gap: int
    allow_sample_gaps: bool
    min_conf: float
    min_bbox_width: float = 0.0
    min_bbox_height: float = 0.0
    min_mean_iou: float = 0.0
    max_center_jump_ratio: float = float("inf")
    max_tubelets_per_video: Optional[int] = None


@dataclass
class GateRuntime:
    spec: GateSpec
    jsonl_file: Any
    rejected_writer: csv.DictWriter
    failed_writer: csv.DictWriter
    global_state: Dict[str, int]
    video_stats: List[Dict[str, Any]]


def setup_logging(output_root: Path) -> None:
    logs_dir = output_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "dual_motion_tubelet_tracks.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def safe_prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        important_outputs = [
            output_dir / "motion_tubelet_tracks.jsonl",
            output_dir / "motion_tubelet_tracks_summary.json",
            output_dir / "motion_tubelet_tracks_failed.csv",
            output_dir / "motion_tubelet_tracks_rejected.csv",
        ]
        has_existing_outputs = any(path.exists() for path in important_outputs)

        if has_existing_outputs and not overwrite:
            raise SystemExit(
                f"ERROR: output_dir already contains extraction outputs:\n"
                f"  {output_dir}\n\n"
                f"Use a new --output_dir or pass --overwrite if replacing them."
            )

        if overwrite:
            for path in important_outputs:
                if path.exists():
                    path.unlink()
            previews_dir = output_dir / "debug_previews"
            if previews_dir.exists():
                shutil.rmtree(previews_dir)

    output_dir.mkdir(parents=True, exist_ok=True)


def find_videos(input_dir: Path, recursive: bool) -> List[Path]:
    if not input_dir.exists():
        raise SystemExit(f"ERROR: input_dir does not exist: {input_dir}")

    pattern_iter = input_dir.rglob("*") if recursive else input_dir.glob("*")
    videos = [
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    videos.sort(key=lambda p: str(p).lower())
    return videos


def gate_args_view(shared_args: argparse.Namespace, gate: GateSpec) -> argparse.Namespace:
    """
    Build a small argparse-like object so we can reuse the original reject_reasons().
    """
    return argparse.Namespace(
        tubelet_frames=gate.tubelet_frames,
        stride=gate.stride,
        min_conf=gate.min_conf,
        min_bbox_width=gate.min_bbox_width,
        min_bbox_height=gate.min_bbox_height,
        min_mean_iou=gate.min_mean_iou,
        max_center_jump_ratio=gate.max_center_jump_ratio,
        max_track_gap=gate.max_track_gap,
        allow_sample_gaps=gate.allow_sample_gaps,
        max_tubelets_per_video=gate.max_tubelets_per_video,
        output_dir=gate.output_dir,
        save_debug_previews=shared_args.save_debug_previews,
        debug_preview_limit=shared_args.debug_preview_limit,
    )


def make_initial_video_stats(video_path: Path, video_id: str) -> Dict[str, Any]:
    return {
        "video_path": str(video_path),
        "video_id": video_id,
        "status": "ok",
        "source_fps": None,
        "frame_count": None,
        "duration_sec": None,
        "frame_step": None,
        "effective_sample_fps": None,
        "target_window_duration_sec": None,
        "sampled_frames": 0,
        "tracked_frames": 0,
        "accepted_tubelets": 0,
        "rejected_tubelets": 0,
        "unique_track_ids": 0,
        "elapsed_sec": None,
        "error": None,
    }


def process_video_dual(
    video_path: Path,
    input_dir: Path,
    model: YOLO,
    runtimes: List[GateRuntime],
    shared_args: argparse.Namespace,
) -> None:
    started = time.time()
    video_id = base.make_video_id(video_path, input_dir, shared_args.video_id_from)

    # Keep tracker state persistent inside each video, but never across separate files.
    base.reset_yolo_tracker_state(model)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        for rt in runtimes:
            stats = make_initial_video_stats(video_path, video_id)
            stats["status"] = "failed"
            stats["error"] = "could_not_open_video"
            rt.failed_writer.writerow(stats)
            rt.video_stats.append(stats)
        return

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    if source_fps <= 0:
        # Use 5 as global fallback since backend canonical sampler is 5 FPS.
        source_fps = 5.0
        logging.warning("FPS unavailable for %s; falling back to 5.0", video_path)

    duration_sec = frame_count / source_fps if source_fps > 0 else None

    gate_states: Dict[str, Dict[str, Any]] = {}
    for rt in runtimes:
        gate = rt.spec
        frame_step = max(1, int(round(source_fps / gate.sample_fps)))
        effective_sample_fps = source_fps / frame_step
        target_window_duration_sec = float(gate.tubelet_frames / gate.sample_fps) if gate.sample_fps > 0 else None

        if abs(effective_sample_fps - gate.sample_fps) > 0.05:
            logging.warning(
                "[%s] Requested sample_fps=%.3f but effective_sample_fps=%.3f for %s because source_fps=%.3f and frame_step=%d",
                gate.name, gate.sample_fps, effective_sample_fps, video_path.name, source_fps, frame_step
            )

        buffer_len = gate.tubelet_frames + gate.stride + gate.max_track_gap + 4
        gate_states[gate.name] = {
            "stats": make_initial_video_stats(video_path, video_id),
            "frame_step": frame_step,
            "effective_sample_fps": effective_sample_fps,
            "sample_index": -1,
            "buffers": {},
            "seen_track_ids": set(),
            "debug_saved_for_video": 0,
            "buffer_len": buffer_len,
            "target_window_duration_sec": target_window_duration_sec,
        }

        st = gate_states[gate.name]["stats"]
        st.update({
            "source_fps": source_fps,
            "frame_count": frame_count,
            "duration_sec": duration_sec,
            "frame_step": frame_step,
            "effective_sample_fps": effective_sample_fps,
            "target_window_duration_sec": target_window_duration_sec,
        })

    frame_index = 0

    try:
        pbar_total = frame_count if frame_count > 0 else None
        pbar_context = tqdm(total=pbar_total, desc=f"Tracking dual {video_path.name}", unit="frame", disable=shared_args.no_progress)
        with pbar_context as pbar:
            while frame_count <= 0 or frame_index < frame_count:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break

                if pbar_total:
                    pbar.update(1)

                current_frame_index = frame_index
                frame_h, frame_w = frame.shape[:2]

                # ONE tracking call per decoded frame, shared by both gates.
                results = model.track(
                    frame,
                    persist=True,
                    tracker=shared_args.tracker,
                    conf=shared_args.det_conf,
                    iou=shared_args.iou,
                    imgsz=shared_args.imgsz,
                    classes=[0],
                    device=shared_args.device,
                    half=bool(shared_args.half),
                    compile=bool(shared_args.compile_model),
                    verbose=False,
                )

                detections = base.extract_detections_from_result(results[0]) if results else []

                for rt in runtimes:
                    gate = rt.spec
                    state = gate_states[gate.name]
                    state["stats"]["tracked_frames"] += 1

                    for track_id, _conf, _bbox in detections:
                        state["seen_track_ids"].add(track_id)

                    if (current_frame_index % state["frame_step"]) != 0:
                        continue

                    state["sample_index"] += 1
                    sample_index = state["sample_index"]
                    state["stats"]["sampled_frames"] += 1
                    time_sec = current_frame_index / source_fps if source_fps > 0 else sample_index / gate.sample_fps

                    if not detections:
                        continue

                    buffers = state["buffers"]

                    for track_id, conf, bbox in detections:
                        if track_id not in buffers:
                            buffers[track_id] = base.TrackBuffer(
                                track_id=track_id,
                                maxlen=state["buffer_len"],
                                max_track_gap=gate.max_track_gap,
                            )

                        item = base.TrackItem(
                            sample_index=sample_index,
                            frame_index=current_frame_index,
                            time_sec=time_sec,
                            bbox_xywh=bbox,
                            conf=conf,
                            frame_width=frame_w,
                            frame_height=frame_h,
                        )
                        buffers[track_id].append(item)

                        for window in buffers[track_id].candidate_windows(gate.tubelet_frames, gate.stride):
                            quality = base.compute_quality(window)
                            gate_args = gate_args_view(shared_args, gate)
                            reasons = base.reject_reasons(window, quality, gate_args)

                            if reasons:
                                state["stats"]["rejected_tubelets"] += 1
                                rt.rejected_writer.writerow({
                                    "video_path": str(video_path),
                                    "video_id": video_id,
                                    "track_id": track_id,
                                    "start_frame": window[0].frame_index if window else "",
                                    "end_frame": window[-1].frame_index if window else "",
                                    "start_time_sec": window[0].time_sec if window else "",
                                    "end_time_sec": window[-1].time_sec if window else "",
                                    "reasons": "|".join(sorted(set(reasons))),
                                    **quality,
                                })
                                continue

                            if (
                                gate.max_tubelets_per_video is not None
                                and state["stats"]["accepted_tubelets"] >= gate.max_tubelets_per_video
                            ):
                                continue

                            local_index = state["stats"]["accepted_tubelets"]
                            global_index = rt.global_state["next_tubelet_index"]
                            rt.global_state["next_tubelet_index"] += 1

                            tubelet_id = (
                                f"{gate.name}__{video_id}__track{track_id}"
                                f"__t{window[0].frame_index}_{window[-1].frame_index}"
                                f"__{global_index:08d}"
                            )

                            source_frame_indices = [int(item.frame_index) for item in window]
                            sample_indices = [int(item.sample_index) for item in window]
                            source_times_sec = [float(item.time_sec) for item in window]
                            frame_gaps = [
                                int(source_frame_indices[i] - source_frame_indices[i - 1])
                                for i in range(1, len(source_frame_indices))
                            ]
                            sample_gaps = [
                                int(sample_indices[i] - sample_indices[i - 1])
                                for i in range(1, len(sample_indices))
                            ]

                            bboxes_xywh = [[float(v) for v in item.bbox_xywh] for item in window]
                            bboxes_xyxy = [base.xywh_to_list_xyxy(item.bbox_xywh) for item in window]
                            bboxes_xywh_clipped = [
                                [float(v) for v in base.clip_xywh_to_frame(item.bbox_xywh, item.frame_width, item.frame_height)]
                                for item in window
                            ]
                            bboxes_xyxy_clipped = [base.xywh_to_list_xyxy(b) for b in bboxes_xywh_clipped]

                            bbox_centers_xy = [[float(v) for v in base.center_xy(item.bbox_xywh)] for item in window]
                            bbox_bottom_centers_xy = [[float(v) for v in base.bottom_center_xy(item.bbox_xywh)] for item in window]
                            bbox_bottom_centers_xy_clipped = [[float(v) for v in base.bottom_center_xy(b)] for b in bboxes_xywh_clipped]
                            bbox_widths = [float(item.bbox_xywh[2]) for item in window]
                            bbox_heights = [float(item.bbox_xywh[3]) for item in window]
                            confs = [float(item.conf) for item in window]

                            record = {
                                "schema_version": "motion_tubelet_tracks_v1.2_live_parity_dual",
                                "gate_name": gate.name,
                                "tubelet_id": tubelet_id,
                                "video_path": str(video_path),
                                "video_id": video_id,
                                "track_id": int(track_id),

                                "source_fps": float(source_fps),
                                "sample_fps": float(gate.sample_fps),
                                "effective_sample_fps": float(state["effective_sample_fps"]),
                                "frame_step": int(state["frame_step"]),
                                "tubelet_frames": int(gate.tubelet_frames),
                                "stride": int(gate.stride),

                                "start_frame": int(window[0].frame_index),
                                "end_frame": int(window[-1].frame_index),
                                "start_time_sec": float(window[0].time_sec),
                                "end_time_sec": float(window[-1].time_sec),
                                "tubelet_duration_sec": float(window[-1].time_sec - window[0].time_sec),
                                "target_window_duration_sec": float(gate.tubelet_frames / gate.sample_fps) if gate.sample_fps > 0 else None,

                                "source_frame_indices": source_frame_indices,
                                "sample_indices": sample_indices,
                                "source_times_sec": source_times_sec,
                                "frame_gaps": frame_gaps,
                                "sample_gaps": sample_gaps,

                                "bboxes_xywh": bboxes_xywh,
                                "bboxes_xyxy": bboxes_xyxy,
                                "bboxes_xywh_clipped": bboxes_xywh_clipped,
                                "bboxes_xyxy_clipped": bboxes_xyxy_clipped,
                                "bbox_centers_xy": bbox_centers_xy,
                                "bbox_bottom_centers_xy": bbox_bottom_centers_xy,
                                "bbox_bottom_centers_xy_clipped": bbox_bottom_centers_xy_clipped,
                                "bbox_widths": bbox_widths,
                                "bbox_heights": bbox_heights,
                                "confs": confs,

                                "mean_conf": quality["mean_conf"],
                                "min_conf": quality["min_conf"],
                                "mean_iou": quality["mean_iou"],
                                "max_center_jump_ratio": quality["max_center_jump_ratio"],
                                "mean_bbox_area_ratio": quality["mean_bbox_area_ratio"],

                                "frame_width": int(window[0].frame_width),
                                "frame_height": int(window[0].frame_height),

                                "local_tubelet_index": int(local_index),
                                "global_tubelet_index": int(global_index),
                            }

                            base.write_jsonl_record(rt.jsonl_file, record)
                            state["stats"]["accepted_tubelets"] += 1

                            if shared_args.save_debug_previews and state["debug_saved_for_video"] < shared_args.debug_preview_limit:
                                base.save_debug_preview(video_path, gate.output_dir, tubelet_id, window)
                                state["debug_saved_for_video"] += 1

                frame_index += 1

    except Exception as exc:
        logging.exception("Failed while processing video: %s", video_path)
        for rt in runtimes:
            state = gate_states[rt.spec.name]
            state["stats"]["status"] = "failed"
            state["stats"]["error"] = repr(exc)
            rt.failed_writer.writerow(state["stats"])

    finally:
        cap.release()

    elapsed = time.time() - started
    for rt in runtimes:
        state = gate_states[rt.spec.name]
        state["stats"]["unique_track_ids"] = len(state["seen_track_ids"])
        state["stats"]["elapsed_sec"] = elapsed
        rt.video_stats.append(state["stats"])
        logging.info(
            "Video done | %s | gate=%s | status=%s | accepted=%s | rejected=%s | sampled=%s",
            video_path.name,
            rt.spec.name,
            state["stats"]["status"],
            state["stats"]["accepted_tubelets"],
            state["stats"]["rejected_tubelets"],
            state["stats"]["sampled_frames"],
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="One-pass live-parity extraction for Pose and Homography tubelets."
    )

    p.add_argument("--input_dir", required=True, type=Path)
    p.add_argument("--output_root", required=True, type=Path)
    p.add_argument("--yolo_model", required=True, type=Path)

    p.add_argument("--tracker", default="bytetrack.yaml")
    p.add_argument("--device", default=None)
    p.add_argument("--half", action="store_true")
    p.add_argument("--compile_model", action="store_true")
    p.add_argument("--no_progress", action="store_true")

    p.add_argument("--det_conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.7)
    p.add_argument("--imgsz", type=int, default=640)

    p.add_argument("--limit_videos", type=int, default=None)
    p.add_argument("--recursive", action="store_true")
    p.add_argument("--video_id_from", choices=["stem", "relative_path"], default="relative_path")
    p.add_argument("--overwrite", action="store_true")

    p.add_argument("--save_debug_previews", action="store_true")
    p.add_argument("--debug_preview_limit", type=int, default=20)

    # Pose defaults
    p.add_argument("--pose_sample_fps", type=float, default=5.0)
    p.add_argument("--pose_tubelet_frames", type=int, default=24)
    p.add_argument("--pose_stride", type=int, default=6)
    p.add_argument("--pose_max_track_gap", type=int, default=0)
    p.add_argument("--pose_min_conf", type=float, default=0.25)

    # Homography defaults based on standalone Stage-3 live tester
    p.add_argument("--hom_sample_fps", type=float, default=2.5)
    p.add_argument("--hom_tubelet_frames", type=int, default=16)
    p.add_argument("--hom_stride", type=int, default=8)
    p.add_argument("--hom_max_track_gap", type=int, default=8)
    p.add_argument("--hom_min_conf", type=float, default=0.25)
    p.add_argument("--hom_allow_sample_gaps", action="store_true", default=True)

    return p.parse_args()


def write_summary(rt: GateRuntime, shared_args: argparse.Namespace, started_all: float) -> None:
    gate = rt.spec
    summary_path = gate.output_dir / "motion_tubelet_tracks_summary.json"
    jsonl_path = gate.output_dir / "motion_tubelet_tracks.jsonl"
    failed_path = gate.output_dir / "motion_tubelet_tracks_failed.csv"
    rejected_path = gate.output_dir / "motion_tubelet_tracks_rejected.csv"

    total_accepted = int(sum(int(s.get("accepted_tubelets") or 0) for s in rt.video_stats))
    total_rejected = int(sum(int(s.get("rejected_tubelets") or 0) for s in rt.video_stats))
    total_sampled_frames = int(sum(int(s.get("sampled_frames") or 0) for s in rt.video_stats))
    total_tracked_frames = int(sum(int(s.get("tracked_frames") or 0) for s in rt.video_stats))
    failed_videos = [s for s in rt.video_stats if s.get("status") != "ok"]

    summary = {
        "script": Path(__file__).name,
        "schema_version": "motion_tubelet_tracks_v1.2_live_parity_dual",
        "gate_name": gate.name,
        "created_at_unix": time.time(),
        "elapsed_sec": time.time() - started_all,

        "input_dir": str(shared_args.input_dir),
        "output_dir": str(gate.output_dir),
        "yolo_model": str(shared_args.yolo_model),
        "tracker": shared_args.tracker,
        "device": shared_args.device,

        "settings": {
            "sample_fps": gate.sample_fps,
            "tubelet_frames": gate.tubelet_frames,
            "stride": gate.stride,
            "det_conf": shared_args.det_conf,
            "min_conf": gate.min_conf,
            "min_bbox_width": gate.min_bbox_width,
            "min_bbox_height": gate.min_bbox_height,
            "min_mean_iou": gate.min_mean_iou,
            "max_center_jump_ratio": gate.max_center_jump_ratio,
            "max_track_gap": gate.max_track_gap,
            "allow_sample_gaps": bool(gate.allow_sample_gaps),
            "target_window_duration_sec": float(gate.tubelet_frames / gate.sample_fps) if gate.sample_fps > 0 else None,
            "imgsz": shared_args.imgsz,
            "iou": shared_args.iou,
            "half": bool(shared_args.half),
            "compile_model": bool(shared_args.compile_model),
            "no_progress": bool(shared_args.no_progress),
            "limit_videos": shared_args.limit_videos,
            "recursive": shared_args.recursive,
            "video_id_from": shared_args.video_id_from,
        },

        "totals": {
            "videos_requested": len(rt.video_stats),
            "videos_ok": len(rt.video_stats) - len(failed_videos),
            "videos_failed": len(failed_videos),
            "sampled_frames": total_sampled_frames,
            "tracked_frames": total_tracked_frames,
            "accepted_tubelets": total_accepted,
            "rejected_tubelets": total_rejected,
        },

        "outputs": {
            "motion_tubelet_tracks_jsonl": str(jsonl_path),
            "summary_json": str(summary_path),
            "failed_csv": str(failed_path),
            "rejected_csv": str(rejected_path),
        },

        "parity_note": (
            "YOLO.track() was run once on every decoded frame and the tracked outputs were "
            "fed to separate gate-specific sampling/tubelet buffers."
        ),

        "video_stats": rt.video_stats,
    }

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logging.info("[%s] Extraction complete", gate.name)
    logging.info("[%s] Tracked decoded frames: %d", gate.name, total_tracked_frames)
    logging.info("[%s] Accepted tubelets: %d", gate.name, total_accepted)
    logging.info("[%s] Rejected tubelets: %d", gate.name, total_rejected)
    logging.info("[%s] Summary: %s", gate.name, summary_path)
    logging.info("[%s] JSONL: %s", gate.name, jsonl_path)


def main() -> None:
    args = parse_args()

    args.output_root.mkdir(parents=True, exist_ok=True)
    setup_logging(args.output_root)

    if not args.yolo_model.exists():
        raise SystemExit(f"ERROR: yolo_model does not exist: {args.yolo_model}")

    videos = find_videos(args.input_dir, recursive=args.recursive)
    if args.limit_videos is not None:
        videos = videos[:args.limit_videos]

    if not videos:
        raise SystemExit(f"ERROR: no videos found in: {args.input_dir}")

    pose_spec = GateSpec(
        name="pose",
        output_dir=args.output_root / "motion_tubelets_pose_live_parity_5fps_24f_s6_50vid",
        sample_fps=args.pose_sample_fps,
        tubelet_frames=args.pose_tubelet_frames,
        stride=args.pose_stride,
        max_track_gap=args.pose_max_track_gap,
        allow_sample_gaps=False,
        min_conf=args.pose_min_conf,
    )

    hom_spec = GateSpec(
        name="homography_macro",
        output_dir=args.output_root / "motion_tubelets_homography_live_parity_2p5fps_16f_s8_50vid",
        sample_fps=args.hom_sample_fps,
        tubelet_frames=args.hom_tubelet_frames,
        stride=args.hom_stride,
        max_track_gap=args.hom_max_track_gap,
        allow_sample_gaps=bool(args.hom_allow_sample_gaps),
        min_conf=args.hom_min_conf,
    )

    for gate in [pose_spec, hom_spec]:
        safe_prepare_output_dir(gate.output_dir, args.overwrite)

    logging.info("Starting DUAL motion tubelet extraction")
    logging.info("Input dir: %s", args.input_dir)
    logging.info("Output root: %s", args.output_root)
    logging.info("YOLO model: %s", args.yolo_model)
    logging.info("Videos to process: %d", len(videos))
    logging.info("Shared live-parity tracking: YOLO.track() ONCE on every decoded frame")
    logging.info("Pose: sample_fps=%.3f | tubelet_frames=%d | stride=%d | max_gap=%d | allow_gaps=False",
                 pose_spec.sample_fps, pose_spec.tubelet_frames, pose_spec.stride, pose_spec.max_track_gap)
    logging.info("Homography: sample_fps=%.3f | tubelet_frames=%d | stride=%d | max_gap=%d | allow_gaps=%s",
                 hom_spec.sample_fps, hom_spec.tubelet_frames, hom_spec.stride, hom_spec.max_track_gap, hom_spec.allow_sample_gaps)

    if torch is not None and torch.cuda.is_available():
        torch.backends.cudnn.benchmark = True
        logging.info("CUDA available: %s", torch.cuda.get_device_name(0))
        if args.device is None:
            args.device = "cuda"
            logging.info("No --device provided; using cuda automatically.")
    elif args.device and str(args.device).startswith("cuda"):
        logging.warning("--device cuda was requested, but torch.cuda.is_available() is false.")

    model = YOLO(str(args.yolo_model))

    failed_fields = [
        "video_path", "video_id", "status", "source_fps", "frame_count",
        "duration_sec", "frame_step", "effective_sample_fps", "target_window_duration_sec", "sampled_frames",
        "tracked_frames", "accepted_tubelets", "rejected_tubelets", "unique_track_ids",
        "elapsed_sec", "error",
    ]

    rejected_fields = [
        "video_path", "video_id", "track_id", "start_frame", "end_frame",
        "start_time_sec", "end_time_sec", "reasons", "mean_conf", "min_conf",
        "mean_iou", "max_center_jump_ratio", "mean_bbox_area_ratio",
        "min_bbox_width", "min_bbox_height",
    ]

    started_all = time.time()

    runtimes: List[GateRuntime] = []
    open_files = []
    try:
        for gate in [pose_spec, hom_spec]:
            jsonl_path = gate.output_dir / "motion_tubelet_tracks.jsonl"
            failed_path = gate.output_dir / "motion_tubelet_tracks_failed.csv"
            rejected_path = gate.output_dir / "motion_tubelet_tracks_rejected.csv"

            jsonl_file = jsonl_path.open("w", encoding="utf-8", newline="\n")
            failed_file = failed_path.open("w", encoding="utf-8", newline="")
            rejected_file = rejected_path.open("w", encoding="utf-8", newline="")
            open_files.extend([jsonl_file, failed_file, rejected_file])

            failed_writer = csv.DictWriter(failed_file, fieldnames=failed_fields)
            rejected_writer = csv.DictWriter(rejected_file, fieldnames=rejected_fields)
            failed_writer.writeheader()
            rejected_writer.writeheader()

            runtimes.append(GateRuntime(
                spec=gate,
                jsonl_file=jsonl_file,
                rejected_writer=rejected_writer,
                failed_writer=failed_writer,
                global_state={"next_tubelet_index": 0},
                video_stats=[],
            ))

        for video_path in videos:
            process_video_dual(
                video_path=video_path,
                input_dir=args.input_dir,
                model=model,
                runtimes=runtimes,
                shared_args=args,
            )

    finally:
        for f in open_files:
            try:
                f.close()
            except Exception:
                pass

    for rt in runtimes:
        write_summary(rt, args, started_all)


if __name__ == "__main__":
    main()
