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

# ----------------------------
# Config (env)
# ----------------------------
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000").strip()
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
S3_BUCKET = os.getenv("S3_BUCKET", "evidence")

# If MINIO_ENDPOINT includes http:// or https://, we derive secure from scheme.
# You can also force it with MINIO_SECURE=true/false
MINIO_SECURE_ENV = os.getenv("MINIO_SECURE", "").lower().strip()
FORCE_SECURE: Optional[bool] = None
if MINIO_SECURE_ENV in ("true", "1", "yes"):
    FORCE_SECURE = True
elif MINIO_SECURE_ENV in ("false", "0", "no"):
    FORCE_SECURE = False

PORT = int(os.getenv("PORT", "8010"))

# Limits (optional)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MB default

# ----------------------------
# Helpers
# ----------------------------
def _parse_endpoint(endpoint: str) -> tuple[str, bool]:
    """Return (host:port, secure) for Minio client."""
    ep = endpoint
    if ep.startswith("http://"):
        host = ep[len("http://") :]
        secure = False
    elif ep.startswith("https://"):
        host = ep[len("https://") :]
        secure = True
    else:
        # Minio expects host:port; assume not secure unless forced
        host = ep
        secure = False
    if FORCE_SECURE is not None:
        secure = FORCE_SECURE
    return host, secure


def _guess_content_type(filename: str, provided: Optional[str]) -> str:
    if provided and provided != "application/octet-stream":
        return provided
    ct, _ = mimetypes.guess_type(filename)
    return ct or "application/octet-stream"


def _ensure_bucket(client: Minio, bucket: str) -> None:
    # Auto-create bucket if missing
    found = client.bucket_exists(bucket)
    if not found:
        client.make_bucket(bucket)


def _build_object_key(kind: str, camera_id: int, event_id: str, ext: str, frame_index: Optional[int]) -> str:
    ext = (ext or "jpg").lstrip(".").lower()

    if kind == "face":
        # One image per event_id
        return f"faces/cam_{camera_id}/{event_id}.{ext}"

    if kind == "anomaly":
        # Potentially many frames per event_id
        if frame_index is not None:
            return f"anomalies/cam_{camera_id}/{event_id}/frame_{frame_index:06d}.{ext}"
        # If frame_index not provided, store as a single artifact
        return f"anomalies/cam_{camera_id}/{event_id}/{event_id}.{ext}"

    # Future-proof (should not happen due to validation)
    return f"misc/cam_{camera_id}/{event_id}.{ext}"


# ----------------------------
# App
# ----------------------------
app = FastAPI(title=APP_NAME, version="1.0.0")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "service": APP_NAME,
        "status": "ok",
        "bucket": S3_BUCKET,
    }


@app.post("/evidence/upload")
async def upload_evidence(
    file: UploadFile = File(...),
    event_id: str = Form(...),
    camera_id: int = Form(...),
    kind: str = Form(...),  # "face" | "anomaly"
    frame_index: Optional[int] = Form(None),
    ext: Optional[str] = Form(None),
) -> JSONResponse:
    kind = (kind or "").strip().lower()
    if kind not in ("face", "anomaly"):
        raise HTTPException(status_code=400, detail=f"Invalid kind: {kind}. Must be 'face' or 'anomaly'.")

    # Read bytes (we want sha256 + size; also enforce size cap)
    start = time.time()
    data = await file.read()

    size_bytes = len(data)
    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Upload too large: {size_bytes} bytes > MAX_UPLOAD_BYTES={MAX_UPLOAD_BYTES}.",
        )

    sha256 = hashlib.sha256(data).hexdigest()

    # Decide extension
    if ext:
        use_ext = ext
    else:
        # derive from filename if possible, else jpg
        use_ext = os.path.splitext(file.filename or "")[1].lstrip(".") or "jpg"

    object_key = _build_object_key(kind, int(camera_id), event_id, use_ext, frame_index)

    # MinIO client
    host, secure = _parse_endpoint(MINIO_ENDPOINT)
    client = Minio(
        host,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=secure,
    )

    # Ensure bucket and upload
    try:
        _ensure_bucket(client, S3_BUCKET)

        content_type = _guess_content_type(file.filename or f"{event_id}.{use_ext}", file.content_type)

        # Put object
        client.put_object(
            bucket_name=S3_BUCKET,
            object_name=object_key,
            data=io_bytes(data),
            length=size_bytes,
            content_type=content_type,
        )

    except S3Error as e:
        raise HTTPException(status_code=502, detail=f"MinIO error: {e.code} {e.message}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}: {e}") from e

    evidence_ref = f"s3://{S3_BUCKET}/{object_key}"
    elapsed_ms = int((time.time() - start) * 1000)

    return JSONResponse(
        {
            "bucket": S3_BUCKET,
            "key": object_key,
            "evidence_ref": evidence_ref,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "kind": kind,
            "camera_id": int(camera_id),
            "event_id": event_id,
            "frame_index": frame_index,
            "processing_time_ms": elapsed_ms,
        }
    )


# ----------------------------
# Small helper: bytes -> stream
# ----------------------------
class io_bytes:
    """
    Minimal file-like wrapper for Minio put_object to avoid importing BytesIO everywhere.
    """
    def __init__(self, b: bytes):
        self._b = b
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._b) - self._pos
        chunk = self._b[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
