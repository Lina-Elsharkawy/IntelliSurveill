import os
import json
import base64
import requests
from typing import Optional, Any, Dict, Tuple
from kafka import KafkaConsumer

BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9093")
BACKEND_MATCH_URL = os.getenv("BACKEND_MATCH_URL", "http://vector-match:8000/match")
# ---------------------------------------------------------------------------
# Set the default ingest URL for the new anomaly pipeline.
#
# The old pipeline posted to /ingest/scene_embedding.  The new dual‐stream
# distribution pipeline exposes /ingest/person-context-tubelet.  Use the
# environment variable to override if needed, but default to the new
# endpoint.
ANOMALY_INGEST_URL = os.getenv(
    "ANOMALY_INGEST_URL",
    "http://anomaly-service:8000/ingest/person-context-tubelet",
)
GROUP_ID = os.getenv("KAFKA_GROUP_ID", "backend-consumer")
TOPICS = [
    t.strip()
    for t in os.getenv("KAFKA_TOPICS", "face_events,anomaly_events,vad.frames.uploaded").split(",")
    if t.strip()
]

EVIDENCE_GATEWAY_UPLOAD = os.getenv(
    "EVIDENCE_GATEWAY_UPLOAD",
    "http://evidence-gateway:8010/evidence/upload",
)
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")
DEFAULT_DEVICE_KEY = os.getenv("DEFAULT_DEVICE_KEY", "edge-device-unknown")
# Optional future backend endpoint. Leave empty until backend route is implemented.
VAD_FRAME_INGEST_URL = os.getenv("VAD_FRAME_INGEST_URL", "").strip()


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
# VAD raw-frame reference handler
# ---------------------------------------------------------------------------

VAD_FRAME_REQUIRED_FIELDS = (
    "schema_version",
    "event_type",
    "frame_uid",
    "camera_id",
    "frame_index",
    "captured_at",
    "bucket",
    "object_key",
    "content_type",
    "width",
    "height",
)


def _validate_vad_frame_event(event: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Validate the new VAD frame-ref contract.

    Kafka must carry metadata only. The image itself must already exist in MinIO.
    """
    missing = [field for field in VAD_FRAME_REQUIRED_FIELDS if event.get(field) in (None, "")]
    if missing:
        return False, f"missing required fields: {missing}"

    if event.get("schema_version") != "vad.frame_uploaded.v1":
        return False, f"unsupported schema_version={event.get('schema_version')!r}"

    if event.get("event_type") != "frame_uploaded":
        return False, f"unsupported event_type={event.get('event_type')!r}"

    try:
        int(event.get("camera_id"))
        int(event.get("frame_index"))
        int(event.get("width"))
        int(event.get("height"))
    except Exception as e:
        return False, f"invalid numeric field: {e}"

    if str(event.get("content_type")).lower() not in ("image/jpeg", "image/jpg", "image/png"):
        return False, f"unsupported content_type={event.get('content_type')!r}"

    return True, "ok"


def _build_vad_frame_ingest_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the frame-ref event for the future backend ingest endpoint."""
    bucket = str(event["bucket"])
    object_key = str(event["object_key"])
    object_uri = event.get("object_uri") or event.get("evidence_ref") or f"s3://{bucket}/{object_key}"

    return {
        "schema_version": "vad.frame_uploaded.v1",
        "event_type": "frame_uploaded",
        "frame_uid": str(event["frame_uid"]),
        "camera_id": int(event["camera_id"]),
        "camera_key": event.get("camera_key"),
        "edge_device_key": event.get("edge_device_key") or DEFAULT_DEVICE_KEY,
        "frame_index": int(event["frame_index"]),
        "captured_at": str(event["captured_at"]),
        "monotonic_ts": event.get("monotonic_ts"),
        "target_fps": event.get("target_fps"),
        "width": int(event["width"]),
        "height": int(event["height"]),
        "bucket": bucket,
        "object_key": object_key,
        "object_uri": object_uri,
        "content_type": str(event["content_type"]),
        "size_bytes": event.get("size_bytes"),
        "sha256": event.get("sha256"),
        "metadata": event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
    }


def handle_vad_frame_uploaded(event: dict) -> bool:
    ok, reason = _validate_vad_frame_event(event)
    frame_uid = event.get("frame_uid", "?")
    if not ok:
        print(f"[VAD_FRAME][DROP] frame_uid={frame_uid} reason={reason} keys={list(event.keys())}")
        return False

    payload = _build_vad_frame_ingest_payload(event)
    object_uri = payload["object_uri"]
    print(
        f"[VAD_FRAME] frame_uid={payload['frame_uid']} camera={payload['camera_id']} "
        f"frame_index={payload['frame_index']} object={object_uri} "
        f"size={payload.get('size_bytes')} backend_ingest={'enabled' if VAD_FRAME_INGEST_URL else 'disabled'}"
    )

    # Backend route is intentionally optional for this phase. Until it exists,
    # the consumer validates/logs frame refs and commits the Kafka offset.
    if not VAD_FRAME_INGEST_URL:
        return True

    try:
        r = requests.post(VAD_FRAME_INGEST_URL, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"[VAD_FRAME][HTTP] frame_uid={payload['frame_uid']} {r.status_code} {r.text}")
            return False
        print(f"[VAD_FRAME][INGEST] frame_uid={payload['frame_uid']} status={r.status_code}")
        return True
    except requests.exceptions.ConnectionError as e:
        print(f"[VAD_FRAME][ERROR] cannot reach {VAD_FRAME_INGEST_URL} frame_uid={payload['frame_uid']} err={e}")
        return False
    except Exception as e:
        print(f"[VAD_FRAME][ERROR] frame_uid={payload['frame_uid']} error={e}")
        return False


# ---------------------------------------------------------------------------
# Anomaly event handler — updated for v3 pipeline
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> list:
    """Return value as a list only when it is already a list; otherwise []."""
    return value if isinstance(value, list) else []


def _extract_motion_stats(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract motion stats from either top-level event fields or metadata.

    The edge/Jetson should send these values, not embeddings.  The backend
    anomaly-service will use them for high-speed, abrupt-direction, and
    track-instability gates.
    """
    metadata = event.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    motion_stats = event.get("motion_stats") or metadata.get("motion_stats") or {}
    if not isinstance(motion_stats, dict):
        motion_stats = {}

    # Backward/edge-friendly fallbacks: allow common motion keys at top level
    # or inside metadata without requiring the edge script to wrap them first.
    for key in (
        "max_speed_norm",
        "speed_norm",
        "max_speed",
        "max_turn_angle",
        "turn_angle",
        "turn_speed",
        "max_turn_speed",
        "track_gap_count",
        "gap_count",
        "lost_frames",
        "track_instability_reason",
        "instability_reason",
    ):
        if key not in motion_stats:
            if key in event:
                motion_stats[key] = event[key]
            elif key in metadata:
                motion_stats[key] = metadata[key]

    return motion_stats


def _build_anomaly_ingest_payload(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build the payload for the new backend anomaly ingest service.

    IMPORTANT ARCHITECTURE RULE:
    The Jetson/edge pipeline must NOT send embeddings.

    The edge should send evidence references and motion metadata only.  This
    consumer forwards those references to anomaly-service, and anomaly-service
    extracts VideoMAE person/context embeddings on the backend.

    Accepted anomaly event fields:
      - device_key
      - event_key or event_id
      - camera_id
      - track_id
      - window_start_ts
      - window_end_ts
      - person_frames / context_frames
      - frames                  (legacy alias, used for both person/context)
      - representative_frame_ref
      - person_clip_ref / context_clip_ref
      - person_bbox_sequence
      - motion_stats
      - metadata

    This function deliberately does NOT forward:
      - embedding
      - embedding_dim
      - embedding_model
      - precomputed_person_embedding
      - precomputed_context_embedding
    """
    event_key = event.get("event_key") or event.get("event_id")
    if not event_key:
        print("[ANOM][DROP] missing event_key/event_id")
        return None

    metadata = event.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    device_key = (
        event.get("device_key")
        or metadata.get("device_key")
        or DEFAULT_DEVICE_KEY
    )

    try:
        camera_id = int(event.get("camera_id", 0))
    except Exception:
        camera_id = 0

    track_id = event.get("track_id")
    if track_id is not None:
        try:
            track_id = int(track_id)
        except Exception:
            track_id = None

    window_start_ts = event.get("window_start_ts") or event.get("start_ts")
    window_end_ts = event.get("window_end_ts") or event.get("end_ts")
    if not window_start_ts:
        print(f"[ANOM][DROP] missing window_start_ts for event_key={event_key}")
        return None

    # Preferred new fields.
    person_frames = _as_list(event.get("person_frames"))
    context_frames = _as_list(event.get("context_frames"))

    # Legacy/edge-friendly alias: if the edge sends only `frames`, use them
    # for both person and context until the edge script starts sending true
    # wider context crops separately.
    legacy_frames = _as_list(event.get("frames"))
    if legacy_frames:
        if not person_frames:
            person_frames = legacy_frames
        if not context_frames:
            context_frames = legacy_frames

    person_clip_ref = event.get("person_clip_ref")
    context_clip_ref = event.get("context_clip_ref")
    representative_frame_ref = event.get("representative_frame_ref")

    # Backward convenience: if no representative frame was supplied, use the
    # middle frame from whichever frame list exists. This lets VLM reasoning
    # work even before the edge script has a dedicated representative upload.
    if not representative_frame_ref:
        candidate_frames = context_frames or person_frames
        if candidate_frames:
            representative_frame_ref = candidate_frames[len(candidate_frames) // 2]

    if not (person_frames or context_frames or person_clip_ref or context_clip_ref):
        print(
            f"[ANOM][DROP] no evidence refs for event_key={event_key}; "
            "need person_frames/context_frames/frames or person_clip_ref/context_clip_ref"
        )
        return None

    person_bbox_sequence = event.get("person_bbox_sequence")
    if person_bbox_sequence is None:
        person_bbox_sequence = metadata.get("person_bbox_sequence") or []
    if not isinstance(person_bbox_sequence, list):
        person_bbox_sequence = []

    motion_stats = _extract_motion_stats(event)

    # Preserve useful metadata, but explicitly mark that embeddings are not
    # expected from the edge in the new architecture.
    clean_metadata = dict(metadata)
    clean_metadata.update({
        "edge_sent_embeddings": False,
        "backend_extracts_videomae": True,
    })

    payload: Dict[str, Any] = {
        "device_key": str(device_key),
        "event_key": str(event_key),
        "camera_id": camera_id,
        "window_start_ts": str(window_start_ts),
        "metadata": clean_metadata,
        "motion_stats": motion_stats,
        "person_bbox_sequence": person_bbox_sequence,
    }

    if window_end_ts:
        payload["window_end_ts"] = str(window_end_ts)
    if track_id is not None:
        payload["track_id"] = track_id
    if person_frames:
        payload["person_frames"] = person_frames
    if context_frames:
        payload["context_frames"] = context_frames
    if person_clip_ref:
        payload["person_clip_ref"] = str(person_clip_ref)
    if context_clip_ref:
        payload["context_clip_ref"] = str(context_clip_ref)
    if representative_frame_ref:
        payload["representative_frame_ref"] = str(representative_frame_ref)

    return payload

def handle_anomaly_event(event: dict) -> bool:
    event_key = event.get("event_key") or event.get("event_id")
    camera_id = event.get("camera_id", "?")
    track_id = event.get("track_id", "?")
    frames = event.get("frames") or event.get("person_frames") or event.get("context_frames") or []
    frames_n = len(frames) if isinstance(frames, list) else 0
    has_clip = bool(event.get("person_clip_ref") or event.get("context_clip_ref"))
    has_rep = bool(event.get("representative_frame_ref"))

    print(
        f"[ANOM] event_key={event_key} camera={camera_id} "
        f"track={track_id} frames={frames_n} clips={has_clip} representative={has_rep} "
        f"edge_embeddings=not_expected"
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
        r = requests.post(ANOMALY_INGEST_URL, json=payload, timeout=120)
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
    print(f"[consumer] anomaly_ingest={ANOMALY_INGEST_URL}")
    print(f"[consumer] vad_frame_ingest={VAD_FRAME_INGEST_URL or 'disabled'}")
    print(f"[consumer] evidence_gateway={EVIDENCE_GATEWAY_UPLOAD}")

    try:
        for msg in consumer:
            ok = False

            if msg.topic == "face_events":
                ok = handle_face_event(msg.value)
            elif msg.topic == "anomaly_events":
                ok = handle_anomaly_event(msg.value)
            elif msg.topic == "vad.frames.uploaded":
                ok = handle_vad_frame_uploaded(msg.value)
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