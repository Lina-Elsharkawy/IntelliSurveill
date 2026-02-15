import json, uuid, time
import base64
import requests
from kafka import KafkaProducer

BOOTSTRAP = "kafka:9093"
TOPIC = "face_events"

# IMPORTANT:
# - inside docker network: evidence-gateway hostname works
EVIDENCE_GATEWAY_UPLOAD = "http://evidence-gateway:8010/evidence/upload"

# tiny valid JPEG (1x1) as base64 (just for testing)
TINY_JPG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEA8QDw8PDw8PDw8PDw8PDw8QFREWFhURFRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMtNygtLisBCgoKDg0OGhAQGi0lHyUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBEQACEQEDEQH/xAAXAAEBAQEAAAAAAAAAAAAAAAAAAQID/8QAFhABAQEAAAAAAAAAAAAAAAAAAAEQ/8QAFQEBAQAAAAAAAAAAAAAAAAAAAgP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwDkA//Z"


def upload_to_gateway(*, jpg_bytes: bytes, event_id: str, camera_id: int, kind: str = "face", ext: str = "jpg") -> str:
    files = {
        "file": (f"{event_id}.{ext}", jpg_bytes, "image/jpeg"),
    }
    data = {
        "event_id": event_id,
        "camera_id": str(camera_id),
        "kind": kind,
        "ext": ext,
    }
    r = requests.post(EVIDENCE_GATEWAY_UPLOAD, files=files, data=data, timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["evidence_ref"]


producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    key_serializer=lambda k: k.encode("utf-8"),
)

event_id = str(uuid.uuid4())
camera_id = 1

jpg_bytes = base64.b64decode(TINY_JPG_B64)
evidence_ref = upload_to_gateway(jpg_bytes=jpg_bytes, event_id=event_id, camera_id=camera_id)

payload = {
    "event_id": event_id,
    "camera_id": camera_id,
    "ts_ms": int(time.time() * 1000),
    "embedding": [1.0] + [0.0] * 511,
    # Option C: send ref, not the image bytes
    "evidence_ref": evidence_ref,
    "processing_time_ms": 10,
    "model_version": "test",
    "quality_score": 0.99,
    "message_type": "face_event",
}

producer.send(TOPIC, key=event_id, value=payload)
producer.flush(5)
print("sent", event_id, "evidence_ref=", evidence_ref)
