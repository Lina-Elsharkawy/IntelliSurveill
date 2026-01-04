package com.grad01.streaming.model;

import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serializable;
import java.util.Objects;

/**
 * Represents an anomaly alert to be written to the `anomalies_logs` table.
 * Schema aligned with the database.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class AnomalyAlert implements Serializable {
    private static final long serialVersionUID = 1L;

    @JsonProperty("detected_id")
    private Long detectedId;

    @JsonProperty("camera_id")
    private Long cameraId;

    @JsonProperty("anomaly_id")
    private Long anomalyId;

    @JsonProperty("timestamp")
    private String timestamp;

    // Extended fields for Kafka output (not in DB table)
    @JsonProperty("anomaly_type")
    private String anomalyType;

    @JsonProperty("description")
    private String description;

    @JsonProperty("count")
    private Integer count;

    public AnomalyAlert() {}

    public AnomalyAlert(Long detectedId, Long cameraId, Long anomalyId, String timestamp,
                        String anomalyType, String description, Integer count) {
        this.detectedId = detectedId;
        this.cameraId = cameraId;
        this.anomalyId = anomalyId;
        this.timestamp = timestamp;
        this.anomalyType = anomalyType;
        this.description = description;
        this.count = count;
    }

    // Getters
    public Long getDetectedId() { return detectedId; }
    public Long getCameraId() { return cameraId; }
    public Long getAnomalyId() { return anomalyId; }
    public String getTimestamp() { return timestamp; }
    public String getAnomalyType() { return anomalyType; }
    public String getDescription() { return description; }
    public Integer getCount() { return count; }

    // Setters
    public void setDetectedId(Long detectedId) { this.detectedId = detectedId; }
    public void setCameraId(Long cameraId) { this.cameraId = cameraId; }
    public void setAnomalyId(Long anomalyId) { this.anomalyId = anomalyId; }
    public void setTimestamp(String timestamp) { this.timestamp = timestamp; }
    public void setAnomalyType(String anomalyType) { this.anomalyType = anomalyType; }
    public void setDescription(String description) { this.description = description; }
    public void setCount(Integer count) { this.count = count; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        AnomalyAlert that = (AnomalyAlert) o;
        return Objects.equals(cameraId, that.cameraId) &&
               Objects.equals(anomalyId, that.anomalyId) &&
               Objects.equals(timestamp, that.timestamp);
    }

    @Override
    public int hashCode() {
        return Objects.hash(cameraId, anomalyId, timestamp);
    }

    @Override
    public String toString() {
        return "AnomalyAlert{" +
                "cameraId=" + cameraId +
                ", anomalyType='" + anomalyType + '\'' +
                ", description='" + description + '\'' +
                ", count=" + count +
                '}';
    }
}
