package com.grad01.streaming;

import com.grad01.streaming.model.AnomalyAlert;
import com.grad01.streaming.model.LogEvent;
import com.grad01.streaming.model.RuleConfig;
import com.grad01.streaming.processor.DynamicAnomalyDetector;

import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.state.MapStateDescriptor;
import org.apache.flink.api.common.typeinfo.BasicTypeInfo;
import org.apache.flink.api.common.typeinfo.TypeHint;
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.connector.base.DeliveryGuarantee;
import org.apache.flink.connector.jdbc.JdbcConnectionOptions;
import org.apache.flink.connector.jdbc.JdbcExecutionOptions;
import org.apache.flink.connector.jdbc.JdbcSink;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.formats.json.JsonDeserializationSchema;
import org.apache.flink.formats.json.JsonSerializationSchema;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.BroadcastStream;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.CheckpointConfig;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Production-ready Flink Job for Frequency Anomaly Detection.
 * 
 * Features:
 * - Consumes access logs from Kafka 'logs' topic
 * - Detects brute-force style attacks (high frequency access)
 * - Dynamic rule configuration via 'anomaly-config' broadcast stream
 * - Writes entry logs to PostgreSQL 'entry_logs' table
 * - Writes anomaly alerts to PostgreSQL 'anomalies_logs' table
 * - Publishes alerts to Kafka 'frequency_alerts' topic
 * - Checkpointing for fault tolerance
 * - Prometheus metrics integration
 */
public class FrequencyAnomalyJob {
    private static final Logger LOG = LoggerFactory.getLogger(FrequencyAnomalyJob.class);

    // Kafka Topics
    private static final String TOPIC_LOGS = "logs";
    private static final String TOPIC_ALERTS = "frequency_alerts";
    private static final String TOPIC_CONFIG = "anomaly-config";

    // Consumer Groups
    private static final String GROUP_ID_LOGS = "flink_frequency_detector";
    private static final String GROUP_ID_CONFIG = "flink_config_reader";

    // State Descriptor Name
    public static final String STATE_RULES = "RulesBroadcastState";

    public static void main(String[] args) throws Exception {
        LOG.info("Starting Frequency Anomaly Detection Job");

        // Environment configuration from env vars
        String bootstrapServers = getEnvOrDefault("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092");
        String jdbcUrl = getEnvOrDefault("JDBC_URL", "jdbc:postgresql://postgres-db:5432/logging_db");
        String jdbcUser = getEnvOrDefault("JDBC_USER", "postgres");
        String jdbcPassword = getEnvOrDefault("JDBC_PASSWORD", "postgres");
        int parallelism = Integer.parseInt(getEnvOrDefault("FLINK_PARALLELISM", "1"));
        long checkpointInterval = Long.parseLong(getEnvOrDefault("CHECKPOINT_INTERVAL_MS", "60000"));

        LOG.info("Configuration: bootstrapServers={}, jdbcUrl={}, parallelism={}, checkpointInterval={}ms",
                bootstrapServers, jdbcUrl, parallelism, checkpointInterval);

        // Create execution environment
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        env.setParallelism(parallelism);

        // Enable checkpointing for fault tolerance
        configureCheckpointing(env, checkpointInterval);

        // 1. Logs Source (Kafka)
        DataStream<LogEvent> logsStream = createLogsSource(env, bootstrapServers);

        // 2. Config Source (Kafka Broadcast)
        BroadcastStream<RuleConfig> configBroadcast = createConfigBroadcast(env, bootstrapServers);

        // 3. Process: Connect logs with config and detect anomalies
        MapStateDescriptor<String, RuleConfig> ruleStateDescriptor = new MapStateDescriptor<>(
                STATE_RULES,
                BasicTypeInfo.STRING_TYPE_INFO,
                TypeInformation.of(new TypeHint<RuleConfig>() {})
        );

        SingleOutputStreamOperator<AnomalyAlert> alerts = logsStream
                .keyBy(LogEvent::getCameraId)
                .connect(configBroadcast)
                .process(new DynamicAnomalyDetector(ruleStateDescriptor))
                .name("Anomaly Detection")
                .uid("anomaly-detector");

        // 4. Sink: Write ALL logs to entry_logs table
        logsStream.addSink(createEntryLogsSink(jdbcUrl, jdbcUser, jdbcPassword))
                .name("JDBC Sink: entry_logs")
                .uid("jdbc-entry-logs");

        // 5. Sink: Write anomaly alerts to anomalies_logs table
        alerts.addSink(createAnomaliesLogsSink(jdbcUrl, jdbcUser, jdbcPassword))
                .name("JDBC Sink: anomalies_logs")
                .uid("jdbc-anomalies-logs");

        // 6. Sink: Publish alerts to Kafka for downstream consumers
        alerts.sinkTo(createKafkaAlertsSink(bootstrapServers))
                .name("Kafka Sink: frequency_alerts")
                .uid("kafka-alerts");

        LOG.info("Job graph created, executing...");
        env.execute("Frequency Anomaly Detection");
    }

    private static void configureCheckpointing(StreamExecutionEnvironment env, long interval) {
        env.enableCheckpointing(interval, CheckpointingMode.EXACTLY_ONCE);

        CheckpointConfig checkpointConfig = env.getCheckpointConfig();
        checkpointConfig.setCheckpointTimeout(120000);
        checkpointConfig.setMinPauseBetweenCheckpoints(30000);
        checkpointConfig.setMaxConcurrentCheckpoints(1);
        checkpointConfig.setExternalizedCheckpointCleanup(
                CheckpointConfig.ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION
        );

        LOG.info("Checkpointing enabled with interval={}ms, mode=EXACTLY_ONCE", interval);
    }

    private static DataStream<LogEvent> createLogsSource(StreamExecutionEnvironment env, String bootstrapServers) {
        KafkaSource<LogEvent> source = KafkaSource.<LogEvent>builder()
                .setBootstrapServers(bootstrapServers)
                .setTopics(TOPIC_LOGS)
                .setGroupId(GROUP_ID_LOGS)
                .setStartingOffsets(OffsetsInitializer.latest())
                .setValueOnlyDeserializer(new JsonDeserializationSchema<>(LogEvent.class))
                .build();

        return env.fromSource(source, WatermarkStrategy.noWatermarks(), "Kafka Source: logs")
                .uid("kafka-logs-source");
    }

    private static BroadcastStream<RuleConfig> createConfigBroadcast(StreamExecutionEnvironment env, String bootstrapServers) {
        KafkaSource<RuleConfig> configSource = KafkaSource.<RuleConfig>builder()
                .setBootstrapServers(bootstrapServers)
                .setTopics(TOPIC_CONFIG)
                .setGroupId(GROUP_ID_CONFIG)
                .setStartingOffsets(OffsetsInitializer.latest())
                .setValueOnlyDeserializer(new JsonDeserializationSchema<>(RuleConfig.class))
                .build();

        MapStateDescriptor<String, RuleConfig> ruleStateDescriptor = new MapStateDescriptor<>(
                STATE_RULES,
                BasicTypeInfo.STRING_TYPE_INFO,
                TypeInformation.of(new TypeHint<RuleConfig>() {})
        );

        return env.fromSource(configSource, WatermarkStrategy.noWatermarks(), "Kafka Source: config")
                .uid("kafka-config-source")
                .broadcast(ruleStateDescriptor);
    }

    private static org.apache.flink.streaming.api.functions.sink.SinkFunction<LogEvent> createEntryLogsSink(
            String jdbcUrl, String user, String password) {
        
        return JdbcSink.sink(
                "INSERT INTO entry_logs (timestamp, detected_id, camera_id, authorized, event_type, " +
                        "location, device_status, image_video_ref, processing_time, model_version) " +
                        "VALUES (to_timestamp(?::numeric), ?, ?, ?, ?, ?, ?, ?, ?::interval, ?)",
                (statement, event) -> {
                    statement.setString(1, event.getTimestamp());
                    statement.setObject(2, event.getDetectedId());
                    statement.setObject(3, event.getCameraId());
                    statement.setObject(4, event.getAuthorized());
                    statement.setString(5, event.getEventType());
                    statement.setString(6, event.getLocation());
                    statement.setString(7, event.getDeviceStatus());
                    statement.setString(8, event.getImageVideoRef());
                    statement.setString(9, event.getProcessingTime());
                    statement.setString(10, event.getModelVersion());
                },
                JdbcExecutionOptions.builder()
                        .withBatchSize(100)
                        .withBatchIntervalMs(1000)
                        .withMaxRetries(3)
                        .build(),
                new JdbcConnectionOptions.JdbcConnectionOptionsBuilder()
                        .withUrl(jdbcUrl)
                        .withDriverName("org.postgresql.Driver")
                        .withUsername(user)
                        .withPassword(password)
                        .build()
        );
    }

    private static org.apache.flink.streaming.api.functions.sink.SinkFunction<AnomalyAlert> createAnomaliesLogsSink(
            String jdbcUrl, String user, String password) {
        
        return JdbcSink.sink(
                "INSERT INTO anomalies_logs (timestamp, detected_id, camera_id, anomaly_id) " +
                        "VALUES (to_timestamp(?::numeric), ?, ?, ?)",
                (statement, alert) -> {
                    statement.setString(1, alert.getTimestamp());
                    statement.setObject(2, alert.getDetectedId());
                    statement.setObject(3, alert.getCameraId());
                    statement.setObject(4, alert.getAnomalyId());
                },
                JdbcExecutionOptions.builder()
                        .withBatchSize(50)
                        .withBatchIntervalMs(500)
                        .withMaxRetries(3)
                        .build(),
                new JdbcConnectionOptions.JdbcConnectionOptionsBuilder()
                        .withUrl(jdbcUrl)
                        .withDriverName("org.postgresql.Driver")
                        .withUsername(user)
                        .withPassword(password)
                        .build()
        );
    }

    private static KafkaSink<AnomalyAlert> createKafkaAlertsSink(String bootstrapServers) {
        return KafkaSink.<AnomalyAlert>builder()
                .setBootstrapServers(bootstrapServers)
                .setRecordSerializer(KafkaRecordSerializationSchema.<AnomalyAlert>builder()
                        .setTopic(TOPIC_ALERTS)
                        .setValueSerializationSchema(new JsonSerializationSchema<AnomalyAlert>())
                        .build())
                .setDeliveryGuarantee(DeliveryGuarantee.AT_LEAST_ONCE)
                .build();
    }

    private static String getEnvOrDefault(String key, String defaultValue) {
        String value = System.getenv(key);
        return (value != null && !value.isEmpty()) ? value : defaultValue;
    }
}
