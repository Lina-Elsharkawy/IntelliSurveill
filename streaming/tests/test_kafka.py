import os
import pytest
import uuid
import time
from kafka import KafkaAdminClient, KafkaProducer, KafkaConsumer
from kafka.errors import NoBrokersAvailable

KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

@pytest.fixture(scope="module")
def kafka_admin():
    retries = 5
    while retries > 0:
        try:
            client = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)
            yield client
            client.close()
            return
        except NoBrokersAvailable:
            time.sleep(2)
            retries -= 1
    pytest.fail("Could not connect to Kafka Admin")

@pytest.fixture(scope="module")
def kafka_producer():
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: str(v).encode('utf-8')
    )

def test_topics_exist(kafka_admin):
    """Verify that the required topics exist."""
    existing_topics = kafka_admin.list_topics()
    required_topics = {'logs', 'anomalies', 'frequency_alerts'}
    
    # Check if all required topics are present in existing topics
    missing = required_topics - set(existing_topics)
    assert not missing, f"Missing topics: {missing}"

def test_produce_consume_logs(kafka_producer):
    """Verify that we can produce to and consume from the logs topic."""
    topic = 'logs'
    test_message = f"test-message-{uuid.uuid4()}"
    
    # Produce
    kafka_producer.send(topic, value=test_message)
    kafka_producer.flush()
    
    # Consume
    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        auto_offset_reset='earliest',
        consumer_timeout_ms=5000, # Stop after 5s if no message
        value_deserializer=lambda x: x.decode('utf-8')
    )
    
    found = False
    for msg in consumer:
        if msg.value == test_message:
            found = True
            break
            
    consumer.close()
    assert found, "Did not receive the test message from logs topic"
