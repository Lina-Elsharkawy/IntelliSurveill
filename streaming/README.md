# Real-Time Anomaly Detection Pipeline

Production-ready streaming pipeline for detecting security anomalies in camera access logs.

## Architecture

```
Kafka (logs) ──► Flink Job ──┬──► PostgreSQL (entry_logs, anomalies_logs)
                             └──► Kafka (frequency_alerts)
                    ▲
                    │
Kafka (anomaly-config) ─── Dynamic Rules (Broadcast State)
```

## Features

- **Frequency Anomaly Detection**: Detects brute-force style attacks
- **Dynamic Rules**: Update detection thresholds at runtime via Kafka
- **Dual Sink**: Writes to PostgreSQL AND Kafka
- **Fault Tolerance**: Exactly-once checkpointing enabled
- **Alert Suppression**: Debounce to prevent alert storms
- **Prometheus Metrics**: Built-in monitoring

## Quick Start

```bash
# 1. Start services
docker compose up -d kafka postgres-db flinkjobmanager flinktaskmanager

# 2. Submit job
docker exec graduation-project-flinkjobmanager-1 flink run /opt/flink/usrlib/flink-anomaly-detection.jar

# 3. Check job status
docker exec graduation-project-flinkjobmanager-1 flink list
```

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` | Kafka connection |
| `JDBC_URL` | `jdbc:postgresql://postgres-db:5432/logging_db` | PostgreSQL connection |
| `JDBC_USER` | `postgres` | DB username |
| `JDBC_PASSWORD` | `postgres` | DB password |
| `FLINK_PARALLELISM` | `1` | Job parallelism |
| `CHECKPOINT_INTERVAL_MS` | `60000` | Checkpoint interval |

## Kafka Topics

| Topic | Purpose |
|-------|---------|
| `logs` | Input: Camera access events |
| `frequency_alerts` | Output: Anomaly alerts |
| `anomaly-config` | Input: Dynamic rule updates |

## Input Schema (logs topic)

```json
{
  "detected_id": 123,
  "camera_id": 1,
  "timestamp": "1735084800",
  "authorized": true,
  "event_type": "entry_attempt",
  "location": "Building A",
  "device_status": "active",
  "image_video_ref": "s3://bucket/image.jpg",
  "processing_time": "00:00:00.5",
  "model_version": "1.0.0"
}
```

## Output Schema (frequency_alerts topic)

```json
{
  "detected_id": 123,
  "camera_id": 1,
  "anomaly_id": 1,
  "timestamp": "1735084800",
  "anomaly_type": "FREQUENCY_ANOMALY",
  "description": "High frequency access: 6 attempts in 30s (threshold: 5)",
  "count": 6
}
```

## Dynamic Rule Configuration

The detection threshold and window can be changed **at runtime** via the `anomaly-config` topic. This allows the frontend to update rules without restarting the job.

**Schema:**
```json
{
  "threshold": 10,        // Number of events before triggering alert
  "window_seconds": 60,   // Time window to count events
  "anomaly_id": 1         // FK to anomalies table
}
```

**Example (CLI):**
```bash
echo '{"threshold":3,"window_seconds":60,"anomaly_id":1}' | \
  docker exec -i kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic anomaly-config
```

**Frontend Integration:**
Your frontend should publish to this topic when user changes the threshold settings. The Flink job will immediately apply the new rule to all incoming events.

## Monitoring

- **Flink Web UI**: http://localhost:8081
- **Prometheus Metrics**: http://localhost:9249

## Project Structure

```
streaming/
├── flink-java/           # Java Flink job (primary)
│   ├── src/main/java/
│   │   └── com/grad01/streaming/
│   │       ├── FrequencyAnomalyJob.java
│   │       ├── model/
│   │       │   ├── LogEvent.java
│   │       │   ├── AnomalyAlert.java
│   │       │   └── RuleConfig.java
│   │       └── processor/
│   │           └── DynamicAnomalyDetector.java
│   ├── src/test/java/    # Unit tests
│   ├── pom.xml
│   └── Dockerfile
├── kafka/                # Topic management
│   └── create_topics.py
└── tests/                # E2E tests
```

## Testing

### Java Unit Tests (Flink Operator Harness)
```bash
cd streaming/flink-java
mvn test
```

Tests include:
- `DynamicAnomalyDetectorHarnessTest` - Threshold detection, alert suppression, dynamic rules
- POJO serialization tests

### Python E2E Tests
```bash
cd streaming/tests
pip install -r requirements.txt
pytest -v
```

Tests include:
- `test_flink_e2e.py` - End-to-end flow with DB verification
- `test_db_integration.py` - Schema and FK validation
- `test_kafka.py` - Kafka connectivity

