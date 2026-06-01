import io
import os
import time
import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from minio import Minio
from minio.error import S3Error
from urllib.parse import unquote
from fastapi.responses import StreamingResponse

APP_NAME = "evidence-gateway"

# ---------------------------------------------------------------------------
# Config (env)
# ---------------------------------------------------------------------------

MINIO_ENDPOINT   = os.getenv("MINIO_ENDPOINT",   "http://minio:9000").strip()
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
S3_BUCKET        = os.getenv("S3_BUCKET",        "evidence")
PORT             = int(os.getenv("PORT",          "8010"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10MB

MINIO_SECURE_ENV = os.getenv("MINIO_SECURE", "").lower().strip()
FORCE_SECURE: Optional[bool] = None
if MINIO_SECURE_ENV in ("true", "1", "yes"):
    FORCE_SECURE = True
elif MINIO_SECURE_ENV in ("false", "0", "no"):
    FORCE_SECURE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_endpoint(endpoint: str) -> tuple[str, bool]:
    """Return (host:port, secure) for Minio client."""
    if endpoint.startswith("http://"):
        host, secure = endpoint[len("http://"):], False
    elif endpoint.startswith("https://"):
        host, secure = endpoint[len("https://"):], True
    else:
        host, secure = endpoint, False
    if FORCE_SECURE is not None:
        secure = FORCE_SECURE
    return host, secure


def _guess_content_type(filename: str, provided: Optional[str]) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)



def _safe_path_part(value: Optional[str], fallback: str = "unknown") -> str:
    """Return a filesystem/S3-key safe path segment."""
    text = (value or fallback).strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("._") or fallback


def _parse_capture_dt(captured_at: Optional[str]) -> datetime:
    """Parse ISO timestamp, falling back to current UTC for object-key partitioning."""
    if captured_at:
        try:
            raw = captured_at.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)

def _build_object_key(
    kind: str,
    camera_id: int,
    event_id: str,
    ext: str,
    frame_index: Optional[int] = None,
    track_id: Optional[int] = None,
    camera_key: Optional[str] = None,
    captured_at: Optional[str] = None,
) -> str:
    """
    Compute the object key for a given upload type.

    Supported kinds:

      * face   – single face JPEG per event
      * raw_frame – raw sampled VAD frame uploaded by the edge/Jetson
      * anomaly – person‐crop frames from the deprecated student pipeline
      * person_clip – MP4 clip of the tracked person (requires track_id)
      * context_clip – MP4 clip of the scene around the person (requires track_id)
      * representative_frame – single representative JPEG for the tubelet (requires track_id)
      * metadata – JSON metadata for the tubelet (requires track_id)
      * misc – fallback for unknown kinds

    For the new tubelet types, the key structure is:

      tubelets/cam_{camera_id}/track_{track_id}/{event_id}/<file>

    where <file> is one of person.mp4, context.mp4, representative.jpg or metadata.json.
    """
    # Normalize extension: default to jpg for images, mp4 for clips, json for metadata.
    ext = (ext or "").lstrip(".").lower()

    # Legacy face upload: one image per event
    if kind == "face":
        use_ext = ext or "jpg"
        return f"faces/cam_{camera_id}/{event_id}.{use_ext}"

    # New VAD raw-frame upload: Jetson sends sampled frames only; backend does all AI.
    if kind == "raw_frame":
        use_ext = ext or "jpg"
        cam_part = _safe_path_part(camera_key, f"cam_{camera_id}")
        dt = _parse_capture_dt(captured_at)
        if frame_index is not None:
            filename = f"frame_{frame_index:012d}.{use_ext}"
        else:
            filename = f"{_safe_path_part(event_id)}.{use_ext}"
        return (
            f"frames/{cam_part}/{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/"
            f"{dt.hour:02d}/{filename}"
        )

    # Legacy anomaly upload: frames from the old pipeline
    if kind == "anomaly":
        use_ext = ext or "jpg"
        if frame_index is not None:
            return f"anomalies/cam_{camera_id}/{event_id}/frame_{frame_index:06d}.{use_ext}"
        return f"anomalies/cam_{camera_id}/{event_id}/{event_id}.{use_ext}"

    # New dual‐stream upload types
    if kind in ("person_clip", "context_clip", "representative_frame", "metadata"):
        if track_id is None:
            raise ValueError(f"track_id is required for kind={kind}")
        base_path = f"tubelets/cam_{camera_id}/track_{track_id}/{event_id}"
        if kind == "person_clip":
            use_ext = ext or "mp4"
            return f"{base_path}/person.{use_ext}"
        if kind == "context_clip":
            use_ext = ext or "mp4"
            return f"{base_path}/context.{use_ext}"
        if kind == "representative_frame":
            use_ext = ext or "jpg"
            return f"{base_path}/representative.{use_ext}"
        if kind == "metadata":
            use_ext = ext or "json"
            return f"{base_path}/metadata.{use_ext}"

    # Default fallback: store in misc
    use_ext = ext or "jpg"
    return f"misc/cam_{camera_id}/{event_id}.{use_ext}"
def _parse_s3_ref(ref: str) -> tuple[str, str]:
    """
    Parse s3://bucket/object/key.jpg into (bucket, object_key).
    """
    if not ref or not ref.startswith("s3://"):
        raise ValueError("Invalid s3 ref")

    rest = ref[len("s3://"):]
    parts = rest.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("Invalid s3 ref format")

    return parts[0], parts[1]

# ---------------------------------------------------------------------------
# Minio client — created once at startup, reused across all requests
# ---------------------------------------------------------------------------

def _build_minio_client() -> Minio:
    host, secure = _parse_endpoint(MINIO_ENDPOINT)
    return Minio(
        host,
        access_key = MINIO_ACCESS_KEY,
        secret_key = MINIO_SECRET_KEY,
        secure     = secure,
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title=APP_NAME, version="2.0.0")

# Single shared Minio client — avoids reconnecting on every request
_minio: Optional[Minio] = None


@app.on_event("startup")
async def startup() -> None:
    global _minio
    _minio = _build_minio_client()
    _ensure_bucket(_minio, S3_BUCKET)


def get_minio() -> Minio:
    if _minio is None:
        raise RuntimeError("Minio client not initialized.")
    return _minio


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "service": APP_NAME,
        "status":  "ok",
        "bucket":  S3_BUCKET,
        "minio":   MINIO_ENDPOINT,
    }


@app.post("/evidence/upload")
async def upload_evidence(
    file:        UploadFile      = File(...),
    event_id:    str             = Form(...),
    camera_id:   int             = Form(...),
    kind:        str             = Form(...),
    frame_index: Optional[int]  = Form(None),
    ext:         Optional[str]  = Form(None),
    track_id:    Optional[int]  = Form(None),
    camera_key:  Optional[str]  = Form(None),
    captured_at: Optional[str]  = Form(None),
    edge_device_key: Optional[str] = Form(None),
) -> JSONResponse:
    """
    Upload a piece of evidence to MinIO.

    ``kind`` determines how the object key is constructed.  Supported values are:

      * ``face`` – single face image per event
      * ``raw_frame`` – raw 5 fps VAD frame uploaded by the Jetson/edge node
      * ``anomaly`` – deprecated anomaly frame uploads
      * ``person_clip`` – MP4 clip of a person tubelet (requires ``track_id``)
      * ``context_clip`` – MP4 clip of the scene around the person (requires ``track_id``)
      * ``representative_frame`` – JPEG snapshot for the tubelet (requires ``track_id``)
      * ``metadata`` – JSON metadata for the tubelet (requires ``track_id``)

    If an unknown ``kind`` is supplied, the object will be stored in the
    ``misc`` folder.
    """
    kind = (kind or "").strip().lower()
    allowed_kinds = {
        "face",
        "raw_frame",
        "anomaly",
        "person_clip",
        "context_clip",
        "representative_frame",
        "metadata",
    }
    if kind not in allowed_kinds:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid kind={kind!r}. Must be one of: "
                f"{', '.join(sorted(allowed_kinds))}."
            ),
        )

    # Read and validate
    started    = time.time()
    data       = await file.read()
    size_bytes = len(data)

    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Upload too large: {size_bytes} bytes "
                f"> MAX_UPLOAD_BYTES={MAX_UPLOAD_BYTES}."
            ),
        )

    sha256 = hashlib.sha256(data).hexdigest()

    # Determine extension: fall back to file suffix when ext is not provided
    use_ext = ext or os.path.splitext(file.filename or "")[1].lstrip(".")
    # Build the object key.  Pass track_id to allow tubelet uploads.  Any
    # ValueError will be surfaced as a 400 HTTP error.
    try:
        object_key = _build_object_key(
            kind=kind,
            camera_id=int(camera_id),
            event_id=event_id,
            ext=use_ext or "",
            frame_index=frame_index,
            track_id=track_id,
            camera_key=camera_key,
            captured_at=captured_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    content_type = _guess_content_type(
        file.filename or f"{event_id}.{use_ext or 'bin'}", file.content_type
    )

    # Upload to MinIO
    client = get_minio()
    try:
        client.put_object(
            bucket_name  = S3_BUCKET,
            object_name  = object_key,
            data         = io.BytesIO(data),
            length       = size_bytes,
            content_type = content_type,
        )
    except S3Error as e:
        raise HTTPException(
            status_code=502,
            detail=f"MinIO error: {e.code} {e.message}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {type(e).__name__}: {e}",
        ) from e

    object_uri = f"s3://{S3_BUCKET}/{object_key}"
    elapsed_ms   = int((time.time() - started) * 1000)

    return JSONResponse({
        "bucket":             S3_BUCKET,
        "key":                object_key,
        "object_key":         object_key,
        "object_uri":         object_uri,
        "evidence_ref":       object_uri,
        "size_bytes":         size_bytes,
        "sha256":             sha256,
        "kind":               kind,
        "camera_id":          int(camera_id),
        "camera_key":         camera_key,
        "edge_device_key":    edge_device_key,
        "event_id":           event_id,
        "frame_uid":          event_id if kind == "raw_frame" else None,
        "frame_index":        frame_index,
        "captured_at":        captured_at,
        "processing_time_ms": elapsed_ms,
    })

@app.get("/evidence/object")
def get_evidence_object(ref: str):
    """
    Stream an object back from MinIO using a stored s3://... reference.
    """
    try:
        decoded_ref = unquote(ref)
        bucket, object_key = _parse_s3_ref(decoded_ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    client = get_minio()

    try:
        stat = client.stat_object(bucket, object_key)
        obj = client.get_object(bucket, object_key)

        content_type = stat.content_type or mimetypes.guess_type(object_key)[0] or "application/octet-stream"

        return StreamingResponse(
            obj.stream(32 * 1024),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{os.path.basename(object_key)}"'
            },
        )
    except S3Error as e:
        raise HTTPException(status_code=404, detail=f"MinIO error: {e.code} {e.message}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fetch failed: {type(e).__name__}: {e}") from e

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)