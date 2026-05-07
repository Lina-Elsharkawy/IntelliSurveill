"""
Evidence I/O helpers for the dual-stream anomaly service.

This module only reads evidence. Uploading remains the responsibility of
edge/services/evidence_gateway/app.py.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Optional
from urllib.parse import quote

import cv2  # type: ignore
import numpy as np
import requests

EVIDENCE_GATEWAY_OBJECT_URL = os.getenv(
    "EVIDENCE_GATEWAY_OBJECT_URL",
    "http://evidence-gateway:8010/evidence/object",
).rstrip("?")
EVIDENCE_FETCH_TIMEOUT_SEC = float(os.getenv("EVIDENCE_FETCH_TIMEOUT_SEC", "15"))

_IMAGE_PREFIXES = (
    "data:image/jpeg;base64,",
    "data:image/jpg;base64,",
    "data:image/png;base64,",
)


def _normalise_ref(ref: Any) -> Optional[str]:
    if ref is None or isinstance(ref, bytes):
        return None
    value = str(ref).strip()
    return value or None


def evidence_object_url(ref: str) -> str:
    """
    Convert an evidence reference into a retrievable URL.

    http(s) refs are returned unchanged.
    s3:// refs are routed through the evidence-gateway /evidence/object endpoint.
    """
    ref = ref.strip()
    if ref.startswith(("http://", "https://")):
        return ref
    if ref.startswith("s3://"):
        return f"{EVIDENCE_GATEWAY_OBJECT_URL}?ref={quote(ref, safe='')}"
    return ref


def _strip_data_uri_prefix(value: str) -> str:
    lower = value.lower()
    for prefix in _IMAGE_PREFIXES:
        if lower.startswith(prefix):
            return value[len(prefix):]
    return value


def _try_decode_base64(value: str) -> Optional[bytes]:
    try:
        raw = _strip_data_uri_prefix(value).strip()
        if raw.startswith(("s3://", "http://", "https://", "/", "./", "../")):
            return None
        if len(raw) < 32:
            return None
        return base64.b64decode(raw, validate=True)
    except Exception:
        return None


def fetch_bytes(ref: Any) -> Optional[bytes]:
    """
    Fetch raw bytes from bytes, base64/data URI, local file path, http(s), or s3://.
    """
    if ref is None:
        return None
    if isinstance(ref, bytes):
        return ref

    value = _normalise_ref(ref)
    if not value:
        return None

    decoded = _try_decode_base64(value)
    if decoded is not None:
        return decoded

    url_or_path = evidence_object_url(value)

    try:
        p = Path(url_or_path)
        if p.exists() and p.is_file():
            return p.read_bytes()
    except Exception:
        pass

    if not url_or_path.startswith(("http://", "https://")):
        return None

    try:
        resp = requests.get(url_or_path, timeout=EVIDENCE_FETCH_TIMEOUT_SEC)
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


def _decode_image_bgr(data: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img if img is not None else None


def fetch_frames(frames: Iterable[Any]) -> List[np.ndarray]:
    """Decode frame refs/base64 images into OpenCV BGR frames."""
    images: List[np.ndarray] = []
    for frame in frames or []:
        data = fetch_bytes(frame)
        if not data:
            continue
        img = _decode_image_bgr(data)
        if img is not None:
            images.append(img)
    return images


def fetch_jpeg_bytes(ref: Any) -> Optional[bytes]:
    """Return image bytes suitable for Ollama VLM."""
    data = fetch_bytes(ref)
    if not data:
        return None
    if data.startswith(b"\xff\xd8\xff"):
        return data
    img = _decode_image_bgr(data)
    if img is None:
        return data
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None
    return bytes(buf)


def fetch_image_rgb(ref: Any) -> Optional[np.ndarray]:
    data = fetch_bytes(ref)
    if not data:
        return None
    img_bgr = _decode_image_bgr(data)
    if img_bgr is None:
        return None
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)


def sample_frames(frames: List[Any], num_frames: int) -> List[Any]:
    """Uniformly sample up to num_frames from a frame list."""
    if not isinstance(frames, list) or num_frames <= 0:
        return []
    n = len(frames)
    if n <= num_frames:
        return frames
    if num_frames == 1:
        return [frames[n // 2]]
    indices = np.linspace(0, n - 1, num_frames).round().astype(int).tolist()
    return [frames[i] for i in indices]


def fetch_clip_frames(ref: Any, n: int = 4) -> List[np.ndarray]:
    """
    Download/read a video clip and sample up to n frames as OpenCV BGR arrays.
    Supports local paths, http(s), and s3:// refs via evidence-gateway.
    """
    value = _normalise_ref(ref)
    if not value:
        return []

    local_path: Optional[str] = None
    try:
        p = Path(value)
        if p.exists() and p.is_file():
            local_path = str(p)
    except Exception:
        local_path = None

    tmp_path: Optional[str] = None
    if local_path is None:
        data = fetch_bytes(value)
        if not data:
            return []
        suffix = ".mp4"
        lower = value.lower()
        for ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            if lower.endswith(ext):
                suffix = ext
                break
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(data)
            tmp.flush()
            tmp_path = tmp.name
        finally:
            tmp.close()
        local_path = tmp_path

    frames: List[np.ndarray] = []
    cap = cv2.VideoCapture(local_path)
    try:
        if not cap.isOpened():
            return []
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total > 0:
            indices = np.linspace(0, max(total - 1, 0), max(1, n)).round().astype(int).tolist()
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ok, frame = cap.read()
                if ok and frame is not None:
                    frames.append(frame)
        else:
            all_frames: List[np.ndarray] = []
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                all_frames.append(frame)
                if len(all_frames) > 512:
                    break
            frames = sample_frames(all_frames, n)
    finally:
        cap.release()
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return frames[:n]
