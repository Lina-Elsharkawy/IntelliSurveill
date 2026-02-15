import json, uuid, time
from kafka import KafkaProducer

BOOTSTRAP = "kafka:9093"
TOPIC = "face_events"

# tiny valid JPEG (1x1) as base64 (just for testing)
TINY_JPG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEA8QDw8PDw8PDw8PDw8PDw8QFREWFhURFRUYHSggGBolGxUVITEhJSkrLi4uFx8zODMtNygtLisBCgoKDg0OGhAQGi0lHyUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBEQACEQEDEQH/xAAXAAEBAQEAAAAAAAAAAAAAAAAAAQID/8QAFhABAQEAAAAAAAAAAAAAAAAAAAEQ/8QAFQEBAQAAAAAAAAAAAAAAAAAAAgP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwDkA//Z"

producer = KafkaProducer(
    bootstrap_servers=BOOTSTRAP,
    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    key_serializer=lambda k: k.encode("utf-8"),
)

event_id = str(uuid.uuid4())
payload = {
    "event_id": event_id,
    "camera_id": 1,
    "ts_ms": int(time.time() * 1000),
    "embedding": [1.0] + [0.0] * 511,
    "face_jpeg_b64": TINY_JPG_B64,
    "processing_time_ms": 10,
    "model_version": "test",
    "quality_score": 0.99,
    "message_type": "face_event",
}

producer.send(TOPIC, key=event_id, value=payload)
producer.flush(5)
print("sent", event_id)
