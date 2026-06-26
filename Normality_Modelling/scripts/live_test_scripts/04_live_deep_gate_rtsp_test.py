#!/usr/bin/env python3
r"""
04_live_deep_gate_rtsp_test.py

Standalone Deep Gate live RTSP tester.

Goal:
  Debug live/offline parity for the VideoMAE deep branch only.

Pipeline:
  1) Open RTSP stream.
  2) Run YOLO person tracking every camera frame.
  3) Sample each tracked person at sample_fps.
  4) Build 16-frame tubelets with stride 8.
  5) Crop person frame-by-frame.
  6) Run VideoMAE embedding extraction.
  7) L2-normalize the 768-D embedding.
  8) Score using saved kNN artifact.
  9) Load threshold from JSON.
 10) Apply smoothing and persistence.
 11) Show live overlay.
 12) Save detailed debug outputs.

Example:
  python 04_live_deep_gate_rtsp_test.py ^
    --rtsp_url "rtsp://user:pass@ip:554/stream1" ^
    --output_dir "D:\Embeddings_Distribution\live_tests\deep_only_scores" ^
    --device cuda ^
    --deep_gate_dir "D:\Embeddings_Distribution\normality_models\deep_branch_artifacts_v2_gaussian" ^
    --deep_threshold_key p99_5 ^
    --sample_fps 2.5 ^
    --tubelet_frames 16 ^
    --stride 8 ^
    --smoothing_sigma 2 ^
    --persistence_hits 3 ^
    --persistence_window 5 ^
    --display ^
    --save_evidence ^
    --print_every_tubelet
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import joblib
import numpy as np

try:
    import torch
except Exception as e:
    raise RuntimeError("PyTorch is required for VideoMAE inference.") from e

try:
    from ultralytics import YOLO
except Exception as e:
    raise RuntimeError("ultralytics is required. Install with: pip install ultralytics") from e

try:
    from transformers import VideoMAEImageProcessor, VideoMAEModel
except Exception as e:
    raise RuntimeError(
        "transformers is required. Install with: pip install transformers"
    ) from e


# -----------------------------
# Small utilities
# -----------------------------

CURRENT_BBOX_PAD_RATIO = 0.20

def str2bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {v!r}")


def now_wall() -> float:
    return time.time()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clip_bbox_xyxy(
    bbox: Sequence[float],
    width: int,
    height: int,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = [float(x) for x in bbox]
    x1 = max(0, min(width - 1, int(round(x1))))
    y1 = max(0, min(height - 1, int(round(y1))))
    x2 = max(0, min(width - 1, int(round(x2))))
    y2 = max(0, min(height - 1, int(round(y2))))
    if x2 <= x1:
        x2 = min(width - 1, x1 + 1)
    if y2 <= y1:
        y2 = min(height - 1, y1 + 1)
    return x1, y1, x2, y2


def pad_box_xyxy(
    bbox: Sequence[float],
    width: int,
    height: int,
    pad_ratio: float = 0.20,
) -> Tuple[int, int, int, int]:
    """Frame-by-frame padded person crop box.

    This intentionally avoids temporal union crops. The Deep Gate should see the
    person crop frame-by-frame, matching the offline person-only extractor as
    closely as possible.
    """
    x1, y1, x2, y2 = [float(x) for x in bbox]
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    pad_x = bw * float(pad_ratio)
    pad_y = bh * float(pad_ratio)
    return clip_bbox_xyxy(
        (x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y),
        width=width,
        height=height,
    )


def safe_float(x: Any, default: float = float("nan")) -> float:
    try:
        return float(x)
    except Exception:
        return default


def l2_normalize(vec: np.ndarray, eps: float = 1e-12) -> Tuple[np.ndarray, float, float]:
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    before = float(np.linalg.norm(vec))
    out = vec / max(before, eps)
    after = float(np.linalg.norm(out))
    return out.astype(np.float32), before, after


def gaussian_smooth_latest(values: Sequence[float], sigma: float) -> float:
    """Return Gaussian-weighted smoothed value for the latest point."""
    if not values:
        return float("nan")
    if sigma <= 0:
        return float(values[-1])

    radius = max(1, int(math.ceil(3.0 * sigma)))
    recent = list(values)[-radius:]
    n = len(recent)
    # Oldest -> newest distances from latest: n-1 ... 0
    d = np.arange(n - 1, -1, -1, dtype=np.float32)
    w = np.exp(-(d ** 2) / (2.0 * sigma * sigma))
    w = w / max(float(w.sum()), 1e-12)
    return float(np.sum(np.asarray(recent, dtype=np.float32) * w))


def make_montage(
    images_rgb: Sequence[np.ndarray],
    thumb_w: int = 112,
    thumb_h: int = 112,
    cols: int = 4,
) -> np.ndarray:
    """Create BGR montage image for saving with cv2."""
    if not images_rgb:
        return np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)

    thumbs = []
    for img in images_rgb:
        if img is None or img.size == 0:
            thumb = np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8)
        else:
            thumb = cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        thumbs.append(thumb)

    rows = int(math.ceil(len(thumbs) / float(cols)))
    canvas = np.zeros((rows * thumb_h, cols * thumb_w, 3), dtype=np.uint8)
    for i, thumb in enumerate(thumbs):
        r = i // cols
        c = i % cols
        canvas[r * thumb_h:(r + 1) * thumb_h, c * thumb_w:(c + 1) * thumb_w] = thumb

    return cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)


def draw_label(
    frame_bgr: np.ndarray,
    x: int,
    y: int,
    text: str,
    color: Tuple[int, int, int],
    scale: float = 0.48,
    thickness: int = 1,
) -> None:
    y = max(15, y)
    cv2.putText(frame_bgr, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def atomic_json_write(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# -----------------------------
# Data structures
# -----------------------------

@dataclass
class Sample:
    sample_i: int
    wall_time: float
    frame_i: int
    frame_time_sec: float
    frame_bgr: np.ndarray
    frame_rgb: np.ndarray
    bbox_xyxy: Tuple[int, int, int, int]
    det_conf: float


@dataclass
class TrackState:
    track_id: int
    samples: List[Sample] = field(default_factory=list)
    next_start_sample_pos: int = 0
    last_sample_wall_time: float = 0.0
    last_sample_i: int = -1
    score_history: Deque[float] = field(default_factory=lambda: deque(maxlen=128))
    smooth_hit_history: Deque[bool] = field(default_factory=lambda: deque(maxlen=128))
    last_result: Dict[str, Any] = field(default_factory=dict)
    tubelet_counter: int = 0


# -----------------------------
# Artifact loading
# -----------------------------

def load_threshold(thresholds_path: Path, key: str, k: Optional[int] = None) -> float:
    """Load threshold from flexible JSON layouts.

    Supported examples:
      {"p99_5": 0.123}
      {"thresholds": {"p99_5": 0.123}}
      {"k1": {"p99_5": 0.123}, "k3": {"p99_5": 0.145}}
      {"thresholds": {"k1": {"p99_5": 0.123}}}
      [{"key": "p99_5", "threshold": 0.123}]
    """
    if not thresholds_path.exists():
        raise FileNotFoundError(f"Threshold file not found: {thresholds_path}")

    data = json.loads(thresholds_path.read_text(encoding="utf-8"))

    candidates = []
    if isinstance(data, dict):
        candidates.append(data)
        for nested_key in ("thresholds", "deep_thresholds", "knn_thresholds", "scores"):
            if isinstance(data.get(nested_key), dict):
                candidates.append(data[nested_key])

    k_names = []
    if k is not None:
        k_names = [f"k{k}", str(k), f"deep_k_{k}"]

    # Prefer k-specific thresholds when present.
    for d in candidates:
        for k_name in k_names:
            kd = d.get(k_name) if isinstance(d, dict) else None
            if isinstance(kd, dict) and key in kd:
                return float(kd[key])

    # Then direct thresholds.
    for d in candidates:
        if isinstance(d, dict) and key in d:
            return float(d[key])

    # Helpful fallback for JSONs that store rows/lists
    if isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            row_k = row.get("k", row.get("deep_k", None))
            k_matches = k is None or row_k is None or int(row_k) == int(k)
            if k_matches and row.get("key") == key and "threshold" in row:
                return float(row["threshold"])

    available = []
    for d in candidates:
        if isinstance(d, dict):
            available.extend([str(k0) for k0 in d.keys()])
            for k_name in k_names:
                if isinstance(d.get(k_name), dict):
                    available.extend([f"{k_name}.{kk}" for kk in d[k_name].keys()])
    raise KeyError(
        f"Threshold key {key!r} for k={k!r} not found in {thresholds_path}. "
        f"Available top-level/nested keys include: {sorted(set(available))[:80]}"
    )


def extract_knn_object(artifact: Any) -> Any:
    """Accept common joblib artifact shapes and return an object with kneighbors()."""
    if hasattr(artifact, "kneighbors"):
        return artifact

    if isinstance(artifact, dict):
        for key in (
            "knn",
            "knn_index",
            "index",
            "nearest_neighbors",
            "nn",
            "model",
            "estimator",
        ):
            obj = artifact.get(key)
            if hasattr(obj, "kneighbors"):
                return obj

    raise TypeError(
        "Could not find a kNN object with .kneighbors() in the loaded artifact. "
        "Expected a sklearn NearestNeighbors-like object or a dict containing one."
    )


def score_knn_embedding(
    knn: Any,
    emb_l2: np.ndarray,
    k: int,
) -> Dict[str, Any]:
    x = emb_l2.reshape(1, -1).astype(np.float32)
    distances, indices = knn.kneighbors(x, n_neighbors=int(k), return_distance=True)
    distances = np.asarray(distances).reshape(-1).astype(np.float32)
    indices = np.asarray(indices).reshape(-1)

    # Deep score convention:
    # For k=1 this is the 1-NN distance.
    # For k>1 this is the mean of k nearest distances.
    score = float(np.mean(distances[:k]))
    return {
        "deep_score": score,
        "nearest_neighbor_distance": float(distances[0]) if len(distances) else float("nan"),
        "nearest_neighbor_index": int(indices[0]) if len(indices) else -1,
        "k_distances": [float(x) for x in distances[:k]],
        "k_indices": [int(x) for x in indices[:k]],
    }


# -----------------------------
# VideoMAE embedding extraction
# -----------------------------

class DeepEmbedder:
    def __init__(
        self,
        model_name_or_path: str,
        device: str,
        fp16: bool = False,
        use_fast_processor: bool = False,
        do_flip_channel_order: bool = False,
    ) -> None:
        self.device = torch.device(device if torch.cuda.is_available() or device == "cpu" else "cpu")
        self.fp16 = bool(fp16 and self.device.type == "cuda")
        self.do_flip_channel_order = bool(do_flip_channel_order)

        processor_kwargs = {}
        # Some transformers versions support use_fast and some do not.
        try:
            processor_kwargs["use_fast"] = bool(use_fast_processor)
            self.processor = VideoMAEImageProcessor.from_pretrained(model_name_or_path, **processor_kwargs)
        except TypeError:
            self.processor = VideoMAEImageProcessor.from_pretrained(model_name_or_path)

        self.model = VideoMAEModel.from_pretrained(model_name_or_path)
        self.model.eval()
        self.model.to(self.device)
        if self.fp16:
            self.model.half()

    @torch.no_grad()
    def embed_crops_rgb(self, crops_rgb: Sequence[np.ndarray]) -> np.ndarray:
        frames = []
        for crop in crops_rgb:
            if crop is None or crop.size == 0:
                # Defensive fallback: black crop in RGB.
                crop = np.zeros((224, 224, 3), dtype=np.uint8)

            arr = crop
            if self.do_flip_channel_order:
                # Debug-only switch. Default path is RGB. This intentionally flips RGB<->BGR.
                arr = arr[:, :, ::-1].copy()

            frames.append(arr)

        # Critical color-parity fix:
        # We already convert OpenCV BGR -> RGB before this point. Therefore, tell
        # processors that support this argument NOT to flip channels internally.
        try:
            inputs = self.processor(
                list(frames),
                return_tensors="pt",
                do_flip_channel_order=False,
            )
        except TypeError:
            # Some VideoMAEImageProcessor versions do not expose this kwarg.
            # In that case, the processor expects RGB PIL/NumPy images and does
            # not perform a hidden BGR->RGB flip.
            inputs = self.processor(list(frames), return_tensors="pt")

        pixel_values = inputs["pixel_values"].to(self.device)
        if self.fp16:
            pixel_values = pixel_values.half()

        outputs = self.model(pixel_values=pixel_values)

        # VideoMAEModel returns last_hidden_state: [B, tokens, hidden_size].
        # Use mean pooling over tokens to get one 768-D tubelet embedding.
        emb = outputs.last_hidden_state.mean(dim=1).detach().float().cpu().numpy()[0]
        return emb.astype(np.float32)


# -----------------------------
# CSV/JSONL writers
# -----------------------------

class OutputWriters:
    def __init__(self, output_dir: Path, deep_k: int) -> None:
        self.output_dir = output_dir
        ensure_dir(output_dir)

        self.tubelets_csv_path = output_dir / "tubelets.csv"
        self.tubelets_jsonl_path = output_dir / "tubelets.jsonl"
        self.events_jsonl_path = output_dir / "events.jsonl"
        self.deep_features_csv_path = output_dir / "deep_features_live.csv"

        self.tubelet_fields = [
            "wall_time",
            "track_id",
            "tubelet_index",
            "sample_start_i",
            "sample_end_i",
            "tubelet_start_time",
            "tubelet_end_time",
            "deep_score",
            "deep_threshold",
            "deep_score_smooth",
            "deep_hit_raw",
            "deep_hit_smooth",
            "deep_persistent_hit",
            "deep_catastrophic_hit",
            "deep_catastrophic_threshold",
            "anomaly",
            "reasons",
            "evidence_frame",
            "evidence_montage",
        ]

        self.feature_fields = [
            "wall_time",
            "track_id",
            "tubelet_index",
            "sample_start_i",
            "sample_end_i",
            "deep_score",
            "deep_threshold",
            "deep_score_smooth",
            "embedding_raw_norm_before_l2",
            "embedding_l2_norm_after_l2",
            "nearest_neighbor_distance",
            "nearest_neighbor_index",
        ]
        self.feature_fields.extend([f"knn_distance_{i+1}" for i in range(int(deep_k))])
        self.feature_fields.extend([
            "crop_mean_rgb",
            "crop_std_rgb",
            "crop_min_rgb",
            "crop_max_rgb",
            "crop_mean_area_px",
            "crop_min_area_px",
            "crop_max_area_px",
            "bbox_mean_x1",
            "bbox_mean_y1",
            "bbox_mean_x2",
            "bbox_mean_y2",
            "bbox_mean_w",
            "bbox_mean_h",
            "bbox_mean_area_px",
            "bbox_mean_aspect",
            "bbox_min_conf",
            "bbox_mean_conf",
            "bbox_max_conf",
        ])

        self.tubelets_csv_f = self.tubelets_csv_path.open("w", newline="", encoding="utf-8")
        self.features_csv_f = self.deep_features_csv_path.open("w", newline="", encoding="utf-8")
        self.tubelets_jsonl_f = self.tubelets_jsonl_path.open("w", encoding="utf-8")
        self.events_jsonl_f = self.events_jsonl_path.open("w", encoding="utf-8")

        self.tubelets_writer = csv.DictWriter(
            self.tubelets_csv_f,
            fieldnames=self.tubelet_fields,
            extrasaction="ignore",
        )
        self.features_writer = csv.DictWriter(
            self.features_csv_f,
            fieldnames=self.feature_fields,
            extrasaction="ignore",
        )
        self.tubelets_writer.writeheader()
        self.features_writer.writeheader()

    def write_tubelet(self, row: Dict[str, Any], full_record: Dict[str, Any]) -> None:
        self.tubelets_writer.writerow(row)
        self.tubelets_csv_f.flush()
        self.tubelets_jsonl_f.write(json.dumps(full_record, ensure_ascii=False) + "\n")
        self.tubelets_jsonl_f.flush()

    def write_event(self, event: Dict[str, Any]) -> None:
        self.events_jsonl_f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.events_jsonl_f.flush()

    def write_features(self, row: Dict[str, Any]) -> None:
        self.features_writer.writerow(row)
        self.features_csv_f.flush()

    def close(self) -> None:
        for f in (
            self.tubelets_csv_f,
            self.features_csv_f,
            self.tubelets_jsonl_f,
            self.events_jsonl_f,
        ):
            try:
                f.close()
            except Exception:
                pass


# -----------------------------
# Tubelet processing
# -----------------------------

def crop_persons_rgb(samples: Sequence[Sample]) -> Tuple[List[np.ndarray], Dict[str, float]]:
    crops = []
    crop_areas = []
    pixel_means = []
    pixel_stds = []
    pixel_mins = []
    pixel_maxs = []

    bbox_x1 = []
    bbox_y1 = []
    bbox_x2 = []
    bbox_y2 = []
    bbox_w = []
    bbox_h = []
    bbox_area = []
    bbox_aspect = []
    confs = []

    for s in samples:
        h, w = s.frame_rgb.shape[:2]
        x1, y1, x2, y2 = pad_box_xyxy(s.bbox_xyxy, w, h, pad_ratio=CURRENT_BBOX_PAD_RATIO)
        crop = s.frame_rgb[y1:y2, x1:x2].copy()
        if crop.size == 0:
            crop = np.zeros((224, 224, 3), dtype=np.uint8)

        crops.append(crop)

        cw = max(1, x2 - x1)
        ch = max(1, y2 - y1)
        area = float(cw * ch)

        crop_areas.append(area)
        pixel_means.append(float(np.mean(crop)))
        pixel_stds.append(float(np.std(crop)))
        pixel_mins.append(float(np.min(crop)))
        pixel_maxs.append(float(np.max(crop)))

        bbox_x1.append(float(x1))
        bbox_y1.append(float(y1))
        bbox_x2.append(float(x2))
        bbox_y2.append(float(y2))
        bbox_w.append(float(cw))
        bbox_h.append(float(ch))
        bbox_area.append(area)
        bbox_aspect.append(float(cw / max(ch, 1)))
        confs.append(float(s.det_conf))

    stats = {
        "crop_mean_rgb": float(np.mean(pixel_means)) if pixel_means else float("nan"),
        "crop_std_rgb": float(np.mean(pixel_stds)) if pixel_stds else float("nan"),
        "crop_min_rgb": float(np.min(pixel_mins)) if pixel_mins else float("nan"),
        "crop_max_rgb": float(np.max(pixel_maxs)) if pixel_maxs else float("nan"),
        "crop_mean_area_px": float(np.mean(crop_areas)) if crop_areas else float("nan"),
        "crop_min_area_px": float(np.min(crop_areas)) if crop_areas else float("nan"),
        "crop_max_area_px": float(np.max(crop_areas)) if crop_areas else float("nan"),
        "bbox_mean_x1": float(np.mean(bbox_x1)) if bbox_x1 else float("nan"),
        "bbox_mean_y1": float(np.mean(bbox_y1)) if bbox_y1 else float("nan"),
        "bbox_mean_x2": float(np.mean(bbox_x2)) if bbox_x2 else float("nan"),
        "bbox_mean_y2": float(np.mean(bbox_y2)) if bbox_y2 else float("nan"),
        "bbox_mean_w": float(np.mean(bbox_w)) if bbox_w else float("nan"),
        "bbox_mean_h": float(np.mean(bbox_h)) if bbox_h else float("nan"),
        "bbox_mean_area_px": float(np.mean(bbox_area)) if bbox_area else float("nan"),
        "bbox_mean_aspect": float(np.mean(bbox_aspect)) if bbox_aspect else float("nan"),
        "bbox_min_conf": float(np.min(confs)) if confs else float("nan"),
        "bbox_mean_conf": float(np.mean(confs)) if confs else float("nan"),
        "bbox_max_conf": float(np.max(confs)) if confs else float("nan"),
    }
    return crops, stats


def save_evidence_files(
    evidence_dir: Path,
    samples: Sequence[Sample],
    crops_rgb: Sequence[np.ndarray],
    track_id: int,
    tubelet_index: int,
) -> Tuple[str, str, str]:
    ensure_dir(evidence_dir)

    prefix = f"track{track_id:04d}_tubelet{tubelet_index:06d}"
    frame_path = evidence_dir / f"{prefix}_frame.jpg"
    montage_path = evidence_dir / f"{prefix}_frames_montage.jpg"
    crops_montage_path = evidence_dir / f"{prefix}_crops_montage.jpg"

    # Evidence frame: last frame with bbox drawn.
    last = samples[-1]
    frame = last.frame_bgr.copy()
    x1, y1, x2, y2 = last.bbox_xyxy
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
    cv2.imwrite(str(frame_path), frame)

    # Full-frame montage: resize RGB full frames.
    full_rgb = [s.frame_rgb for s in samples]
    cv2.imwrite(str(montage_path), make_montage(full_rgb, thumb_w=160, thumb_h=90, cols=4))

    # Cropped-person montage.
    cv2.imwrite(str(crops_montage_path), make_montage(crops_rgb, thumb_w=112, thumb_h=112, cols=4))

    return str(frame_path), str(montage_path), str(crops_montage_path)


def process_tubelet(
    args: argparse.Namespace,
    track: TrackState,
    tubelet_samples: Sequence[Sample],
    embedder: DeepEmbedder,
    knn: Any,
    deep_threshold: float,
    catastrophic_threshold: Optional[float],
    writers: OutputWriters,
    evidence_dir: Path,
    embeddings_dir: Path,
    crops_dir: Path,
) -> Dict[str, Any]:
    track.tubelet_counter += 1
    tubelet_index = track.tubelet_counter

    crops_rgb, crop_bbox_stats = crop_persons_rgb(tubelet_samples)

    emb_raw = embedder.embed_crops_rgb(crops_rgb)
    emb_l2, emb_norm_before, emb_norm_after = l2_normalize(emb_raw)

    knn_info = score_knn_embedding(knn, emb_l2, args.deep_k)
    deep_score = float(knn_info["deep_score"])

    track.score_history.append(deep_score)
    deep_score_smooth = gaussian_smooth_latest(track.score_history, args.smoothing_sigma)

    deep_hit_raw = bool(deep_score > deep_threshold)
    deep_hit_smooth = bool(deep_score_smooth > deep_threshold)
    track.smooth_hit_history.append(deep_hit_smooth)

    recent_hits = list(track.smooth_hit_history)[-args.persistence_window:]
    deep_persistent_hit = bool(sum(bool(x) for x in recent_hits) >= args.persistence_hits)

    # Latency-aware safety branch:
    # Persistent smoothed hits are conservative. A very high raw score can bypass
    # smoothing/persistence when it exceeds a stricter threshold such as p99_9.
    catastrophic_hit = bool(
        catastrophic_threshold is not None and deep_score > float(catastrophic_threshold)
    )

    anomaly = bool(deep_persistent_hit or catastrophic_hit)

    reasons = []
    if deep_hit_raw:
        reasons.append("deep_raw_score_above_threshold")
    if deep_hit_smooth:
        reasons.append("deep_smoothed_score_above_threshold")
    if deep_persistent_hit:
        reasons.append(f"deep_persistent_{args.persistence_hits}_of_{args.persistence_window}")
    if catastrophic_hit:
        reasons.append(f"sudden_catastrophic_raw_score_above_{args.catastrophic_threshold_key}")

    evidence_frame = ""
    evidence_montage = ""
    evidence_crops_montage = ""

    save_this_evidence = bool(args.save_evidence and (anomaly or args.save_all_tubelets))
    if save_this_evidence:
        evidence_frame, evidence_montage, evidence_crops_montage = save_evidence_files(
            evidence_dir=evidence_dir,
            samples=tubelet_samples,
            crops_rgb=crops_rgb,
            track_id=track.track_id,
            tubelet_index=tubelet_index,
        )

    if args.dump_embeddings:
        ensure_dir(embeddings_dir)
        np.save(embeddings_dir / f"track{track.track_id:04d}_tubelet{tubelet_index:06d}_raw.npy", emb_raw)
        np.save(embeddings_dir / f"track{track.track_id:04d}_tubelet{tubelet_index:06d}_l2.npy", emb_l2)

    if args.dump_crops:
        out_dir = ensure_dir(crops_dir / f"track{track.track_id:04d}_tubelet{tubelet_index:06d}")
        for i, crop in enumerate(crops_rgb):
            cv2.imwrite(str(out_dir / f"crop_{i:02d}.jpg"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))

    first = tubelet_samples[0]
    last = tubelet_samples[-1]

    row = {
        "wall_time": now_wall(),
        "track_id": track.track_id,
        "tubelet_index": tubelet_index,
        "sample_start_i": first.sample_i,
        "sample_end_i": last.sample_i,
        "tubelet_start_time": first.frame_time_sec,
        "tubelet_end_time": last.frame_time_sec,
        "deep_score": deep_score,
        "deep_threshold": deep_threshold,
        "deep_catastrophic_threshold": catastrophic_threshold,
        "deep_score_smooth": deep_score_smooth,
        "deep_hit_raw": int(deep_hit_raw),
        "deep_hit_smooth": int(deep_hit_smooth),
        "deep_persistent_hit": int(deep_persistent_hit),
        "deep_catastrophic_hit": int(catastrophic_hit),
        "deep_catastrophic_threshold": catastrophic_threshold if catastrophic_threshold is not None else "",
        "anomaly": int(anomaly),
        "reasons": "|".join(reasons),
        "evidence_frame": evidence_frame,
        "evidence_montage": evidence_montage,
    }

    full_record = {
        **row,
        "evidence_crops_montage": evidence_crops_montage,
        "deep_k": int(args.deep_k),
        "k_distances": knn_info["k_distances"],
        "k_indices": knn_info["k_indices"],
        "embedding_raw_norm_before_l2": emb_norm_before,
        "embedding_l2_norm_after_l2": emb_norm_after,
        "crop_bbox_stats": crop_bbox_stats,
        "samples": [
            {
                "sample_i": s.sample_i,
                "wall_time": s.wall_time,
                "frame_i": s.frame_i,
                "frame_time_sec": s.frame_time_sec,
                "bbox_xyxy": list(map(int, s.bbox_xyxy)),
                "det_conf": float(s.det_conf),
            }
            for s in tubelet_samples
        ],
    }

    feature_row = {
        "wall_time": row["wall_time"],
        "track_id": track.track_id,
        "tubelet_index": tubelet_index,
        "sample_start_i": first.sample_i,
        "sample_end_i": last.sample_i,
        "deep_score": deep_score,
        "deep_threshold": deep_threshold,
        "deep_catastrophic_threshold": catastrophic_threshold,
        "deep_score_smooth": deep_score_smooth,
        "embedding_raw_norm_before_l2": emb_norm_before,
        "embedding_l2_norm_after_l2": emb_norm_after,
        "nearest_neighbor_distance": knn_info["nearest_neighbor_distance"],
        "nearest_neighbor_index": knn_info["nearest_neighbor_index"],
        **crop_bbox_stats,
    }
    for i in range(int(args.deep_k)):
        vals = knn_info["k_distances"]
        feature_row[f"knn_distance_{i+1}"] = float(vals[i]) if i < len(vals) else float("nan")

    writers.write_tubelet(row, full_record)
    writers.write_features(feature_row)

    if anomaly:
        writers.write_event(full_record)

    track.last_result = {
        "deep_score": deep_score,
        "deep_threshold": deep_threshold,
        "deep_catastrophic_threshold": catastrophic_threshold,
        "deep_score_smooth": deep_score_smooth,
        "deep_hit_raw": deep_hit_raw,
        "deep_hit_smooth": deep_hit_smooth,
        "deep_persistent_hit": deep_persistent_hit,
        "deep_catastrophic_hit": catastrophic_hit,
        "deep_catastrophic_threshold": catastrophic_threshold,
        "anomaly": anomaly,
        "tubelet_index": tubelet_index,
    }

    if args.print_every_tubelet:
        status = "ANOMALY" if anomaly else "NORMAL"
        print(
            f"[tubelet] track={track.track_id} idx={tubelet_index} "
            f"samples={first.sample_i}->{last.sample_i} "
            f"score={deep_score:.6f} smooth={deep_score_smooth:.6f} "
            f"thr={deep_threshold:.6f} raw={int(deep_hit_raw)} "
            f"smooth_hit={int(deep_hit_smooth)} persist={int(deep_persistent_hit)} "
            f"{status}",
            flush=True,
        )

    return full_record


# -----------------------------
# Main loop
# -----------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone Deep Gate RTSP live tester.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    p.add_argument("--rtsp_url", required=True)
    p.add_argument("--output_dir", required=True)
    p.add_argument("--device", default="cuda")

    p.add_argument("--det_model", default="yolov8n.pt")
    p.add_argument("--det_conf", type=float, default=0.35)
    p.add_argument("--det_imgsz", type=int, default=640)
    p.add_argument("--tracker", default="bytetrack.yaml")

    p.add_argument("--sample_fps", type=float, default=2.5)
    p.add_argument("--tubelet_frames", type=int, default=16)
    p.add_argument("--stride", type=int, default=8)

    p.add_argument(
        "--deep_gate_dir",
        default=r"D:\Embeddings_Distribution\normality_models\deep_branch_artifacts_v2_gaussian",
    )
    p.add_argument("--deep_k", type=int, default=3)
    p.add_argument("--deep_threshold_key", default="p99_5")
    p.add_argument("--catastrophic_threshold_key", default="p99_9")
    p.add_argument("--disable_catastrophic_bypass", action="store_true")
    p.add_argument("--bbox_pad_ratio", type=float, default=0.20)

    p.add_argument("--smoothing_sigma", type=float, default=2.0)
    p.add_argument("--persistence_hits", type=int, default=3)
    p.add_argument("--persistence_window", type=int, default=5)
    p.add_argument("--max_track_gap_samples", type=int, default=8)

    p.add_argument("--display", action="store_true")
    p.add_argument("--save_evidence", action="store_true")
    p.add_argument("--save_all_tubelets", action="store_true")
    p.add_argument("--print_every_tubelet", action="store_true")
    p.add_argument("--max_runtime_sec", type=float, default=0.0)

    # Optional deep debug args.
    p.add_argument("--deep_fp16", type=str2bool, default=True)
    p.add_argument("--deep_use_fast_processor", type=str2bool, default=False)
    p.add_argument("--deep_do_flip_channel_order", type=str2bool, default=False)
    p.add_argument("--dump_embeddings", action="store_true")
    p.add_argument("--dump_crops", action="store_true")
    p.add_argument("--dump_deep_features", action="store_true")

    # Extra optional path for explicit parity. Default is the usual VideoMAE base.
    p.add_argument("--videomae_model_name", default="MCG-NJU/videomae-base")

    return p.parse_args()


def summarize_settings(args: argparse.Namespace, deep_threshold: float, output_dir: Path, catastrophic_threshold: Optional[float] = None) -> Dict[str, Any]:
    return {
        "script": "04_live_deep_gate_rtsp_test.py",
        "created_wall_time": now_wall(),
        "rtsp_url_redacted": redact_rtsp(args.rtsp_url),
        "output_dir": str(output_dir),
        "runtime_settings": vars(args),
        "deep_threshold": deep_threshold,
        "deep_catastrophic_threshold": catastrophic_threshold,
        "notes": {
            "pipeline": [
                "YOLO tracking runs every camera frame.",
                "Per-track samples are captured at sample_fps.",
                "Tubelets use tubelet_frames and stride in sampled-person-track space.",
                "OpenCV BGR frames are converted to RGB before person cropping.",
                "VideoMAE embedding is mean-pooled from last_hidden_state and L2-normalized.",
                "kNN score is mean distance of deep_k nearest neighbors.",
                "Smoothing is Gaussian-weighted over recent tubelet scores per track.",
                "Persistence is computed over recent smoothed hits per track.",
            ],
            "deep_do_flip_channel_order": (
                "Default false. If true, RGB crops are flipped to BGR before processor. "
                "Use only to test suspected offline/live channel-order mismatch."
            ),
        },
    }


def redact_rtsp(url: str) -> str:
    # Keep enough for debugging but remove credentials.
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    return f"{scheme}://<redacted>@" + rest.split("@", 1)[1]


def open_capture(rtsp_url: str) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open RTSP/video source: {redact_rtsp(rtsp_url)}")
    return cap


def detect_person_tracks(
    model: YOLO,
    frame_bgr: np.ndarray,
    args: argparse.Namespace,
) -> List[Dict[str, Any]]:
    results = model.track(
        source=frame_bgr,
        persist=True,
        tracker=args.tracker,
        conf=args.det_conf,
        imgsz=args.det_imgsz,
        classes=[0],
        verbose=False,
    )

    persons: List[Dict[str, Any]] = []
    if not results:
        return persons

    r = results[0]
    if r.boxes is None or len(r.boxes) == 0:
        return persons

    boxes = r.boxes
    xyxy = boxes.xyxy.detach().cpu().numpy() if boxes.xyxy is not None else np.empty((0, 4))
    confs = boxes.conf.detach().cpu().numpy() if boxes.conf is not None else np.zeros((len(xyxy),))
    ids = None
    if boxes.id is not None:
        ids = boxes.id.detach().cpu().numpy().astype(int)

    if ids is None:
        # YOLO sometimes detects before tracker assigns IDs. We skip those frames because
        # tubelets must be track-consistent.
        return persons

    h, w = frame_bgr.shape[:2]
    for i in range(len(xyxy)):
        track_id = int(ids[i])
        bbox = clip_bbox_xyxy(xyxy[i], w, h)
        persons.append({
            "track_id": track_id,
            "bbox_xyxy": bbox,
            "conf": float(confs[i]) if i < len(confs) else float("nan"),
        })
    return persons


def add_sample_to_track(
    tracks: Dict[int, TrackState],
    person: Dict[str, Any],
    frame_bgr: np.ndarray,
    frame_rgb: np.ndarray,
    frame_i: int,
    frame_time_sec: float,
    sample_i: int,
) -> TrackState:
    track_id = int(person["track_id"])
    track = tracks.get(track_id)
    if track is None:
        track = TrackState(track_id=track_id)
        tracks[track_id] = track

    s = Sample(
        sample_i=sample_i,
        wall_time=now_wall(),
        frame_i=frame_i,
        frame_time_sec=frame_time_sec,
        frame_bgr=frame_bgr.copy(),
        frame_rgb=frame_rgb.copy(),
        bbox_xyxy=person["bbox_xyxy"],
        det_conf=float(person["conf"]),
    )
    track.samples.append(s)
    track.last_sample_wall_time = s.wall_time
    track.last_sample_i = sample_i
    return track


def prune_stale_tracks(
    tracks: Dict[int, TrackState],
    current_sample_i: int,
    max_track_gap_samples: int,
) -> None:
    stale = []
    for tid, tr in tracks.items():
        if tr.last_sample_i >= 0 and (current_sample_i - tr.last_sample_i) > max_track_gap_samples:
            stale.append(tid)
    for tid in stale:
        del tracks[tid]


def annotate_overlay(
    frame_bgr: np.ndarray,
    persons: Sequence[Dict[str, Any]],
    tracks: Dict[int, TrackState],
) -> np.ndarray:
    out = frame_bgr.copy()
    for p in persons:
        tid = int(p["track_id"])
        x1, y1, x2, y2 = p["bbox_xyxy"]
        tr = tracks.get(tid)
        last = tr.last_result if tr is not None else {}

        anomaly = bool(last.get("anomaly", False))
        color = (0, 0, 255) if anomaly else (0, 200, 0)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

        score = last.get("deep_score", float("nan"))
        thr = last.get("deep_threshold", float("nan"))
        smooth = last.get("deep_score_smooth", float("nan"))
        raw = int(bool(last.get("deep_hit_raw", False)))
        sh = int(bool(last.get("deep_hit_smooth", False)))
        ph = int(bool(last.get("deep_persistent_hit", False)))
        ch = int(bool(last.get("deep_catastrophic_hit", False)))
        status = "ANOMALY" if anomaly else "NORMAL"

        lines = [
            f"id={tid} {status}",
            f"raw={safe_float(score):.4f} thr={safe_float(thr):.4f}",
            f"smooth={safe_float(smooth):.4f}",
            f"hit raw/sm/persist/cat={raw}/{sh}/{ph}/{ch}",
        ]
        for j, line in enumerate(lines):
            draw_label(out, x1, y1 - 8 - (len(lines) - 1 - j) * 17, line, color)

    return out


def main() -> int:
    args = parse_args()

    output_dir = ensure_dir(Path(args.output_dir))
    evidence_dir = ensure_dir(output_dir / "evidence")
    embeddings_dir = ensure_dir(output_dir / "embeddings")
    crops_dir = ensure_dir(output_dir / "crops")

    deep_gate_dir = Path(args.deep_gate_dir)
    knn_path = deep_gate_dir / "models" / "03_knn_index.joblib"
    thresholds_path = deep_gate_dir / "04_thresholds.json"

    if not knn_path.exists():
        raise FileNotFoundError(f"kNN artifact not found: {knn_path}")

    print(f"[load] kNN artifact: {knn_path}", flush=True)
    artifact = joblib.load(knn_path)
    knn = extract_knn_object(artifact)

    deep_threshold = load_threshold(thresholds_path, args.deep_threshold_key, k=args.deep_k)
    print(f"[load] threshold k={args.deep_k} {args.deep_threshold_key} = {deep_threshold:.6f}", flush=True)

    catastrophic_threshold = None
    if not args.disable_catastrophic_bypass:
        try:
            catastrophic_threshold = load_threshold(
                thresholds_path,
                args.catastrophic_threshold_key,
                k=args.deep_k,
            )
            print(
                f"[load] catastrophic raw bypass threshold k={args.deep_k} "
                f"{args.catastrophic_threshold_key} = {catastrophic_threshold:.6f}",
                flush=True,
            )
        except Exception as e:
            print(
                f"[warn] catastrophic bypass disabled because threshold "
                f"{args.catastrophic_threshold_key!r} for k={args.deep_k} was not found: {e}",
                flush=True,
            )
            catastrophic_threshold = None

    global CURRENT_BBOX_PAD_RATIO
    CURRENT_BBOX_PAD_RATIO = float(args.bbox_pad_ratio)

    print(f"[load] YOLO detector: {args.det_model}", flush=True)
    det_model = YOLO(args.det_model)

    print(f"[load] VideoMAE: {args.videomae_model_name}", flush=True)
    embedder = DeepEmbedder(
        model_name_or_path=args.videomae_model_name,
        device=args.device,
        fp16=args.deep_fp16,
        use_fast_processor=args.deep_use_fast_processor,
        do_flip_channel_order=args.deep_do_flip_channel_order,
    )
    print(f"[load] VideoMAE device={embedder.device} fp16={embedder.fp16}", flush=True)

    atomic_json_write(output_dir / "live_summary.json", summarize_settings(args, deep_threshold, output_dir, catastrophic_threshold))

    writers = OutputWriters(output_dir=output_dir, deep_k=args.deep_k)

    cap = open_capture(args.rtsp_url)
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if not src_fps or src_fps <= 0 or math.isnan(src_fps):
        src_fps = 30.0

    sample_interval_sec = 1.0 / max(float(args.sample_fps), 1e-6)
    print(
        f"[run] source_fps≈{src_fps:.3f}, sample_fps={args.sample_fps}, "
        f"sample_interval={sample_interval_sec:.3f}s",
        flush=True,
    )

    tracks: Dict[int, TrackState] = {}
    frame_i = 0
    sample_i = -1
    start_wall = now_wall()
    last_sample_wall = 0.0
    processed_tubelets = 0
    anomaly_events = 0

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok or frame_bgr is None:
                print("[warn] Failed to read frame. Reconnecting/opening source again...", flush=True)
                cap.release()
                time.sleep(0.5)
                cap = open_capture(args.rtsp_url)
                continue

            frame_i += 1
            elapsed = now_wall() - start_wall
            frame_time_sec = elapsed

            if args.max_runtime_sec and elapsed >= args.max_runtime_sec:
                print("[run] max_runtime_sec reached.", flush=True)
                break

            persons = detect_person_tracks(det_model, frame_bgr, args)

            should_sample = (now_wall() - last_sample_wall) >= sample_interval_sec
            frame_rgb = None

            if should_sample:
                sample_i += 1
                last_sample_wall = now_wall()
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

                for person in persons:
                    tr = add_sample_to_track(
                        tracks=tracks,
                        person=person,
                        frame_bgr=frame_bgr,
                        frame_rgb=frame_rgb,
                        frame_i=frame_i,
                        frame_time_sec=frame_time_sec,
                        sample_i=sample_i,
                    )

                    # Build all ready tubelets for this track.
                    while tr.next_start_sample_pos + args.tubelet_frames <= len(tr.samples):
                        tubelet_samples = tr.samples[
                            tr.next_start_sample_pos:tr.next_start_sample_pos + args.tubelet_frames
                        ]

                        rec = process_tubelet(
                            args=args,
                            track=tr,
                            tubelet_samples=tubelet_samples,
                            embedder=embedder,
                            knn=knn,
                            deep_threshold=deep_threshold,
                            catastrophic_threshold=catastrophic_threshold,
                            writers=writers,
                            evidence_dir=evidence_dir,
                            embeddings_dir=embeddings_dir,
                            crops_dir=crops_dir,
                        )
                        processed_tubelets += 1
                        if bool(rec.get("anomaly")):
                            anomaly_events += 1

                        tr.next_start_sample_pos += args.stride

                    # Prevent unbounded memory growth while preserving future windows.
                    min_keep_pos = max(0, tr.next_start_sample_pos - args.tubelet_frames)
                    if min_keep_pos > 0:
                        tr.samples = tr.samples[min_keep_pos:]
                        tr.next_start_sample_pos -= min_keep_pos

                prune_stale_tracks(
                    tracks=tracks,
                    current_sample_i=sample_i,
                    max_track_gap_samples=args.max_track_gap_samples,
                )

            if args.display:
                overlay = annotate_overlay(frame_bgr, persons, tracks)
                draw_label(
                    overlay,
                    12,
                    24,
                    f"Deep Gate Only | tubelets={processed_tubelets} events={anomaly_events} tracks={len(tracks)}",
                    (255, 255, 255),
                    scale=0.62,
                    thickness=2,
                )
                cv2.imshow("Deep Gate RTSP Test", overlay)
                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    print("[run] display quit requested.", flush=True)
                    break

    except KeyboardInterrupt:
        print("\n[run] interrupted by user.", flush=True)

    finally:
        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        writers.close()

        final_summary = summarize_settings(args, deep_threshold, output_dir, catastrophic_threshold)
        final_summary.update({
            "finished_wall_time": now_wall(),
            "runtime_sec": now_wall() - start_wall,
            "frames_read": frame_i,
            "samples_emitted": sample_i + 1,
            "processed_tubelets": processed_tubelets,
            "persistent_anomaly_events": anomaly_events,
            "final_active_tracks": len(tracks),
            "output_files": {
                "tubelets_csv": str(output_dir / "tubelets.csv"),
                "tubelets_jsonl": str(output_dir / "tubelets.jsonl"),
                "events_jsonl": str(output_dir / "events.jsonl"),
                "deep_features_live_csv": str(output_dir / "deep_features_live.csv"),
                "live_summary_json": str(output_dir / "live_summary.json"),
                "evidence_dir": str(evidence_dir),
            },
        })
        atomic_json_write(output_dir / "live_summary.json", final_summary)

        print(
            f"[done] frames={frame_i} samples={sample_i + 1} "
            f"tubelets={processed_tubelets} events={anomaly_events}",
            flush=True,
        )
        print(f"[done] output_dir={output_dir}", flush=True)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("[fatal]", repr(e), file=sys.stderr)
        traceback.print_exc()
        raise
