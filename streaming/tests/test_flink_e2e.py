import os
import pytest
import json
import time
import uuid
from kafka import KafkaProducer, KafkaConsumer

KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

@pytest.fixture(scope="module")
def kafka_producer():
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )

def test_frequency_anomaly_detection(kafka_producer):
    """
    End-to-End test for Flink Frequency Anomaly Detection.
    1. Produce > 5 messages for a specific camera_id within a short window.
    2. Listen to 'frequency_alerts' topic.
    3. Verify an alert is received for that camera_id.
    """
    camera_id = f"test-cam-{uuid.uuid4()}"
    
    # 1. Produce messages
    # The Flink job looks for > 5 messages in 30s.
    print(f"Sending 10 log entries for {camera_id}...")
    for i in range(10):
        message = {
            "camera_id": camera_id,
            "timestamp": str(time.time()),
            "event_type": "entry_attempt"
        }
        kafka_producer.send('logs', value=message)
    
    kafka_producer.flush()
    
    # 2. Consume alerts
    print("Listening for alerts...")
    consumer = KafkaConsumer(
        'frequency_alerts',
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='latest', # Only look for new alerts
        consumer_timeout_ms=30000, # Wait up to 30s (Flink window is 30s)
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )
    
    alert_received = False
    start_time = time.time()
    
    for msg in consumer:
        data = msg.value
        print(f"Received alert: {data}")
        if data.get('camera_id') == camera_id:
            alert_received = True
            # Verify structure
            assert data.get('anomaly_type') == 'Frequency'
            assert 'description' in data
            break
            
        if time.time() - start_time > 30:
            break
            
    consumer.close()
    
    assert alert_received, f"Did not receive frequency alert for {camera_id} within timeout"
