# Edge Face Agent (Jetson-ready)

This folder contains a modular edge application that:
1) captures frames (USB now, CSI later)
2) extracts face embeddings via InsightFace
3) publishes events to Kafka (topic `logs` by default)

## Message schema sent to Kafka
Every message includes (as requested):
- event_id
- camera_id
- embedding (512 floats)
- event_type = "face_detected"
- processing_time_ms
- model_version
- quality_score

Plus optional: ts, bbox, location, device_status, image_video_ref.

## Run (dev laptop)
1. Start your server docker-compose (Kafka must be reachable).
2. In this folder:
   ```bash
   pip install -r requirements.txt
   pip install opencv-python numpy insightface PyYAML
   python main.py
   ```

## Deploy to Jetson (high level)
- Copy this folder into your project `edge/edge_face_agent/`
- Set `kafka.bootstrap_servers` to `<SERVER_IP>:9093` in config.yaml
- On Jetson, set camera.type to `csi` and adjust sensor_id/flip_method
- Run `python3 main.py` or register a systemd service.

(We can add a systemd service file next.)
