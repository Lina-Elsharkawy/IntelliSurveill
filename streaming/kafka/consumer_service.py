import os
import json
import base64
import requests
from typing import Optional, Any, Dict, List
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093")
BACKEND_MATCH_URL = os.getenv("BACKEND_MATCH_URL", "http://vector-match:8000/match")
ANOMALY_INGEST_URL = os.getenv("ANOMALY_INGEST_URL","http://anomaly-service:8000/ingest/scene_embedding")
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "backend-consumer")
TOPICS = [t.strip() for t in os.getenv("KAFKA_TOPICS", "face_events,anomaly_events").split(",") if t.strip()]

EVIDENCE_GATEWAY_UPLOAD = os.getenv("EVIDENCE_GATEWAY_UPLOAD", "http://evidence-gateway:8010/evidence/upload")
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")
DEFAULT_DEVICE_KEY = os.getenv("DEFAULT_DEVICE_KEY", "edge-device-unknown")


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
    data = {"event_id": event_id, "camera_id": str(camera_id), "kind": "face", "ext": "jpg"}
    try:
        r = requests.post(EVIDENCE_GATEWAY_UPLOAD, files=files, data=data, timeout=10)
        if r.status_code != 200:
            print(f"[FACE] gateway upload failed event_id={event_id}: {r.status_code} {r.text}")
            return None
        return r.json().get("evidence_ref")
    except Exception as e:
        print(f"[FACE] gateway upload exception event_id={event_id}: {e}")
        return None


def handle_face_event(event: dict):
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
    print(f"[FACE] event_id={event_id} camera={camera_id} emb_len={emb_len} evidence={evidence_ref}")

    try:
        resp = requests.post(BACKEND_MATCH_URL, json=payload, timeout=5)
        if resp.status_code != 200:
            print(f"[MATCH][HTTP] {resp.status_code} {resp.text}")
            return
        result = resp.json()
        print(
            f"[MATCH] event_id={result.get('event_id')} status={result.get('status')} "
            f"entry_log_id={result.get('entry_log_id')} detected_id={result.get('detected_id')} "
            f"best={result.get('best_similarity')} margin={result.get('margin')} "
            f"unknown_face_event_id={result.get('unknown_face_event_id')}"
        )
    except Exception as e:
        print(f"[MATCH][ERROR] event_id={event_id} error={e}")


def _l2_norm(vec: List[float]) -> Optional[List[float]]:
    try:
        import math
        n = math.sqrt(sum(float(x) * float(x) for x in vec))
        if n <= 1e-12:
            return None
        return [float(x) / n for x in vec]
    except Exception:
        return None


def _build_anomaly_ingest_payload(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_key = event.get("event_key") or event.get("event_id")
    if not event_key:
        return None

    device_key = event.get("device_key") or (event.get("metadata") or {}).get("device_key") or DEFAULT_DEVICE_KEY
    camera_id = int(event.get("camera_id", 0))

    window_start_ts = event.get("window_start_ts")
    window_end_ts = event.get("window_end_ts")

    if not window_start_ts:
        ts = event.get("ts_ms") or event.get("ts")
        if ts is None:
            return None
        window_start_ts = str(ts)
        window_end_ts = str(ts)

    embedding_pca = event.get("embedding_pca")
    embedding_model = event.get("embedding_model") or "unknown"

    if embedding_pca is None:
        md = event.get("metadata") or {}
        embedding_pca = md.get("embedding_pca")
        if md.get("embedding_model"):
            embedding_model = md.get("embedding_model")

    if not isinstance(embedding_pca, list) or len(embedding_pca) != 128:
        ns = event.get("novelty_score")
        if ns is None:
            print(f"[ANOM][DROP] missing embedding_pca len=128 for event_key={event_key}")
            return None
        v = float(ns)
        embedding_pca = _l2_norm([v] * 128)
        if embedding_pca is None:
            print(f"[ANOM][DROP] zero-norm fallback embedding for event_key={event_key}")
            return None
        embedding_model = "fallback:novelty_score"
    else:
        embedding_pca = _l2_norm([float(x) for x in embedding_pca])
        if embedding_pca is None:
            print(f"[ANOM][DROP] zero-norm embedding_pca for event_key={event_key}")
            return None

    frames = event.get("frames") or event.get("evidence_refs") or []
    if frames and not isinstance(frames, list):
        frames = []

    payload: Dict[str, Any] = {
        "device_key": str(device_key),
        "event_key": str(event_key),
        "camera_id": camera_id,
        "entry_log_id": event.get("entry_log_id"),
        "window_start_ts": str(window_start_ts),
        "window_end_ts": str(window_end_ts) if window_end_ts is not None else None,
        "embedding_model": str(embedding_model),
        "embedding_pca": embedding_pca,
        "embedding_raw": event.get("embedding_raw"),
        "frames": frames or None,
        "image_ref": event.get("image_ref"),
        "video_ref": event.get("video_ref"),
    }
    return {k: v for k, v in payload.items() if v is not None}


def handle_anomaly_event(event: dict):
    # --- log using event_key (new) with fallback to event_id (old) ---
    event_key = event.get("event_key") or event.get("event_id")
    camera_id = event.get("camera_id", "?")
    score = event.get("novelty_score")
    if score is None:
        score = event.get("score")
    frames = event.get("frames") or event.get("evidence_refs") or []
    try:
        frames_n = len(frames) if isinstance(frames, list) else 0
    except Exception:
        frames_n = 0

    print(f"[ANOM] event_key={event_key} camera={camera_id} score={score} frames={frames_n}")

    payload = _build_anomaly_ingest_payload(event)
    if payload is None:
        print(f"[ANOM][DROP] could not build ingest payload from event keys={list(event.keys())}")
        return

    ek = payload.get("event_key")
    try:
        r = requests.post(ANOMALY_INGEST_URL, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[ANOM][HTTP] event_key={ek} {r.status_code} {r.text}")
            return
        j = r.json()
        print(f"[ANOM][INGEST] event_key={ek} ok candidate_id={j.get('candidate_id')} abnormal={j.get('abnormal')}")
    except requests.exceptions.ConnectionError as e:
        print(f"[ANOM][ERROR] event_key={ek} cannot reach anomaly-service at {ANOMALY_INGEST_URL} err={e}")
    except Exception as e:
        print(f"[ANOM][ERROR] event_key={ek} error={e}")


def main():
    consumer = KafkaConsumer(
        *TOPICS,
        bootstrap_servers=BOOTSTRAP,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )

    print(f"[consumer] bootstrap={BOOTSTRAP} topics={TOPICS} group={GROUP_ID}")
    print(f"[consumer] evidence_gateway={EVIDENCE_GATEWAY_UPLOAD} bucket={S3_BUCKET}")

    try:
        for msg in consumer:
            if msg.topic == "face_events":
                handle_face_event(msg.value)
            elif msg.topic == "anomaly_events":
                handle_anomaly_event(msg.value)
            else:
                print(f"[WARN] unexpected topic={msg.topic}")
    except KeyboardInterrupt:
        print("[consumer] stopping.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
