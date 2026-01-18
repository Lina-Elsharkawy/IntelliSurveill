package com.grad01.streaming.processor;

import com.grad01.streaming.model.AnomalyAlert;
import com.grad01.streaming.model.LogEvent;
import com.grad01.streaming.model.RuleConfig;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for DynamicAnomalyDetector components.
 */
class DynamicAnomalyDetectorTest {

    @Test
    @DisplayName("RuleConfig should have correct defaults")
    void ruleConfigDefaults() {
        RuleConfig rule = new RuleConfig();
        
        assertThat(rule.getThreshold()).isEqualTo(RuleConfig.DEFAULT_THRESHOLD);
        assertThat(rule.getWindowSeconds()).isEqualTo(RuleConfig.DEFAULT_WINDOW_SECONDS);
        assertThat(rule.getAnomalyId()).isEqualTo(RuleConfig.DEFAULT_ANOMALY_ID);
    }

    @Test
    @DisplayName("RuleConfig should accept custom values")
    void ruleConfigCustomValues() {
        RuleConfig rule = new RuleConfig(10, 120, 2L);
        
        assertThat(rule.getThreshold()).isEqualTo(10);
        assertThat(rule.getWindowSeconds()).isEqualTo(120);
        assertThat(rule.getAnomalyId()).isEqualTo(2L);
    }

    @Test
    @DisplayName("LogEvent should serialize correctly")
    void logEventSerialization() {
        LogEvent event = new LogEvent();
        event.setCameraId(1L);
        event.setTimestamp("1735084800");
        event.setEventType("entry_attempt");
        event.setAuthorized(true);
        event.setLocation("Building A");

        assertThat(event.getCameraId()).isEqualTo(1L);
        assertThat(event.getEventType()).isEqualTo("entry_attempt");
        assertThat(event.getAuthorized()).isTrue();
        assertThat(event.getLocation()).isEqualTo("Building A");
    }

    @Test
    @DisplayName("LogEvent equals and hashCode")
    void logEventEquality() {
        LogEvent event1 = new LogEvent();
        event1.setCameraId(1L);
        event1.setTimestamp("1735084800");
        event1.setDetectedId(100L);

        LogEvent event2 = new LogEvent();
        event2.setCameraId(1L);
        event2.setTimestamp("1735084800");
        event2.setDetectedId(100L);

        assertThat(event1).isEqualTo(event2);
        assertThat(event1.hashCode()).isEqualTo(event2.hashCode());
    }

    @Test
    @DisplayName("AnomalyAlert should contain all required fields")
    void anomalyAlertFields() {
        AnomalyAlert alert = new AnomalyAlert(
                100L, // detectedId
                1L,   // cameraId
                1L,   // anomalyId
                "1735084800",
                "FREQUENCY_ANOMALY",
                "Test description",
                10
        );

        assertThat(alert.getCameraId()).isEqualTo(1L);
        assertThat(alert.getAnomalyId()).isEqualTo(1L);
        assertThat(alert.getAnomalyType()).isEqualTo("FREQUENCY_ANOMALY");
        assertThat(alert.getCount()).isEqualTo(10);
        assertThat(alert.getDetectedId()).isEqualTo(100L);
    }

    @Test
    @DisplayName("AnomalyAlert equals and hashCode")
    void anomalyAlertEquality() {
        AnomalyAlert alert1 = new AnomalyAlert(100L, 1L, 1L, "1735084800", "TYPE", "Desc", 5);
        AnomalyAlert alert2 = new AnomalyAlert(100L, 1L, 1L, "1735084800", "TYPE", "Desc", 5);

        assertThat(alert1).isEqualTo(alert2);
        assertThat(alert1.hashCode()).isEqualTo(alert2.hashCode());
    }

    @Test
    @DisplayName("AnomalyAlert toString should be readable")
    void anomalyAlertToString() {
        AnomalyAlert alert = new AnomalyAlert(100L, 1L, 1L, "1735084800", "FREQUENCY_ANOMALY", "Test", 5);
        
        String str = alert.toString();
        assertThat(str).contains("cameraId=1");
        assertThat(str).contains("FREQUENCY_ANOMALY");
    }
}
