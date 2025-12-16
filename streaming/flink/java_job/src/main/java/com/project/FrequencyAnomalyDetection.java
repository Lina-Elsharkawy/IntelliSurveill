package com.project;

import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.windowing.assigners.SlidingProcessingTimeWindows;
import org.apache.flink.streaming.api.windowing.time.Time;
import org.apache.flink.api.common.typeinfo.Types;
import org.apache.flink.api.java.tuple.Tuple2;
import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.databind.JsonNode;
import org.apache.flink.shaded.jackson2.com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.flink.api.common.functions.MapFunction;
import org.apache.flink.api.common.functions.ReduceFunction;
import org.apache.flink.api.common.functions.FilterFunction;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;

public class FrequencyAnomalyDetection {

    public static void main(String[] args) throws Exception {
        final StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();

        String kafkaBootstrapServers = System.getenv().getOrDefault("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092");

        KafkaSource<String> source = KafkaSource.<String>builder()
                .setBootstrapServers(kafkaBootstrapServers)
                .setTopics("logs")
                .setGroupId("flink_frequency_detector")
                .setStartingOffsets(OffsetsInitializer.latest())
                .setValueOnlyDeserializer(new SimpleStringSchema())
                .build();

        DataStream<String> kafkaStream = env.fromSource(source, WatermarkStrategy.noWatermarks(), "Kafka Source");

        DataStream<Tuple2<String, Integer>> alerts = kafkaStream
                .map(new MapFunction<String, Tuple2<String, Integer>>() {
                    private final ObjectMapper jsonParser = new ObjectMapper();

                    @Override
                    public Tuple2<String, Integer> map(String value) throws Exception {
                        JsonNode jsonNode = jsonParser.readTree(value);
                        String cameraId = jsonNode.get("camera_id").asText();
                        return new Tuple2<>(cameraId, 1);
                    }
                })
                .keyBy(0)
                .window(SlidingProcessingTimeWindows.of(Time.seconds(30), Time.seconds(5)))
                .reduce(new ReduceFunction<Tuple2<String, Integer>>() {
                    @Override
                    public Tuple2<String, Integer> reduce(Tuple2<String, Integer> a, Tuple2<String, Integer> b) {
                        return new Tuple2<>(a.f0, a.f1 + b.f1);
                    }
                })
                .filter(new FilterFunction<Tuple2<String, Integer>>() {
                    @Override
                    public boolean filter(Tuple2<String, Integer> value) throws Exception {
                        return value.f1 > 5;
                    }
                });

        KafkaSink<String> sink = KafkaSink.<String>builder()
                .setBootstrapServers(kafkaBootstrapServers)
                .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                        .setTopic("frequency_alerts")
                        .setValueSerializationSchema(new SimpleStringSchema())
                        .build()
                )
                .build();

        alerts.map(new MapFunction<Tuple2<String, Integer>, String>() {
            @Override
            public String map(Tuple2<String, Integer> value) throws Exception {
                return "{\"camera_id\": \"" + value.f0 + "\", \"anomaly_type\": \"Frequency\", \"description\": \"High frequency access detected: " + value.f1 + " attempts in 30s\"}";
            }
        }).sinkTo(sink);


        env.execute("Frequency Anomaly Detection (Java)");
    }
}
