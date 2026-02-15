import os
import json
import base64
import requests
from typing import Optional

import boto3
from botocore.client import Config
from kafka import KafkaConsumer


BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093")
BACKEND_MATCH_URL = os.getenv("BACKEND_MATCH_URL", "http://vector-match:8000/match")

GROUP_ID = os.getenv("KAFKA_GROUP_ID", "backend-consumer")
TOPICS = [t.strip() for t in os.getenv("KAFKA_TOPICS", "face_events,anomaly_events").split(",") if t.strip()]

# ---- MinIO / S3 settings (Option A) ----
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://minio:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin123")
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")
S3_REGION = os.getenv("S3_REGION", "us-east-1")


def s3_client():
    # MinIO needs path-style addressing usually
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def ensure_bucket(client):
    # Create bucket if missing (safe for MinIO)
    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except Exception:
        client.create_bucket(Bucket=S3_BUCKET)


def upload_face_jpeg_b64_to_minio(event: dict) -> Optional[str]:
    b64 = event.get("face_jpeg_b64")
    if not b64:
        return None

    event_id = event.get("event_id", "no_event_id")
    camera_id = event.get("camera_id", "unknown_camera")

    # where we store it in MinIO
    key = f"faces/cam_{camera_id}/{event_id}.jpg"

    try:
        jpg_bytes = base64.b64decode(b64, validate=True)
    except Exception as e:
        print(f"[FACE] invalid base64 for event_id={event_id}: {e}")
        return None

    try:
        client = s3_client()
        ensure_bucket(client)
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=jpg_bytes,
            ContentType="image/jpeg",
        )
        return key
    except Exception as e:
        print(f"[FACE] failed to upload to MinIO for event_id={event_id}: {e}")
        return None


def handle_face_event(event: dict):
    # 1) Upload image to MinIO first (you already have this function)
    key = upload_face_jpeg_b64_to_minio(event)
    image_ref = f"s3://{S3_BUCKET}/{key}" if key else None

    # 2) Normalize required fields to match EdgeEvent
    event_id = str(event.get("event_id", ""))
    camera_id = int(event.get("camera_id", 0))

    emb = event.get("embedding") or []
    try:
        emb = [float(x) for x in emb]  # ensure List[float]
    except Exception:
        emb = []

    # (Optional) normalize quality_score to float if present
    qs = event.get("quality_score")
    try:
        qs = float(qs) if qs is not None else None
    except Exception:
        qs = None

    # 3) Build payload EXACTLY for EdgeEvent
    payload = {
        "event_id": event_id,
        "camera_id": camera_id,
        "embedding": emb,
        "event_type": event.get("event_type") or "face_detected",
        "image_video_ref": image_ref,
        "processing_time_ms": event.get("processing_time_ms"),
        "model_version": event.get("model_version"),
        "quality_score": qs,
    }

    # IMPORTANT: EdgeEvent.ts is Optional[str] — only include it as string
    ts = event.get("ts")
    if ts is None and event.get("ts_ms") is not None:
        ts = event.get("ts_ms")
    if ts is not None:
        payload["ts"] = str(ts)

    emb_len = len(emb) if isinstance(emb, list) else None
    print(
        f"[FACE] event_id={event_id} camera={camera_id} emb_len={emb_len} evidence={image_ref}"
    )

    # 4) Call vector-match backend
    try:
        resp = requests.post(BACKEND_MATCH_URL, json=payload, timeout=5)

        # Print FastAPI validation details if 422 (or any non-200)
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



def handle_anomaly_event(event: dict):
    print(f"[ANOM] event_id={event.get('event_id')} camera={event.get('camera_id')} score={event.get('novelty_score')}")


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
    print(f"[consumer] evidence: endpoint={S3_ENDPOINT} bucket={S3_BUCKET}")

    try:
        for msg in consumer:
            topic = msg.topic
            event = msg.value

            if topic == "face_events":
                handle_face_event(event)
            elif topic == "anomaly_events":
                handle_anomaly_event(event)
            else:
                print(f"[WARN] unexpected topic={topic}")

    except KeyboardInterrupt:
        print("[consumer] stopping.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
