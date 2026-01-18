package com.grad01.streaming.model;

import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serializable;
import java.util.Objects;

/**
 * Represents a dynamic rule configuration for anomaly detection.
 * Can be updated at runtime via Kafka broadcast stream.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public class RuleConfig implements Serializable {
    private static final long serialVersionUID = 1L;

    public static final int DEFAULT_THRESHOLD = 5;
    public static final int DEFAULT_WINDOW_SECONDS = 30;
    public static final long DEFAULT_ANOMALY_ID = 1L; // FK to anomalies table

    @JsonProperty("threshold")
    private int threshold;

    @JsonProperty("window_seconds")
    private int windowSeconds;

    @JsonProperty("anomaly_id")
    private long anomalyId;

    public RuleConfig() {
        this.threshold = DEFAULT_THRESHOLD;
        this.windowSeconds = DEFAULT_WINDOW_SECONDS;
        this.anomalyId = DEFAULT_ANOMALY_ID;
    }

    public RuleConfig(int threshold, int windowSeconds, long anomalyId) {
        this.threshold = threshold;
        this.windowSeconds = windowSeconds;
        this.anomalyId = anomalyId;
    }

    // Getters
    public int getThreshold() { return threshold; }
    public int getWindowSeconds() { return windowSeconds; }
    public long getAnomalyId() { return anomalyId; }

    // Setters
    public void setThreshold(int threshold) { this.threshold = threshold; }
    public void setWindowSeconds(int windowSeconds) { this.windowSeconds = windowSeconds; }
    public void setAnomalyId(long anomalyId) { this.anomalyId = anomalyId; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        RuleConfig that = (RuleConfig) o;
        return threshold == that.threshold &&
               windowSeconds == that.windowSeconds &&
               anomalyId == that.anomalyId;
    }

    @Override
    public int hashCode() {
        return Objects.hash(threshold, windowSeconds, anomalyId);
    }

    @Override
    public String toString() {
        return "RuleConfig{" +
                "threshold=" + threshold +
                ", windowSeconds=" + windowSeconds +
                ", anomalyId=" + anomalyId +
                '}';
    }
}
