# Streaming Tests

This directory contains tests and utilities for verifying the streaming pipeline (Kafka + Flink).

## Files

- `test_producer.py`: A Python script that generates mock log data and sends it to the `logs` Kafka topic. Use this to trigger the anomaly detection Flink job.
- `test_kafka.py`: (Existing) Kafka connectivity test.
- `test_flink_e2e.py`: (Existing) End-to-end test.

## How to Run

## How to Run

### Prerequisites

1.  **Install Test Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### Running Tests

We use `pytest` for all tests.

1.  **Run all tests**:
    ```bash
    pytest
    ```

2.  **Run specific test file**:
    ```bash
    pytest test_flink_e2e.py
    ```

### Environment

Tests default to connecting to `localhost:9092`. You can override this with:

```bash
export KAFKA_BOOTSTRAP_SERVERS=localhost:9093
pytest
```
*Note: If running outside Docker, ensure `KAFKA_BOOTSTRAP_SERVERS` points to the exposed port (e.g., 9093 is mapped to 9092 in docker-compose).*
