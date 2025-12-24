package com.grad01.streaming;

import com.fasterxml.jackson.annotation.JsonProperty;

public class RuleConfig {
    @JsonProperty("threshold")
    public int threshold;

    @JsonProperty("windowSeconds")
    public int windowSeconds; // currently unused in simple window logic, but good for broadcast state logic

    public RuleConfig() {
    }

    public RuleConfig(int threshold, int windowSeconds) {
        this.threshold = threshold;
        this.windowSeconds = windowSeconds;
    }

    @Override
    public String toString() {
        return "RuleConfig{" +
                "threshold=" + threshold +
                ", windowSeconds=" + windowSeconds +
                '}';
    }
}
