import io
import os
import time
import hashlib
import mimetypes
from typing import Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from minio import Minio
from minio.error import S3Error

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


def _build_object_key(
    kind:        str,
    camera_id:   int,
    event_id:    str,
    ext:         str,
    frame_index: Optional[int],
) -> str:
    ext = (ext or "jpg").lstrip(".").lower()

    if kind == "face":
        # One image per event
        return f"faces/cam_{camera_id}/{event_id}.{ext}"

    if kind == "anomaly":
        # 16 person-crop frames per event, organized by event_id folder
        if frame_index is not None:
            return f"anomalies/cam_{camera_id}/{event_id}/frame_{frame_index:06d}.{ext}"
        return f"anomalies/cam_{camera_id}/{event_id}/{event_id}.{ext}"

    return f"misc/cam_{camera_id}/{event_id}.{ext}"


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
    kind:        str             = Form(...),        # "face" | "anomaly"
    frame_index: Optional[int]  = Form(None),
    ext:         Optional[str]  = Form(None),
) -> JSONResponse:
    kind = (kind or "").strip().lower()
    if kind not in ("face", "anomaly"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid kind={kind!r}. Must be 'face' or 'anomaly'.",
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

    # Determine extension
    use_ext = ext or os.path.splitext(file.filename or "")[1].lstrip(".") or "jpg"

    object_key   = _build_object_key(kind, int(camera_id), event_id, use_ext, frame_index)
    content_type = _guess_content_type(
        file.filename or f"{event_id}.{use_ext}", file.content_type
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

    evidence_ref = f"s3://{S3_BUCKET}/{object_key}"
    elapsed_ms   = int((time.time() - started) * 1000)

    return JSONResponse({
        "bucket":             S3_BUCKET,
        "key":                object_key,
        "evidence_ref":       evidence_ref,
        "size_bytes":         size_bytes,
        "sha256":             sha256,
        "kind":               kind,
        "camera_id":          int(camera_id),
        "event_id":           event_id,
        "frame_index":        frame_index,
        "processing_time_ms": elapsed_ms,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)