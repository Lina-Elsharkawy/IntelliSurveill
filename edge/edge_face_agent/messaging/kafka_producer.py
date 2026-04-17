import base64
import json
import os
import re
from typing import Optional, Tuple

import requests
from kafka import KafkaProducer


class KafkaEventProducer:
    def __init__(self, cfg: dict):
        kcfg = cfg["kafka"]
        self.topic = kcfg["topic"]

        self.evidence_upload_url = (
            cfg.get("evidence_gateway", {}).get("upload_url")
            or os.getenv("EVIDENCE_GATEWAY_UPLOAD", "http://evidence-gateway:8010/evidence/upload")
        )

        self.producer = KafkaProducer(
            bootstrap_servers=kcfg["bootstrap_servers"],
            acks="all",
            retries=10,
            linger_ms=10,
            compression_type=None,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            max_request_size=5_000_000,
        )

    def _coerce_camera_id(self, raw_value) -> int:
        if isinstance(raw_value, int):
            return raw_value
        if raw_value is None:
            return 0

        s = str(raw_value).strip()
        if s.isdigit():
            return int(s)

        match = re.search(r"(\d+)$", s)
        if match:
            return int(match.group(1))

        return 0

    def _extract_evidence_bytes(self, event: dict) -> Tuple[Optional[bytes], Optional[str]]:
        if event.get("face_jpeg_b64"):
            try:
                return base64.b64decode(event["face_jpeg_b64"], validate=True), "jpg"
            except Exception:
                return None, None

        if event.get("evidence_bytes_b64"):
            try:
                ext = event.get("evidence_ext") or "jpg"
                return base64.b64decode(event["evidence_bytes_b64"], validate=True), ext
            except Exception:
                return None, None

        if event.get("evidence_local_path"):
            p = event["evidence_local_path"]
            try:
                _, ext = os.path.splitext(p)
                ext = ext.lstrip(".") or "jpg"
                with open(p, "rb") as f:
                    return f.read(), ext
            except Exception:
                return None, None

        return None, None

    def _upload_to_gateway(
        self,
        *,
        evidence_bytes: bytes,
        event_id: str,
        camera_id: int,
        kind: str,
        ext: str,
        frame_index: Optional[int] = None,
    ) -> str:
        files = {"file": (f"{event_id}.{ext}", evidence_bytes, "application/octet-stream")}
        data = {
            "event_id": event_id,
            "camera_id": str(camera_id),
            "kind": kind,
            "ext": ext,
        }
        if frame_index is not None:
            data["frame_index"] = str(frame_index)

        r = requests.post(self.evidence_upload_url, files=files, data=data, timeout=10)
        r.raise_for_status()
        j = r.json()
        return j["evidence_ref"]

    def _ensure_evidence_ref(self, event: dict) -> dict:
        if event.get("evidence_ref"):
            return event

        if event.get("image_video_ref"):
            event["evidence_ref"] = event["image_video_ref"]
            return event

        evidence_bytes, ext = self._extract_evidence_bytes(event)
        if not evidence_bytes:
            return event

        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise ValueError("event_id is required to upload evidence.")

        camera_id = self._coerce_camera_id(event.get("camera_id"))
        kind = (event.get("evidence_kind") or event.get("kind") or "face").lower().strip()
        if kind not in ("face", "anomaly"):
            kind = "face"

        frame_index = event.get("frame_index")
        try:
            frame_index = int(frame_index) if frame_index is not None else None
        except Exception:
            frame_index = None

        evidence_ref = self._upload_to_gateway(
            evidence_bytes=evidence_bytes,
            event_id=event_id,
            camera_id=camera_id,
            kind=kind,
            ext=ext or "jpg",
            frame_index=frame_index,
        )

        event["evidence_ref"] = evidence_ref
        event["camera_id"] = camera_id
        event.pop("face_jpeg_b64", None)
        event.pop("evidence_bytes_b64", None)
        return event

    def send(self, event: dict, key: str):
        event["camera_id"] = self._coerce_camera_id(event.get("camera_id"))
        event = self._ensure_evidence_ref(event)

        if event.get("evidence_ref") and not event.get("image_video_ref"):
            event["image_video_ref"] = event["evidence_ref"]

        self.producer.send(self.topic, key=key, value=event)

    def flush(self):
        self.producer.flush(timeout=5)

    def close(self):
        try:
            self.flush()
        finally:
            self.producer.close()
