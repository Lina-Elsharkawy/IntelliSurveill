import json
import os
import time
import uuid
from kafka import KafkaProducer

# --------- EDIT THESE ---------
KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "<BACKEND_IP>:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "anomaly_events")
DEVICE_KEY = os.getenv("DEVICE_KEY", "jetson_test_01")
CAMERA_ID = int(os.getenv("CAMERA_ID", "1"))
# ------------------------------

def main():
    # Create a deterministic window
    now_ms = int(time.time() * 1000)
    w_start = str(now_ms - 4000)
    w_end = str(now_ms)

    event_key = f"{DEVICE_KEY}:cam_{CAMERA_ID}:{w_start}-{w_end}"

    # 128 floats required by anomaly-service
    embedding_pca = [0.01] * 128

    payload = {
        "event_type": "scene_window",
        "event_key": event_key,
        "device_key": DEVICE_KEY,
        "camera_id": CAMERA_ID,
        "window_start_ts": w_start,
        "window_end_ts": w_end,
        "embedding_model": "test",
        "embedding_pca": embedding_pca,

        # Optional fields
        "frames": ["s3://evidence/anomalies/cam_1/host_test_event_1/frame_000000.jpg"],
        "novelty_score": 1.0,
        "threshold": 0.7,
        "model_version": "edge-test",
        "processing_time_ms": 10,
        "metadata": {"source": "test_anomaly_kafka_produce.py"},
    }

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        retries=5,
        linger_ms=50,
    )

    producer.send(TOPIC, payload)
    producer.flush(10)
    print("✅ Sent anomaly event to Kafka")
    print("bootstrap:", KAFKA_BOOTSTRAP)
    print("topic:", TOPIC)
    print("event_key:", event_key)

if __name__ == "__main__":
    main()
