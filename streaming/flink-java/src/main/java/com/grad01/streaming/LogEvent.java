package com.grad01.streaming;

import com.fasterxml.jackson.annotation.JsonProperty;

public class LogEvent {
    @JsonProperty("camera_id")
    public String cameraId;

    @JsonProperty("timestamp")
    public String timestamp;

    @JsonProperty("event_type")
    public String eventType;

    public LogEvent() {}

    public LogEvent(String cameraId, String timestamp, String eventType) {
        this.cameraId = cameraId;
        this.timestamp = timestamp;
        this.eventType = eventType;
    }

    @Override
    public String toString() {
        return "LogEvent{" +
                "cameraId='" + cameraId + '\'' +
                ", timestamp='" + timestamp + '\'' +
                ", eventType='" + eventType + '\'' +
                '}';
    }
}
