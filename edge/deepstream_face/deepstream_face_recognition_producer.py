#!/usr/bin/env python3
"""
Step 10B:
Production-clean full-resolution landmark-aligned SCRFD + ArcFace DeepStream test.

Pipeline:
Camera
→ SCRFD PGIE with fixed parser + tensor output
→ custom full-res CPU-mapped 5-point ArcFace alignment preprocess
→ ArcFace nvinfer input-tensor-meta
→ clean face event output with 512D normalized embedding stats

This script:
- Does NOT use PyCUDA ArcFace.
- Does NOT publish Kafka yet.
- Does NOT run anomaly yet.
- Prints clean JSON-style face events.
"""

import ctypes
import json
import sys
import time
import os
import uuid
import base64
import logging
import requests
from datetime import datetime, timezone
import numpy as np
import cv2

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

try:
    import pyds
except ImportError:
    print("ERROR: pyds is not importable.")
    sys.exit(1)

try:
    from kafka import KafkaProducer
except Exception:
    KafkaProducer = None


SCRFD_CONFIG = os.environ.get("SCRFD_CONFIG_OVERRIDE", "/opt/deepstream_face/config_infer_primary_scrfd_onnx_batchdim_tensor_fixed.txt")
PREPROCESS_CONFIG = "/opt/deepstream_face/config_preprocess_arcface_fullres_cpu.txt"
ARCFACE_CONFIG = "/opt/deepstream_face/config_infer_arcface_input_tensor_meta.txt"

DEVICE = "/dev/video0"
FRAME_W = 640
FRAME_H = 480
FPS = int(os.environ.get("FACE_CAMERA_FPS", "10"))

# Recognition/event throttling.
# 1 = publish/print every embedding. 5 = every 5th embedding, etc.
EVENT_EVERY_N_EMBEDDINGS = int(os.environ.get("FACE_EVENT_EVERY_N", "5"))

# Actual inference throttling:
# The live stream can stay at 30 FPS, but the face AI branch will only send
# every Nth frame to SCRFD + ArcFace.
FACE_INFER_EVERY_N = max(1, int(os.environ.get("FACE_INFER_EVERY_N", "5")))

CAMERA_ID = int(os.environ.get("CAMERA_ID", "1"))
SITE_ID = os.environ.get("SITE_ID", "jetson_nano_lab")

ENABLE_KAFKA = os.environ.get("ENABLE_KAFKA", "0") == "1"
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "face_events")

# Optional live preview branch:
# Publishes Rapoo camera to MediaMTX as H264-in-MPEGTS over UDP.
ENABLE_LIVE_UDP = os.environ.get("ENABLE_LIVE_UDP", "1") == "1"
LIVE_UDP_HOST = os.environ.get("LIVE_UDP_HOST", "172.21.0.244")
LIVE_UDP_PORT = int(os.environ.get("LIVE_UDP_PORT", "5004"))
LIVE_H264_BITRATE = int(os.environ.get("LIVE_H264_BITRATE", "800000"))

# Evidence handling:
# - DIRECT mode uploads JPEG to evidence-gateway from Jetson and sends evidence_ref in Kafka.
# - B64 fallback mode sends face_jpeg_b64 in Kafka and lets the consumer upload it.
EVIDENCE_MODE = os.environ.get("EVIDENCE_MODE", "direct").strip().lower()
ENABLE_FACE_JPEG_B64 = os.environ.get("ENABLE_FACE_JPEG_B64", "0") == "1"
FACE_JPEG_QUALITY = int(os.environ.get("FACE_JPEG_QUALITY", "80"))
FACE_CROP_PAD = float(os.environ.get("FACE_CROP_PAD", "0.25"))

# Production quality gate:
# Do not publish weak/false detections. This prevents blurry gray crops
# and low-confidence unknown faces from polluting the frontend/database.
MIN_FACE_SCORE = float(os.environ.get("MIN_FACE_SCORE", "0.60"))
MIN_FACE_BOX_W = float(os.environ.get("MIN_FACE_BOX_W", "70"))
MIN_FACE_BOX_H = float(os.environ.get("MIN_FACE_BOX_H", "70"))
REQUIRE_EVIDENCE_REF = os.environ.get("REQUIRE_EVIDENCE_REF", "1") == "1"

EVIDENCE_GATEWAY_UPLOAD = os.environ.get(
    "EVIDENCE_GATEWAY_UPLOAD",
    "http://172.21.0.244:8010/evidence/upload",
)



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
LOG = logging.getLogger("step10b_clean_fullres_face_events")


def make_element(factory, name):
    elem = Gst.ElementFactory.make(factory, name)
    if not elem:
        raise RuntimeError("Could not create element {} ({})".format(factory, name))
    return elem


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


class CleanFaceEventMonitor:
    def __init__(self):
        self.frames_seen = 0
        self.scrfd_tensors_seen = 0
        self.arcface_embeddings_seen = 0
        self.last_ts = time.time()
        self.last_scrfd = None
        self.latest_face_jpeg_b64 = None
        self.latest_face_jpeg_bytes = None
        self.latest_face_jpeg_frame_num = None
        self.producer = None

        self.tensor_meta_type = int(pyds.NvDsMetaType.NVDSINFER_TENSOR_OUTPUT_META)

        if ENABLE_KAFKA:
            if KafkaProducer is None:
                LOG.error("ENABLE_KAFKA=1 but kafka-python is not installed/importable.")
            else:
                self.producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
                    key_serializer=lambda v: v.encode("utf-8") if isinstance(v, str) else v,
                    linger_ms=10,
                    retries=3,
                )
                LOG.info("Kafka enabled: bootstrap=%s topic=%s", KAFKA_BOOTSTRAP, KAFKA_TOPIC)

    def _read_layer(self, layer):
        name = str(layer.layerName)
        dtype = int(layer.dataType)

        dims = []
        count = 1

        for i in range(layer.dims.numDims):
            d = int(layer.dims.d[i])
            dims.append(d)
            count *= d

        if dtype == 0:
            ptr = ctypes.cast(
                pyds.get_ptr(layer.buffer),
                ctypes.POINTER(ctypes.c_float),
            )
            arr = np.ctypeslib.as_array(ptr, shape=(count,))
            arr = np.array(arr, copy=True).astype(np.float32)

        elif dtype == 1:
            ptr = ctypes.cast(
                pyds.get_ptr(layer.buffer),
                ctypes.POINTER(ctypes.c_uint16),
            )
            arr_u16 = np.ctypeslib.as_array(ptr, shape=(count,))
            arr = np.array(arr_u16, copy=True).view(np.float16).astype(np.float32)

        else:
            return name, dims, None

        return name, dims, arr

    def _decode_scrfd_summary_from_tensor_meta(self, tensor_meta):
        """
        Lightweight SCRFD summary for event metadata only.
        The real full-res alignment is done in the custom C++ preprocess library.
        """
        layers = {}

        for i in range(int(tensor_meta.num_output_layers)):
            layer = pyds.get_nvds_LayerInfo(tensor_meta, i)
            name, dims, arr = self._read_layer(layer)
            if arr is not None:
                layers[name] = arr

        score_names = ["448", "471", "494"]
        bbox_names = ["451", "474", "497"]
        kps_names = ["454", "477", "500"]
        feat_w = [80, 40, 20]
        strides = [8, 16, 32]

        best = {
            "score": -1.0,
            "level": -1,
            "idx": -1,
        }

        for level, score_name in enumerate(score_names):
            if score_name not in layers:
                continue

            scores = layers[score_name].reshape(-1)
            idx = int(np.argmax(scores))
            score = float(scores[idx])

            if score > best["score"]:
                best = {
                    "score": score,
                    "level": level,
                    "idx": idx,
                }

        if best["level"] < 0:
            return None

        level = best["level"]
        idx = best["idx"]

        bbox_arr = layers.get(bbox_names[level])
        kps_arr = layers.get(kps_names[level])

        if bbox_arr is None or kps_arr is None:
            return None

        bbox_arr = bbox_arr.reshape(-1, 4)
        kps_arr = kps_arr.reshape(-1, 10)

        st = strides[level]
        fw = feat_w[level]

        anchor_pair_index = idx // 2
        y = anchor_pair_index // fw
        x = anchor_pair_index % fw

        cx = (x + 0.5) * st
        cy = (y + 0.5) * st

        b = bbox_arr[idx]

        x1 = cx - float(b[0]) * st
        y1 = cy - float(b[1]) * st
        x2 = cx + float(b[2]) * st
        y2 = cy + float(b[3]) * st

        kp = kps_arr[idx]
        kps = []

        for j in range(5):
            px = cx + float(kp[2 * j]) * st
            py = cy + float(kp[2 * j + 1]) * st
            kps.append([round(px, 2), round(py, 2)])

        # Map SCRFD net coordinates 640x640 to camera frame 640x480.
        sx = FRAME_W / 640.0
        sy = FRAME_H / 640.0

        bbox_frame = [
            round(x1 * sx, 2),
            round(y1 * sy, 2),
            round((x2 - x1) * sx, 2),
            round((y2 - y1) * sy, 2),
        ]

        kps_frame = [[round(p[0] * sx, 2), round(p[1] * sy, 2)] for p in kps]

        return {
            "score": round(best["score"], 6),
            "bbox_net_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
            "bbox_frame_xywh": bbox_frame,
            "landmarks_net": kps,
            "landmarks_frame": kps_frame,
            "stride": st,
        }


    def _extract_face_jpeg_b64(self, gst_buffer, frame_meta, scrfd_summary):
        # We need to extract JPEG in either mode:
        # - EVIDENCE_MODE=direct: upload JPEG from Jetson and send evidence_ref
        # - ENABLE_FACE_JPEG_B64=1: fallback by sending base64 in Kafka
        if EVIDENCE_MODE != "direct" and not ENABLE_FACE_JPEG_B64:
            return None

        if not scrfd_summary:
            return None

        bbox = scrfd_summary.get("bbox_frame_xywh")
        if not bbox or len(bbox) != 4:
            return None

        try:
            # This requires the buffer at the probe point to be RGBA.
            surface = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
            frame_rgba = np.array(surface, copy=True, order="C")

            if frame_rgba.ndim != 3 or frame_rgba.shape[2] < 3:
                return None

            h, w = frame_rgba.shape[:2]

            x, y, bw, bh = [float(v) for v in bbox]
            pad = FACE_CROP_PAD * max(bw, bh)

            x1 = int(max(0, x - pad))
            y1 = int(max(0, y - pad))
            x2 = int(min(w, x + bw + pad))
            y2 = int(min(h, y + bh + pad))

            if x2 <= x1 or y2 <= y1:
                return None

            crop_rgba = frame_rgba[y1:y2, x1:x2]

            if crop_rgba.shape[2] == 4:
                crop_bgr = cv2.cvtColor(crop_rgba, cv2.COLOR_RGBA2BGR)
            else:
                crop_bgr = cv2.cvtColor(crop_rgba, cv2.COLOR_RGB2BGR)

            ok, enc = cv2.imencode(
                ".jpg",
                crop_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), FACE_JPEG_QUALITY],
            )

            if not ok:
                return None

            jpg_bytes = enc.tobytes()
            self.latest_face_jpeg_bytes = jpg_bytes
            return base64.b64encode(jpg_bytes).decode("ascii")

        except Exception as e:
            LOG.warning("face JPEG extraction failed: %s", e)
            return None


    def _upload_latest_face_evidence(self, event_id, camera_id):
        if EVIDENCE_MODE != "direct":
            return None

        if not self.latest_face_jpeg_bytes:
            return None

        files = {
            "file": (
                "{}.jpg".format(event_id),
                self.latest_face_jpeg_bytes,
                "image/jpeg",
            )
        }

        data = {
            "event_id": str(event_id),
            "camera_id": str(camera_id),
            "kind": "face",
            "ext": "jpg",
        }

        try:
            r = requests.post(
                EVIDENCE_GATEWAY_UPLOAD,
                files=files,
                data=data,
                timeout=5,
            )

            if r.status_code != 200:
                LOG.warning(
                    "direct evidence upload failed event_id=%s status=%s body=%s",
                    event_id,
                    r.status_code,
                    r.text[:300],
                )
                return None

            evidence_ref = r.json().get("evidence_ref")
            return evidence_ref

        except Exception as e:
            LOG.warning("direct evidence upload exception event_id=%s err=%s", event_id, e)
            return None

    def _inspect_user_meta_for_tensors(self, user_meta, where, frame_num):
        meta_type = int(user_meta.base_meta.meta_type)

        if meta_type != self.tensor_meta_type:
            return

        tensor_meta = pyds.NvDsInferTensorMeta.cast(user_meta.user_meta_data)

        try:
            uid = int(tensor_meta.unique_id)
        except Exception:
            uid = -1

        if uid == 1:
            # SCRFD tensor output, attached at frame_user_meta.
            self.scrfd_tensors_seen += 1
            summary = self._decode_scrfd_summary_from_tensor_meta(tensor_meta)
            if summary is not None:
                self.last_scrfd = {
                    "frame_num": frame_num,
                    **summary,
                }

        elif uid == 2:
            # ArcFace output, attached at batch_user_meta.
            if int(tensor_meta.num_output_layers) <= 0:
                return

            layer = pyds.get_nvds_LayerInfo(tensor_meta, 0)
            name, dims, arr = self._read_layer(layer)

            if arr is None:
                return

            emb = arr.reshape(-1).astype(np.float32)

            if emb.size != 512:
                return

            raw_norm = float(np.linalg.norm(emb))
            norm_emb = emb / max(raw_norm, 1e-12)
            norm = float(np.linalg.norm(norm_emb))

            self.arcface_embeddings_seen += 1

            if self.arcface_embeddings_seen % EVENT_EVERY_N_EMBEDDINGS != 1:
                return

            now_iso = datetime.now(timezone.utc).isoformat()

            embedding_list = [round(float(x), 7) for x in norm_emb.tolist()]
            frame_number = self.last_scrfd.get("frame_num") if self.last_scrfd else None
            detector_score = self.last_scrfd.get("score") if self.last_scrfd else None
            bbox_frame_xywh = self.last_scrfd.get("bbox_frame_xywh") if self.last_scrfd else None
            landmarks_frame = self.last_scrfd.get("landmarks_frame") if self.last_scrfd else None

            # Drop weak/invalid detections before uploading evidence or sending Kafka.
            valid_face = True
            reason = ""

            if detector_score is None or float(detector_score) < MIN_FACE_SCORE:
                valid_face = False
                reason = "low_score"

            if valid_face:
                if not bbox_frame_xywh or len(bbox_frame_xywh) != 4:
                    valid_face = False
                    reason = "missing_bbox"
                else:
                    try:
                        bw = float(bbox_frame_xywh[2])
                        bh = float(bbox_frame_xywh[3])
                        if bw < MIN_FACE_BOX_W or bh < MIN_FACE_BOX_H:
                            valid_face = False
                            reason = "small_bbox"
                    except Exception:
                        valid_face = False
                        reason = "bad_bbox"

            if not valid_face:
                if self.arcface_embeddings_seen % max(EVENT_EVERY_N_EMBEDDINGS, 1) == 1:
                    LOG.info(
                        "[drop] face event dropped reason=%s score=%s bbox=%s",
                        reason,
                        detector_score,
                        bbox_frame_xywh,
                    )
                return

            event_id = str(uuid.uuid4())
            evidence_ref = self._upload_latest_face_evidence(event_id, CAMERA_ID)

            if REQUIRE_EVIDENCE_REF and not evidence_ref and not ENABLE_FACE_JPEG_B64:
                LOG.info(
                    "[drop] face event dropped reason=no_evidence_ref score=%s bbox=%s",
                    detector_score,
                    bbox_frame_xywh,
                )
                return

            # Backend-compatible face event.
            # The current streaming consumer expects top-level camera_id:int and embedding:list.
            event = {
                "event_id": event_id,
                "event_type": "face_detected",
                "pipeline": "fullres_scrfd_landmark_aligned_arcface_native",

                # IMPORTANT: numeric camera id for backend consumer.
                "camera_id": CAMERA_ID,
                "site_id": SITE_ID,

                # Consumer supports ts or ts_ms. Keep timestamp_utc too for debugging.
                "ts": now_iso,
                "timestamp_utc": now_iso,
                "frame_num": frame_number,

                # IMPORTANT: top-level embedding for consumer_service.py.
                "embedding": embedding_list,
                "embedding_dim": int(emb.size),
                "quality_score": detector_score,

                # Useful metadata. Consumer will ignore unknown fields safely.
                "bbox_frame_xywh": bbox_frame_xywh,
                "landmarks_frame": landmarks_frame,
                "detector_score": detector_score,
                "model_version": "scrfd_det10g_fullres_align_arcface_w600k_r50_fp16",
                "processing_time_ms": None,

                # Production path: Jetson uploads image and sends only evidence_ref.
                # Fallback path: optionally send face_jpeg_b64 if direct upload fails.
                "evidence_ref": evidence_ref,
                "image_video_ref": evidence_ref,
                "face_jpeg_b64": (
                    self.latest_face_jpeg_b64
                    if (evidence_ref is None and ENABLE_FACE_JPEG_B64)
                    else None
                ),

                "detector": {
                    "name": "SCRFD",
                    "score": detector_score,
                    "bbox_frame_xywh": bbox_frame_xywh,
                    "landmarks_frame": landmarks_frame,
                    "stride": self.last_scrfd.get("stride") if self.last_scrfd else None,
                },

                "recognizer": {
                    "name": "ArcFace",
                    "embedding_dim": int(emb.size),
                    "raw_norm": round(raw_norm, 6),
                    "normalized_norm": round(norm, 6),
                },

                "debug": {
                    "arcface_layer": name,
                    "arcface_dims": dims,
                    "embedding_min": round(float(emb.min()), 6),
                    "embedding_max": round(float(emb.max()), 6),
                    "embedding_mean": round(float(emb.mean()), 6),
                    "embedding_first8": [round(float(x), 6) for x in norm_emb[:8]],
                },
            }

            if self.producer is not None:
                key = "{}:{}".format(CAMERA_ID, event["frame_num"])
                self.producer.send(KAFKA_TOPIC, key=key, value=event)
                self.producer.poll(0)

            print(json.dumps({
                "event_type": event["event_type"],
                "event_id": event["event_id"],
                "camera_id": event["camera_id"],
                "frame_num": event["frame_num"],
                "detector_score": event["detector"]["score"],
                "bbox_frame_xywh": event["detector"]["bbox_frame_xywh"],
                "embedding_dim": event["recognizer"]["embedding_dim"],
                "normalized_norm": event["recognizer"]["normalized_norm"],
                "kafka_enabled": self.producer is not None,
                "has_evidence_ref": bool(event.get("evidence_ref")),
                "has_face_jpeg_b64": bool(event.get("face_jpeg_b64")),
                "evidence_mode": EVIDENCE_MODE,
            }, ensure_ascii=False, indent=2))

    def probe(self, pad, info, user_data):
        gst_buffer = info.get_buffer()
        if not gst_buffer:
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        if not batch_meta:
            return Gst.PadProbeReturn.OK

        self.frames_seen += 1

        # Frame-level user meta first: SCRFD tensor output.
        # This ensures SCRFD score/bbox/landmarks are ready before ArcFace batch meta is processed.
        l_frame = batch_meta.frame_meta_list
        while l_frame:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break

            frame_num = int(frame_meta.frame_num)

            l_user = frame_meta.frame_user_meta_list
            while l_user:
                try:
                    user_meta = pyds.NvDsUserMeta.cast(l_user.data)
                    self._inspect_user_meta_for_tensors(user_meta, "frame_user_meta", frame_num)
                except Exception as e:
                    LOG.debug("frame user meta inspect failed: %s", e)

                try:
                    l_user = l_user.next
                except StopIteration:
                    break

            if self.last_scrfd and self.last_scrfd.get("frame_num") == frame_num:
                self.latest_face_jpeg_b64 = self._extract_face_jpeg_b64(
                    gst_buffer,
                    frame_meta,
                    self.last_scrfd,
                )
                self.latest_face_jpeg_frame_num = frame_num

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        # Batch-level user meta second: ArcFace tensor output when using input-tensor-meta.
        l_buser = batch_meta.batch_user_meta_list
        while l_buser:
            try:
                user_meta = pyds.NvDsUserMeta.cast(l_buser.data)
                self._inspect_user_meta_for_tensors(user_meta, "batch_user_meta", -1)
            except Exception as e:
                LOG.debug("batch user meta inspect failed: %s", e)

            try:
                l_buser = l_buser.next
            except StopIteration:
                break

        now = time.time()
        if now - self.last_ts >= 5.0:
            LOG.info(
                "[stats] frames=%s scrfd_tensors=%s arcface_embeddings=%s",
                self.frames_seen,
                self.scrfd_tensors_seen,
                self.arcface_embeddings_seen,
            )
            self.last_ts = now

        return Gst.PadProbeReturn.OK


def build_pipeline(monitor):
    pipeline = Gst.Pipeline.new("step10b-clean-fullres-face-events")

    source = make_element("v4l2src", "source")
    source.set_property("device", DEVICE)
    source.set_property("do-timestamp", True)

    raw_caps = make_element("capsfilter", "raw-caps")
    raw_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "image/jpeg,width={},height={},framerate={}/1".format(FRAME_W, FRAME_H, FPS)
        ),
    )

    jpegdec = make_element("jpegdec", "jpegdec")
    videoconvert = make_element("videoconvert", "videoconvert")
    nvvidconv = make_element("nvvideoconvert", "nvvidconv")

    nvmm_caps = make_element("capsfilter", "nvmm-caps")
    nvmm_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=NV12,width={},height={},framerate={}/1".format(
                FRAME_W,
                FRAME_H,
                FPS,
            )
        ),
    )

    camera_tee = make_element("tee", "camera-tee")

    face_queue = make_element("queue", "face-queue")
    face_queue.set_property("max-size-buffers", 4)
    face_queue.set_property("max-size-time", 0)
    face_queue.set_property("max-size-bytes", 0)

    live_queue = None
    live_h264enc = None
    live_h264parse = None
    live_h264_caps = None
    live_mpegtsmux = None
    live_udpsink = None

    if ENABLE_LIVE_UDP:
        live_queue = make_element("queue", "live-queue")
        live_queue.set_property("leaky", 2)
        live_queue.set_property("max-size-buffers", 2)
        live_queue.set_property("max-size-time", 0)
        live_queue.set_property("max-size-bytes", 0)

        live_h264enc = make_element("nvv4l2h264enc", "live-h264-enc")
        live_h264enc.set_property("bitrate", LIVE_H264_BITRATE)

        for prop_name, prop_value in [
            ("insert-sps-pps", True),
            ("iframeinterval", FPS),
        ]:
            try:
                live_h264enc.set_property(prop_name, prop_value)
            except Exception:
                pass

        live_h264parse = make_element("h264parse", "live-h264-parse")
        try:
            live_h264parse.set_property("config-interval", 1)
        except Exception:
            pass

        live_h264_caps = make_element("capsfilter", "live-h264-caps")
        live_h264_caps.set_property(
            "caps",
            Gst.Caps.from_string("video/x-h264,stream-format=byte-stream,alignment=au"),
        )

        live_mpegtsmux = make_element("mpegtsmux", "live-mpegts-mux")

        live_udpsink = make_element("udpsink", "live-udp-sink")
        live_udpsink.set_property("host", LIVE_UDP_HOST)
        live_udpsink.set_property("port", LIVE_UDP_PORT)
        live_udpsink.set_property("sync", False)
        live_udpsink.set_property("async", False)

    streammux = make_element("nvstreammux", "streammux")
    streammux.set_property("width", FRAME_W)
    streammux.set_property("height", FRAME_H)
    streammux.set_property("batch-size", 1)
    streammux.set_property("batched-push-timeout", 40000)
    streammux.set_property("live-source", 1)
    streammux.set_property("num-surfaces-per-frame", 1)

    pgie = make_element("nvinfer", "scrfd-pgie")
    pgie.set_property("config-file-path", SCRFD_CONFIG)

    preprocess = make_element("nvdspreprocess", "arcface-fullres-preprocess")
    preprocess.set_property("config-file", PREPROCESS_CONFIG)

    arcface = make_element("nvinfer", "arcface-input-tensor-nvinfer")
    arcface.set_property("config-file-path", ARCFACE_CONFIG)
    arcface.set_property("input-tensor-meta", True)

    post_rgba_conv = make_element("nvvideoconvert", "post-arcface-rgba-conv")

    post_rgba_caps = make_element("capsfilter", "post-arcface-rgba-caps")
    post_rgba_caps.set_property(
        "caps",
        Gst.Caps.from_string(
            "video/x-raw(memory:NVMM),format=RGBA,width={},height={}".format(
                FRAME_W,
                FRAME_H,
            )
        ),
    )

    sink = make_element("fakesink", "sink")
    sink.set_property("sync", False)
    sink.set_property("async", False)

    for elem in [
        source,
        raw_caps,
        jpegdec,
        videoconvert,
        nvvidconv,
        nvmm_caps,
        camera_tee,
        face_queue,
        streammux,
        pgie,
        preprocess,
        arcface,
        post_rgba_conv,
        post_rgba_caps,
        sink,
    ]:
        pipeline.add(elem)

    if ENABLE_LIVE_UDP:
        for elem in [
            live_queue,
            live_h264enc,
            live_h264parse,
            live_h264_caps,
            live_mpegtsmux,
            live_udpsink,
        ]:
            pipeline.add(elem)

    if not source.link(raw_caps):
        raise RuntimeError("source -> raw_caps failed")
    if not raw_caps.link(jpegdec):
        raise RuntimeError("raw_caps -> jpegdec failed")
    if not jpegdec.link(videoconvert):
        raise RuntimeError("jpegdec -> videoconvert failed")
    if not videoconvert.link(nvvidconv):
        raise RuntimeError("videoconvert -> nvvidconv failed")
    if not nvvidconv.link(nvmm_caps):
        raise RuntimeError("nvvidconv -> nvmm_caps failed")

    if not nvmm_caps.link(camera_tee):
        raise RuntimeError("nvmm_caps -> camera_tee failed")

    tee_src_template = camera_tee.get_pad_template("src_%u")

    # Drop frames only on the face inference branch.
    # This reduces SCRFD + ArcFace GPU load while keeping live preview smooth.
    face_drop_state = {"seen": 0, "kept": 0}

    def face_infer_skip_probe(pad, info, user_data):
        if FACE_INFER_EVERY_N <= 1:
            return Gst.PadProbeReturn.OK

        buf = info.get_buffer()
        if not buf:
            return Gst.PadProbeReturn.OK

        face_drop_state["seen"] += 1

        # Keep frame 1, 1+N, 1+2N, ...
        if (face_drop_state["seen"] - 1) % FACE_INFER_EVERY_N == 0:
            face_drop_state["kept"] += 1
            return Gst.PadProbeReturn.OK

        return Gst.PadProbeReturn.DROP

    # Face branch.
    tee_face_pad = camera_tee.request_pad(tee_src_template, None, None)
    face_queue_sink = face_queue.get_static_pad("sink")
    if tee_face_pad.link(face_queue_sink) != Gst.PadLinkReturn.OK:
        raise RuntimeError("camera_tee -> face_queue failed")

    mux_sinkpad = streammux.get_request_pad("sink_0")
    face_srcpad = face_queue.get_static_pad("src")

    if not mux_sinkpad or not face_srcpad:
        raise RuntimeError("Could not get streammux/face_queue pads")

    face_srcpad.add_probe(Gst.PadProbeType.BUFFER, face_infer_skip_probe, None)

    if face_srcpad.link(mux_sinkpad) != Gst.PadLinkReturn.OK:
        raise RuntimeError("face_queue -> streammux failed")

    LOG.info(
        "Face inference throttling enabled: processing every %s frame(s)",
        FACE_INFER_EVERY_N,
    )

    # Live MediaMTX branch over UDP/MPEG-TS.
    if ENABLE_LIVE_UDP:
        tee_live_pad = camera_tee.request_pad(tee_src_template, None, None)
        live_queue_sink = live_queue.get_static_pad("sink")
        if tee_live_pad.link(live_queue_sink) != Gst.PadLinkReturn.OK:
            raise RuntimeError("camera_tee -> live_queue failed")

        if not live_queue.link(live_h264enc):
            raise RuntimeError("live_queue -> live_h264enc failed")
        if not live_h264enc.link(live_h264parse):
            raise RuntimeError("live_h264enc -> live_h264parse failed")
        if not live_h264parse.link(live_h264_caps):
            raise RuntimeError("live_h264parse -> live_h264_caps failed")
        if not live_h264_caps.link(live_mpegtsmux):
            raise RuntimeError("live_h264_caps -> live_mpegtsmux failed")
        if not live_mpegtsmux.link(live_udpsink):
            raise RuntimeError("live_mpegtsmux -> live_udpsink failed")

        LOG.info("Live UDP/MPEGTS enabled: udp://%s:%s", LIVE_UDP_HOST, LIVE_UDP_PORT)

    if not streammux.link(pgie):
        raise RuntimeError("streammux -> pgie failed")
    if not pgie.link(preprocess):
        raise RuntimeError("pgie -> preprocess failed")
    if not preprocess.link(arcface):
        raise RuntimeError("preprocess -> arcface failed")
    if not arcface.link(post_rgba_conv):
        raise RuntimeError("arcface -> post_rgba_conv failed")
    if not post_rgba_conv.link(post_rgba_caps):
        raise RuntimeError("post_rgba_conv -> post_rgba_caps failed")
    if not post_rgba_caps.link(sink):
        raise RuntimeError("post_rgba_caps -> sink failed")

    pad = post_rgba_caps.get_static_pad("src")
    if not pad:
        raise RuntimeError("Could not get post_rgba_caps src pad")

    pad.add_probe(Gst.PadProbeType.BUFFER, monitor.probe, None)

    return pipeline


def main():
    Gst.init(None)

    monitor = CleanFaceEventMonitor()
    pipeline = build_pipeline(monitor)

    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    print("Starting production DeepStream face recognition producer with quality gate")
    print("SCRFD config:", SCRFD_CONFIG)
    print("Preprocess config:", PREPROCESS_CONFIG)
    print("ArcFace config:", ARCFACE_CONFIG)
    print("Face camera FPS:", FPS)
    print("Face inference every N frames:", FACE_INFER_EVERY_N)
    print("Live UDP enabled:", ENABLE_LIVE_UDP, "UDP:", LIVE_UDP_HOST, LIVE_UDP_PORT)

    pipeline.set_state(Gst.State.PLAYING)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Interrupted.")
    finally:
        print("Stopping pipeline...")
        pipeline.set_state(Gst.State.NULL)
        time.sleep(0.5)
        print("Stopped.")


if __name__ == "__main__":
    main()
