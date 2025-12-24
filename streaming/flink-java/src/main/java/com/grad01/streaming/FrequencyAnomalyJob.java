package com.grad01.streaming;

import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.state.BroadcastState;
import org.apache.flink.api.common.state.ListState;
import org.apache.flink.api.common.state.ListStateDescriptor;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.typeinfo.BasicTypeInfo;
import org.apache.flink.api.common.typeinfo.TypeHint;
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.formats.json.JsonDeserializationSchema;
import org.apache.flink.formats.json.JsonSerializationSchema;
import org.apache.flink.streaming.api.datastream.BroadcastStream;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.co.KeyedBroadcastProcessFunction;
import org.apache.flink.util.Collector;

import java.util.ArrayList;
import java.util.List;

/**
 * Flink Job for Frequency Anomaly Detection.
 * <p>
 * This job detects "brute force" style attacks by counting access attempts for
 * each camera
 * within a sliding time window.
 * <p>
 * Features:
 * 1. Consumes 'logs' topic (Access Logs).
 * 2. Consumes 'anomaly-config' topic (Broadcast Stream for dynamic rules).
 * 3. Uses Broadcast State Pattern to update detection rules (threshold, window)
 * at runtime.
 * 4. Sinks alerts to 'frequency_alerts' topic.
 */
public class FrequencyAnomalyJob {

        // Kafka Topics and Groups
        private static final String TOPIC_LOGS = "logs";
        private static final String TOPIC_ALERTS = "frequency_alerts";
        private static final String TOPIC_CONFIG = "anomaly-config";
        private static final String GROUP_ID_JOB = "flink_frequency_detector_java";
        private static final String GROUP_ID_CONFIG = "flink_config_reader";

        // State Descriptor Names
        private static final String STATE_RULES = "RulesBroadcastState";
        private static final String STATE_EVENTS = "RecentEvents";

        public static void main(String[] args) throws Exception {
                StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
                env.setParallelism(1);

                String boostrapServers = System.getenv().getOrDefault("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092");

                // 1. Logs Source
                JsonDeserializationSchema<LogEvent> logFormat = new JsonDeserializationSchema<>(LogEvent.class);
                KafkaSource<LogEvent> logsSource = KafkaSource.<LogEvent>builder()
                                .setBootstrapServers(boostrapServers)
                                .setTopics(TOPIC_LOGS)
                                .setGroupId(GROUP_ID_JOB)
                                .setStartingOffsets(OffsetsInitializer.latest())
                                .setValueOnlyDeserializer(logFormat)
                                .build();

                DataStream<LogEvent> logsStream = env.fromSource(logsSource, WatermarkStrategy.noWatermarks(),
                                "Logs Source");

                // 2. Config Source (Broadcast)
                JsonDeserializationSchema<RuleConfig> configFormat = new JsonDeserializationSchema<>(RuleConfig.class);
                KafkaSource<RuleConfig> configSource = KafkaSource.<RuleConfig>builder()
                                .setBootstrapServers(boostrapServers)
                                .setTopics(TOPIC_CONFIG)
                                .setGroupId(GROUP_ID_CONFIG)
                                .setStartingOffsets(OffsetsInitializer.latest())
                                .setValueOnlyDeserializer(configFormat)
                                .build();

                DataStream<RuleConfig> configStream = env.fromSource(configSource, WatermarkStrategy.noWatermarks(),
                                "Config Source");

                // 3. Define Broadcast State
                MapStateDescriptor<String, RuleConfig> ruleStateDescriptor = new MapStateDescriptor<>(
                                STATE_RULES,
                                BasicTypeInfo.STRING_TYPE_INFO,
                                TypeInformation.of(new TypeHint<RuleConfig>() {
                                }));

                BroadcastStream<RuleConfig> broadcastConfigStream = configStream.broadcast(ruleStateDescriptor);

                // 4. Connect and Process
                DataStream<Alert> alerts = logsStream
                                .keyBy(event -> event.cameraId)
                                .connect(broadcastConfigStream)
                                .process(new DynamicAnomalyDetector());

                // 5. Sink
                JsonSerializationSchema<Alert> jsonSerializer = new JsonSerializationSchema<>();
                KafkaSink<Alert> sink = KafkaSink.<Alert>builder()
                                .setBootstrapServers(boostrapServers)
                                .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                                                .setTopic(TOPIC_ALERTS)
                                                .setValueSerializationSchema(jsonSerializer)
                                                .build())
                                .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
                                .build();

                alerts.sinkTo(sink);

                env.execute("Frequency Anomaly Detection (Dynamic)");
        }

        /**
         * Process Function that handles the connection between the high-volume Log
         * stream
         * and the low-volume Config broadcast stream.
         */
        public static class DynamicAnomalyDetector
                        extends KeyedBroadcastProcessFunction<String, LogEvent, RuleConfig, Alert> {

                // State to hold the current rule (Broadcast State)
                private final MapStateDescriptor<String, RuleConfig> ruleStateDescriptor = new MapStateDescriptor<>(
                                STATE_RULES,
                                BasicTypeInfo.STRING_TYPE_INFO,
                                TypeInformation.of(new TypeHint<RuleConfig>() {
                                }));

                // State to hold recent event timestamps for the specific camera (Keyed State)
                private final ListStateDescriptor<Long> eventsStateDescriptor = new ListStateDescriptor<>(
                                STATE_EVENTS,
                                BasicTypeInfo.LONG_TYPE_INFO);

                @Override
                public void processBroadcastElement(RuleConfig value, Context ctx, Collector<Alert> out)
                                throws Exception {
                        // Update the global rule in the broadcast state
                        BroadcastState<String, RuleConfig> state = ctx.getBroadcastState(ruleStateDescriptor);
                        state.put("global_rule", value);
                        System.out.println("Updated Rule: " + value);
                }

                @Override
                public void processElement(LogEvent value, ReadOnlyContext ctx, Collector<Alert> out) throws Exception {
                        // 1. Get current rule (or default)
                        RuleConfig rule = ctx.getBroadcastState(ruleStateDescriptor).get("global_rule");
                        if (rule == null) {
                                rule = new RuleConfig(5, 30); // Default: 5 attempts in 30 seconds
                        }

                        // 2. Add current event time to history
                        ListState<Long> history = getRuntimeContext().getListState(eventsStateDescriptor);
                        // Robust timestamp parsing (assuming source sends string seconds/postgres
                        // default)
                        long currentTime;
                        try {
                                // Try to parse as double first just in case, then cast to long seconds
                                currentTime = (long) Double.parseDouble(value.timestamp) * 1000;
                        } catch (Exception e) {
                                // Fallback or skip
                                return;
                        }
                        history.add(currentTime);

                        // 3. Prune old events and count
                        // We use a manual windowing logic here because standard Window operators
                        // are hard to combine with dynamic timeouts from Broadcast state.
                        List<Long> recentEvents = new ArrayList<>();
                        int count = 0;
                        long windowStart = currentTime - (rule.windowSeconds * 1000L);

                        for (Long timestamp : history.get()) {
                                if (timestamp >= windowStart) {
                                        recentEvents.add(timestamp);
                                        count++;
                                }
                        }

                        // Update state: remove old events to keep state size small
                        history.update(recentEvents);

                        // 4. Check threshold
                        if (count > rule.threshold) {
                                out.collect(new Alert(
                                                value.cameraId,
                                                "Frequency",
                                                String.format("High frequency access detected: %d attempts in %ds (Threshold: %d)",
                                                                count, rule.windowSeconds, rule.threshold)));
                        }
                }
        }
}
