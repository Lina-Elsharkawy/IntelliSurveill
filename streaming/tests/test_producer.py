from kafka import KafkaProducer
import json
import time
import datetime

import os

# Configuration
KAFKA_BROKER = os.environ.get('KAFKA_BROKER', 'kafka:9092')
TOPIC = 'logs'

def create_producer():
    try:
        producer = KafkaProducer(
            bootstrap_servers=[KAFKA_BROKER],
            value_serializer=lambda x: json.dumps(x).encode('utf-8')
        )
        return producer
    except Exception as e:
        print(f"Error connecting to Kafka: {e}")
        return None

def generate_data():
    return {
        'camera_id': 'cam-001',
        'timestamp': datetime.datetime.now().isoformat(),
        'event_type': 'motion_detected'
    }

def main():
    producer = create_producer()
    if not producer:
        return

    print(f"Producing data to topic '{TOPIC}' on {KAFKA_BROKER}...")
    try:
        # Produce 10 messages rapidly to trigger the >5 count threshold
        for i in range(10):
            data = generate_data()
            producer.send(TOPIC, value=data)
            print(f"Sent: {data}")
            time.sleep(0.1) # Fast enough to be within 30s window
        
        producer.flush()
        print("Done producing messages.")
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        producer.close()

if __name__ == "__main__":
    main()
