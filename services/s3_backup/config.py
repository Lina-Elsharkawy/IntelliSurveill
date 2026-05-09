"""
Pydantic settings for the S3 backup service.
Loaded from environment variables and/or .env file.
"""

from __future__ import annotations

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Immutable environment-based settings."""

    # ── MinIO source ──────────────────────────────────────────────
    minio_endpoint: str = Field("http://minio:9000", description="MinIO endpoint URL")
    minio_access_key: str = Field("minioadmin", description="MinIO access key")
    minio_secret_key: str = Field("minioadmin123", description="MinIO secret key")
    minio_bucket: str = Field("evidence", description="Source MinIO bucket")
    minio_secure: bool = Field(False, description="Use HTTPS for MinIO")

    # ── AWS S3 target ─────────────────────────────────────────────
    aws_access_key_id: str = Field("", description="AWS access key ID")
    aws_secret_access_key: str = Field("", description="AWS secret access key")
    aws_s3_bucket: str = Field("my-evidence-backup", description="Target AWS S3 bucket")
    aws_s3_region: str = Field("us-east-1", description="AWS S3 region")
    aws_s3_prefix: str = Field("evidence-backup/", description="Key prefix in AWS S3")
    aws_s3_endpoint_url: str = Field("", description="Custom S3 endpoint URL (for MinIO / S3-compatible targets)")

    # ── Backup defaults ──────────────────────────────────────────
    backup_prefixes: str = Field(
        "faces/",
        description="Comma-separated MinIO object prefixes to back up",
    )
    backup_interval_hours: int = Field(6, ge=1, le=168, description="Hours between backups")
    sync_state_file: str = Field("/data/sync_state.json", description="Path to sync state file")
    config_file: str = Field("/data/backup_config.json", description="Path to persisted config")

    # ── API ───────────────────────────────────────────────────────
    api_host: str = Field("0.0.0.0", description="API listen host")
    api_port: int = Field(8020, description="API listen port")
    log_level: str = Field("INFO", description="Log level")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()