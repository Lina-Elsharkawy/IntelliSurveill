import os
import json
from typing import List, Optional, Dict, Any

import cv2
import requests
from kafka import KafkaProducer


class AnomalyEventProducer:
    """
    Edge anomaly producer.

    Steady-state design (recommended):
      - Upload N representative frames to evidence-gateway (MinIO)
      - Send ONE Kafka message per scene-window/anomaly-candidate with:
          device_key, event_key, camera_id, window_start_ts, window_end_ts,
          embedding_pca (len=128), embedding_model,
          frames[] (S3 refs), plus novelty_score/threshold metadata.

    Backward-compat:
      - If callers still use send_anomaly_event(..., evidence_refs=[...]) with no embedding,
        you can pass embedding_pca explicitly via extra['embedding_pca'] (not recommended),
        or let the consumer reject/patch it.
    """

    def __init__(self, cfg: dict):
        kcfg = cfg.get("kafka", {})
        self.topic = kcfg.get("topic_anomaly", "anomaly_events")
        self.bootstrap = kcfg.get("bootstrap_servers", "kafka:9093")

        eg = cfg.get("evidence_gateway", {})
        self.upload_url = eg.get("upload_url") or os.getenv(
            "EVIDENCE_GATEWAY_UPLOAD", "http://evidence-gateway:8010/evidence/upload"
        )

        self.producer = KafkaProducer(
            bootstrap_servers=self.bootstrap,
            acks="all",
            retries=10,
            linger_ms=10,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            max_request_size=5_000_000,
        )

    def _encode_jpg(self, frame_bgr, jpg_quality: int = 85) -> bytes:
        ok, buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpg_quality)])
        if not ok:
            raise RuntimeError("cv2.imencode(.jpg) failed")
        return buf.tobytes()

    def upload_frame(
        self,
        *,
        frame_bgr,
        event_id: str,
        camera_id: int,
        frame_index: int,
        jpg_quality: int = 85,
    ) -> str:
        """
        Upload a single evidence frame to the evidence-gateway.

        Returns:
          evidence_ref like: s3://<bucket>/<key>
        """
        jpg_bytes = self._encode_jpg(frame_bgr, jpg_quality=jpg_quality)

        files = {"file": (f"frame_{frame_index:06d}.jpg", jpg_bytes, "image/jpeg")}
        data = {
            "event_id": event_id,
            "camera_id": str(camera_id),
            "kind": "anomaly",
            "ext": "jpg",
            "frame_index": str(frame_index),
        }

        r = requests.post(self.upload_url, files=files, data=data, timeout=10)
        r.raise_for_status()
        j = r.json()
        return j["evidence_ref"]

    def send_scene_window_event(
        self,
        *,
        device_key: str,
        event_key: str,
        camera_id: int,
        window_start_ts: str,
        window_end_ts: Optional[str],
        embedding_pca: List[float],
        embedding_model: str = "unknown",
        frames: Optional[List[str]] = None,
        image_ref: Optional[str] = None,
        video_ref: Optional[str] = None,
        novelty_score: Optional[float] = None,
        threshold: Optional[float] = None,
        model_version: Optional[str] = None,
        processing_time_ms: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send the canonical anomaly payload expected by the backend anomaly-service.

        IMPORTANT: embedding_pca must be length 128.
        """
        payload: Dict[str, Any] = {
            "device_key": device_key,
            "event_key": event_key,
            "camera_id": int(camera_id),
            "window_start_ts": str(window_start_ts),
            "window_end_ts": str(window_end_ts) if window_end_ts is not None else None,
            "embedding_model": embedding_model,
            "embedding_pca": [float(x) for x in embedding_pca],
            "frames": frames or None,
            "image_ref": image_ref,
            "video_ref": video_ref,
        }
        # Remove explicit None keys to keep message small/clean
        payload = {k: v for k, v in payload.items() if v is not None}

        if novelty_score is not None:
            payload["novelty_score"] = float(novelty_score)
        if threshold is not None:
            payload["threshold"] = float(threshold)
        if model_version is not None:
            payload["model_version"] = str(model_version)
        if processing_time_ms is not None:
            payload["processing_time_ms"] = int(processing_time_ms)
        if extra:
            payload["metadata"] = extra

        self.producer.send(self.topic, key=event_key, value=payload)

    # -------------------------
    # Backward-compat wrapper
    # -------------------------
    def send_anomaly_event(
        self,
        *,
        event_id: str,
        camera_id: int,
        ts_ms: int,
        novelty_score: float,
        threshold: float,
        model_version: str,
        processing_time_ms: int,
        evidence_refs: List[str],
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Legacy helper kept for older scripts.

        NOTE: This legacy payload is NOT sufficient for anomaly-service ingest by itself.
        Prefer send_scene_window_event(...) instead.

        If you must use this legacy API temporarily, you can pass:
          extra["device_key"], extra["event_key"], extra["window_start_ts"], extra["window_end_ts"],
          extra["embedding_pca"] (len=128), extra["embedding_model"]
        """
        payload: Dict[str, Any] = {
            "event_id": event_id,
            "camera_id": int(camera_id),
            "ts_ms": int(ts_ms),
            "event_type": "anomaly_candidate",
            "novelty_score": float(novelty_score),
            "threshold": float(threshold),
            "model_version": str(model_version),
            "processing_time_ms": int(processing_time_ms),
            "evidence_refs": evidence_refs,
        }
        if extra:
            payload["metadata"] = extra

        self.producer.send(self.topic, key=event_id, value=payload)

    def flush(self) -> None:
        self.producer.flush(timeout=5)

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self.producer.close()
