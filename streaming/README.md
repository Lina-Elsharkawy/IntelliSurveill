# Real-Time Anomaly Detection Module

## 🔎 Business Overview
This module creates a **real-time security shield** for our camera infrastructure. By analyzing the stream of access logs as they happen, we can instantly detect potential security threats before they escalate.

**Key Feature: Frequency Anomaly Detection**
We automatically flag "Brute Force" style attacks—specifically, when a single camera experiences an unusually high number of access attempts (more than 5) within a short window (30 seconds).

## 🏗️ Technical Architecture
The system follows a modern streaming architecture:

1.  **Input (Kafka Topic: `logs`)**: Raw access logs from cameras are ingested here.
2.  **Processing (Flink - Java)**: A high-performance Flink job consumes the logs, groups them by camera, and applies a sliding window algorithm to count events.
3.  **Output (Kafka Topic: `frequency_alerts`)**: If a threshold is breached, an alert is immediately published to this topic for downstream action (notification, dashboarding, etc.).

## 📂 Directory Structure

-   `flink-java/`: **[NEW]** The main (production) implementation of the Anomaly Detection job, written in Java for performance and type safety.
-   `flink/`: The legacy Python prototype of the Flink job.
-   `kafka/`: Scripts and utilities for setting up the Kafka infrastructure (e.g., creating topics).
-   `tests/`: End-to-end integration tests to verify the entire pipeline.
-   `minio/`: Configuration for object storage (if applicable).

## 👩‍💻 Developer Guide

### Prerequisites
-   Java 11+
-   Maven
-   Running Kafka instance (accessible at `localhost:9092` or configured via `KAFKA_BOOTSTRAP_SERVERS`)

### Building the Project
Navigate to the Java project folder and build the "Fat Jar":
```bash
cd flink-java
mvn clean package
```
The artifact will be created at: `streaming/flink-java/target/flink-anomaly-detection-1.0-SNAPSHOT.jar`

### Running the Job
Submit the jar to your Flink cluster (or run locally):
```bash
# Example local run
java -jar flink-java/target/flink-anomaly-detection-1.0-SNAPSHOT.jar
```

### Running Tests
We have Python-based integration tests that treat the Flink job as a black box.

1.  **Install Dependencies**:
    ```bash
    pip install -r tests/requirements.txt
    ```

2.  **Run Tests**:
    ```bash
    pytest tests/test_flink_e2e.py
    ```
