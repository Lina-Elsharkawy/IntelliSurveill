import os
from pyflink.common import Types, Row
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import FlinkKafkaConsumer, FlinkKafkaProducer
from pyflink.datastream.formats.json import JsonRowDeserializationSchema, JsonRowSerializationSchema
from pyflink.datastream.window import SlidingProcessingTimeWindows
from pyflink.common.time import Time

def frequency_anomaly_detection():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)

    # Kafka Config
    kafka_bootstrap_servers = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092')
    
    # Source: Logs Topic
    kafka_consumer = FlinkKafkaConsumer(
        topics='logs',
        deserialization_schema=JsonRowDeserializationSchema.builder()
            .type_info(Types.ROW_NAMED(
                ['camera_id', 'timestamp', 'event_type'],
                [Types.STRING(), Types.STRING(), Types.STRING()]
            ))
            .ignore_parse_errors()
            .build(),
        properties={'bootstrap.servers': kafka_bootstrap_servers, 'group.id': 'flink_frequency_detector'}
    )
    kafka_consumer.set_start_from_latest()

    ds = env.add_source(kafka_consumer)

    # Logic: Key by camera_id, Window 30s, Count > 5
    # Map to (camera_id, 1)
    # KeyBy(0) -> camera_id
    # Window: Sliding 30s, Slide 5s
    # Reduce: Sum counts
    # Filter: Count > 5
    # Map: Format output as Row
    
    alerts = ds \
        .map(lambda row: (row['camera_id'], 1), output_type=Types.TUPLE([Types.STRING(), Types.INT()])) \
        .key_by(lambda x: x[0]) \
        .window(SlidingProcessingTimeWindows.of(Time.seconds(30), Time.seconds(5))) \
        .reduce(lambda a, b: (a[0], a[1] + b[1])) \
        .filter(lambda x: x[1] > 5) \
        .map(lambda x: Row(camera_id=x[0], anomaly_type='Frequency', description=f"High frequency access detected: {x[1]} attempts in 30s"), 
             output_type=Types.ROW_NAMED(['camera_id', 'anomaly_type', 'description'], [Types.STRING(), Types.STRING(), Types.STRING()]))

    # Sink: Frequency Alerts Topic
    kafka_producer = FlinkKafkaProducer(
        topic='frequency_alerts',
        serialization_schema=JsonRowSerializationSchema.builder()
            .type_info(Types.ROW_NAMED(['camera_id', 'anomaly_type', 'description'], [Types.STRING(), Types.STRING(), Types.STRING()]))
            .build(),
        producer_config={'bootstrap.servers': kafka_bootstrap_servers}
    )

    alerts.add_sink(kafka_producer)

    env.execute("Frequency Anomaly Detection")

if __name__ == '__main__':
    frequency_anomaly_detection()
