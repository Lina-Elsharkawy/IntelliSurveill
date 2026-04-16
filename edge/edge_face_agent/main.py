import logging
import time
import uuid
from collections import deque

import numpy as np
import yaml

from camera.camera_source import CameraSource
from face.face_recognition_trt import TensorRTFacePipeline
from messaging.kafka_producer import KafkaEventProducer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
LOG = logging.getLogger("edge_face_agent")


def load_cfg(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _coerce_camera_id(raw_value):
    if isinstance(raw_value, int):
        return raw_value
    if raw_value is None:
        return 0

    s = str(raw_value).strip()
    if s.isdigit():
        return int(s)

    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits) if digits else 0


def cosine_similarity(a, b):
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)

    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0

    return float(np.dot(a, b) / (na * nb))


class RecentFaceCache:
    def __init__(self, ttl_sec=3.0, sim_threshold=0.72, max_items=50):
        self.ttl_sec = float(ttl_sec)
        self.sim_threshold = float(sim_threshold)
        self.max_items = int(max_items)
        self.items = deque()

    def _prune(self, now_ts):
        while self.items and (now_ts - self.items[0]["ts"]) > self.ttl_sec:
            self.items.popleft()

    def should_send(self, embedding, now_ts):
        self._prune(now_ts)

        emb = np.asarray(embedding, dtype=np.float32)

        for item in self.items:
            sim = cosine_similarity(emb, item["embedding"])
            if sim >= self.sim_threshold:
                return False

        self.items.append(
            {
                "ts": float(now_ts),
                "embedding": emb,
            }
        )

        while len(self.items) > self.max_items:
            self.items.popleft()

        return True


def main():
    cfg = load_cfg()

    cam = CameraSource(cfg)
    face_pipe = TensorRTFacePipeline(cfg)
    producer = KafkaEventProducer(cfg)

    every_n = int(cfg.get("runtime", {}).get("send_every_n_frames", 2))
    camera_id = _coerce_camera_id(cfg.get("kafka", {}).get("camera_id", 0))
    model_version = str(cfg.get("face", {}).get("model_name", "buffalo_l_trt"))

    dedup_cfg = cfg.get("dedup", {})
    recent_face_cache = RecentFaceCache(
        ttl_sec=float(dedup_cfg.get("ttl_sec", 3.0)),
        sim_threshold=float(dedup_cfg.get("sim_threshold", 0.72)),
        max_items=int(dedup_cfg.get("max_items", 50)),
    )

    frame_i = 0
    sent_events = 0
    skipped_duplicates = 0
    last_log_ts = time.time()

    LOG.info(
        "Face agent started. camera_id=%s every_n=%s model_version=%s dedup_ttl=%s dedup_sim=%.3f",
        camera_id,
        every_n,
        model_version,
        recent_face_cache.ttl_sec,
        recent_face_cache.sim_threshold,
    )

    try:
        for frame_bgr, ts_ms in cam.frames():
            frame_i += 1
            if frame_i % every_n != 0:
                continue

            t0 = time.time()
            faces = face_pipe.infer(frame_bgr)
            proc_ms = int((time.time() - t0) * 1000)

            if not faces:
                now = time.time()
                if now - last_log_ts >= 5:
                    LOG.info(
                        "frames=%s sent=%s skipped_duplicates=%s last_proc_ms=%s no faces",
                        frame_i,
                        sent_events,
                        skipped_duplicates,
                        proc_ms,
                    )
                    last_log_ts = now
                continue

            sent_this_frame = 0
            skipped_this_frame = 0

            for face in faces:
                emb = face.get("embedding")
                if emb is None:
                    continue

                now_ts = time.time()
                if not recent_face_cache.should_send(emb, now_ts):
                    skipped_duplicates += 1
                    skipped_this_frame += 1
                    continue

                event_id = str(uuid.uuid4())
                event = {
                    "event_id": event_id,
                    "camera_id": camera_id,
                    "event_type": "face_detected",
                    "ts_ms": ts_ms,
                    "processing_time_ms": proc_ms,
                    "model_version": model_version,
                    **face,
                }

                producer.send(event, key=event_id)
                sent_events += 1
                sent_this_frame += 1

            LOG.info(
                "frame=%s faces=%s sent_this_frame=%s skipped_this_frame=%s sent_total=%s skipped_duplicates=%s proc_ms=%s",
                frame_i,
                len(faces),
                sent_this_frame,
                skipped_this_frame,
                sent_events,
                skipped_duplicates,
                proc_ms,
            )

    except KeyboardInterrupt:
        LOG.info("Interrupted by user.")
    finally:
        try:
            producer.close()
        finally:
            cam.release()

        LOG.info(
            "Stopped. frames=%s sent=%s skipped_duplicates=%s",
            frame_i,
            sent_events,
            skipped_duplicates,
        )


if __name__ == "__main__":
    main()