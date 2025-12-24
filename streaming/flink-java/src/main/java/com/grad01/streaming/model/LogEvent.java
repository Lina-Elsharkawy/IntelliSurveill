package com.grad01.streaming.model;

import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serializable;
import java.util.Objects;

/**
 * Represents an entry log event from the camera access system.
 * Schema aligned with the `entry_logs` database table.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class LogEvent implements Serializable {
    private static final long serialVersionUID = 1L;

    @JsonProperty("detected_id")
    private Long detectedId;

    @JsonProperty("camera_id")
    private Long cameraId;

    @JsonProperty("timestamp")
    private String timestamp;

    @JsonProperty("authorized")
    private Boolean authorized;

    @JsonProperty("event_type")
    private String eventType;

    @JsonProperty("location")
    private String location;

    @JsonProperty("device_status")
    private String deviceStatus;

    @JsonProperty("image_video_ref")
    private String imageVideoRef;

    @JsonProperty("processing_time")
    private String processingTime;

    @JsonProperty("model_version")
    private String modelVersion;

    public LogEvent() {}

    // Getters
    public Long getDetectedId() { return detectedId; }
    public Long getCameraId() { return cameraId; }
    public String getTimestamp() { return timestamp; }
    public Boolean getAuthorized() { return authorized; }
    public String getEventType() { return eventType; }
    public String getLocation() { return location; }
    public String getDeviceStatus() { return deviceStatus; }
    public String getImageVideoRef() { return imageVideoRef; }
    public String getProcessingTime() { return processingTime; }
    public String getModelVersion() { return modelVersion; }

    // Setters
    public void setDetectedId(Long detectedId) { this.detectedId = detectedId; }
    public void setCameraId(Long cameraId) { this.cameraId = cameraId; }
    public void setTimestamp(String timestamp) { this.timestamp = timestamp; }
    public void setAuthorized(Boolean authorized) { this.authorized = authorized; }
    public void setEventType(String eventType) { this.eventType = eventType; }
    public void setLocation(String location) { this.location = location; }
    public void setDeviceStatus(String deviceStatus) { this.deviceStatus = deviceStatus; }
    public void setImageVideoRef(String imageVideoRef) { this.imageVideoRef = imageVideoRef; }
    public void setProcessingTime(String processingTime) { this.processingTime = processingTime; }
    public void setModelVersion(String modelVersion) { this.modelVersion = modelVersion; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        LogEvent logEvent = (LogEvent) o;
        return Objects.equals(detectedId, logEvent.detectedId) &&
               Objects.equals(cameraId, logEvent.cameraId) &&
               Objects.equals(timestamp, logEvent.timestamp);
    }

    @Override
    public int hashCode() {
        return Objects.hash(detectedId, cameraId, timestamp);
    }

    @Override
    public String toString() {
        return "LogEvent{" +
                "detectedId=" + detectedId +
                ", cameraId=" + cameraId +
                ", timestamp='" + timestamp + '\'' +
                ", eventType='" + eventType + '\'' +
                ", authorized=" + authorized +
                '}';
    }
}
