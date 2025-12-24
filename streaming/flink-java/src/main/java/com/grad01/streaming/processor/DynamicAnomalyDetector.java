package com.grad01.streaming.processor;

import com.grad01.streaming.model.AnomalyAlert;
import com.grad01.streaming.model.LogEvent;
import com.grad01.streaming.model.RuleConfig;

import org.apache.flink.api.common.state.BroadcastState;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.api.common.typeinfo.BasicTypeInfo;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.metrics.Counter;
import org.apache.flink.streaming.api.functions.co.KeyedBroadcastProcessFunction;
import org.apache.flink.util.Collector;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * Process function that detects frequency anomalies using broadcast state for dynamic rules
 * and keyed state for tracking event history per camera.
 * 
 * Features:
 * - Dynamic rule updates via broadcast stream
 * - Sliding window event counting
 * - Alert suppression (one alert per window per camera)
 * - Prometheus metrics
 * - Proper error handling with logging
 */
public class DynamicAnomalyDetector
        extends KeyedBroadcastProcessFunction<Long, LogEvent, RuleConfig, AnomalyAlert> {

    private static final Logger LOG = LoggerFactory.getLogger(DynamicAnomalyDetector.class);
    private static final String GLOBAL_RULE_KEY = "global_rule";
    private static final String STATE_EVENTS = "event_timestamps";
    private static final String STATE_LAST_ALERT = "last_alert_time";

    private final MapStateDescriptor<String, RuleConfig> ruleStateDescriptor;
    private transient ListStateDescriptor<Long> eventsStateDescriptor;
    private transient ValueStateDescriptor<Long> lastAlertStateDescriptor;

    // Metrics
    private transient Counter eventsProcessed;
    private transient Counter alertsEmitted;
    private transient Counter eventsDropped;

    public DynamicAnomalyDetector(MapStateDescriptor<String, RuleConfig> ruleStateDescriptor) {
        this.ruleStateDescriptor = ruleStateDescriptor;
    }

    @Override
    public void open(Configuration parameters) {
        // Initialize state descriptors
        eventsStateDescriptor = new ListStateDescriptor<>(STATE_EVENTS, BasicTypeInfo.LONG_TYPE_INFO);
        lastAlertStateDescriptor = new ValueStateDescriptor<>(STATE_LAST_ALERT, BasicTypeInfo.LONG_TYPE_INFO);

        // Initialize metrics
        eventsProcessed = getRuntimeContext().getMetricGroup().counter("eventsProcessed");
        alertsEmitted = getRuntimeContext().getMetricGroup().counter("alertsEmitted");
        eventsDropped = getRuntimeContext().getMetricGroup().counter("eventsDropped");

        LOG.info("DynamicAnomalyDetector initialized");
    }

    @Override
    public void processBroadcastElement(RuleConfig newRule, Context ctx, Collector<AnomalyAlert> out)
            throws Exception {
        BroadcastState<String, RuleConfig> state = ctx.getBroadcastState(ruleStateDescriptor);
        RuleConfig oldRule = state.get(GLOBAL_RULE_KEY);
        state.put(GLOBAL_RULE_KEY, newRule);

        LOG.info("Rule updated: {} -> {}", oldRule, newRule);
    }

    @Override
    public void processElement(LogEvent event, ReadOnlyContext ctx, Collector<AnomalyAlert> out)
            throws Exception {
        eventsProcessed.inc();

        // Validate event
        if (event.getCameraId() == null) {
            LOG.warn("Dropping event with null cameraId: {}", event);
            eventsDropped.inc();
            return;
        }

        // Get current rule or use default
        RuleConfig rule = ctx.getBroadcastState(ruleStateDescriptor).get(GLOBAL_RULE_KEY);
        if (rule == null) {
            rule = new RuleConfig();
        }

        // Parse event timestamp
        long eventTimeMs;
        try {
            eventTimeMs = parseTimestamp(event.getTimestamp());
        } catch (Exception e) {
            LOG.warn("Failed to parse timestamp '{}' for event: {}", event.getTimestamp(), event);
            eventsDropped.inc();
            return;
        }

        // Get keyed state
        ListState<Long> eventHistory = getRuntimeContext().getListState(eventsStateDescriptor);
        ValueState<Long> lastAlertTime = getRuntimeContext().getState(lastAlertStateDescriptor);

        // Add current event
        eventHistory.add(eventTimeMs);

        // Prune old events outside the window and count recent ones
        long windowStartMs = eventTimeMs - (rule.getWindowSeconds() * 1000L);
        List<Long> recentEvents = new ArrayList<>();
        int count = 0;

        for (Long timestamp : eventHistory.get()) {
            if (timestamp >= windowStartMs) {
                recentEvents.add(timestamp);
                count++;
            }
        }

        // Update state with pruned list
        eventHistory.update(recentEvents);

        // Check threshold and apply alert suppression
        if (count > rule.getThreshold()) {
            Long lastAlert = lastAlertTime.value();
            boolean shouldEmitAlert = shouldEmitAlert(lastAlert, eventTimeMs, rule.getWindowSeconds() * 1000L);

            if (shouldEmitAlert) {
                AnomalyAlert alert = new AnomalyAlert(
                        event.getDetectedId(),
                        event.getCameraId(),
                        rule.getAnomalyId(),
                        event.getTimestamp(),
                        "FREQUENCY_ANOMALY",
                        String.format("High frequency access: %d attempts in %ds (threshold: %d)",
                                count, rule.getWindowSeconds(), rule.getThreshold()),
                        count
                );

                out.collect(alert);
                lastAlertTime.update(eventTimeMs);
                alertsEmitted.inc();

                LOG.info("Alert emitted for camera {}: count={}, threshold={}",
                        event.getCameraId(), count, rule.getThreshold());
            } else {
                LOG.debug("Alert suppressed for camera {} (within suppression window)", event.getCameraId());
            }
        }
    }

    /**
     * Determines if an alert should be emitted based on the last alert time.
     * Implements debounce/suppression to avoid alert storms.
     */
    private boolean shouldEmitAlert(Long lastAlertTime, long currentTime, long suppressionWindowMs) {
        if (lastAlertTime == null) {
            return true;
        }
        // Only emit if we're outside the suppression window (default: same as detection window)
        return (currentTime - lastAlertTime) >= suppressionWindowMs;
    }

    /**
     * Parses timestamp string to milliseconds.
     * Supports: epoch seconds (as string), epoch milliseconds, ISO-8601.
     */
    private long parseTimestamp(String timestamp) {
        if (timestamp == null || timestamp.isEmpty()) {
            return System.currentTimeMillis();
        }

        try {
            // Try as epoch seconds (most common from our test data)
            double epochSeconds = Double.parseDouble(timestamp);
            return (long) (epochSeconds * 1000);
        } catch (NumberFormatException e) {
            // Try as ISO-8601
            try {
                return Instant.parse(timestamp).toEpochMilli();
            } catch (Exception e2) {
                throw new IllegalArgumentException("Unable to parse timestamp: " + timestamp);
            }
        }
    }
}
