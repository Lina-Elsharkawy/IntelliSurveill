#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
import torch.nn as nn
from kafka import KafkaProducer
from PIL import Image

# -----------------------------------------------------------------------------
# Same preprocessing / architecture logic as training
# -----------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
IMAGENET_MEAN = torch.tensor([0.485, 0.456, 0.406], dtype=torch.float32).view(3, 1, 1)
IMAGENET_STD = torch.tensor([0.229, 0.224, 0.225], dtype=torch.float32).view(3, 1, 1)


def uniform_sample_paths(paths: Sequence[Path], n: int) -> list[Path]:
    if len(paths) == n:
        return list(paths)
    if len(paths) > n:
        idxs = np.round(np.linspace(0, len(paths) - 1, n)).astype(int)
        return [paths[i] for i in idxs]
    out = list(paths)
    while len(out) < n:
        out.append(paths[-1])
    return out


def load_and_preprocess_image(path: Path, size: int) -> torch.Tensor:
    with Image.open(path) as img:
        img = img.convert("RGB").resize((size, size), Image.BILINEAR)
        arr = np.asarray(img, dtype=np.float32) / 255.0
    x = torch.from_numpy(arr).permute(2, 0, 1).contiguous()
    return (x - IMAGENET_MEAN) / IMAGENET_STD


class FrameStem(nn.Module):
    """Same CNN stem as train_tiny_transformer_v3.py"""
    def __init__(self, d_model: int) -> None:
        super().__init__()
        c1, c2, c3 = 64, 128, 256
        self.net = nn.Sequential(
            nn.Conv2d(3, c1, kernel_size=7, stride=2, padding=3, bias=False),
            nn.BatchNorm2d(c1), nn.GELU(),
            nn.Conv2d(c1, c2, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(c2), nn.GELU(),
            nn.Conv2d(c2, c3, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(c3), nn.GELU(),
            nn.Conv2d(c3, d_model, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(d_model), nn.GELU(),
        )
        self.pool = nn.AdaptiveAvgPool2d((1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.pool(self.net(x)).flatten(1)


class TinyTransformerStudent(nn.Module):
    """Same student architecture as training"""
    def __init__(
        self,
        num_frames: int,
        target_dim: int,
        d_model: int = 256,
        nhead: int = 4,
        num_layers: int = 4,
        dim_feedforward: int = 512,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.num_frames = int(num_frames)
        self.target_dim = int(target_dim)
        self.d_model = int(d_model)

        self.stem = FrameStem(d_model)
        self.pos_embed = nn.Parameter(torch.zeros(1, self.num_frames, d_model))
        self.cls_token = nn.Parameter(torch.zeros(1, 1, d_model))

        enc_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            enc_layer, num_layers=num_layers, norm=nn.LayerNorm(d_model)
        )
        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model * 2, target_dim),
        )

    def forward(self, video: torch.Tensor) -> torch.Tensor:
        # video: [B, T, C, H, W]
        b, t, c, h, w = video.shape
        x = video.reshape(b * t, c, h, w)
        x = self.stem(x).view(b, t, self.d_model)
        x = x + self.pos_embed[:, :t, :]
        cls = self.cls_token.expand(b, -1, -1)
        x = torch.cat([cls, x], dim=1)
        x = self.encoder(x)
        return self.head(x[:, 1:, :].mean(dim=1))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

@dataclass
class ModelRuntimeConfig:
    num_frames: int
    target_dim: int
    d_model: int
    nhead: int
    num_layers: int
    dim_feedforward: int
    dropout: float
    image_size: int


def ts_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def discover_frame_paths(tubelet_dir: Path, expected_frames: int) -> list[Path]:
    frame_paths = sorted(
        p for p in tubelet_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    if not frame_paths:
        raise FileNotFoundError(f"No image frames found in {tubelet_dir}")
    return uniform_sample_paths(frame_paths, expected_frames)


def load_runtime_config(ckpt: dict, config_json_path: Path | None) -> ModelRuntimeConfig:
    mc = ckpt.get("model_config", {}) or {}

    # Optional fallback to config.json if needed
    cfg_json = {}
    if config_json_path is not None and config_json_path.exists():
        with config_json_path.open("r", encoding="utf-8") as f:
            cfg_json = json.load(f)

    def pick(key: str, default):
        if key in mc:
            return mc[key]
        if key in cfg_json:
            return cfg_json[key]
        return default

    return ModelRuntimeConfig(
        num_frames=int(pick("num_frames", pick("expected_frames", 16))),
        target_dim=int(pick("target_dim", 2304)),
        d_model=int(pick("d_model", 256)),
        nhead=int(pick("nhead", 4)),
        num_layers=int(pick("num_layers", 4)),
        dim_feedforward=int(pick("dim_feedforward", 512)),
        dropout=float(pick("dropout", 0.1)),
        image_size=int(pick("image_size", 224)),
    )


def load_student_model(
    checkpoint_path: Path,
    config_json_path: Path | None,
    device: torch.device,
) -> tuple[TinyTransformerStudent, ModelRuntimeConfig]:
    ckpt = torch.load(str(checkpoint_path), map_location=device)
    runtime_cfg = load_runtime_config(ckpt, config_json_path)

    model = TinyTransformerStudent(
        num_frames=runtime_cfg.num_frames,
        target_dim=runtime_cfg.target_dim,
        d_model=runtime_cfg.d_model,
        nhead=runtime_cfg.nhead,
        num_layers=runtime_cfg.num_layers,
        dim_feedforward=runtime_cfg.dim_feedforward,
        dropout=runtime_cfg.dropout,
    ).to(device)

    state = ckpt.get("model_state")
    if not state:
        raise RuntimeError("Checkpoint does not contain 'model_state'.")

    model.load_state_dict(state, strict=True)
    model.eval()
    return model, runtime_cfg


@torch.inference_mode()
def compute_embedding(
    model: TinyTransformerStudent,
    runtime_cfg: ModelRuntimeConfig,
    tubelet_dir: Path,
    device: torch.device,
) -> tuple[np.ndarray, list[Path]]:
    frame_paths = discover_frame_paths(tubelet_dir, runtime_cfg.num_frames)
    frames = [load_and_preprocess_image(p, runtime_cfg.image_size) for p in frame_paths]
    video = torch.stack(frames, dim=0).unsqueeze(0).to(device)  # [1, T, C, H, W]
    emb = model(video).squeeze(0).detach().cpu().numpy().astype(np.float32, copy=False)
    return emb, frame_paths


def build_s3_refs(bucket: str, s3_prefix: str, frame_paths: list[Path]) -> list[str]:
    prefix = s3_prefix.strip("/")

    # Use the actual uploaded filenames from the local tubelet folder.
    return [f"s3://{bucket}/{prefix}/{p.name}" for p in frame_paths]


def send_event(bootstrap: str, topic: str, event: dict) -> tuple[int, int]:
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda v: v.encode("utf-8"),
    )
    future = producer.send(topic, key=event["event_key"], value=event)
    record_metadata = future.get(timeout=15)
    producer.flush()
    producer.close()
    return record_metadata.partition, record_metadata.offset


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute a real student embedding from a tubelet and send to Kafka.")
    p.add_argument("--tubelet-dir", required=True, help="Local folder containing the tubelet frames.")
    p.add_argument("--checkpoint", required=True, help="Path to best_student.pt")
    p.add_argument("--config-json", default="", help="Optional path to config.json")
    p.add_argument("--bootstrap", default="localhost:9092", help="Kafka bootstrap for host-side script.")
    p.add_argument("--topic", default="anomaly_events", help="Kafka topic name.")
    p.add_argument("--bucket", default="evidence", help="MinIO bucket name already holding uploaded frames.")
    p.add_argument("--camera-id", type=int, default=1)
    p.add_argument("--track-id", type=int, default=1)
    p.add_argument("--device-key", default="host-test")
    p.add_argument("--embedding-model", default="student-v3-multiscale")
    p.add_argument("--event-key", required=True, help="Must match the uploaded MinIO folder if you want frame refs to resolve.")
    p.add_argument(
        "--s3-prefix",
        required=True,
        help="Object prefix inside the bucket, e.g. anomalies/cam_1/real_test_0001",
    )
    p.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="Inference device for the local student model.",
    )
    p.add_argument(
        "--offline-l2-threshold",
        type=float,
        default=27.09760856628418,
        help="Your offline p95 L2 threshold; included in metadata for debugging only.",
    )
    return p.parse_args()


def resolve_device(device_arg: str) -> torch.device:
    if device_arg == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(device_arg)


def main() -> None:
    args = parse_args()
    device = resolve_device(args.device)

    tubelet_dir = Path(args.tubelet_dir)
    checkpoint_path = Path(args.checkpoint)
    config_json_path = Path(args.config_json) if args.config_json else None

    if not tubelet_dir.exists():
        raise FileNotFoundError(f"Tubelet dir not found: {tubelet_dir}")
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")
    if config_json_path and not config_json_path.exists():
        raise FileNotFoundError(f"Config JSON not found: {config_json_path}")

    model, runtime_cfg = load_student_model(checkpoint_path, config_json_path, device)
    embedding, frame_paths = compute_embedding(model, runtime_cfg, tubelet_dir, device)
    frames = build_s3_refs(args.bucket, args.s3_prefix, frame_paths)

    now = datetime.now(timezone.utc)
    window_start = now
    window_end = now + timedelta(seconds=4)

    event = {
        "device_key": args.device_key,
        "event_key": args.event_key,
        "camera_id": args.camera_id,
        "track_id": args.track_id,
        "window_start_ts": ts_iso(window_start),
        "window_end_ts": ts_iso(window_end),
        "embedding": embedding.tolist(),
        "embedding_dim": int(embedding.shape[0]),
        "embedding_model": args.embedding_model,
        "frames": frames,
        "metadata": {
            "num_frames": runtime_cfg.num_frames,
            "image_size": runtime_cfg.image_size,
            "student_checkpoint": str(checkpoint_path),
            "tubelet_dir": str(tubelet_dir),
            "device_used": str(device),
            "offline_l2_p95_threshold": args.offline_l2_threshold,
        },
    }

    partition, offset = send_event(args.bootstrap, args.topic, event)

    print("Sent anomaly event to Kafka")
    print(f"bootstrap:       {args.bootstrap}")
    print(f"topic:           {args.topic}")
    print(f"partition:       {partition}")
    print(f"offset:          {offset}")
    print(f"event_key:       {event['event_key']}")
    print(f"embedding_dim:   {event['embedding_dim']}")
    print(f"tubelet_dir:     {tubelet_dir}")
    print(f"window_start_ts: {event['window_start_ts']}")
    print(f"window_end_ts:   {event['window_end_ts']}")
    print("first_frame_ref: ", frames[0] if frames else "<none>")


if __name__ == "__main__":
    main()