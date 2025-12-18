import os
import time
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, NoBrokersAvailable

def create_topics():
    bootstrap_servers = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    print(f"Connecting to Kafka at {bootstrap_servers}...")

    admin_client = None
    retries = 5
    while retries > 0:
        try:
            admin_client = KafkaAdminClient(
                bootstrap_servers=bootstrap_servers,
                client_id='topic_creator'
            )
            print("Connected to Kafka.")
            break
        except NoBrokersAvailable:
            print("Kafka not available yet. Retrying in 5 seconds...")
            time.sleep(5)
            retries -= 1
    
    if not admin_client:
        print("Failed to connect to Kafka after multiple retries. Exiting.")
        return

    topics_to_create = [
        NewTopic(name="logs", num_partitions=3, replication_factor=1),
        NewTopic(name="anomalies", num_partitions=3, replication_factor=1),
        NewTopic(name="frequency_alerts", num_partitions=3, replication_factor=1),
        NewTopic(name="anomaly-config", num_partitions=3, replication_factor=1)
    ]

    existing_topics = admin_client.list_topics()
    print(f"Existing topics: {existing_topics}")

    new_topics = []
    for topic in topics_to_create:
        if topic.name not in existing_topics:
            new_topics.append(topic)
        else:
            print(f"Topic '{topic.name}' already exists.")

    if new_topics:
        try:
            admin_client.create_topics(new_topics=new_topics)
            print(f"Created topics: {[t.name for t in new_topics]}")
        except TopicAlreadyExistsError:
            print("Some topics already exist.")
        except Exception as e:
            print(f"Error creating topics: {e}")
    else:
        print("All topics already exist.")

    admin_client.close()

if __name__ == "__main__":
    create_topics()
