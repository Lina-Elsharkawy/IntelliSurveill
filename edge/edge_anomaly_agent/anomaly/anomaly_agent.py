#!/usr/bin/env python3
"""
Anomaly Agent — runs on the Jetson edge device.

Person-level tubelet pipeline (Option B):
    1. Read frame from CameraSource
    2. Motion detection (MOG2) — skip quiet frames
    3. YOLO person detection — get bounding boxes per frame
    4. IoU Tracker — assign persistent track_id to each person
    5. Per track: accumulate 16 person crops (with stride 8)
    6. When a track has 16 crops → student inference → 2304-d embedding
    7. Upload 16 crops to MinIO via evidence-gateway
    8. Publish Kafka event: embedding + s3 refs + track metadata

The backend receives the Kafka event, fetches frames from MinIO,
runs VideoMAE teacher on them, computes L2(student, teacher),
and decides whether to trigger the reasoning pipeline.

Usage:
    python anomaly_agent.py --config config.yaml
"""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import yaml
from PIL import Image
from ultralytics import YOLO

from camera_source import CameraSource
from kafka_producer import AnomalyEventProducer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("anomaly_agent")

# ---------------------------------------------------------------------------
# Preprocessing constants
# ---------------------------------------------------------------------------

IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
IMAGENET_STD  = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


# ---------------------------------------------------------------------------
# Student model — exact v3 architecture
# ---------------------------------------------------------------------------

class FrameStem(nn.Module):
    def __init__(self, d_model: int) -> None:
        super().__init__()
        c1, c2, c3 = 64, 128, 256
        self.net = nn.Sequential(
            nn.Conv2d(3,  c1, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(c1), nn.GELU(),
            nn.Conv2d(c1, c2, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(c2), nn.GELU(),
            nn.Conv2d(c2, c3, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(c3), nn.GELU(),
            nn.Conv2d(c3, d_model, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(d_model), nn.GELU(),
        )
        self.pool = nn.AdaptiveAvgPool2d((1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool(self.net(x)).flatten(1)


class TinyTransformerStudent(nn.Module):
    def __init__(
        self,
        num_frames:      int,
        target_dim:      int,
        d_model:         int   = 256,
        nhead:           int   = 4,
        num_layers:      int   = 4,
        dim_feedforward: int   = 512,
        dropout:         float = 0.0,
    ) -> None:
        super().__init__()
        self.num_frames = int(num_frames)
        self.d_model    = int(d_model)

        self.stem      = FrameStem(d_model)
        self.pos_embed = nn.Parameter(torch.zeros(1, self.num_frames, d_model))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_model))

        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=nhead,
            dim_feedforward=dim_feedforward, dropout=dropout,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            enc_layer, num_layers=num_layers, norm=nn.LayerNorm(d_model)
        )
        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, target_dim),
        )

    def forward(self, video: torch.Tensor) -> torch.Tensor:
        b, t, c, h, w = video.shape
        x   = video.reshape(b * t, c, h, w)
        x   = self.stem(x).view(b, t, self.d_model)
        x   = x + self.pos_embed[:, :t, :]
        cls = self.cls_token.expand(b, -1, -1)
        x   = torch.cat([cls, x], dim=1)
        x   = self.encoder(x)
        return self.head(x[:, 1:, :].mean(dim=1))


def load_student(
    checkpoint_path: str,
    device: torch.device,
) -> tuple[TinyTransformerStudent, dict]:
    ckpt = torch.load(checkpoint_path, map_location=device)
    if not isinstance(ckpt, dict):
        raise RuntimeError("Student checkpoint must be a dict.")
    if "model_config" not in ckpt or "model_state" not in ckpt:
        raise RuntimeError("Checkpoint missing model_config or model_state.")

    cfg = ckpt["model_config"]
    required = ("num_frames", "target_dim")
    missing = [k for k in required if k not in cfg]
    if missing:
        raise RuntimeError(f"Checkpoint model_config missing required keys: {missing}")

    num_frames = int(cfg["num_frames"])
    target_dim = int(cfg["target_dim"])
    if num_frames <= 0:
        raise RuntimeError(f"Invalid num_frames in checkpoint: {num_frames}")
    if target_dim <= 0:
        raise RuntimeError(f"Invalid target_dim in checkpoint: {target_dim}")

    model = TinyTransformerStudent(
        num_frames      = num_frames,
        target_dim      = target_dim,
        d_model         = int(cfg.get("d_model", 256)),
        nhead           = int(cfg.get("nhead", 4)),
        num_layers      = int(cfg.get("num_layers", 4)),
        dim_feedforward = int(cfg.get("dim_feedforward", 512)),
        dropout         = 0.0,
    ).to(device)
    model.load_state_dict(ckpt["model_state"], strict=True)
    model.eval()
    return model, cfg



# ---------------------------------------------------------------------------
# IoU Tracker
# ---------------------------------------------------------------------------

def iou_xyxy(a: np.ndarray, b: np.ndarray) -> float:
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union  = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class TrackState:
    track_id:       int
    bbox:           np.ndarray
    conf:           float
    last_frame_idx: int
    hits:           int
    missed:         int


class GreedyIoUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_missed: int = 8) -> None:
        self.iou_threshold = iou_threshold
        self.max_missed    = max_missed
        self.next_track_id = 1
        self.tracks: list[TrackState] = []

    def update(
        self,
        detections: list[tuple[np.ndarray, float]],
        frame_idx:  int,
    ) -> list[TrackState]:
        assigned_tracks: set[int] = set()
        assigned_dets:   set[int] = set()

        for t_idx, track in enumerate(self.tracks):
            best_det = None
            best_iou = 0.0
            for d_idx, (bbox, conf) in enumerate(detections):
                if d_idx in assigned_dets:
                    continue
                score = iou_xyxy(track.bbox, bbox)
                if score > best_iou:
                    best_iou = score
                    best_det = d_idx
            if best_det is not None and best_iou >= self.iou_threshold:
                bbox, conf = detections[best_det]
                track.bbox           = bbox
                track.conf           = conf
                track.last_frame_idx = frame_idx
                track.hits          += 1
                track.missed         = 0
                assigned_tracks.add(t_idx)
                assigned_dets.add(best_det)

        for t_idx, track in enumerate(self.tracks):
            if t_idx not in assigned_tracks:
                track.missed += 1

        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]

        for d_idx, (bbox, conf) in enumerate(detections):
            if d_idx in assigned_dets:
                continue
            self.tracks.append(TrackState(
                track_id       = self.next_track_id,
                bbox           = bbox,
                conf           = conf,
                last_frame_idx = frame_idx,
                hits           = 1,
                missed         = 0,
            ))
            self.next_track_id += 1

        return self.tracks

    def alive_ids(self) -> set[int]:
        """Return set of all track IDs currently alive (not yet expired)."""
        return {t.track_id for t in self.tracks}


# ---------------------------------------------------------------------------
# Per-track tubelet buffer
# ---------------------------------------------------------------------------

@dataclass
class TrackBuffer:
    """Accumulates person crops for one track."""
    track_id:      int
    window_frames: int
    window_stride: int
    crop_pad:      float = 0.1

    # Each entry: (frame_idx, crop_bgr, ts_ms)
    crops:       list[tuple[int, np.ndarray, int]] = field(default_factory=list)
    total_added: int = 0

    def add(self, frame_idx: int, crop: np.ndarray, ts_ms: int) -> None:
        self.crops.append((frame_idx, crop, ts_ms))
        self.total_added += 1

    def ready(self) -> bool:
        """
        True when a complete window is ready to publish.

        FIX: original used total_added % window_stride == 0 which fired
        at frame 8 before 16 crops were accumulated. Correct formula:
        first window fires exactly at total_added == window_frames,
        then every window_stride crops after that.
        """
        if self.total_added < self.window_frames:
            return False
        return (self.total_added - self.window_frames) % self.window_stride == 0

    def get_window(self) -> tuple[list[np.ndarray], int, int]:
        """Return the last window_frames crops with their timestamps."""
        window   = self.crops[-self.window_frames:]
        frames   = [c for _, c, _ in window]
        start_ts = window[0][2]
        end_ts   = window[-1][2]
        return frames, start_ts, end_ts

    def trim(self) -> None:
        """Keep only the last window_frames crops to bound memory."""
        if len(self.crops) > self.window_frames:
            self.crops = self.crops[-self.window_frames:]


def clamp_box(
    box:     np.ndarray,
    frame_w: int,
    frame_h: int,
    pad:     float = 0.1,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box.tolist()
    bw = x2 - x1; bh = y2 - y1
    x1 -= bw * pad; y1 -= bh * pad
    x2 += bw * pad; y2 += bh * pad
    return (
        max(0, int(round(x1))),
        max(0, int(round(y1))),
        min(frame_w, int(round(x2))),
        min(frame_h, int(round(y2))),
    )


# ---------------------------------------------------------------------------
# Motion detector
# ---------------------------------------------------------------------------

class MotionDetector:
    def __init__(self, cfg: dict) -> None:
        acfg      = cfg["anomaly"]
        self.fgbg = cv2.createBackgroundSubtractorMOG2(
            history       = int(acfg.get("mog2_history",        200)),
            varThreshold  = float(acfg.get("mog2_var_threshold", 30)),
            detectShadows = bool(acfg.get("mog2_detect_shadows", True)),
        )
        self.learning_rate   = float(acfg.get("learning_rate",        0.02))
        self.min_object_area = float(acfg.get("min_object_area",      8000))
        self.downscale_width = int(acfg.get("motion_downscale_width", 640))
        k = int(acfg.get("morph_kernel", 5))
        self._kernel       = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self._dilate_iters = int(acfg.get("dilate_iters", 2))

    def has_motion(self, frame_bgr: np.ndarray) -> bool:
        h, w = frame_bgr.shape[:2]
        if w > self.downscale_width:
            scale = self.downscale_width / w
            small = cv2.resize(frame_bgr, (self.downscale_width, int(h * scale)))
        else:
            small = frame_bgr

        mask = self.fgbg.apply(small, learningRate=self.learning_rate)
        mask = (mask == 255).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  self._kernel)
        mask = cv2.dilate(mask, self._kernel, iterations=self._dilate_iters)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return any(cv2.contourArea(c) >= self.min_object_area for c in contours)


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def preprocess_crop(crop_bgr: np.ndarray, image_size: int) -> torch.Tensor:
    """BGR crop → normalized float tensor [C, H, W]."""
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb).resize((image_size, image_size), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    x   = torch.from_numpy(arr).permute(2, 0, 1)
    return (x - IMAGENET_MEAN) / IMAGENET_STD


def crops_to_tensor(
    crops:      list[np.ndarray],
    image_size: int,
    device:     torch.device,
    use_fp16:   bool,
) -> torch.Tensor:
    """List of BGR crops → [1, T, C, H, W] on device."""
    tensors = [preprocess_crop(c, image_size) for c in crops]
    video   = torch.stack(tensors, dim=0).unsqueeze(0)
    video   = video.to(device, non_blocking=True)
    if use_fp16 and device.type == "cuda":
        video = video.half()
    return video


# ---------------------------------------------------------------------------
# Evidence upload
# ---------------------------------------------------------------------------

def upload_crops(
    producer:    AnomalyEventProducer,
    crops:       list[np.ndarray],
    event_id:    str,
    camera_id:   int,
    jpg_quality: int,
) -> list[str]:
    """Upload person crops to MinIO. Returns list of s3:// refs."""
    refs = []
    for i, crop in enumerate(crops):
        try:
            ref = producer.upload_frame(
                frame_bgr   = crop,
                event_id    = event_id,
                camera_id   = camera_id,
                frame_index = i,
                jpg_quality = jpg_quality,
            )
            refs.append(ref)
        except Exception as e:
            log.warning(f"Crop upload failed (frame {i}): {e}")
    return refs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts_iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()


def maybe_log_stats(
    last_ts:     float,
    every_sec:   float,
    n_frames:    int,
    n_motion:    int,
    n_persons:   int,
    n_published: int,
) -> float:
    now = time.time()
    if (now - last_ts) >= every_sec:
        log.info(
            f"[stats] frames={n_frames} motion_frames={n_motion} "
            f"person_detections={n_persons} published={n_published}"
        )
        return now
    return last_ts



def should_run_detection(
    *,
    frame_idx: int,
    has_motion: bool,
    has_live_tracks: bool,
    quiet_detection_every_n: int,
) -> bool:
    if has_motion or has_live_tracks:
        return True
    if quiet_detection_every_n <= 0:
        return False
    return frame_idx % quiet_detection_every_n == 0


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def run(cfg: dict) -> None:
    acfg = cfg["anomaly"]
    scfg = cfg["student"]

    # --- Device ---
    device_str = scfg.get("device", "cuda")
    device     = torch.device(
        device_str
        if (device_str != "cuda" or torch.cuda.is_available())
        else "cpu"
    )
    use_fp16 = bool(scfg.get("use_fp16", True)) and device.type == "cuda"
    log.info(f"Device: {device}  fp16={use_fp16}")

    # --- Student model ---
    ckpt_path = scfg["checkpoint"]
    log.info(f"Loading student: {ckpt_path}")
    student, model_cfg = load_student(ckpt_path, device)
    image_size    = int(model_cfg.get("image_size", 224))
    num_frames    = int(model_cfg["num_frames"])
    model_version = scfg.get("model_version", "student-v3-multiscale")
    log.info(
        f"Student ready: num_frames={num_frames} "
        f"image_size={image_size} "
        f"target_dim={model_cfg['target_dim']}"
    )

    # --- Camera ---
    log.info("Opening camera...")
    camera  = CameraSource(cfg)
    frame_w = camera.width
    frame_h = camera.height

    # --- Motion detector ---
    motion_detector = MotionDetector(cfg)

    # --- YOLO person detector ---
    yolo_model_path = acfg.get("yolo_model", "yolov8n.pt")
    yolo_conf       = float(acfg.get("yolo_conf",    0.35))
    min_bbox_area   = float(acfg.get("min_bbox_area", 1600.0))
    yolo_device     = "0" if device.type == "cuda" else "cpu"
    log.info(f"Loading YOLO: {yolo_model_path}")
    yolo = YOLO(yolo_model_path)

    # --- Tracker ---
    tracker = GreedyIoUTracker(
        iou_threshold = float(acfg.get("tracker_iou_thresh", 0.3)),
        max_missed    = int(acfg.get("tracker_max_missed",   8)),
    )

    # --- Per-track buffers ---
    window_frames = num_frames
    window_stride = int(acfg.get("window_stride", 8))
    crop_pad      = float(acfg.get("crop_pad", 0.1))
    track_buffers: dict[int, TrackBuffer] = {}

    # --- Kafka producer ---
    log.info("Connecting to Kafka...")
    producer    = AnomalyEventProducer(cfg)
    device_key  = str(cfg.get("device_key", "jetson_01"))
    camera_id   = int(cfg.get("camera_id", 1))
    jpg_quality = int(acfg.get("jpg_quality", 85))

    # --- Cooldown per track ---
    cooldown_sec        = float(acfg.get("cooldown_sec", 2.0))
    track_last_publish: dict[int, float] = {}

    # --- Stats ---
    print_every_sec = float(acfg.get("print_every_sec", 5.0))
    last_print_ts   = time.time()
    n_frames        = 0
    n_motion        = 0
    n_persons       = 0
    n_published     = 0
    frame_idx       = 0

    log.info("Anomaly agent running. Press Ctrl+C to stop.")

    try:
        for frame_bgr, ts_ms in camera.frames():
            n_frames  += 1
            frame_idx += 1

            # ----------------------------------------------------------
            # Step 1: Motion detection
            # ----------------------------------------------------------
            has_motion = motion_detector.has_motion(frame_bgr)
            if has_motion:
                n_motion += 1

            quiet_detection_every_n = int(acfg.get("quiet_detection_every_n", 5))
            run_detection = should_run_detection(
                frame_idx=frame_idx,
                has_motion=has_motion,
                has_live_tracks=bool(tracker.tracks),
                quiet_detection_every_n=quiet_detection_every_n,
            )

            detections: list[tuple[np.ndarray, float]] = []

            # ----------------------------------------------------------
            # Step 2: YOLO person detection
            # ----------------------------------------------------------
            if run_detection:
                results = yolo.predict(
                    frame_bgr, verbose=False, classes=[0],
                    conf=yolo_conf, device=yolo_device,
                )
            else:
                results = []


            if results and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                confs = results[0].boxes.conf.cpu().numpy()
                for box, conf in zip(boxes, confs):
                    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
                    if area < min_bbox_area:
                        continue
                    detections.append((box.astype(np.float32), float(conf)))
                    n_persons += 1

            # ----------------------------------------------------------
            # Step 3: Update tracker
            # ----------------------------------------------------------
            active_tracks = tracker.update(detections, frame_idx)

            # ----------------------------------------------------------
            # Step 4: Crop and buffer per track detected this frame
            # ----------------------------------------------------------
            for track in active_tracks:
                # Only crop for tracks detected in this exact frame
                if track.last_frame_idx != frame_idx:
                    continue

                x1, y1, x2, y2 = clamp_box(
                    track.bbox, frame_w, frame_h, pad=crop_pad
                )
                crop = frame_bgr[y1:y2, x1:x2]
                if crop.size == 0:
                    continue

                if track.track_id not in track_buffers:
                    track_buffers[track.track_id] = TrackBuffer(
                        track_id      = track.track_id,
                        window_frames = window_frames,
                        window_stride = window_stride,
                        crop_pad      = crop_pad,
                    )

                buf = track_buffers[track.track_id]
                buf.add(frame_idx, crop, ts_ms)

                # --------------------------------------------------
                # Step 5: Check if window is ready for this track
                # --------------------------------------------------
                if not buf.ready():
                    continue

                # Cooldown check per track
                now      = time.time()
                last_pub = track_last_publish.get(track.track_id, 0.0)
                if (now - last_pub) < cooldown_sec:
                    buf.trim()
                    continue

                crops, start_ts, end_ts = buf.get_window()
                buf.trim()

                # --------------------------------------------------
                # Step 6: Student inference
                # --------------------------------------------------
                t_infer = time.time()
                with torch.no_grad():
                    video_tensor = crops_to_tensor(
                        crops, image_size, device, use_fp16
                    )
                    with torch.autocast(
                        device_type = device.type,
                        enabled     = (use_fp16 and device.type == "cuda"),
                    ):
                        embedding = student(video_tensor)   # [1, 2304]

                embedding_list = embedding[0].float().cpu().tolist()
                infer_ms       = int((time.time() - t_infer) * 1000)

                # --------------------------------------------------
                # Step 7: Upload crops to MinIO
                # --------------------------------------------------
                event_id  = str(uuid.uuid4())
                t_upload  = time.time()
                refs      = upload_crops(
                    producer    = producer,
                    crops       = crops,
                    event_id    = event_id,
                    camera_id   = camera_id,
                    jpg_quality = jpg_quality,
                )
                upload_ms = int((time.time() - t_upload) * 1000)

                if not refs:
                    log.warning(
                        f"Track {track.track_id}: no crops uploaded, skipping."
                    )
                    continue

                # --------------------------------------------------
                # Step 8: Publish Kafka event
                # --------------------------------------------------
                event_key = f"{device_key}_{event_id}"
                producer.send_scene_window_event(
                    device_key         = device_key,
                    event_key          = event_key,
                    camera_id          = camera_id,
                    track_id           = track.track_id,
                    window_start_ts    = ts_iso(start_ts),
                    window_end_ts      = ts_iso(end_ts),
                    embedding          = embedding_list,
                    embedding_model    = model_version,
                    frames             = refs,
                    processing_time_ms = infer_ms + upload_ms,
                    extra={
                        "event_id":   event_id,
                        "device_key": device_key,
                        "num_frames": window_frames,
                        "image_size": image_size,
                        "infer_ms":   infer_ms,
                        "upload_ms":  upload_ms,
                    },
                )

                track_last_publish[track.track_id] = now
                n_published += 1

                log.info(
                    f"Published track={track.track_id} "
                    f"event={event_id} "
                    f"frames={len(refs)} "
                    f"infer={infer_ms}ms upload={upload_ms}ms"
                )

            # ----------------------------------------------------------
            # FIX: Dead track cleanup — use tracker.alive_ids() not
            # per-frame active detections. A track is dead only when
            # the tracker has removed it (missed > max_missed), not
            # just because it wasn't detected this frame.
            # ----------------------------------------------------------
            alive = tracker.alive_ids()
            dead_ids = set(track_buffers.keys()) - alive
            for tid in dead_ids:
                buf = track_buffers.pop(tid, None)
                if buf:
                    log.debug(
                        f"Track {tid} expired with "
                        f"{len(buf.crops)}/{window_frames} crops — discarded."
                    )

            last_print_ts = maybe_log_stats(
                last_print_ts, print_every_sec,
                n_frames, n_motion, n_persons, n_published,
            )

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        log.info("Shutting down...")
        camera.release()
        producer.close()
        log.info(
            f"Final stats: frames={n_frames} motion={n_motion} "
            f"persons={n_persons} published={n_published}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    return p.parse_args()


def main() -> None:
    args     = parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit(f"Config not found: {cfg_path}")
    with cfg_path.open() as f:
        cfg = yaml.safe_load(f)
    run(cfg)


if __name__ == "__main__":
    main()