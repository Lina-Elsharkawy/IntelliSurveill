#!/usr/bin/env python3
"""
Kafka Topic Management Script

Creates required Kafka topics for the streaming pipeline.
Idempotent: safe to run multiple times.
"""

import argparse
import logging
import os
import sys
import time

from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError, NoBrokersAvailable

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default topic configurations
DEFAULT_TOPICS = [
    {"name": "logs", "partitions": 3, "replication_factor": 1},
    {"name": "anomalies", "partitions": 3, "replication_factor": 1},
    {"name": "frequency_alerts", "partitions": 3, "replication_factor": 1},
    {"name": "anomaly-config", "partitions": 1, "replication_factor": 1},
]


def create_admin_client(bootstrap_servers: str, max_retries: int = 10, retry_delay: int = 5) -> KafkaAdminClient:
    """Create Kafka admin client with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Connecting to Kafka at {bootstrap_servers} (attempt {attempt}/{max_retries})")
            client = KafkaAdminClient(
                bootstrap_servers=bootstrap_servers,
                client_id='topic_manager'
            )
            logger.info("Successfully connected to Kafka")
            return client
        except NoBrokersAvailable:
            if attempt < max_retries:
                logger.warning(f"Kafka not available. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error("Failed to connect to Kafka after maximum retries")
                raise


def create_topics(admin_client: KafkaAdminClient, topics: list) -> None:
    """Create topics if they don't exist."""
    existing_topics = set(admin_client.list_topics())
    logger.info(f"Existing topics: {existing_topics}")

    topics_to_create = []
    for topic_config in topics:
        if topic_config["name"] not in existing_topics:
            topics_to_create.append(NewTopic(
                name=topic_config["name"],
                num_partitions=topic_config["partitions"],
                replication_factor=topic_config["replication_factor"]
            ))
        else:
            logger.info(f"Topic '{topic_config['name']}' already exists")

    if topics_to_create:
        try:
            admin_client.create_topics(new_topics=topics_to_create, validate_only=False)
            created_names = [t.name for t in topics_to_create]
            logger.info(f"Created topics: {created_names}")
        except TopicAlreadyExistsError:
            logger.info("Some topics already exist (race condition)")
        except Exception as e:
            logger.error(f"Error creating topics: {e}")
            raise
    else:
        logger.info("All required topics already exist")


def main():
    parser = argparse.ArgumentParser(description='Manage Kafka topics')
    parser.add_argument(
        '--bootstrap-servers',
        default=os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
        help='Kafka bootstrap servers'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=10,
        help='Maximum connection retries'
    )
    args = parser.parse_args()

    try:
        admin_client = create_admin_client(args.bootstrap_servers, args.max_retries)
        create_topics(admin_client, DEFAULT_TOPICS)
        admin_client.close()
        logger.info("Topic management completed successfully")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Topic management failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
