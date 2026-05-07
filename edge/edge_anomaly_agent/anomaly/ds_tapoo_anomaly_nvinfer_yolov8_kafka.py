#!/usr/bin/env python3
"""
Tapoo anomaly pipeline using DeepStream nvinfer YOLOv8 person detection.

NEW script.
Does NOT touch ds_tapoo_anomaly_probe.py.
Does NOT load student model.
Does NOT use PyCUDA.
Sends anomaly_events with embedding=None.

Pipeline:
    Tapoo RTSP
    -> DeepStream decode
    -> nvstreammux
    -> nvinfer YOLOv8 raw tensor
    -> RGBA surface
    -> Python parse person boxes
    -> IoU tracker
    -> 16-frame crop window
    -> evidence upload
    -> Kafka anomaly_events
"""

import sys
import os
import time
import uuid
import yaml
import argparse
import logging
import ctypes
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

import cv2
import numpy as np

try:
    import pyds
except ImportError:
    print("ERROR: pyds is not installed/importable.")
    sys.exit(1)

from kafka_producer import AnomalyEventProducer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("tapoo_anomaly_nvinfer_yolov8")


PERSON_CLASS_ID = 0
INPUT_W = 640
INPUT_H = 640


def make_element(factory, name):
    elem = Gst.ElementFactory.make(factory, name)
    if not elem:
        raise RuntimeError("Could not create element: {} ({})".format(factory, name))
    return elem


def ts_iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()


def iou_xyxy(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])

    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0

    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def nms_xyxy(boxes, scores, iou_thresh):
    if len(boxes) == 0:
        return []

    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]

    keep = []

    while order.size > 0:
        i = int(order[0])
        keep.append(i)

        if order.size == 1:
            break

        rest = order[1:]

        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])

        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h

        union = areas[i] + areas[rest] - inter
        iou = np.where(union > 0, inter / union, 0.0)

        order = rest[iou <= iou_thresh]

    return keep


def clamp_box(box, frame_w, frame_h, pad=0.1):
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


def bbox_to_record(box_np, frame_idx, ts_ms, frame_w, frame_h, conf):
    x1, y1, x2, y2 = [float(x) for x in box_np.tolist()]
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return {
        "frame_idx": int(frame_idx),
        "ts_ms": int(ts_ms),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "w": w,
        "h": h,
        "cx": cx,
        "cy": cy,
        "xyxy": [x1, y1, x2, y2],
        "xywh": [x1, y1, w, h],
        "cx_norm": cx / float(max(1, frame_w)),
        "cy_norm": cy / float(max(1, frame_h)),
        "w_norm": w / float(max(1, frame_w)),
        "h_norm": h / float(max(1, frame_h)),
        "confidence": float(conf),
    }


def compute_motion_stats(bbox_sequence, frame_w, frame_h, expected_frame_step=None):
    """Compute lightweight motion stats for one 16-detection tubelet.

    DeepStream nvinfer uses ``interval=1`` in this deployment, so detections
    normally arrive on frame indices like 545, 547, 549, ... .  The old logic
    counted every jump greater than 1 as a lost frame, which produced false
    values such as gap_count=15/lost_frames=15 for a perfectly continuous
    16-detection window.  This function estimates the expected detector step
    from the bbox sequence and only counts gaps larger than that expected step.
    """
    if not bbox_sequence or len(bbox_sequence) < 2:
        return {
            "max_speed_norm": 0.0,
            "avg_speed_norm": 0.0,
            "max_turn_angle": 0.0,
            "avg_turn_angle": 0.0,
            "turn_angle": 0.0,
            "turn_speed": 0.0,
            "max_turn_speed": 0.0,
            "track_gap_count": 0,
            "gap_count": 0,
            "lost_frames": 0,
            "track_instability": 0,
            "expected_frame_step": int(expected_frame_step or 1),
            "num_boxes": len(bbox_sequence or []),
            "frame_w": int(frame_w),
            "frame_h": int(frame_h),
        }

    raw_frame_gaps = []
    for prev, cur in zip(bbox_sequence[:-1], bbox_sequence[1:]):
        raw_gap = int(cur.get("frame_idx", 0)) - int(prev.get("frame_idx", 0))
        if raw_gap > 0:
            raw_frame_gaps.append(raw_gap)

    if expected_frame_step is None:
        # Use the smallest positive observed step as the normal detector cadence.
        # For nvinfer interval=1 this becomes 2; for interval=0 it becomes 1.
        expected_step = min(raw_frame_gaps) if raw_frame_gaps else 1
    else:
        expected_step = int(expected_frame_step)
    expected_step = max(1, int(expected_step))

    speeds = []
    vectors = []
    gaps = 0
    lost_frames = 0

    for prev, cur in zip(bbox_sequence[:-1], bbox_sequence[1:]):
        frame_gap = max(1, int(cur.get("frame_idx", 0)) - int(prev.get("frame_idx", 0)))
        sample_gap = max(1.0, float(frame_gap) / float(expected_step))

        dx_total = float(cur.get("cx_norm", 0.0)) - float(prev.get("cx_norm", 0.0))
        dy_total = float(cur.get("cy_norm", 0.0)) - float(prev.get("cy_norm", 0.0))
        dx = dx_total / sample_gap
        dy = dy_total / sample_gap
        speed = float((dx * dx + dy * dy) ** 0.5)
        speeds.append(speed)
        vectors.append((dx, dy))

        if frame_gap > expected_step:
            gaps += 1
            lost_frames += int(frame_gap - expected_step)

    turn_angles = []
    turn_speeds = []
    for v1, v2 in zip(vectors[:-1], vectors[1:]):
        n1 = float((v1[0] * v1[0] + v1[1] * v1[1]) ** 0.5)
        n2 = float((v2[0] * v2[0] + v2[1] * v2[1]) ** 0.5)
        if n1 <= 1e-6 or n2 <= 1e-6:
            continue
        dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
        dot = max(-1.0, min(1.0, dot))
        angle = float(np.degrees(np.arccos(dot)))
        turn_angles.append(angle)
        turn_speeds.append(max(n1, n2))

    max_turn_angle = float(max(turn_angles) if turn_angles else 0.0)
    avg_turn_angle = float(sum(turn_angles) / len(turn_angles) if turn_angles else 0.0)
    max_turn_speed = float(max(turn_speeds) if turn_speeds else 0.0)

    return {
        "max_speed_norm": float(max(speeds) if speeds else 0.0),
        "avg_speed_norm": float(sum(speeds) / len(speeds) if speeds else 0.0),
        "max_turn_angle": max_turn_angle,
        "avg_turn_angle": avg_turn_angle,
        "turn_angle": max_turn_angle,
        "turn_speed": max_turn_speed,
        "max_turn_speed": max_turn_speed,
        "track_gap_count": int(gaps),
        "gap_count": int(gaps),
        "lost_frames": int(lost_frames),
        "track_instability": int(lost_frames),
        "expected_frame_step": int(expected_step),
        "raw_frame_gaps": raw_frame_gaps,
        "num_boxes": int(len(bbox_sequence)),
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
    }


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
        self.iou_threshold = float(iou_threshold)
        self.max_missed = int(max_missed)
        self.next_track_id = 1
        self.tracks = []

    def update(self, detections, frame_idx):
        assigned_dets = set()
        assigned_tracks = set()

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
                track.bbox = bbox
                track.conf = conf
                track.last_frame_idx = frame_idx
                track.hits += 1
                track.missed = 0
                assigned_tracks.add(t_idx)
                assigned_dets.add(best_det)

        for t_idx, track in enumerate(self.tracks):
            if t_idx not in assigned_tracks:
                track.missed += 1

        self.tracks = [t for t in self.tracks if t.missed <= self.max_missed]

        for d_idx, (bbox, conf) in enumerate(detections):
            if d_idx in assigned_dets:
                continue

            self.tracks.append(
                TrackState(
                    track_id=self.next_track_id,
                    bbox=bbox,
                    conf=float(conf),
                    last_frame_idx=frame_idx,
                    hits=1,
                    missed=0,
                )
            )
            self.next_track_id += 1

        return self.tracks

    def alive_ids(self):
        return set([t.track_id for t in self.tracks])


@dataclass
class TrackBuffer:
    track_id: int
    window_frames: int
    window_stride: int
    crop_pad: float = 0.1
    crops: List[Tuple[int, np.ndarray, np.ndarray, int, Dict[str, Any]]] = field(default_factory=list)
    total_added: int = 0

    def add(self, frame_idx, person_crop, context_crop, ts_ms, bbox_record):
        self.crops.append((frame_idx, person_crop, context_crop, ts_ms, bbox_record))
        self.total_added += 1

    def ready(self):
        if self.total_added < self.window_frames:
            return False
        return (self.total_added - self.window_frames) % self.window_stride == 0

    def get_window(self):
        window = self.crops[-self.window_frames:]
        person_frames = [person_crop for _, person_crop, _, _, _ in window]
        context_frames = [context_crop for _, _, context_crop, _, _ in window]
        bbox_sequence = [bbox_record for _, _, _, _, bbox_record in window]
        start_ts = window[0][3]
        end_ts = window[-1][3]
        return person_frames, context_frames, bbox_sequence, start_ts, end_ts

    def trim(self):
        if len(self.crops) > self.window_frames:
            self.crops = self.crops[-self.window_frames:]


def upload_crops(producer, crops, event_id, camera_id, jpg_quality, role, frame_index_offset=0):
    refs = []

    for i, crop in enumerate(crops):
        try:
            ref = producer.upload_frame(
                frame_bgr=crop,
                event_id=event_id,
                camera_id=camera_id,
                frame_index=frame_index_offset + i,
                jpg_quality=jpg_quality,
                role=role,
            )
            refs.append(ref)
        except Exception as e:
            log.warning("%s upload failed frame=%s err=%s", role, i, e)

    return refs


def get_layer_array(layer):
    dims = layer.dims

    shape = []
    for i in range(dims.numDims):
        shape.append(int(dims.d[i]))

    if not shape:
        raise RuntimeError("Output tensor has empty shape")

    volume = 1
    for d in shape:
        volume *= int(d)

    ptr = ctypes.cast(pyds.get_ptr(layer.buffer), ctypes.POINTER(ctypes.c_float))
    arr = np.ctypeslib.as_array(ptr, shape=(volume,))
    arr = np.array(arr, copy=True)

    return arr.reshape(shape), shape


def parse_yolov8_persons(output, frame_w, frame_h, conf_thresh, nms_thresh):
    out = output

    if out.ndim == 3 and out.shape[0] == 1:
        out = out[0]

    if out.ndim != 2:
        raise RuntimeError("Unexpected YOLOv8 output ndim/shape: {}".format(output.shape))

    if out.shape[0] == 84:
        preds = out.T
    elif out.shape[1] == 84:
        preds = out
    else:
        raise RuntimeError("Unexpected YOLOv8 output shape: {}".format(output.shape))

    boxes = []
    scores = []

    scale = min(float(INPUT_W) / float(frame_w), float(INPUT_H) / float(frame_h))
    new_w = frame_w * scale
    new_h = frame_h * scale
    pad_x = (INPUT_W - new_w) / 2.0
    pad_y = (INPUT_H - new_h) / 2.0

    for pred in preds:
        person_score = float(pred[4 + PERSON_CLASS_ID])

        if person_score < conf_thresh:
            continue

        cx, cy, bw, bh = [float(v) for v in pred[:4]]

        x1 = (cx - bw / 2.0 - pad_x) / scale
        y1 = (cy - bh / 2.0 - pad_y) / scale
        x2 = (cx + bw / 2.0 - pad_x) / scale
        y2 = (cy + bh / 2.0 - pad_y) / scale

        x1 = max(0.0, min(float(frame_w - 1), x1))
        y1 = max(0.0, min(float(frame_h - 1), y1))
        x2 = max(0.0, min(float(frame_w - 1), x2))
        y2 = max(0.0, min(float(frame_h - 1), y2))

        if x2 <= x1 or y2 <= y1:
            continue

        boxes.append([x1, y1, x2, y2])
        scores.append(person_score)

    keep = nms_xyxy(boxes, scores, nms_thresh)

    detections = []
    for i in keep:
        detections.append(
            (
                np.asarray(boxes[i], dtype=np.float32),
                float(scores[i]),
            )
        )

    return detections


class NvinferYoloAnomalyProcessor:
    def __init__(self, cfg):
        self.cfg = cfg
        self.acfg = cfg["anomaly"]

        self.frame_w = int(cfg["camera"].get("width", 640))
        self.frame_h = int(cfg["camera"].get("height", 480))

        self.device_key = str(cfg.get("device_key", "jetson_01"))
        self.camera_id = int(cfg.get("camera_id", 2))

        self.conf_thresh = float(self.acfg.get("yolo_conf", 0.35))
        self.nms_thresh = float(self.acfg.get("yolo_nms_thresh", 0.45))
        self.min_bbox_area = float(self.acfg.get("min_bbox_area", 1600.0))

        self.tracker = GreedyIoUTracker(
            iou_threshold=float(self.acfg.get("tracker_iou_thresh", 0.3)),
            max_missed=int(self.acfg.get("tracker_max_missed", 8)),
        )

        self.window_frames = int(self.acfg.get("window_frames", self.acfg.get("num_frames", 16)))
        self.window_stride = int(self.acfg.get("window_stride", 8))
        self.crop_pad = float(self.acfg.get("crop_pad", 0.1))
        self.context_pad = float(self.acfg.get("context_pad", 0.75))
        self.cooldown_sec = float(self.acfg.get("cooldown_sec", 2.0))
        self.jpg_quality = int(self.acfg.get("jpg_quality", 85))

        self.track_buffers = {}
        self.track_last_publish = {}

        self.producer = AnomalyEventProducer(cfg)

        self.frame_idx = 0
        self.n_frames = 0
        self.n_tensor_frames = 0
        self.n_persons = 0
        self.n_tracks = 0
        self.n_published = 0
        self.last_print_ts = time.time()
        self.print_every_sec = float(self.acfg.get("print_every_sec", 5.0))
        self.printed_tensor_info = False

        log.warning("Student model permanently disabled in this script. Kafka embeddings are not sent.")
        log.warning("PyCUDA YOLO is not used. Person detection comes from DeepStream nvinfer.")

    def parse_tensor_meta(self, frame_meta):
        l_user = frame_meta.frame_user_meta_list

        while l_user is not None:
            try:
                user_meta = pyds.NvDsUserMeta.cast(l_user.data)
            except StopIteration:
                break

            if user_meta.base_meta.meta_type == pyds.NvDsMetaType.NVDSINFER_TENSOR_OUTPUT_META:
                tensor_meta = pyds.NvDsInferTensorMeta.cast(user_meta.user_meta_data)

                if tensor_meta.num_output_layers < 1:
                    return []

                layer = pyds.get_nvds_LayerInfo(tensor_meta, 0)
                output, shape = get_layer_array(layer)

                if not self.printed_tensor_info:
                    log.info("First tensor layer name=%s shape=%s", layer.layerName, shape)
                    log.info(
                        "Tensor values min=%.6f max=%.6f mean=%.6f",
                        float(np.min(output)),
                        float(np.max(output)),
                        float(np.mean(output)),
                    )
                    self.printed_tensor_info = True

                self.n_tensor_frames += 1

                detections = parse_yolov8_persons(
                    output,
                    self.frame_w,
                    self.frame_h,
                    self.conf_thresh,
                    self.nms_thresh,
                )

                filtered = []
                for box_np, conf in detections:
                    area = max(0.0, box_np[2] - box_np[0]) * max(0.0, box_np[3] - box_np[1])
                    if area < self.min_bbox_area:
                        continue
                    filtered.append((box_np, conf))

                return filtered

            try:
                l_user = l_user.next
            except StopIteration:
                break

        return []

    def process_frame(self, frame_bgr, frame_meta):
        ts_ms = int(time.time() * 1000)

        self.n_frames += 1
        self.frame_idx += 1

        detections = self.parse_tensor_meta(frame_meta)
        self.n_persons += len(detections)

        active_tracks = self.tracker.update(detections, self.frame_idx)
        self.n_tracks = len(active_tracks)

        for track in active_tracks:
            if track.last_frame_idx != self.frame_idx:
                continue

            x1, y1, x2, y2 = clamp_box(track.bbox, self.frame_w, self.frame_h, pad=self.crop_pad)
            crop = frame_bgr[y1:y2, x1:x2]

            cx1, cy1, cx2, cy2 = clamp_box(track.bbox, self.frame_w, self.frame_h, pad=self.context_pad)
            context_crop = frame_bgr[cy1:cy2, cx1:cx2]

            if crop is None or crop.size == 0:
                continue
            if context_crop is None or context_crop.size == 0:
                context_crop = crop

            bbox_record = bbox_to_record(
                track.bbox,
                self.frame_idx,
                ts_ms,
                self.frame_w,
                self.frame_h,
                track.conf,
            )

            if track.track_id not in self.track_buffers:
                self.track_buffers[track.track_id] = TrackBuffer(
                    track_id=track.track_id,
                    window_frames=self.window_frames,
                    window_stride=self.window_stride,
                    crop_pad=self.crop_pad,
                )

            buf = self.track_buffers[track.track_id]
            buf.add(self.frame_idx, crop, context_crop, ts_ms, bbox_record)

            if not buf.ready():
                continue

            now = time.time()
            last_pub = self.track_last_publish.get(track.track_id, 0.0)
            if now - last_pub < self.cooldown_sec:
                buf.trim()
                continue

            person_crops, context_crops, bbox_sequence, start_ts, end_ts = buf.get_window()
            buf.trim()

            event_id = str(uuid.uuid4())

            t_upload = time.time()
            person_refs = upload_crops(
                self.producer,
                person_crops,
                event_id,
                self.camera_id,
                self.jpg_quality,
                role="person",
                frame_index_offset=0,
            )
            context_refs = upload_crops(
                self.producer,
                context_crops,
                event_id,
                self.camera_id,
                self.jpg_quality,
                role="context",
                frame_index_offset=10000,
            )
            upload_ms = int((time.time() - t_upload) * 1000)

            if len(person_refs) != self.window_frames or len(context_refs) != self.window_frames:
                log.warning(
                    "Track %s partial upload person=%s/%s context=%s/%s; skipping event",
                    track.track_id,
                    len(person_refs),
                    self.window_frames,
                    len(context_refs),
                    self.window_frames,
                )
                continue

            representative_frame_ref = context_refs[len(context_refs) // 2]
            motion_stats = compute_motion_stats(bbox_sequence, self.frame_w, self.frame_h)
            event_key = "{}_{}".format(self.device_key, event_id)

            self.producer.send_scene_window_event(
                device_key=self.device_key,
                event_key=event_key,
                camera_id=self.camera_id,
                track_id=track.track_id,
                window_start_ts=ts_iso(start_ts),
                window_end_ts=ts_iso(end_ts),
                person_frames=person_refs,
                context_frames=context_refs,
                representative_frame_ref=representative_frame_ref,
                person_bbox_sequence=bbox_sequence,
                motion_stats=motion_stats,
                processing_time_ms=upload_ms,
                metadata={
                    "event_id": event_id,
                    "device_key": self.device_key,
                    "num_frames": self.window_frames,
                    "image_size": {"width": self.frame_w, "height": self.frame_h},
                    "infer_ms": 0,
                    "upload_ms": upload_ms,
                    "source": "deepstream_tapoo_nvinfer_yolov8",
                    "ds_frame_num": int(frame_meta.frame_num),
                    "scoring_enabled": False,
                    "student_disabled": True,
                    "embedding_is_null": True,
                    "detector": "deepstream-nvinfer-yolov8n",
                    "det_conf": float(track.conf),
                    "bbox_xyxy": [float(x) for x in track.bbox.tolist()],
                    "context_pad": float(self.context_pad),
                    "crop_pad": float(self.crop_pad),
                },
            )

            self.track_last_publish[track.track_id] = now
            self.n_published += 1

            log.info(
                "PUBLISHED anomaly track=%s event=%s person_frames=%s context_frames=%s upload=%sms embeddings=not_sent",
                track.track_id,
                event_id,
                len(person_refs),
                len(context_refs),
                upload_ms,
            )

        alive = self.tracker.alive_ids()
        dead_ids = set(self.track_buffers.keys()) - alive
        for tid in dead_ids:
            self.track_buffers.pop(tid, None)

        self.maybe_print_stats()

    def maybe_print_stats(self):
        now = time.time()
        if now - self.last_print_ts >= self.print_every_sec:
            log.info(
                "[stats] frames=%s tensor_frames=%s persons=%s tracks=%s published=%s",
                self.n_frames,
                self.n_tensor_frames,
                self.n_persons,
                self.n_tracks,
                self.n_published,
            )
            self.last_print_ts = now

    def close(self):
        self.producer.close()


def anomaly_probe(pad, info, processor):
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        return Gst.PadProbeReturn.OK

    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    l_frame = batch_meta.frame_meta_list

    while l_frame is not None:
        try:
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break

        try:
            surface = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
            frame_rgba = np.array(surface, copy=True, order="C")
            frame_bgr = cv2.cvtColor(frame_rgba, cv2.COLOR_RGBA2BGR)

            processor.process_frame(frame_bgr, frame_meta)

        except Exception as e:
            log.exception("Anomaly nvinfer processing failed: %s", e)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


def bus_call(bus, message, loop):
    if message.type == Gst.MessageType.EOS:
        print("End of stream")
        loop.quit()
    elif message.type == Gst.MessageType.ERROR:
        err, debug = message.parse_error()
        print("ERROR:", err)
        print("DEBUG:", debug)
        loop.quit()
    return True


def cb_rtsp_newpad(src, new_pad, decodebin):
    sink_pad = decodebin.get_static_pad("sink")
    if sink_pad.is_linked():
        return

    caps = new_pad.get_current_caps() or new_pad.query_caps()
    if caps:
        structure = caps.get_structure(0)
        name = structure.get_name()
        if "application/x-rtp" not in name:
            return

    ret = new_pad.link(sink_pad)
    if ret != Gst.PadLinkReturn.OK:
        log.error("Failed to link rtspsrc to decodebin: %s", ret)


def cb_decodebin_newpad(decodebin, decoder_src_pad, nvvidconv):
    caps = decoder_src_pad.get_current_caps() or decoder_src_pad.query_caps()
    structure = caps.get_structure(0)
    name = structure.get_name()

    if "video" not in name:
        return

    sink_pad = nvvidconv.get_static_pad("sink")
    if sink_pad.is_linked():
        return

    ret = decoder_src_pad.link(sink_pad)
    if ret != Gst.PadLinkReturn.OK:
        log.error("Failed to link decodebin to nvvideoconvert: %s", ret)


def build_pipeline(cfg, infer_config, processor):
    cam_cfg = cfg["camera"]
    rtsp_url = cam_cfg["rtsp_url"]
    frame_w = int(cam_cfg.get("width", 640))
    frame_h = int(cam_cfg.get("height", 480))
    latency = int(cam_cfg.get("latency", 200))

    pipeline = Gst.Pipeline.new("tapoo-anomaly-nvinfer-yolov8-kafka")

    source = make_element("rtspsrc", "tapoo-rtsp-source")
    source.set_property("location", rtsp_url)
    source.set_property("latency", latency)
    source.set_property("protocols", 4)

    decodebin = make_element("decodebin", "tapoo-decodebin")
    nvvidconv1 = make_element("nvvideoconvert", "tapoo-nvvidconv-before-mux")

    nvmm_caps = make_element("capsfilter", "tapoo-nvmm-caps")
    nvmm_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=NV12,width={},height={}".format(frame_w, frame_h)
        ),
    )

    streammux = make_element("nvstreammux", "stream-muxer")
    streammux.set_property("width", frame_w)
    streammux.set_property("height", frame_h)
    streammux.set_property("batch-size", 1)
    streammux.set_property("batched-push-timeout", 40000)
    streammux.set_property("live-source", 1)
    streammux.set_property("num-surfaces-per-frame", 1)

    pgie = make_element("nvinfer", "primary-yolov8-raw-tensor")
    pgie.set_property("config-file-path", infer_config)

    nvvidconv2 = make_element("nvvideoconvert", "tapoo-nvvidconv-rgba")

    rgba_caps = make_element("capsfilter", "tapoo-rgba-caps")
    rgba_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=RGBA,width={},height={}".format(frame_w, frame_h)
        ),
    )

    sink = make_element("fakesink", "fake-sink")
    sink.set_property("sync", False)
    sink.set_property("async", False)

    for elem in [
        source,
        decodebin,
        nvvidconv1,
        nvmm_caps,
        streammux,
        pgie,
        nvvidconv2,
        rgba_caps,
        sink,
    ]:
        pipeline.add(elem)

    source.connect("pad-added", cb_rtsp_newpad, decodebin)
    decodebin.connect("pad-added", cb_decodebin_newpad, nvvidconv1)

    if not nvvidconv1.link(nvmm_caps):
        raise RuntimeError("nvvidconv1 -> nvmm_caps failed")

    sinkpad = streammux.get_request_pad("sink_0")
    srcpad = nvmm_caps.get_static_pad("src")
    if srcpad.link(sinkpad) != Gst.PadLinkReturn.OK:
        raise RuntimeError("nvmm_caps -> streammux failed")

    if not streammux.link(pgie):
        raise RuntimeError("streammux -> nvinfer failed")

    if not pgie.link(nvvidconv2):
        raise RuntimeError("nvinfer -> nvvidconv2 failed")

    if not nvvidconv2.link(rgba_caps):
        raise RuntimeError("nvvidconv2 -> rgba_caps failed")

    if not rgba_caps.link(sink):
        raise RuntimeError("rgba_caps -> fakesink failed")

    probe_pad = rgba_caps.get_static_pad("src")
    if not probe_pad:
        raise RuntimeError("Could not get rgba_caps src pad")

    probe_pad.add_probe(Gst.PadProbeType.BUFFER, anomaly_probe, processor)

    return pipeline


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="/opt/deepstream_anomaly/config.yaml")
    p.add_argument(
        "--infer-config",
        default="/opt/deepstream_anomaly/config_infer_yolov8n_raw_tensor.txt",
    )
    return p.parse_args()


def main():
    args = parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        raise SystemExit("Config not found: {}".format(cfg_path))

    infer_config = str(Path(args.infer_config))
    if not Path(infer_config).exists():
        raise SystemExit("Infer config not found: {}".format(infer_config))

    with cfg_path.open("r") as f:
        cfg = yaml.safe_load(f)

    Gst.init(None)

    processor = NvinferYoloAnomalyProcessor(cfg)
    pipeline = build_pipeline(cfg, infer_config, processor)

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print("Starting Tapoo anomaly nvinfer YOLOv8 Kafka pipeline...")
    print("Config:", cfg_path)
    print("Infer config:", infer_config)
    print("Detector: DeepStream nvinfer YOLOv8 raw tensor")
    print("Student model: disabled permanently")
    print("Embedding: not sent")
    print("PyCUDA: not used")
    print("Kafka topic:", cfg.get("kafka", {}).get("topic_anomaly", "anomaly_events"))

    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        pipeline.set_state(Gst.State.NULL)
        processor.close()
        print("Stopped.")


if __name__ == "__main__":
    main()