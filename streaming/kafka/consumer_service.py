import os
import json
import base64
import requests
from typing import Optional
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093")
BACKEND_MATCH_URL = os.getenv("BACKEND_MATCH_URL", "http://vector-match:8000/match")
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "backend-consumer")
TOPICS = [
    t.strip()
    for t in os.getenv("KAFKA_TOPICS", "face_events").split(",")
    if t.strip()
]

EVIDENCE_GATEWAY_UPLOAD = os.getenv(
    "EVIDENCE_GATEWAY_UPLOAD",
    "http://evidence-gateway:8010/evidence/upload",
)


# ---------------------------------------------------------------------------
# Face event handler
# ---------------------------------------------------------------------------

def upload_face_b64_via_gateway(event: dict) -> Optional[str]:
    b64 = event.get("face_jpeg_b64")
    if not b64:
        return None

    event_id = str(event.get("event_id", "no_event_id"))
    camera_id = int(event.get("camera_id", 0))

    try:
        jpg_bytes = base64.b64decode(b64, validate=True)
    except Exception as e:
        print(f"[FACE] invalid base64 for event_id={event_id}: {e}")
        return None

    files = {"file": (f"{event_id}.jpg", jpg_bytes, "image/jpeg")}
    data = {
        "event_id": event_id,
        "camera_id": str(camera_id),
        "kind": "face",
        "ext": "jpg",
    }

    try:
        r = requests.post(EVIDENCE_GATEWAY_UPLOAD, files=files, data=data, timeout=10)
        if r.status_code != 200:
            print(
                f"[FACE] gateway upload failed event_id={event_id}: "
                f"{r.status_code} {r.text}"
            )
            return None
        return r.json().get("evidence_ref")
    except Exception as e:
        print(f"[FACE] gateway upload exception event_id={event_id}: {e}")
        return None


def handle_face_event(event: dict) -> bool:
    evidence_ref = event.get("evidence_ref") or event.get("image_video_ref")
    if not evidence_ref:
        evidence_ref = upload_face_b64_via_gateway(event)

    event_id = str(event.get("event_id", ""))
    camera_id = int(event.get("camera_id", 0))

    emb = event.get("embedding") or []
    try:
        emb = [float(x) for x in emb]
    except Exception:
        emb = []

    qs = event.get("quality_score")
    try:
        qs = float(qs) if qs is not None else None
    except Exception:
        qs = None

    payload = {
        "event_id": event_id,
        "camera_id": camera_id,
        "embedding": emb,
        "event_type": event.get("event_type") or "face_detected",
        "image_video_ref": evidence_ref,
        "processing_time_ms": event.get("processing_time_ms"),
        "model_version": event.get("model_version"),
        "quality_score": qs,
    }

    ts = event.get("ts")
    if ts is None and event.get("ts_ms") is not None:
        ts = event.get("ts_ms")
    if ts is not None:
        payload["ts"] = str(ts)

    emb_len = len(emb) if isinstance(emb, list) else None
    print(
        f"[FACE] event_id={event_id} camera={camera_id} "
        f"emb_len={emb_len} evidence={evidence_ref}"
    )

    try:
        resp = requests.post(BACKEND_MATCH_URL, json=payload, timeout=5)
        if resp.status_code != 200:
            print(f"[MATCH][HTTP] {resp.status_code} {resp.text}")
            return False

        result = resp.json()
        print(
            f"[MATCH] event_id={result.get('event_id')} status={result.get('status')} "
            f"entry_log_id={result.get('entry_log_id')} "
            f"detected_id={result.get('detected_id')} "
            f"best={result.get('best_similarity')} "
            f"margin={result.get('margin')} "
            f"unknown_face_event_id={result.get('unknown_face_event_id')}"
        )
        return True
    except Exception as e:
        print(f"[MATCH][ERROR] event_id={event_id} error={e}")
        return False


# ---------------------------------------------------------------------------
# Main consumer loop
# ---------------------------------------------------------------------------

def main() -> None:
    import time

    consumer = None
    last_error = None

    for attempt in range(1, 31):
        try:
            consumer = KafkaConsumer(
                *TOPICS,
                bootstrap_servers=BOOTSTRAP,
                group_id=GROUP_ID,
                auto_offset_reset="latest",
                enable_auto_commit=False,
                value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            )
            break
        except Exception as e:
            last_error = e
            print(
                f"[consumer][WAIT] attempt={attempt}/30 "
                f"bootstrap={BOOTSTRAP} error={e}"
            )
            time.sleep(2)

    if consumer is None:
        raise RuntimeError(f"Failed to connect to Kafka at {BOOTSTRAP}: {last_error}")

    print(f"[consumer] bootstrap={BOOTSTRAP} topics={TOPICS} group={GROUP_ID}")
    print(f"[consumer] evidence_gateway={EVIDENCE_GATEWAY_UPLOAD}")

    try:
        for msg in consumer:
            ok = False

            if msg.topic == "face_events":
                ok = handle_face_event(msg.value)
            else:
                print(f"[WARN] unexpected topic={msg.topic}")

            if ok:
                consumer.commit()
            else:
                print(f"[consumer][NO_COMMIT] topic={msg.topic} offset={msg.offset}")
    except KeyboardInterrupt:
        print("[consumer] stopping.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
