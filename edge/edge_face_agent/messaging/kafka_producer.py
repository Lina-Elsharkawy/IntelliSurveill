import json
from kafka import KafkaProducer


class KafkaEventProducer:
    def __init__(self, cfg: dict):
        kcfg = cfg["kafka"]
        self.topic = kcfg["topic"]

        self.producer = KafkaProducer(
            bootstrap_servers=kcfg["bootstrap_servers"],
            acks="all",
            retries=10,
            linger_ms=10,
            compression_type="lz4",
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8"),
            max_request_size=5_000_000,
        )

    def send(self, event: dict, key: str):
        # async send
        self.producer.send(self.topic, key=key, value=event)

    def flush(self):
        self.producer.flush(timeout=5)

    def close(self):
        try:
            self.flush()
        finally:
            self.producer.close()
