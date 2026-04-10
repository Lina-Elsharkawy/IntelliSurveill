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

import argparse
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set

import cv2
try:
  cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:
    try:
        cv2.setLogLevel(3)
    except Exception:
        pass    
import numpy as np
import torch
import torch.nn as nn
import yaml
from PIL import Image

from camera_source import CameraSource
from kafka_producer import AnomalyEventProducer

try:
    import tensorrt as trt
except ImportError:
    trt = None

try:
    import pycuda.driver as cuda
    import pycuda.autoinit  # noqa: F401  # initializes CUDA context
except ImportError:
    cuda = None


import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "loglevel;quiet"
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
    def __init__(self, d_model):
        # type: (int) -> None
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

    def forward(self, x):
        # type: (torch.Tensor) -> torch.Tensor
        return self.pool(self.net(x)).flatten(1)


class TinyTransformerStudent(nn.Module):
    def __init__(
        self,
        num_frames,
        target_dim,
        d_model=256,
        nhead=4,
        num_layers=4,
        dim_feedforward=512,
        dropout=0.0,
    ):
        # type: (int, int, int, int, int, int, float) -> None
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

    def forward(self, video):
        # type: (torch.Tensor) -> torch.Tensor
        b, t, c, h, w = video.shape
        x   = video.reshape(b * t, c, h, w)
        x   = self.stem(x).view(b, t, self.d_model)
        x   = x + self.pos_embed[:, :t, :]
        cls = self.cls_token.expand(b, -1, -1)
        x   = torch.cat([cls, x], dim=1)
        x   = self.encoder(x)
        return self.head(x[:, 1:, :].mean(dim=1))


def load_student(checkpoint_path, device):
    # type: (str, torch.device) -> Tuple[TinyTransformerStudent, Dict]
    ckpt = torch.load(checkpoint_path, map_location=device)
    if not isinstance(ckpt, dict):
        raise RuntimeError("Student checkpoint must be a dict.")
    if "model_config" not in ckpt or "model_state" not in ckpt:
        raise RuntimeError("Checkpoint missing model_config or model_state.")

    cfg = ckpt["model_config"]
    required = ("num_frames", "target_dim")
    missing = [k for k in required if k not in cfg]
    if missing:
        raise RuntimeError("Checkpoint model_config missing required keys: {}".format(missing))

    num_frames = int(cfg["num_frames"])
    target_dim = int(cfg["target_dim"])
    if num_frames <= 0:
        raise RuntimeError("Invalid num_frames in checkpoint: {}".format(num_frames))
    if target_dim <= 0:
        raise RuntimeError("Invalid target_dim in checkpoint: {}".format(target_dim))

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

def iou_xyxy(a, b):
    # type: (np.ndarray, np.ndarray) -> float
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
    track_id: int
    bbox: np.ndarray
    conf: float
    last_frame_idx: int
    hits: int
    missed: int


class GreedyIoUTracker:
    def __init__(self, iou_threshold=0.3, max_missed=8):
        # type: (float, int) -> None
        self.iou_threshold = iou_threshold
        self.max_missed    = max_missed
        self.next_track_id = 1
        self.tracks = []  # type: List[TrackState]

    def update(self, detections, frame_idx):
        # type: (List[Tuple[np.ndarray, float]], int) -> List[TrackState]
        assigned_tracks = set()  # type: Set[int]
        assigned_dets   = set()  # type: Set[int]

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

    def alive_ids(self):
        # type: () -> Set[int]
        return set([t.track_id for t in self.tracks])


# ---------------------------------------------------------------------------
# Per-track tubelet buffer
# ---------------------------------------------------------------------------

@dataclass
class TrackBuffer:
    track_id: int
    window_frames: int
    window_stride: int
    crop_pad: float = 0.1
    crops: List[Tuple[int, np.ndarray, int]] = field(default_factory=list)
    total_added: int = 0

    def add(self, frame_idx, crop, ts_ms):
        # type: (int, np.ndarray, int) -> None
        self.crops.append((frame_idx, crop, ts_ms))
        self.total_added += 1

    def ready(self):
        # type: () -> bool
        if self.total_added < self.window_frames:
            return False
        return (self.total_added - self.window_frames) % self.window_stride == 0

    def get_window(self):
        # type: () -> Tuple[List[np.ndarray], int, int]
        window   = self.crops[-self.window_frames:]
        frames   = [c for _, c, _ in window]
        start_ts = window[0][2]
        end_ts   = window[-1][2]
        return frames, start_ts, end_ts

    def trim(self):
        # type: () -> None
        if len(self.crops) > self.window_frames:
            self.crops = self.crops[-self.window_frames:]


def clamp_box(box, frame_w, frame_h, pad=0.1):
    # type: (np.ndarray, int, int, float) -> Tuple[int, int, int, int]
    x1, y1, x2, y2 = box.tolist()
    bw = x2 - x1
    bh = y2 - y1
    x1 -= bw * pad
    y1 -= bh * pad
    x2 += bw * pad
    y2 += bh * pad
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
    def __init__(self, cfg):
        # type: (Dict) -> None
        acfg      = cfg["anomaly"]
        self.fgbg = cv2.createBackgroundSubtractorMOG2(
            history       = int(acfg.get("mog2_history", 200)),
            varThreshold  = float(acfg.get("mog2_var_threshold", 30)),
            detectShadows = bool(acfg.get("mog2_detect_shadows", True)),
        )
        self.learning_rate   = float(acfg.get("learning_rate", 0.02))
        self.min_object_area = float(acfg.get("min_object_area", 8000))
        self.downscale_width = int(acfg.get("motion_downscale_width", 640))
        k = int(acfg.get("morph_kernel", 5))
        self._kernel       = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self._dilate_iters = int(acfg.get("dilate_iters", 2))

    def has_motion(self, frame_bgr):
        # type: (np.ndarray) -> bool
        h, w = frame_bgr.shape[:2]
        if w > self.downscale_width:
            scale = float(self.downscale_width) / float(w)
            small = cv2.resize(frame_bgr, (self.downscale_width, int(h * scale)))
        else:
            small = frame_bgr

        mask = self.fgbg.apply(small, learningRate=self.learning_rate)
        mask = (mask == 255).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
        mask = cv2.dilate(mask, self._kernel, iterations=self._dilate_iters)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return any(cv2.contourArea(c) >= self.min_object_area for c in contours)


# ---------------------------------------------------------------------------
# TensorRT YOLOv8 Detector
# ---------------------------------------------------------------------------

class YOLODetector:
    """
    TensorRT YOLOv8 detector using a serialized .engine file.
    Keeps the same predict(...) return shape as the previous detectors
    so the rest of the pipeline remains untouched.
    """
    TRT_LOGGER = None

    def __init__(self, engine_path, conf_threshold=0.35, nms_threshold=0.45):
        # type: (str, float, float) -> None
        if trt is None:
            raise RuntimeError("tensorrt Python package is not installed.")
        if cuda is None:
            raise RuntimeError(
                "pycuda is required for TensorRT inference in Python on this script."
            )

        self.engine_path = engine_path
        self.conf_threshold = float(conf_threshold)
        self.nms_threshold = float(nms_threshold)

        if YOLODetector.TRT_LOGGER is None:
            YOLODetector.TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

        with open(engine_path, "rb") as f, trt.Runtime(YOLODetector.TRT_LOGGER) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError("Failed to deserialize TensorRT engine: {}".format(engine_path))

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Failed to create TensorRT execution context.")

        self.input_binding_idx = None
        self.output_binding_idx = None
        for i in range(self.engine.num_bindings):
            if self.engine.binding_is_input(i):
                self.input_binding_idx = i
            else:
                self.output_binding_idx = i

        if self.input_binding_idx is None or self.output_binding_idx is None:
            raise RuntimeError("Could not find input/output bindings in TensorRT engine.")

        input_shape = tuple(self.engine.get_binding_shape(self.input_binding_idx))
        output_shape = tuple(self.engine.get_binding_shape(self.output_binding_idx))

        if len(input_shape) != 4:
            raise RuntimeError("Unexpected TensorRT input shape: {}".format(input_shape))

        if input_shape[0] == -1:
            # static batch 1 profile for this pipeline
            self.context.set_binding_shape(self.input_binding_idx, (1, input_shape[1], input_shape[2], input_shape[3]))
            input_shape = tuple(self.context.get_binding_shape(self.input_binding_idx))
            output_shape = tuple(self.context.get_binding_shape(self.output_binding_idx))

        self.batch_size = int(input_shape[0])
        self.input_c = int(input_shape[1])
        self.input_h = int(input_shape[2])
        self.input_w = int(input_shape[3])

        if self.batch_size != 1:
            raise RuntimeError("Only batch size 1 is supported, got {}".format(self.batch_size))

        self.input_dtype = trt.nptype(self.engine.get_binding_dtype(self.input_binding_idx))
        self.output_dtype = trt.nptype(self.engine.get_binding_dtype(self.output_binding_idx))

        self.input_shape = tuple(self.context.get_binding_shape(self.input_binding_idx))
        self.output_shape = tuple(self.context.get_binding_shape(self.output_binding_idx))

        self.host_input = cuda.pagelocked_empty(int(trt.volume(self.input_shape)), dtype=self.input_dtype)
        self.host_output = cuda.pagelocked_empty(int(trt.volume(self.output_shape)), dtype=self.output_dtype)
        self.device_input = cuda.mem_alloc(self.host_input.nbytes)
        self.device_output = cuda.mem_alloc(self.host_output.nbytes)
        self.bindings = [0] * self.engine.num_bindings
        self.bindings[self.input_binding_idx] = int(self.device_input)
        self.bindings[self.output_binding_idx] = int(self.device_output)
        self.stream = cuda.Stream()

        log.info(
            "YOLODetector TRT ready: engine={} input_shape={} output_shape={} input_dtype={} output_dtype={}".format(
                engine_path, self.input_shape, self.output_shape, self.input_dtype, self.output_dtype
            )
        )

    def _preprocess(self, frame_bgr):
        # type: (np.ndarray) -> np.ndarray
        resized = cv2.resize(frame_bgr, (self.input_w, self.input_h), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        x = rgb.astype(np.float32) / 255.0
        x = np.transpose(x, (2, 0, 1))
        x = np.expand_dims(x, axis=0)
        return np.ascontiguousarray(x, dtype=self.input_dtype)

    def _infer(self, input_tensor):
        # type: (np.ndarray) -> np.ndarray
        np.copyto(self.host_input, input_tensor.ravel())
        cuda.memcpy_htod_async(self.device_input, self.host_input, self.stream)
        self.context.execute_async_v2(bindings=self.bindings, stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(self.host_output, self.device_output, self.stream)
        self.stream.synchronize()
        return self.host_output.reshape(self.output_shape)

    def predict(self, frame_bgr, classes=None):
        # type: (np.ndarray, Optional[List[int]]) -> List[object]
        orig_h, orig_w = frame_bgr.shape[:2]
        allowed_classes = set(classes) if classes is not None else None

        input_tensor = self._preprocess(frame_bgr)
        output = self._infer(input_tensor)

        # Expected YOLOv8 TensorRT output shape after export/build: (1, 84, 8400)
        if len(output.shape) == 3 and output.shape[0] == 1:
            preds = output[0].T
        elif len(output.shape) == 2:
            preds = output.T
        else:
            raise RuntimeError("Unexpected YOLO TensorRT output shape: {}".format(output.shape))

        boxes = []
        confidences = []

        scale_x = float(orig_w) / float(self.input_w)
        scale_y = float(orig_h) / float(self.input_h)

        for pred in preds:
            if pred.shape[0] < 6:
                continue

            class_scores = pred[4:]
            class_id = int(np.argmax(class_scores))
            confidence = float(class_scores[class_id])

            if confidence < self.conf_threshold:
                continue
            if allowed_classes is not None and class_id not in allowed_classes:
                continue

            cx, cy, bw, bh = pred[:4]
            cx *= scale_x
            cy *= scale_y
            bw *= scale_x
            bh *= scale_y

            x1 = cx - (bw / 2.0)
            y1 = cy - (bh / 2.0)
            x2 = cx + (bw / 2.0)
            y2 = cy + (bh / 2.0)

            x1 = max(0.0, min(float(orig_w - 1), x1))
            y1 = max(0.0, min(float(orig_h - 1), y1))
            x2 = max(0.0, min(float(orig_w - 1), x2))
            y2 = max(0.0, min(float(orig_h - 1), y2))

            if x2 <= x1 or y2 <= y1:
                continue

            boxes.append([x1, y1, x2, y2])
            confidences.append(confidence)

        filtered_boxes = []
        filtered_confidences = []

        if len(boxes) > 0:
            boxes_xywh = [
                [int(round(b[0])), int(round(b[1])),
                 int(round(b[2] - b[0])), int(round(b[3] - b[1]))]
                for b in boxes
            ]
            indices = cv2.dnn.NMSBoxes(
                bboxes=boxes_xywh,
                scores=confidences,
                score_threshold=self.conf_threshold,
                nms_threshold=self.nms_threshold,
            )
            if len(indices) > 0:
                for i in np.array(indices).flatten():
                    filtered_boxes.append(boxes[i])
                    filtered_confidences.append(confidences[i])

        class NumpyWrapper(object):
            def __init__(self, arr):
                self._arr = np.array(arr, dtype=np.float32)

            def cpu(self):
                return self

            def numpy(self):
                return self._arr

            def __len__(self):
                return len(self._arr)

        class BoxesWrapper(object):
            def __init__(self, boxes_xyxy, confs):
                self.xyxy = NumpyWrapper(boxes_xyxy)
                self.conf = NumpyWrapper(confs)

            def __len__(self):
                return len(self.xyxy)

        class Result(object):
            def __init__(self, boxes_xyxy, confs):
                self.boxes = BoxesWrapper(boxes_xyxy, confs)

        return [Result(filtered_boxes, filtered_confidences)]


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def preprocess_crop(crop_bgr, image_size):
    # type: (np.ndarray, int) -> torch.Tensor
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb).resize((image_size, image_size), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    x   = torch.from_numpy(arr).permute(2, 0, 1)
    return (x - IMAGENET_MEAN) / IMAGENET_STD


def crops_to_tensor(crops, image_size, device, use_fp16):
    # type: (List[np.ndarray], int, torch.device, bool) -> torch.Tensor
    tensors = [preprocess_crop(c, image_size) for c in crops]
    video   = torch.stack(tensors, dim=0).unsqueeze(0)
    video   = video.to(device, non_blocking=True)
    if use_fp16 and device.type == "cuda":
        video = video.half()
    return video


# ---------------------------------------------------------------------------
# Evidence upload
# ---------------------------------------------------------------------------

def upload_crops(producer, crops, event_id, camera_id, jpg_quality):
    # type: (AnomalyEventProducer, List[np.ndarray], str, int, int) -> List[str]
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
            log.warning("Crop upload failed (frame {}): {}".format(i, e))
    return refs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts_iso(ts_ms):
    # type: (int) -> str
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def maybe_log_stats(last_ts, every_sec, n_frames, n_motion, n_persons, n_published):
    # type: (float, float, int, int, int, int) -> float
    now = time.time()
    if (now - last_ts) >= every_sec:
        log.info(
            "[stats] frames={} motion_frames={} person_detections={} published={}".format(
                n_frames, n_motion, n_persons, n_published
            )
        )
        return now
    return last_ts


def should_run_detection(frame_idx, has_motion, has_live_tracks, quiet_detection_every_n):
    # type: (int, bool, bool, int) -> bool
    if has_motion or has_live_tracks:
        return True
    if quiet_detection_every_n <= 0:
        return False
    return frame_idx % quiet_detection_every_n == 0


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

def run(cfg):
    # type: (Dict) -> None
    acfg = cfg["anomaly"]
    scfg = cfg["student"]

    device_str = scfg.get("device", "cuda")
    device = torch.device(
        device_str if (device_str != "cuda" or torch.cuda.is_available()) else "cpu"
    )
    use_fp16 = bool(scfg.get("use_fp16", True)) and device.type == "cuda"
    log.info("Device: {}  fp16={}".format(device, use_fp16))

    ckpt_path = scfg["checkpoint"]
    log.info("Loading student: {}".format(ckpt_path))
    student, model_cfg = load_student(ckpt_path, device)
    image_size    = int(model_cfg.get("image_size", 224))
    num_frames    = int(model_cfg["num_frames"])
    model_version = scfg.get("model_version", "student-v3-multiscale")
    log.info(
        "Student ready: num_frames={} image_size={} target_dim={}".format(
            num_frames, image_size, model_cfg["target_dim"]
        )
    )

    log.info("Opening camera...")
    camera  = CameraSource(cfg)
    frame_w = camera.width
    frame_h = camera.height

    motion_detector = MotionDetector(cfg)

    yolo_engine_path = acfg.get("yolo_engine", "/opt/anomaly/models/yolov8n_fp16.engine")
    yolo_conf        = float(acfg.get("yolo_conf", 0.35))
    yolo_nms_thresh  = float(acfg.get("yolo_nms_thresh", 0.45))
    min_bbox_area    = float(acfg.get("min_bbox_area", 1600.0))

    log.info("Loading TensorRT YOLO engine: {}".format(yolo_engine_path))
    yolo = YOLODetector(
        engine_path=yolo_engine_path,
        conf_threshold=yolo_conf,
        nms_threshold=yolo_nms_thresh,
    )

    tracker = GreedyIoUTracker(
        iou_threshold = float(acfg.get("tracker_iou_thresh", 0.3)),
        max_missed    = int(acfg.get("tracker_max_missed", 8)),
    )

    window_frames = num_frames
    window_stride = int(acfg.get("window_stride", 8))
    crop_pad      = float(acfg.get("crop_pad", 0.1))
    track_buffers = {}  # type: Dict[int, TrackBuffer]

    log.info("Preparing Kafka producer (lazy init)...")
    producer = AnomalyEventProducer(cfg)
    log.info("Producer ready (Kafka will connect on first send).")

    device_key  = str(cfg.get("device_key", "jetson_01"))
    camera_id   = int(cfg.get("camera_id", 1))
    jpg_quality = int(acfg.get("jpg_quality", 85))

    cooldown_sec        = float(acfg.get("cooldown_sec", 2.0))
    track_last_publish  = {}  # type: Dict[int, float]

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

            has_motion = motion_detector.has_motion(frame_bgr)
            if has_motion:
                n_motion += 1

            quiet_detection_every_n = int(acfg.get("quiet_detection_every_n", 5))
            run_detection = should_run_detection(
                frame_idx,
                has_motion,
                bool(tracker.tracks),
                quiet_detection_every_n,
            )

            detections = []  # type: List[Tuple[np.ndarray, float]]

            if run_detection:
                results = yolo.predict(frame_bgr, classes=[0])  # COCO class 0 = person
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

            active_tracks = tracker.update(detections, frame_idx)

            for track in active_tracks:
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

                if not buf.ready():
                    continue

                now      = time.time()
                last_pub = track_last_publish.get(track.track_id, 0.0)
                if (now - last_pub) < cooldown_sec:
                    buf.trim()
                    continue

                crops, start_ts, end_ts = buf.get_window()
                buf.trim()

                t_infer = time.time()
                with torch.no_grad():
                    video_tensor = crops_to_tensor(
                        crops, image_size, device, use_fp16
                    )

                    if use_fp16 and device.type == "cuda" and hasattr(torch, "autocast"):
                        with torch.autocast(device_type=device.type, enabled=True):
                            embedding = student(video_tensor)
                    else:
                        embedding = student(video_tensor)

                embedding_list = embedding[0].float().cpu().tolist()
                infer_ms       = int((time.time() - t_infer) * 1000)

                event_id = str(uuid.uuid4())
                t_upload = time.time()
                refs = upload_crops(
                    producer    = producer,
                    crops       = crops,
                    event_id    = event_id,
                    camera_id   = camera_id,
                    jpg_quality = jpg_quality,
                )
                upload_ms = int((time.time() - t_upload) * 1000)

                if len(refs) != window_frames:
                    log.warning(
                        "Track {}: partial upload {}/{}, skipping event".format(
                            track.track_id, len(refs), window_frames
                        )
                    )
                    continue

                event_key = "{}_{}".format(device_key, event_id)
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
                    "Published track={} event={} frames={} infer={}ms upload={}ms".format(
                        track.track_id, event_id, len(refs), infer_ms, upload_ms
                    )
                )

            alive = tracker.alive_ids()
            dead_ids = set(track_buffers.keys()) - alive
            for tid in dead_ids:
                buf = track_buffers.pop(tid, None)
                if buf:
                    log.debug(
                        "Track {} expired with {}/{} crops — discarded.".format(
                            tid, len(buf.crops), window_frames
                        )
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
            "Final stats: frames={} motion={} persons={} published={}".format(
                n_frames, n_motion, n_persons, n_published
            )
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    # type: () -> argparse.Namespace
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    return p.parse_args()


def main():
    # type: () -> None
    args     = parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit("Config not found: {}".format(cfg_path))
    with cfg_path.open() as f:
        cfg = yaml.safe_load(f)
    run(cfg)


if __name__ == "__main__":
    main()