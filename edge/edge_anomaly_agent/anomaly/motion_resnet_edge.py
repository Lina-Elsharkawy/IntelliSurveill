import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Tuple, Optional

import cv2
import numpy as np
import psutil
import torch
import torchvision.models as models
import torchvision.transforms as transforms
import yaml

from camera_source import CameraSource
from kafka_producer import AnomalyEventProducer


# -------------------------
# Config loading
# -------------------------
def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_ram_usage_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def sample_evenly(frames: List[np.ndarray], k: int) -> List[np.ndarray]:
    if not frames:
        return []
    k = max(1, int(k))
    if len(frames) <= k:
        return frames
    idx = np.linspace(0, len(frames) - 1, k).astype(int)
    return [frames[int(i)] for i in idx]


def downscale(frame_bgr: np.ndarray, target_w: int) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    if w <= target_w:
        return frame_bgr
    scale = target_w / float(w)
    new_h = max(1, int(h * scale))
    return cv2.resize(frame_bgr, (target_w, new_h), interpolation=cv2.INTER_AREA)


def l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v) + 1e-12)
    return (v / n).astype(np.float32)


def embedding_pca_placeholder_128(emb512: np.ndarray) -> List[float]:
    """Temporary bridge until you plug in your real PCA (512 -> 128).

    We take the first 128 dims and L2-normalize.
    This satisfies the backend schema and lets you test the pipeline end-to-end.
    """
    emb512 = np.asarray(emb512, dtype=np.float32).reshape(-1)
    if emb512.size < 128:
        out = np.zeros((128,), dtype=np.float32)
        out[: emb512.size] = emb512
        return l2_normalize(out).tolist()
    return l2_normalize(emb512[:128]).tolist()


def make_event_key(device_key: str, camera_id: int, w_start_ms: int, w_end_ms: int) -> str:
    return f"{device_key}:cam_{camera_id}:{w_start_ms}-{w_end_ms}"


# -------------------------
# Motion detector (MOG2)
# -------------------------
@dataclass
class MotionSettings:
    mog2_history: int
    mog2_var_threshold: int
    mog2_detect_shadows: bool
    learning_rate: float

    min_object_area: int
    fast_pass_area: int
    min_motion_frames: int
    cooldown_sec: float

    buffer_seconds: float
    motion_downscale_width: int
    morph_kernel: int
    dilate_iters: int


class MotionDetector:
    def __init__(self, s: MotionSettings):
        self.s = s
        self.fgbg = cv2.createBackgroundSubtractorMOG2(
            history=self.s.mog2_history,
            varThreshold=self.s.mog2_var_threshold,
            detectShadows=self.s.mog2_detect_shadows,
        )
        self.kernel = np.ones((self.s.morph_kernel, self.s.morph_kernel), np.uint8)

    def step(self, frame_bgr: np.ndarray) -> Tuple[bool, bool]:
        small = downscale(frame_bgr, self.s.motion_downscale_width)

        fgmask = self.fgbg.apply(small, learningRate=self.s.learning_rate)
        _, fgmask = cv2.threshold(fgmask, 250, 255, cv2.THRESH_BINARY)

        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, self.kernel)
        fgmask = cv2.dilate(fgmask, self.kernel, iterations=self.s.dilate_iters)

        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        movement = False
        fast_pass = False
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > self.s.min_object_area:
                movement = True
                if area > self.s.fast_pass_area:
                    fast_pass = True

        return movement, fast_pass


# -------------------------
# ResNet-18 embedder (edge-friendly)
# -------------------------
@dataclass
class EmbedSettings:
    embedding_model: str
    sample_count: int
    use_cuda_if_available: bool
    use_fp16_on_cuda: bool
    warmup_batches: int


class ResNet18Embedder:
    def __init__(self, s: EmbedSettings):
        self.s = s
        self.device = "cuda" if (self.s.use_cuda_if_available and torch.cuda.is_available()) else "cpu"

        if self.device == "cuda":
            torch.backends.cudnn.benchmark = True

        resnet = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        backbone = torch.nn.Sequential(*list(resnet.children())[:-1])  # remove classifier head
        backbone.eval().to(self.device)

        self.fp16 = (self.device == "cuda" and self.s.use_fp16_on_cuda)
        if self.fp16:
            backbone = backbone.half()

        self.backbone = backbone

        self.preprocess = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225]),
        ])

        self._warmup()

    def _warmup(self):
        if self.s.warmup_batches <= 0:
            return
        dummy = np.zeros((224, 224, 3), dtype=np.uint8)
        tensors = [self.preprocess(dummy).unsqueeze(0) for _ in range(8)]
        batch = torch.cat(tensors, dim=0).to(self.device)
        if self.fp16:
            batch = batch.half()

        with torch.no_grad():
            for _ in range(self.s.warmup_batches):
                y = self.backbone(batch)
                _ = y.view(y.size(0), -1)

    def embed_window(self, frames_bgr: List[np.ndarray]) -> Tuple[np.ndarray, float]:
        if not frames_bgr:
            return np.zeros((512,), dtype=np.float32), 0.0

        tensors = [self.preprocess(f).unsqueeze(0) for f in frames_bgr]
        batch = torch.cat(tensors, dim=0).to(self.device)
        if self.fp16:
            batch = batch.half()

        t0 = time.time()
        with torch.no_grad():
            e = self.backbone(batch)          # [N, 512, 1, 1]
            e = e.view(e.size(0), -1)         # [N, 512]
            e = torch.nn.functional.normalize(e, dim=-1)
            mean_e = e.mean(dim=0)
            mean_e = torch.nn.functional.normalize(mean_e, dim=0)
        t1 = time.time()

        return mean_e.detach().float().cpu().numpy(), (t1 - t0) * 1000.0


# -------------------------
# Main
# -------------------------
def main():
    cfg = load_config("config.yaml")

    # Required IDs for the backend anomaly-service contract
    device_key = str(cfg.get("device_key", "unknown_device"))
    camera_id = int(cfg.get("camera_id", 1))

    cam_cfg = cfg["camera"]
    fps = int(cam_cfg.get("fps", 10))

    buffer_seconds = float(cfg["anomaly"]["buffer_seconds"])
    buffer_len = max(1, int(buffer_seconds * max(1, fps)))

    evidence_frames = int(cfg["anomaly"].get("evidence_frames", 8))
    jpg_quality = int(cfg["anomaly"].get("jpg_quality", 85))
    threshold = float(cfg["anomaly"].get("threshold", 1.0))
    model_version = str(cfg["anomaly"].get("model_version", "edge-motion-resnet"))
    embedding_model = str(cfg["embedding"].get("embedding_model", "resnet18"))

    motion_s = MotionSettings(
        mog2_history=int(cfg["anomaly"]["mog2_history"]),
        mog2_var_threshold=int(cfg["anomaly"]["mog2_var_threshold"]),
        mog2_detect_shadows=bool(cfg["anomaly"]["mog2_detect_shadows"]),
        learning_rate=float(cfg["anomaly"]["learning_rate"]),

        min_object_area=int(cfg["anomaly"]["min_object_area"]),
        fast_pass_area=int(cfg["anomaly"]["fast_pass_area"]),
        min_motion_frames=int(cfg["anomaly"]["min_motion_frames"]),
        cooldown_sec=float(cfg["anomaly"]["cooldown_sec"]),

        buffer_seconds=buffer_seconds,
        motion_downscale_width=int(cfg["anomaly"]["motion_downscale_width"]),
        morph_kernel=int(cfg["anomaly"]["morph_kernel"]),
        dilate_iters=int(cfg["anomaly"]["dilate_iters"]),
    )

    emb_s = EmbedSettings(
        embedding_model=embedding_model,
        sample_count=int(cfg["embedding"]["sample_count"]),
        use_cuda_if_available=bool(cfg["embedding"]["use_cuda_if_available"]),
        use_fp16_on_cuda=bool(cfg["embedding"]["use_fp16_on_cuda"]),
        warmup_batches=int(cfg["embedding"]["warmup_batches"]),
    )

    cam = CameraSource(cfg)
    detector = MotionDetector(motion_s)
    embedder = ResNet18Embedder(emb_s)
    producer = AnomalyEventProducer(cfg)

    frame_buffer: Deque[np.ndarray] = deque(maxlen=buffer_len)
    ts_buffer: Deque[int] = deque(maxlen=buffer_len)

    motion_counter = 0
    last_trigger = 0.0
    last_stats = time.time()
    stats_every_sec = float(cfg["anomaly"].get("print_every_sec", 5.0))

    print("motion_resnet_edge.py starting...")
    print(f"camera.type={cam_cfg['type']} fps={fps} buffer_len={buffer_len} (buffer_seconds={buffer_seconds})")
    print(f"embed.device={embedder.device} fp16={embedder.fp16} sample_count={emb_s.sample_count}")
    print(f"kafka.bootstrap={cfg.get('kafka',{}).get('bootstrap_servers')} topic={cfg.get('kafka',{}).get('topic_anomaly')}")
    print(f"evidence.upload_url={cfg.get('evidence_gateway',{}).get('upload_url')}")
    print(f"device_key={device_key} camera_id={camera_id}")

    try:
        for frame, ts_ms in cam.frames():
            frame_buffer.append(frame)
            ts_buffer.append(ts_ms)

            movement, fast_pass = detector.step(frame)

            if movement:
                motion_counter += 1
            else:
                motion_counter = 0

            now = time.time()

            triggered = (motion_counter >= motion_s.min_motion_frames) or (fast_pass and motion_counter >= 2)
            if triggered and (now - last_trigger) > motion_s.cooldown_sec:
                window_frames = list(frame_buffer)
                window_ts = list(ts_buffer)
                w_start = int(window_ts[0] if window_ts else ts_ms)
                w_end = int(window_ts[-1] if window_ts else ts_ms)

                # Embedding
                embed_frames = sample_evenly(window_frames, emb_s.sample_count)
                emb512, emb_ms = embedder.embed_window(embed_frames)
                emb_pca_128 = embedding_pca_placeholder_128(emb512)

                # Evidence upload
                evidence_sel = sample_evenly(window_frames, evidence_frames)
                event_key = make_event_key(device_key, camera_id, w_start, w_end)

                upload_t0 = time.time()
                frame_refs: List[str] = []
                for i, fr in enumerate(evidence_sel):
                    try:
                        ref = producer.upload_frame(
                            frame_bgr=fr,
                            event_id=event_key,     # keep event_id == event_key
                            camera_id=camera_id,
                            frame_index=i,
                            jpg_quality=jpg_quality,
                        )
                        frame_refs.append(ref)
                    except Exception as e:
                        print(f"[EVIDENCE][ERROR] event_key={event_key} frame_index={i} err={e}")

                upload_ms = int((time.time() - upload_t0) * 1000)

                # Kafka send
                novelty_score = float(motion_counter) / float(max(1, motion_s.min_motion_frames))
                try:
                    producer.send_scene_window_event(
                        device_key=device_key,
                        event_key=event_key,
                        camera_id=camera_id,
                        window_start_ts=str(w_start),
                        window_end_ts=str(w_end),
                        embedding_pca=emb_pca_128,         # MUST be len 128
                        embedding_model=embedding_model,
                        frames=frame_refs,
                        novelty_score=novelty_score,
                        threshold=threshold,
                        model_version=model_version,
                        processing_time_ms=int(emb_ms) + upload_ms,
                        extra={
                            "buffer_len": buffer_len,
                            "buffer_seconds": buffer_seconds,
                            "fps": fps,
                            "evidence_frames": evidence_frames,
                            "embed_sample_count": emb_s.sample_count,
                            "embed_device": embedder.device,
                            "embed_fp16": bool(embedder.fp16),
                        },
                    )
                    print(f"[KAFKA][ANOM] sent event_key={event_key} frames={len(frame_refs)} emb_ms={emb_ms:.1f} upload_ms={upload_ms}")
                except Exception as e:
                    print(f"[KAFKA][ERROR] event_key={event_key} err={e}")

                ram_mb = get_ram_usage_mb()
                print("\n==============================")
                print("🚨 MOTION WINDOW TRIGGERED")
                print(f"event_key              : {event_key}")
                print(f"window_start_ts_ms     : {w_start}")
                print(f"window_end_ts_ms       : {w_end}")
                print(f"window_frames_total    : {len(window_frames)}")
                print(f"embed_frames_sample    : {len(embed_frames)}")
                print(f"evidence_frames_upload : {len(frame_refs)}")
                print(f"embedding_dim          : {emb512.shape[0]}")
                print(f"embed_time_ms          : {emb_ms:.2f}")
                print(f"ram_mb                 : {ram_mb:.2f}")
                print("==============================\n")

                last_trigger = now
                motion_counter = 0

            if (now - last_stats) >= stats_every_sec:
                ram_mb = get_ram_usage_mb()
                print(f"[stats] ram_mb={ram_mb:.1f} motion_counter={motion_counter} buffer={len(frame_buffer)}")
                last_stats = now

    finally:
        cam.release()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
