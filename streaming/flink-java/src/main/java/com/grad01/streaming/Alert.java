package com.grad01.streaming;

import com.fasterxml.jackson.annotation.JsonProperty;

public class Alert {
    @JsonProperty("camera_id")
    public String cameraId;

    @JsonProperty("anomaly_type")
    public String anomalyType;

    @JsonProperty("description")
    public String description;

    public Alert() {}

    public Alert(String cameraId, String anomalyType, String description) {
        this.cameraId = cameraId;
        this.anomalyType = anomalyType;
        this.description = description;
    }

    @Override
    public String toString() {
        return "Alert{" +
                "cameraId='" + cameraId + '\'' +
                ", anomalyType='" + anomalyType + '\'' +
                ", description='" + description + '\'' +
                '}';
    }
}
