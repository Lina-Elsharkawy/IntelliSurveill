import os
import json
import logging
import threading
from typing import List, Optional, Dict, Any

import cv2
import requests
from kafka import KafkaProducer

log = logging.getLogger(__name__)


class AnomalyEventProducer:
    """
    Edge anomaly producer for the v3 student-teacher pipeline.

    One Kafka message is published per person-track tubelet window:
        device_key      : edge device identifier
        event_key       : unique event UUID
        camera_id       : camera identifier
        track_id        : person track identifier (from IoU tracker)
        window_start_ts : ISO timestamp of first frame in window
        window_end_ts   : ISO timestamp of last frame in window
        embedding       : 2304-d student embedding (list of floats)
        embedding_model : model version string
        frames          : list of s3:// refs to the 16 uploaded person crops
        processing_time_ms : edge inference + upload time

    The backend consumes this event and:
        1. Fetches frames from MinIO
        2. Runs VideoMAE teacher on frames -> 2304-d teacher embedding
        3. Computes L2(student_embedding, teacher_embedding) -> anomaly score
        4. Applies filtering, pose gate, and Ollama reasoning
    """

    def __init__(self, cfg: dict) -> None:
        kcfg                = cfg.get("kafka", {})
        self.topic          = kcfg.get("topic_anomaly", "anomaly_events")
        self.bootstrap      = kcfg.get("bootstrap_servers", "kafka:9093")
        self.send_timeout_s = int(kcfg.get("send_timeout_sec", 10))
        self.flush_every    = int(kcfg.get("flush_every", 1))
        self._sent_since_flush = 0

        eg              = cfg.get("evidence_gateway", {})
        self.upload_url = eg.get("upload_url") or os.getenv(
            "EVIDENCE_GATEWAY_UPLOAD",
            "http://evidence-gateway:8010/evidence/upload",
        )
        
        # Lazy initialization - don't create producer in __init__
        self.producer = None
        self._init_attempted = False
        self._init_lock = threading.Lock()
    
    def _try_init_producer(self, timeout_sec=3.0):
        # type: (float) -> bool
        """
        Attempt to initialize Kafka producer with timeout.
        Returns True if successful, False otherwise.
        Non-blocking - will not hang the calling thread.
        """
        with self._init_lock:
            if self._init_attempted:
                return self.producer is not None
            
            self._init_attempted = True
            
            result = [None]  # type: List[Optional[KafkaProducer]]
            error = [None]   # type: List[Optional[Exception]]
            
            def _init():
                try:
                    result[0] = KafkaProducer(
                        bootstrap_servers = self.bootstrap,
                        acks              = 1,
                        retries           = 0,
                        linger_ms         = 10,
                        value_serializer  = lambda v: json.dumps(
                            v, ensure_ascii=False
                        ).encode("utf-8"),
                        key_serializer    = lambda k: k.encode("utf-8"),
                        max_request_size  = 10_000_000,
                        request_timeout_ms = 2000,
                    )
                except Exception as e:
                    error[0] = e
            
            thread = threading.Thread(target=_init, daemon=True)
            thread.start()
            thread.join(timeout=timeout_sec)
            
            if thread.is_alive():
                log.warning(
                    "Kafka init timed out after {}s (bootstrap={})".format(
                        timeout_sec, self.bootstrap
                    )
                )
                return False
            
            if error[0] is not None:
                log.warning("Kafka init failed: {}".format(error[0]))
                return False
            
            self.producer = result[0]
            if self.producer is not None:
                log.info("Kafka producer initialized successfully")
                return True
            
            return False

    # ------------------------------------------------------------------
    # Evidence upload
    # ------------------------------------------------------------------

    def _encode_jpg(self, frame_bgr, jpg_quality: int = 85) -> bytes:
        ok, buf = cv2.imencode(
            ".jpg", frame_bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)],
        )
        if not ok:
            raise RuntimeError("cv2.imencode(.jpg) failed")
        return buf.tobytes()

    def upload_frame(
        self,
        *,
        frame_bgr,
        event_id:    str,
        camera_id:   int,
        frame_index: int,
        jpg_quality: int = 85,
    ) -> str:
        """
        Upload a single person crop to MinIO via the evidence-gateway.

        Returns:
            evidence_ref: s3://<bucket>/<key>
        """
        jpg_bytes = self._encode_jpg(frame_bgr, jpg_quality=jpg_quality)

        files = {
            "file": (f"frame_{frame_index:06d}.jpg", jpg_bytes, "image/jpeg")
        }
        data = {
            "event_id":    event_id,
            "camera_id":   str(camera_id),
            "kind":        "anomaly",
            "ext":         "jpg",
            "frame_index": str(frame_index),
        }

        r = requests.post(self.upload_url, files=files, data=data, timeout=10)
        r.raise_for_status()
        return r.json()["evidence_ref"]

    # ------------------------------------------------------------------
    # Kafka publish
    # ------------------------------------------------------------------

    def send_scene_window_event(
        self,
        *,
        device_key:         str,
        event_key:          str,
        camera_id:          int,
        track_id:           int,
        window_start_ts:    str,
        window_end_ts:      Optional[str],
        embedding:          List[float],        # 2304-d student embedding
        embedding_model:    str = "student-v3-multiscale",
        frames:             Optional[List[str]] = None,   # s3:// refs
        processing_time_ms: Optional[int] = None,
        extra:              Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Publish one anomaly candidate event to Kafka.

        Fields:
            device_key      : identifies the Jetson device
            event_key       : unique ID for this window (UUID)
            camera_id       : which camera produced the frames
            track_id        : which person track this tubelet belongs to
            window_start_ts : ISO8601 UTC timestamp of first frame
            window_end_ts   : ISO8601 UTC timestamp of last frame
            embedding       : 2304-d float list (student output)
            embedding_model : model version string
            frames          : list of s3:// refs to the 16 person crops
            processing_time_ms : total edge processing time
            extra           : any additional metadata (image_size, infer_ms etc.)
        """
        # Lazy init on first send
        if self.producer is None and not self._init_attempted:
            self._try_init_producer(timeout_sec=3.0)
        
        if self.producer is None:
            log.debug("Kafka unavailable, skipping event: {}".format(event_key))
            return
        
        payload: Dict[str, Any] = {
            "device_key":      device_key,
            "event_key":       event_key,
            "camera_id":       int(camera_id),
            "track_id":        int(track_id),
            "window_start_ts": str(window_start_ts),
            "window_end_ts":   str(window_end_ts) if window_end_ts else None,
            "embedding_model": embedding_model,
            "embedding":       [float(x) for x in embedding],
            "embedding_dim":   len(embedding),
            "frames":          frames or None,
        }

        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        if processing_time_ms is not None:
            payload["processing_time_ms"] = int(processing_time_ms)
        if extra:
            payload["metadata"] = extra

        try:
            future = self.producer.send(self.topic, key=event_key, value=payload)
            future.get(timeout=self.send_timeout_s)
            
            # Increment and flush only if send succeeds
            self._sent_since_flush += 1
            if self.flush_every > 0 and self._sent_since_flush >= self.flush_every:
                self.flush()
                self._sent_since_flush = 0
                
        except Exception as e:
            log.error("Kafka send failed: {}".format(e))

            # SIMPLE DISK FALLBACK (no heavy deps)
            try:
                os.makedirs("/tmp/kafka_backup", exist_ok=True)
                with open("/tmp/kafka_backup/{}.json".format(event_key), "w") as f:
                    json.dump(payload, f)
                log.warning("Saved event locally: {}".format(event_key))
            except Exception as e2:
                log.error("Failed to save backup: {}".format(e2))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def flush(self):
      if self.producer:
        self.producer.flush(timeout=5)

    def close(self):
     if self.producer:
        self.producer.close()