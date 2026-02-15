import uuid
import yaml
import time

from camera import CameraSource
from face import InsightFacePipeline
from messaging import KafkaEventProducer

def load_cfg(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    cfg = load_cfg()
    cam = CameraSource(cfg)
    face_pipe = InsightFacePipeline(cfg)
    producer = KafkaEventProducer(cfg)

    every_n = int(cfg["runtime"].get("send_every_n_frames", 2))
    frame_i = 0

    try:
        for frame_bgr, ts_ms in cam.frames():
            frame_i += 1
            if frame_i % every_n != 0:
                continue

            t0 = time.time()
            faces = face_pipe.infer(frame_bgr)
            proc_ms = int((time.time() - t0) * 1000)

            for f in faces:
                event_id = str(uuid.uuid4())
                event = {
                    "event_id": event_id,
                    "camera_id": cfg["kafka"].get("camera_id", "cam_01"),
                    "ts_ms": ts_ms,
                    "processing_time_ms": proc_ms,
                    "model_version": cfg["face"].get("model_name", "buffalo_l"),
                    **f,
                }
                producer.send(event, key=event_id)

    except KeyboardInterrupt:
        pass
    finally:
        producer.close()
        cam.release()

if __name__ == "__main__":
    main()
