import os
import json
import base64
import requests
from typing import Optional, Any, Dict
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093")
BACKEND_MATCH_URL = os.getenv("BACKEND_MATCH_URL", "http://vector-match:8000/match")
ANOMALY_INGEST_URL = os.getenv(
    "ANOMALY_INGEST_URL",
    "http://anomaly-service:8000/ingest/scene_embedding",
)
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "backend-consumer")
TOPICS = [
    t.strip()
    for t in os.getenv("KAFKA_TOPICS", "face_events,anomaly_events").split(",")
    if t.strip()
]

EVIDENCE_GATEWAY_UPLOAD = os.getenv(
    "EVIDENCE_GATEWAY_UPLOAD",
    "http://evidence-gateway:8010/evidence/upload",
)
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")
DEFAULT_DEVICE_KEY = os.getenv("DEFAULT_DEVICE_KEY", "edge-device-unknown")


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
# Anomaly event handler — updated for v3 pipeline
# ---------------------------------------------------------------------------

def _build_anomaly_ingest_payload(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build the payload for the backend anomaly ingest service.

    v3 Kafka event fields (from kafka_producer.py):
        device_key         : str
        event_key          : str
        camera_id          : int
        track_id           : int
        window_start_ts    : ISO8601 str
        window_end_ts      : ISO8601 str
        embedding          : list[float]
        embedding_dim      : int
        embedding_model    : str
        frames             : list[str]
        processing_time_ms : int
        metadata           : dict
    """
    event_key = event.get("event_key") or event.get("event_id")
    if not event_key:
        print("[ANOM][DROP] missing event_key")
        return None

    device_key = (
        event.get("device_key")
        or (event.get("metadata") or {}).get("device_key")
        or DEFAULT_DEVICE_KEY
    )
    camera_id = int(event.get("camera_id", 0))

    track_id = event.get("track_id")
    if track_id is not None:
        try:
            track_id = int(track_id)
        except Exception:
            track_id = None

    window_start_ts = event.get("window_start_ts")
    window_end_ts = event.get("window_end_ts")
    if not window_start_ts:
        print(f"[ANOM][DROP] missing window_start_ts for event_key={event_key}")
        return None

    embedding = event.get("embedding")
    embedding_model = event.get("embedding_model") or "student-v3-multiscale"
    embedding_dim = event.get("embedding_dim")

    if not isinstance(embedding, list) or len(embedding) == 0:
        print(
            f"[ANOM][DROP] missing or empty embedding for event_key={event_key} "
            f"keys={list(event.keys())}"
        )
        return None

    declared_dim = None
    if embedding_dim is not None:
        try:
            declared_dim = int(embedding_dim)
        except Exception:
            print(
                f"[ANOM][WARN] invalid embedding_dim={embedding_dim!r} "
                f"for event_key={event_key}"
            )

    if declared_dim is not None and len(embedding) != declared_dim:
        print(
            f"[ANOM][WARN] embedding length {len(embedding)} != "
            f"embedding_dim {declared_dim} for event_key={event_key}"
        )

    try:
        embedding = [float(x) for x in embedding]
    except Exception as e:
        print(f"[ANOM][DROP] invalid embedding values for event_key={event_key}: {e}")
        return None

    frames = event.get("frames") or []
    if not isinstance(frames, list):
        print(
            f"[ANOM][WARN] malformed frames field for event_key={event_key}: "
            f"{type(frames).__name__}"
        )
        frames = []

    expected_frames = ((event.get("metadata") or {}).get("num_frames"))
    try:
        expected_frames = int(expected_frames) if expected_frames is not None else None
    except Exception:
        expected_frames = None

    if expected_frames is not None and frames and len(frames) != expected_frames:
        print(
            f"[ANOM][WARN] frames count {len(frames)} != expected {expected_frames} "
            f"for event_key={event_key}"
        )

    payload: Dict[str, Any] = {
        "device_key": str(device_key),
        "event_key": str(event_key),
        "camera_id": camera_id,
        "window_start_ts": str(window_start_ts),
        "window_end_ts": str(window_end_ts) if window_end_ts else None,
        "embedding": embedding,
        "embedding_dim": len(embedding),
        "embedding_model": str(embedding_model),
        "frames": frames if frames else None,
    }

    if track_id is not None:
        payload["track_id"] = track_id

    metadata = event.get("metadata")
    if metadata:
        payload["metadata"] = metadata

    return {k: v for k, v in payload.items() if v is not None}


def handle_anomaly_event(event: dict) -> bool:
    event_key = event.get("event_key") or event.get("event_id")
    camera_id = event.get("camera_id", "?")
    track_id = event.get("track_id", "?")
    frames = event.get("frames") or []
    frames_n = len(frames) if isinstance(frames, list) else 0
    emb_dim = event.get("embedding_dim") or (
        len(event["embedding"]) if isinstance(event.get("embedding"), list) else "?"
    )

    print(
        f"[ANOM] event_key={event_key} camera={camera_id} "
        f"track={track_id} emb_dim={emb_dim} frames={frames_n}"
    )

    payload = _build_anomaly_ingest_payload(event)
    if payload is None:
        print(
            f"[ANOM][DROP] could not build ingest payload "
            f"from event keys={list(event.keys())}"
        )
        return False

    ek = payload.get("event_key")
    try:
        r = requests.post(ANOMALY_INGEST_URL, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[ANOM][HTTP] event_key={ek} {r.status_code} {r.text}")
            return False

        j = r.json()
        print(
            f"[ANOM][INGEST] event_key={ek} "
            f"candidate_id={j.get('anomaly_candidate_id') or j.get('candidate_id')} "
            f"status={j.get('status')}"
        )
        return True
    except requests.exceptions.ConnectionError as e:
        print(
            f"[ANOM][ERROR] event_key={ek} "
            f"cannot reach anomaly-service at {ANOMALY_INGEST_URL} err={e}"
        )
        return False
    except Exception as e:
        print(f"[ANOM][ERROR] event_key={ek} error={e}")
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
                auto_offset_reset="earliest",
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
    print(f"[consumer] anomaly_ingest={ANOMALY_INGEST_URL}")
    print(f"[consumer] evidence_gateway={EVIDENCE_GATEWAY_UPLOAD}")

    try:
        for msg in consumer:
            ok = False

            if msg.topic == "face_events":
                ok = handle_face_event(msg.value)
            elif msg.topic == "anomaly_events":
                ok = handle_anomaly_event(msg.value)
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