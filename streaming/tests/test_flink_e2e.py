"""
End-to-End Tests for Flink Frequency Anomaly Detection Pipeline.

Tests the complete flow:
1. Produce log events to Kafka 'logs' topic
2. Verify Flink job processes and emits alerts to 'frequency_alerts'
3. Verify data is written to PostgreSQL

Prerequisites:
- Kafka and Flink services running
- PostgreSQL with logging_db database
- Valid detected_people and cameras records in DB
"""

import os
import pytest
import json
import time
import uuid
import psycopg2
from kafka import KafkaProducer, KafkaConsumer

# Configuration from environment
KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9093')
POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
POSTGRES_DB = os.environ.get('POSTGRES_DB', 'logging_db')
POSTGRES_USER = os.environ.get('POSTGRES_USER', 'mohamed')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'mohamed')


@pytest.fixture(scope="module")
def kafka_producer():
    """Create Kafka producer with JSON serialization."""
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        retries=5
    )
    yield producer
    producer.close()


@pytest.fixture(scope="module")
def db_connection():
    """Create PostgreSQL connection."""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    yield conn
    conn.close()


def get_valid_ids(db_connection):
    """Get valid detected_id and camera_id from DB."""
    cursor = db_connection.cursor()
    cursor.execute("SELECT id FROM detected_people LIMIT 1")
    detected_id = cursor.fetchone()
    cursor.execute("SELECT id FROM cameras LIMIT 1")
    camera_id = cursor.fetchone()
    cursor.close()
    
    if not detected_id or not camera_id:
        pytest.skip("No valid detected_people or cameras in DB")
    
    return detected_id[0], camera_id[0]


class TestFrequencyAnomalyDetection:
    """E2E tests for frequency anomaly detection."""

    def test_alert_emitted_when_threshold_exceeded(self, kafka_producer, db_connection):
        """
        Verify that an alert is emitted when event count exceeds threshold.
        
        Steps:
        1. Get valid IDs from DB (to satisfy FK constraints)
        2. Produce 10 events for a specific camera within 30s
        3. Consume from frequency_alerts topic
        4. Verify alert is received with correct structure
        """
        detected_id, camera_id = get_valid_ids(db_connection)
        
        # Produce 10 events rapidly
        print(f"Sending 10 events for camera_id={camera_id}, detected_id={detected_id}")
        for _ in range(10):
            message = {
                "detected_id": detected_id,
                "camera_id": camera_id,
                "timestamp": str(int(time.time())),
                "event_type": "entry_attempt",
                "authorized": True,
                "location": "Test Location"
            }
            kafka_producer.send('logs', value=message)
        
        kafka_producer.flush()
        print("Messages sent, waiting for alert...")

        # Consume alerts
        consumer = KafkaConsumer(
            'frequency_alerts',
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset='latest',
            consumer_timeout_ms=35000,  # Flink window is 30s
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        
        alert_received = False
        matching_alert = None
        start_time = time.time()
        
        for msg in consumer:
            data = msg.value
            print(f"Received alert: {data}")
            
            if data.get('camera_id') == camera_id:
                alert_received = True
                matching_alert = data
                break
            
            if time.time() - start_time > 35:
                break
        
        consumer.close()
        
        assert alert_received, f"Did not receive alert for camera_id={camera_id}"
        assert matching_alert.get('anomaly_type') == 'FREQUENCY_ANOMALY'
        assert 'description' in matching_alert
        assert 'count' in matching_alert
        assert matching_alert['count'] > 5  # Should exceed threshold

    def test_events_written_to_entry_logs_table(self, kafka_producer, db_connection):
        """
        Verify that log events are written to entry_logs table.
        
        Steps:
        1. Get initial count from entry_logs
        2. Produce events
        3. Wait for JDBC batch flush
        4. Verify count increased
        """
        detected_id, camera_id = get_valid_ids(db_connection)
        
        cursor = db_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM entry_logs")
        initial_count = cursor.fetchone()[0]
        
        # Produce 5 events
        for _ in range(5):
            message = {
                "detected_id": detected_id,
                "camera_id": camera_id,
                "timestamp": str(int(time.time())),
                "event_type": "db_test",
                "authorized": True,
                "location": "DB Test Location"
            }
            kafka_producer.send('logs', value=message)
        
        kafka_producer.flush()
        
        # Wait for JDBC batch to flush (configured as 1s interval)
        time.sleep(3)
        
        cursor.execute("SELECT COUNT(*) FROM entry_logs")
        final_count = cursor.fetchone()[0]
        cursor.close()
        
        # Refresh connection to see latest data
        db_connection.commit()
        
        assert final_count >= initial_count + 5, \
            f"Expected at least {initial_count + 5} records, got {final_count}"


class TestDynamicConfiguration:
    """Tests for runtime rule configuration via anomaly-config topic."""

    def test_rule_update_changes_threshold(self, kafka_producer, db_connection):
        """
        Verify that sending a new rule updates the detection threshold.
        
        Steps:
        1. Send new rule with threshold=2 
        2. Produce 3 events (would not trigger with default threshold=5)
        3. Verify alert is emitted
        4. Reset rule to default
        """
        detected_id, camera_id = get_valid_ids(db_connection)
        
        # Use a unique camera to avoid interference
        # Note: In production test, you'd use a test camera ID
        
        # Send new rule
        new_rule = {
            "threshold": 2,
            "window_seconds": 60,
            "anomaly_id": 1
        }
        kafka_producer.send('anomaly-config', value=new_rule)
        kafka_producer.flush()
        
        print(f"Rule updated: {new_rule}")
        time.sleep(2)  # Wait for broadcast to propagate
        
        # Produce only 3 events
        for _ in range(3):
            message = {
                "detected_id": detected_id,
                "camera_id": camera_id,
                "timestamp": str(int(time.time())),
                "event_type": "config_test",
                "authorized": True
            }
            kafka_producer.send('logs', value=message)
        
        kafka_producer.flush()
        
        # Consume alerts
        consumer = KafkaConsumer(
            'frequency_alerts',
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset='latest',
            consumer_timeout_ms=15000,
            value_deserializer=lambda x: json.loads(x.decode('utf-8'))
        )
        
        alert_received = False
        
        for msg in consumer:
            data = msg.value
            if data.get('camera_id') == camera_id:
                # Verify the new threshold is in the description
                if 'threshold: 2' in data.get('description', ''):
                    alert_received = True
                    break
        
        consumer.close()
        
        # Reset to default rule
        default_rule = {"threshold": 5, "window_seconds": 30, "anomaly_id": 1}
        kafka_producer.send('anomaly-config', value=default_rule)
        kafka_producer.flush()
        
        assert alert_received, "Alert with new threshold not received"
