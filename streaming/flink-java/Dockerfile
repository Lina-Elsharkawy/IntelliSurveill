# Multi-stage build for Flink Java Anomaly Detection Job

# Stage 1: Build the shaded JAR
FROM maven:3.9-eclipse-temurin-11 AS builder
WORKDIR /app
COPY pom.xml .
# Download dependencies first (cacheable layer)
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn clean package -DskipTests -q

# Stage 2: Flink runtime
FROM apache/flink:1.17.2-scala_2.12-java11

# Copy the shaded JAR to Flink's usrlib
COPY --from=builder /app/target/flink-anomaly-detection-1.0-SNAPSHOT.jar /opt/flink/usrlib/flink-anomaly-detection.jar

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8081/overview || exit 1

# Labels
LABEL maintainer="grad01-team"
LABEL version="1.0"
LABEL description="Flink Anomaly Detection Job"
