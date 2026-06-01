from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from minio import Minio

from .config import VadConfig

log = logging.getLogger("vad.minio_client")


@dataclass(frozen=True)
class UploadedObject:
    bucket: str
    object_key: str
    uri: str
    content_type: str
    size_bytes: int
    sha256: str


class VadMinioClient:
    """Small lazy MinIO wrapper for anomaly evidence only."""

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.enabled = bool(cfg.evidence_enabled)
        self.bucket = cfg.minio_bucket
        self._client: Minio | None = None
        self._public_client: Minio | None = None
        self._bucket_ready = False

    def _get_client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                self.cfg.minio_endpoint,
                access_key=self.cfg.minio_access_key,
                secret_key=self.cfg.minio_secret_key,
                secure=self.cfg.minio_secure,
            )
        if not self._bucket_ready:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
                log.info("Created MinIO bucket %s", self.bucket)
            self._bucket_ready = True
        return self._client

    def _get_public_client(self) -> Minio:
        if self._public_client is None:
            self._public_client = Minio(
                self.cfg.minio_public_endpoint,
                access_key=self.cfg.minio_access_key,
                secret_key=self.cfg.minio_secret_key,
                secure=self.cfg.minio_public_secure,
                region="us-east-1"
            )
        return self._public_client

    def upload_bytes(self, *, object_key: str, data: bytes, content_type: str, metadata: dict[str, Any] | None = None) -> UploadedObject:
        if not self.enabled:
            raise RuntimeError("VAD evidence storage is disabled")
        object_key = object_key.strip().lstrip("/")
        payload = bytes(data)
        sha = hashlib.sha256(payload).hexdigest()
        client = self._get_client()
        client.put_object(
            self.bucket,
            object_key,
            BytesIO(payload),
            length=len(payload),
            content_type=content_type,
            metadata={str(k): str(v) for k, v in (metadata or {}).items()},
        )
        return UploadedObject(
            bucket=self.bucket,
            object_key=object_key,
            uri=f"minio://{self.bucket}/{object_key}",
            content_type=content_type,
            size_bytes=len(payload),
            sha256=sha,
        )

    def generate_presigned_url(self, object_key: str, expires_in_sec: int = 3600) -> str:
        if not self.enabled:
            return ""
        from datetime import timedelta
        client = self._get_public_client()
        return client.presigned_get_object(self.bucket, object_key, expires=timedelta(seconds=expires_in_sec))

    def download_bytes(self, object_key: str) -> bytes:
        """Download one MinIO object as bytes for the reasoning worker."""
        if not self.enabled:
            raise RuntimeError("VAD evidence storage is disabled")
        object_key = object_key.strip().lstrip("/")
        client = self._get_client()
        response = client.get_object(self.bucket, object_key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
