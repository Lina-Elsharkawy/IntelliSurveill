#!/usr/bin/env python3
"""
DeepStream hybrid TRT face pipeline + Kafka publishing.

What this does:
- Keeps the working hybrid DeepStream path:
    camera -> NVMM -> nvstreammux -> RGBA surface -> Python TensorRTFacePipeline
    -> NvDsObjectMeta -> nvtracker -> fakesink

- Adds Kafka publishing for face recognition events:
    detected face + embedding + evidence image -> Kafka topic "face_events"

Why this exists:
- Native DeepStream nvinfer/SCRFD parsing was not reliable.
- Your existing /opt/face_app TensorRTFacePipeline already detects/recognizes faces.
- The backend consumer expects face_events with:
    event_id, camera_id, embedding, event_type, image_video_ref/evidence_ref,
    processing_time_ms, model_version, quality_score, ts/ts_ms

Notes:
- This is NOT full zero-copy because pyds.get_nvds_buf_surface(...)->np.array(copy=True)
  copies a DeepStream surface into a NumPy/OpenCV frame for the existing TRT pipeline.
- DeepStream still handles camera ingest, NVMM conversion, streammux, metadata, and tracker.
"""

import os
import sys
import time
import uuid
import json
import base64
import signal
import logging
from typing import Optional, Tuple, List, Dict, Any

import gi
import cv2
import yaml
import numpy as np
import requests
from kafka import KafkaProducer

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

try:
    import pyds
except ImportError:
    print("ERROR: pyds is not installed/importable.")
    sys.exit(1)

# Reuse the existing working face pipeline
sys.path.insert(0, "/opt/face_app")
from face.face_recognition_trt import TensorRTFacePipeline


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
LOG = logging.getLogger("ds_hybrid_trt_face_kafka")


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

CONFIG_PATH = os.getenv("FACE_CONFIG_PATH", "/opt/face_app/config.yaml")

TRACKER_LIB = os.getenv(
    "DS_TRACKER_LIB",
    "/opt/nvidia/deepstream/deepstream-6.0/lib/libnvds_nvmultiobjecttracker.so",
)
TRACKER_CONFIG = os.getenv(
    "DS_TRACKER_CONFIG",
    "/opt/nvidia/deepstream/deepstream-6.0/samples/configs/deepstream-app/config_tracker_NvDCF_perf.yml",
)

FRAME_W = int(os.getenv("DS_FRAME_W", "640"))
FRAME_H = int(os.getenv("DS_FRAME_H", "480"))
FPS = int(os.getenv("DS_FPS", "30"))
DEVICE = os.getenv("DS_CAMERA_DEVICE", "/dev/video0")

# Start with 1 for debugging. Raise to 2 or 3 later if performance needs help.
INFER_EVERY_N_FRAMES = int(os.getenv("INFER_EVERY_N_FRAMES", "1"))

# Kafka / backend-facing event configuration
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
KAFKA_TOPIC = os.getenv("KAFKA_FACE_TOPIC", "face_events")
EVIDENCE_GATEWAY_UPLOAD = os.getenv(
    "EVIDENCE_GATEWAY_UPLOAD",
    "http://evidence-gateway:8010/evidence/upload",
)

CAMERA_ID = os.getenv("CAMERA_ID", "1")
MODEL_VERSION = os.getenv("FACE_MODEL_VERSION", "deepstream-hybrid-trt-face-v1")

# Deduplication to avoid publishing the same face every frame.
PUBLISH_DEDUP_TTL_SEC = float(os.getenv("PUBLISH_DEDUP_TTL_SEC", "3.0"))
PUBLISH_DEDUP_SIM_THRESHOLD = float(os.getenv("PUBLISH_DEDUP_SIM_THRESHOLD", "0.72"))
PUBLISH_MIN_FACE_SCORE = float(os.getenv("PUBLISH_MIN_FACE_SCORE", "0.35"))
PUBLISH_MIN_FACE_SIZE = int(os.getenv("PUBLISH_MIN_FACE_SIZE", "30"))

# If 1, try to upload evidence on the edge before Kafka.
# If upload fails, the event is still sent with face_jpeg_b64 so the backend consumer can upload it.
UPLOAD_EVIDENCE_BEFORE_KAFKA = os.getenv("UPLOAD_EVIDENCE_BEFORE_KAFKA", "1").strip() not in ("0", "false", "False", "no", "NO")

# Frontend streaming via MediaMTX.
# Jetson sends MPEG-TS/H264 over UDP to the laptop/backend host.
ENABLE_FRONTEND_STREAM = os.getenv("ENABLE_FRONTEND_STREAM", "1").strip().lower() in ("1", "true", "yes", "on")
STREAM_HOST = os.getenv("STREAM_HOST", "172.21.0.239")
STREAM_PORT = int(os.getenv("STREAM_PORT", "8000"))
STREAM_BITRATE = int(os.getenv("STREAM_BITRATE", "2000000"))


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def load_cfg(path=CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_element(factory: str, name: str):
    element = Gst.ElementFactory.make(factory, name)
    if not element:
        raise RuntimeError("Could not create element: {} ({})".format(factory, name))
    return element


def set_property_if_supported(element, prop_name: str, value) -> None:
    try:
        element.set_property(prop_name, value)
    except Exception as e:
        LOG.warning("Could not set %s on %s: %s", prop_name, element.get_name(), e)


def coerce_camera_id(raw_value) -> int:
    try:
        return int(raw_value)
    except Exception:
        s = str(raw_value or "").strip()
        digits = "".join(ch for ch in s if ch.isdigit())
        return int(digits) if digits else 0


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if n <= 1e-8:
        return v
    return v / n


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    a = l2_normalize(a)
    b = l2_normalize(b)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return -1.0
    return float(np.dot(a, b))


def clamp_bbox_xyxy(bbox: List[float]) -> Tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox

    x1 = max(0.0, min(float(FRAME_W - 1), float(x1)))
    y1 = max(0.0, min(float(FRAME_H - 1), float(y1)))
    x2 = max(0.0, min(float(FRAME_W - 1), float(x2)))
    y2 = max(0.0, min(float(FRAME_H - 1), float(y2)))

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    return x1, y1, x2, y2


def crop_face_jpeg_b64(frame_bgr: np.ndarray, bbox: List[float], pad_ratio: float = 0.20) -> Optional[str]:
    if frame_bgr is None or frame_bgr.size == 0:
        return None

    x1, y1, x2, y2 = clamp_bbox_xyxy(bbox)
    w = x2 - x1
    h = y2 - y1
    if w < PUBLISH_MIN_FACE_SIZE or h < PUBLISH_MIN_FACE_SIZE:
        return None

    pad_x = w * pad_ratio
    pad_y = h * pad_ratio

    cx1 = int(max(0, x1 - pad_x))
    cy1 = int(max(0, y1 - pad_y))
    cx2 = int(min(frame_bgr.shape[1] - 1, x2 + pad_x))
    cy2 = int(min(frame_bgr.shape[0] - 1, y2 + pad_y))

    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop is None or crop.size == 0:
        return None

    ok, enc = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None

    return base64.b64encode(enc.tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
# Face dict extraction helpers
# ---------------------------------------------------------------------------

def extract_bbox(face) -> Optional[List[float]]:
    """
    Your TensorRTFacePipeline has previously returned bbox_xyxy.
    This helper also supports common alternative key names.
    """
    for key in ("bbox_xyxy", "bbox", "det", "box"):
        if isinstance(face, dict) and key in face and face[key] is not None:
            b = np.asarray(face[key], dtype=np.float32).reshape(-1)
            if b.size >= 4:
                x1, y1, x2, y2 = b[:4]
                return [float(x1), float(y1), float(x2), float(y2)]

    if isinstance(face, dict) and all(k in face for k in ("x1", "y1", "x2", "y2")):
        return [
            float(face["x1"]),
            float(face["y1"]),
            float(face["x2"]),
            float(face["y2"]),
        ]

    return None


def extract_score(face) -> float:
    for key in ("score", "det_score", "confidence", "conf"):
        if isinstance(face, dict) and key in face:
            try:
                return float(face[key])
            except Exception:
                pass
    return 0.99


def extract_embedding(face) -> Optional[List[float]]:
    """
    Supports likely keys returned by face recognition pipelines.
    If your pipeline uses a different key, add it here.
    """
    for key in (
        "embedding",
        "emb",
        "face_embedding",
        "recognition_embedding",
        "arcface_embedding",
        "feat",
        "feature",
        "features",
    ):
        if isinstance(face, dict) and key in face and face[key] is not None:
            arr = np.asarray(face[key], dtype=np.float32).reshape(-1)
            if arr.size > 0:
                return [float(x) for x in arr.tolist()]

    return None


# ---------------------------------------------------------------------------
# Kafka event producer
# ---------------------------------------------------------------------------

class FaceKafkaPublisher:
    def __init__(self, cfg: dict):
        kcfg = cfg.get("kafka", {}) if isinstance(cfg, dict) else {}

        bootstrap = (
            KAFKA_BOOTSTRAP
            or kcfg.get("bootstrap_servers")
            or kcfg.get("bootstrap")
            or "localhost:9092"
        )

        self.topic = KAFKA_TOPIC or kcfg.get("topic", "face_events")
        self.camera_id = coerce_camera_id(
            os.getenv("CAMERA_ID")
            or cfg.get("camera_id")
            or cfg.get("camera", {}).get("id")
            or 1
        )

        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap,
            acks="all",
            retries=10,
            linger_ms=10,
            compression_type=None,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: str(k).encode("utf-8"),
            max_request_size=5_000_000,
        )

        LOG.info("Kafka publisher ready: bootstrap=%s topic=%s camera_id=%s", bootstrap, self.topic, self.camera_id)

    def upload_evidence(self, *, event_id: str, face_jpeg_b64: str) -> Optional[str]:
        if not UPLOAD_EVIDENCE_BEFORE_KAFKA:
            return None

        try:
            jpg_bytes = base64.b64decode(face_jpeg_b64, validate=True)
        except Exception as e:
            LOG.warning("Could not decode face_jpeg_b64 event_id=%s err=%s", event_id, e)
            return None

        files = {"file": (f"{event_id}.jpg", jpg_bytes, "image/jpeg")}
        data = {
            "event_id": event_id,
            "camera_id": str(self.camera_id),
            "kind": "face",
            "ext": "jpg",
        }

        try:
            r = requests.post(EVIDENCE_GATEWAY_UPLOAD, files=files, data=data, timeout=5)
            if r.status_code != 200:
                LOG.warning(
                    "Evidence upload failed event_id=%s status=%s text=%s",
                    event_id, r.status_code, r.text[:300],
                )
                return None

            evidence_ref = r.json().get("evidence_ref")
            return evidence_ref
        except Exception as e:
            LOG.warning("Evidence upload exception event_id=%s err=%s", event_id, e)
            return None

    def send_face_event(
        self,
        *,
        embedding: List[float],
        bbox: List[float],
        score: float,
        face_jpeg_b64: Optional[str],
        processing_time_ms: int,
        frame_num: int,
    ) -> None:
        event_id = str(uuid.uuid4())
        ts_ms = int(time.time() * 1000)

        event: Dict[str, Any] = {
            "event_id": event_id,
            "camera_id": self.camera_id,
            "embedding": [float(x) for x in embedding],
            "event_type": "face_detected",
            "processing_time_ms": int(processing_time_ms),
            "model_version": MODEL_VERSION,
            "quality_score": float(score),
            "ts_ms": ts_ms,
            "bbox_xyxy": [float(x) for x in bbox],
            "metadata": {
                "source": "deepstream_hybrid_trt",
                "frame_num": int(frame_num),
                "device": DEVICE,
                "frame_w": FRAME_W,
                "frame_h": FRAME_H,
            },
        }

        if face_jpeg_b64:
            evidence_ref = self.upload_evidence(event_id=event_id, face_jpeg_b64=face_jpeg_b64)
            if evidence_ref:
                event["evidence_ref"] = evidence_ref
                event["image_video_ref"] = evidence_ref
            else:
                # Backend consumer can upload this if it has access to evidence-gateway.
                event["face_jpeg_b64"] = face_jpeg_b64

        key = event_id
        self.producer.send(self.topic, key=key, value=event)
        LOG.info(
            "KAFKA sent face_event event_id=%s camera=%s emb_dim=%s score=%.3f evidence=%s b64=%s",
            event_id,
            self.camera_id,
            len(embedding),
            score,
            event.get("evidence_ref"),
            "yes" if event.get("face_jpeg_b64") else "no",
        )

    def flush(self):
        try:
            self.producer.flush(timeout=5)
        except Exception:
            LOG.exception("Kafka flush failed")

    def close(self):
        try:
            self.flush()
        finally:
            try:
                self.producer.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# DeepStream metadata injection
# ---------------------------------------------------------------------------

def add_face_obj_meta(batch_meta, frame_meta, bbox, score) -> bool:
    x1, y1, x2, y2 = clamp_bbox_xyxy(bbox)

    w = max(1.0, x2 - x1)
    h = max(1.0, y2 - y1)

    # Skip tiny invalid boxes
    if w < 10 or h < 10:
        return False

    obj_meta = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)

    obj_meta.unique_component_id = 1
    obj_meta.class_id = 0
    obj_meta.confidence = float(score)
    obj_meta.obj_label = "face"

    obj_meta.rect_params.left = float(x1)
    obj_meta.rect_params.top = float(y1)
    obj_meta.rect_params.width = float(w)
    obj_meta.rect_params.height = float(h)

    obj_meta.rect_params.border_width = 2
    obj_meta.rect_params.border_color.set(0.0, 1.0, 0.0, 1.0)
    obj_meta.rect_params.has_bg_color = 0

    obj_meta.text_params.display_text = "face {:.2f}".format(float(score))
    obj_meta.text_params.x_offset = int(x1)
    obj_meta.text_params.y_offset = max(0, int(y1) - 10)
    obj_meta.text_params.font_params.font_name = "Serif"
    obj_meta.text_params.font_params.font_size = 10
    obj_meta.text_params.font_params.font_color.set(1.0, 1.0, 1.0, 1.0)
    obj_meta.text_params.set_bg_clr = 1
    obj_meta.text_params.text_bg_clr.set(0.0, 0.0, 0.0, 0.7)

    pyds.nvds_add_obj_meta_to_frame(frame_meta, obj_meta, None)
    return True


# ---------------------------------------------------------------------------
# Main detector/probe
# ---------------------------------------------------------------------------

class HybridDetector:
    def __init__(self):
        cfg = load_cfg(CONFIG_PATH)
        self.face_pipe = TensorRTFacePipeline(cfg)
        self.publisher = FaceKafkaPublisher(cfg)

        self.frame_count = 0
        self.last_faces = []

        # Recent embedding cache for dedup.
        self.recent: List[Tuple[float, np.ndarray]] = []

    def should_publish(self, embedding: List[float]) -> bool:
        now = time.time()
        emb = l2_normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))

        # Keep only fresh cache items.
        self.recent = [(t, e) for (t, e) in self.recent if now - t <= PUBLISH_DEDUP_TTL_SEC]

        for _, old_emb in self.recent:
            sim = cosine_sim(emb, old_emb)
            if sim >= PUBLISH_DEDUP_SIM_THRESHOLD:
                return False

        self.recent.append((now, emb))
        return True

    def publish_faces(
        self,
        *,
        faces: List[dict],
        frame_bgr: np.ndarray,
        infer_ms: int,
        frame_num: int,
    ) -> int:
        published = 0

        for face in faces or []:
            bbox = extract_bbox(face)
            if bbox is None:
                continue

            score = extract_score(face)
            if score < PUBLISH_MIN_FACE_SCORE:
                continue

            embedding = extract_embedding(face)
            if not embedding:
                LOG.warning(
                    "Face has bbox but no embedding; not publishing to Kafka. keys=%s",
                    list(face.keys()) if isinstance(face, dict) else type(face),
                )
                continue

            x1, y1, x2, y2 = clamp_bbox_xyxy(bbox)
            if (x2 - x1) < PUBLISH_MIN_FACE_SIZE or (y2 - y1) < PUBLISH_MIN_FACE_SIZE:
                continue

            if not self.should_publish(embedding):
                continue

            face_jpeg_b64 = crop_face_jpeg_b64(frame_bgr, bbox)

            try:
                self.publisher.send_face_event(
                    embedding=embedding,
                    bbox=bbox,
                    score=score,
                    face_jpeg_b64=face_jpeg_b64,
                    processing_time_ms=infer_ms,
                    frame_num=frame_num,
                )
                published += 1
            except Exception as e:
                LOG.exception("Failed to publish face event to Kafka: %s", e)

        return published

    def probe(self, pad, info, user_data):
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

            self.frame_count += 1
            should_infer = (self.frame_count % INFER_EVERY_N_FRAMES) == 0

            faces = []
            infer_ms = 0
            frame_bgr = None

            if should_infer:
                try:
                    # Requires RGBA NVMM surface before this probe.
                    # This is the intentional hybrid-copy step.
                    surface = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    frame_rgba = np.array(surface, copy=True, order="C")

                    # Convert RGBA -> BGR for your existing OpenCV/TensorRT pipeline.
                    frame_bgr = cv2.cvtColor(frame_rgba, cv2.COLOR_RGBA2BGR)

                    t0 = time.time()
                    faces = self.face_pipe.infer(frame_bgr) or []
                    infer_ms = int((time.time() - t0) * 1000)

                    self.last_faces = faces
                    LOG.info(
                        "INFER frame=%s faces=%s infer_ms=%s",
                        frame_meta.frame_num,
                        len(faces),
                        infer_ms,
                    )

                    published = self.publish_faces(
                        faces=faces,
                        frame_bgr=frame_bgr,
                        infer_ms=infer_ms,
                        frame_num=int(frame_meta.frame_num),
                    )

                    if published:
                        LOG.info("PUBLISHED frame=%s kafka_face_events=%s", frame_meta.frame_num, published)

                except Exception as e:
                    LOG.exception("Face inference/publishing failed in DeepStream probe: %s", e)
                    faces = []
            else:
                faces = self.last_faces

            added = 0
            for face in faces or []:
                bbox = extract_bbox(face)
                if bbox is None:
                    LOG.warning(
                        "Face returned without bbox. keys=%s",
                        list(face.keys()) if isinstance(face, dict) else type(face),
                    )
                    continue

                score = extract_score(face)
                if add_face_obj_meta(batch_meta, frame_meta, bbox, score):
                    added += 1

            print("DETECT frame={} added_faces={}".format(frame_meta.frame_num, added))

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        return Gst.PadProbeReturn.OK

    def close(self):
        self.publisher.close()


# ---------------------------------------------------------------------------
# Tracker probe
# ---------------------------------------------------------------------------

def tracker_src_probe(pad, info, user_data):
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

        tracked = []
        l_obj = frame_meta.obj_meta_list
        while l_obj is not None:
            try:
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break

            tracked.append(
                {
                    "id": int(obj_meta.object_id),
                    "conf": float(obj_meta.confidence),
                    "left": float(obj_meta.rect_params.left),
                    "top": float(obj_meta.rect_params.top),
                    "w": float(obj_meta.rect_params.width),
                    "h": float(obj_meta.rect_params.height),
                }
            )

            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        if tracked:
            msg = " ".join(
                [
                    "id={} conf={:.2f} bbox=({:.1f},{:.1f},{:.1f},{:.1f})".format(
                        t["id"], t["conf"], t["left"], t["top"], t["w"], t["h"]
                    )
                    for t in tracked
                ]
            )
            print("TRACK frame={} objects={} {}".format(frame_meta.frame_num, len(tracked), msg))
        else:
            print("TRACK frame={} objects=0".format(frame_meta.frame_num))

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    Gst.init(None)

    pipeline = Gst.Pipeline.new("ds-hybrid-trt-face-kafka-streaming")

    # ------------------------------------------------------------------
    # Camera ingest: use MJPG because the Rapoo camera exposes stable
    # 640x480@30 as Motion-JPEG. Decode to raw, then move into NVMM.
    # ------------------------------------------------------------------
    source = make_element("v4l2src", "camera-source")
    source.set_property("device", DEVICE)
    source.set_property("do-timestamp", True)

    raw_caps = make_element("capsfilter", "raw-caps")
    raw_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "image/jpeg,width={},height={},framerate={}/1".format(
                FRAME_W, FRAME_H, FPS
            )
        ),
    )

    jpegdec = make_element("jpegdec", "jpeg-decoder")
    videoconvert = make_element("videoconvert", "video-convert")
    nvvidconv1 = make_element("nvvideoconvert", "nv-video-convert-1")

    nvmm_caps = make_element("capsfilter", "nvmm-caps")
    nvmm_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=NV12,width={},height={},framerate={}/1".format(
                FRAME_W, FRAME_H, FPS
            )
        ),
    )

    streammux = make_element("nvstreammux", "stream-muxer")
    streammux.set_property("width", FRAME_W)
    streammux.set_property("height", FRAME_H)
    streammux.set_property("batch-size", 1)
    streammux.set_property("batched-push-timeout", 40000)
    streammux.set_property("live-source", 1)
    streammux.set_property("num-surfaces-per-frame", 1)

    nvvidconv2 = make_element("nvvideoconvert", "nv-video-convert-2")
    rgba_caps = make_element("capsfilter", "rgba-caps")
    rgba_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=RGBA,width={},height={}".format(
                FRAME_W, FRAME_H
            )
        ),
    )

    # ------------------------------------------------------------------
    # AI branch: your existing custom TRT detection/recognition injects
    # NvDsObjectMeta before nvtracker.
    # ------------------------------------------------------------------
    tracker = make_element("nvtracker", "face-tracker")
    tracker.set_property("tracker-width", 640)
    tracker.set_property("tracker-height", 384)
    tracker.set_property("gpu-id", 0)
    tracker.set_property("ll-lib-file", TRACKER_LIB)
    tracker.set_property("ll-config-file", TRACKER_CONFIG)
    tracker.set_property("enable-batch-process", 1)
    tracker.set_property("enable-past-frame", 0)

    sink = make_element("fakesink", "fake-sink")
    sink.set_property("sync", False)
    sink.set_property("async", False)

    # ------------------------------------------------------------------
    # Optional frontend stream branch: H264 -> MPEG-TS -> UDP -> MediaMTX.
    # MediaMTX path config should be:
    # paths:
    #   rapoo:
    #     source: udp://0.0.0.0:8000
    # ------------------------------------------------------------------
    tee = None
    ai_queue = None
    stream_queue = None
    stream_convert = None
    stream_caps = None
    encoder = None
    h264parse = None
    mpegtsmux = None
    udpsink = None

    elements = [
        source, raw_caps, jpegdec, videoconvert, nvvidconv1, nvmm_caps,
        streammux, nvvidconv2, rgba_caps, tracker, sink
    ]

    if ENABLE_FRONTEND_STREAM:
        tee = make_element("tee", "stream-tee")

        ai_queue = make_element("queue", "ai-queue")
        ai_queue.set_property("leaky", 2)
        ai_queue.set_property("max-size-buffers", 2)
        ai_queue.set_property("max-size-time", 0)
        ai_queue.set_property("max-size-bytes", 0)

        stream_queue = make_element("queue", "stream-queue")
        stream_queue.set_property("leaky", 2)
        stream_queue.set_property("max-size-buffers", 1)
        stream_queue.set_property("max-size-time", 0)
        stream_queue.set_property("max-size-bytes", 0)

        stream_convert = make_element("nvvideoconvert", "stream-convert")
        stream_caps = make_element("capsfilter", "stream-nv12-caps")
        stream_caps.set_property(
            "caps",
            Gst.Caps.from_string(
                "video/x-raw(memory:NVMM),format=NV12,width={},height={}".format(
                    FRAME_W, FRAME_H
                )
            ),
        )

        encoder = make_element("nvv4l2h264enc", "h264-encoder")
        encoder.set_property("bitrate", STREAM_BITRATE)
        set_property_if_supported(encoder, "insert-sps-pps", 1)
        set_property_if_supported(encoder, "iframeinterval", 15)
        set_property_if_supported(encoder, "control-rate", 1)
        set_property_if_supported(encoder, "preset-level", 1)
        set_property_if_supported(encoder, "bufapi-version", True)

        h264parse = make_element("h264parse", "h264-parser")
        mpegtsmux = make_element("mpegtsmux", "mpegts-mux")

        udpsink = make_element("udpsink", "udp-sink")
        udpsink.set_property("host", STREAM_HOST)
        udpsink.set_property("port", STREAM_PORT)
        udpsink.set_property("sync", False)
        udpsink.set_property("async", False)

        elements.extend([
            tee, ai_queue, stream_queue, stream_convert, stream_caps,
            encoder, h264parse, mpegtsmux, udpsink
        ])

    for elem in elements:
        pipeline.add(elem)

    if not source.link(raw_caps):
        raise RuntimeError("source -> raw_caps failed")
    if not raw_caps.link(jpegdec):
        raise RuntimeError("raw_caps -> jpegdec failed")
    if not jpegdec.link(videoconvert):
        raise RuntimeError("jpegdec -> videoconvert failed")
    if not videoconvert.link(nvvidconv1):
        raise RuntimeError("videoconvert -> nvvideoconvert1 failed")
    if not nvvidconv1.link(nvmm_caps):
        raise RuntimeError("nvvideoconvert1 -> nvmm_caps failed")

    sinkpad = streammux.get_request_pad("sink_0")
    srcpad = nvmm_caps.get_static_pad("src")
    if not sinkpad or not srcpad:
        raise RuntimeError("Failed to get streammux pads")
    if srcpad.link(sinkpad) != Gst.PadLinkReturn.OK:
        raise RuntimeError("nvmm_caps -> streammux failed")

    if not streammux.link(nvvidconv2):
        raise RuntimeError("streammux -> nvvideoconvert2 failed")
    if not nvvidconv2.link(rgba_caps):
        raise RuntimeError("nvvideoconvert2 -> rgba_caps failed")

    if ENABLE_FRONTEND_STREAM:
        if not rgba_caps.link(tee):
            raise RuntimeError("rgba_caps -> tee failed")

        tee_ai_srcpad = tee.get_request_pad("src_%u")
        ai_queue_sinkpad = ai_queue.get_static_pad("sink")
        if not tee_ai_srcpad or not ai_queue_sinkpad:
            raise RuntimeError("Failed to get tee/ai_queue pads")
        if tee_ai_srcpad.link(ai_queue_sinkpad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("tee -> ai_queue failed")

        if not ai_queue.link(tracker):
            raise RuntimeError("ai_queue -> tracker failed")
        if not tracker.link(sink):
            raise RuntimeError("tracker -> sink failed")

        tee_stream_srcpad = tee.get_request_pad("src_%u")
        stream_queue_sinkpad = stream_queue.get_static_pad("sink")
        if not tee_stream_srcpad or not stream_queue_sinkpad:
            raise RuntimeError("Failed to get tee/stream_queue pads")
        if tee_stream_srcpad.link(stream_queue_sinkpad) != Gst.PadLinkReturn.OK:
            raise RuntimeError("tee -> stream_queue failed")

        if not stream_queue.link(stream_convert):
            raise RuntimeError("stream_queue -> stream_convert failed")
        if not stream_convert.link(stream_caps):
            raise RuntimeError("stream_convert -> stream_caps failed")
        if not stream_caps.link(encoder):
            raise RuntimeError("stream_caps -> encoder failed")
        if not encoder.link(h264parse):
            raise RuntimeError("encoder -> h264parse failed")
        if not h264parse.link(mpegtsmux):
            raise RuntimeError("h264parse -> mpegtsmux failed")
        if not mpegtsmux.link(udpsink):
            raise RuntimeError("mpegtsmux -> udpsink failed")
    else:
        if not rgba_caps.link(tracker):
            raise RuntimeError("rgba_caps -> tracker failed")
        if not tracker.link(sink):
            raise RuntimeError("tracker -> sink failed")

    detector = HybridDetector()

    # Run existing TensorRTFacePipeline on each DeepStream frame before tracker.
    det_pad = rgba_caps.get_static_pad("src")
    if not det_pad:
        raise RuntimeError("Could not get rgba_caps src pad")
    det_pad.add_probe(Gst.PadProbeType.BUFFER, detector.probe, None)

    tracker_src_pad = tracker.get_static_pad("src")
    if not tracker_src_pad:
        raise RuntimeError("Could not get tracker src pad")
    tracker_src_pad.add_probe(Gst.PadProbeType.BUFFER, tracker_src_probe, None)

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print("Starting HYBRID DeepStream + existing TRT face pipeline + Kafka...")
    print("Camera -> nvstreammux -> RGBA surface -> TensorRTFacePipeline -> Kafka face_events")
    print("Also: TensorRTFacePipeline -> NvDsObjectMeta -> nvtracker -> fakesink")
    print("This does NOT use nvinfer for SCRFD and does NOT touch/rebuild your engines.")
    print("Kafka topic:", KAFKA_TOPIC)
    print("Evidence gateway:", EVIDENCE_GATEWAY_UPLOAD)
    print("Dedup TTL:", PUBLISH_DEDUP_TTL_SEC, "sec")
    if ENABLE_FRONTEND_STREAM:
        print("Frontend stream: MPEG-TS/H264 UDP -> {}:{}".format(STREAM_HOST, STREAM_PORT))
    else:
        print("Frontend stream: disabled")

    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        pipeline.set_state(Gst.State.NULL)
        detector.close()
        print("Stopped.")


if __name__ == "__main__":
    main()