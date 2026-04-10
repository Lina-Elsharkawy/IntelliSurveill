import argparse
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import yaml

from camera_source import CameraSource
from anomaly_agent import load_student, crops_to_tensor


def center_crop(frame, crop_ratio=0.6):
    h, w = frame.shape[:2]
    cw = int(w * crop_ratio)
    ch = int(h * crop_ratio)
    x1 = max(0, (w - cw) // 2)
    y1 = max(0, (h - ch) // 2)
    x2 = min(w, x1 + cw)
    y2 = min(h, y1 + ch)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return frame
    return crop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--crop-ratio", type=float, default=0.6)
    args = parser.parse_args()

    cfg_path = Path(args.config)
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    scfg = cfg["student"]
    device_str = scfg.get("device", "cuda")
    device = torch.device(
        device_str if (device_str != "cuda" or torch.cuda.is_available()) else "cpu"
    )
    use_fp16 = bool(scfg.get("use_fp16", True)) and device.type == "cuda"

    print(f"device={device} fp16={use_fp16}")

    student, model_cfg = load_student(scfg["checkpoint"], device)
    image_size = int(model_cfg.get("image_size", 224))
    num_frames = int(model_cfg["num_frames"])
    print(f"loaded student: num_frames={num_frames}, image_size={image_size}, cfg={model_cfg}")

    cam = CameraSource(cfg)

    buffer = []
    frame_count = 0

    try:
        for frame, ts_ms in cam.frames():
            frame_count += 1

            crop = center_crop(frame, crop_ratio=args.crop_ratio)
            buffer.append(crop)

            vis = frame.copy()
            cv2.putText(vis, f"buffer={len(buffer)}/{num_frames}", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            cv2.imshow("test_student_inference", vis)

            if len(buffer) < num_frames:
                if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                    break
                continue

            window = buffer[-num_frames:]

            t0 = time.time()
            with torch.no_grad():
                video_tensor = crops_to_tensor(
                    window,
                    image_size=image_size,
                    device=device,
                    use_fp16=use_fp16,
                )

                with torch.autocast(
                    device_type=device.type,
                    enabled=(use_fp16 and device.type == "cuda"),
                ):
                    embedding = student(video_tensor)

            if device.type == "cuda":
                torch.cuda.synchronize()

            dt_ms = (time.time() - t0) * 1000.0
            emb = embedding[0].float().cpu().numpy()

            print(
                f"frame_count={frame_count} "
                f"embedding_shape={tuple(embedding.shape)} "
                f"embedding_dim={emb.shape[0]} "
                f"infer_ms={dt_ms:.2f}"
            )

            # slide by 8 frames to mimic your real stride
            stride = int(cfg.get("anomaly", {}).get("window_stride", 8))
            if stride > 0:
                buffer = buffer[-(num_frames - stride):]
            else:
                buffer = buffer[-num_frames:]

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break

    finally:
        cam.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()