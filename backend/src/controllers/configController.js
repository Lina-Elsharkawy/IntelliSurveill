const { Kafka } = require('kafkajs');

const kafka = new Kafka({
    clientId: 'backend-config-producer',
    brokers: [process.env.KAFKA_BOOTSTRAP_SERVERS || 'kafka:9092'],
});

const producer = kafka.producer();

const connectProducer = async () => {
    try {
        await producer.connect();
        console.log('Connected to Kafka for config updates');
    } catch (error) {
        console.error('Error connecting to Kafka:', error);
    }
};

connectProducer();

exports.updateConfig = async (req, res) => {
    const { threshold, windowSeconds } = req.body;

    if (!threshold || !windowSeconds) {
        return res.status(400).json({ error: 'Missing threshold or windowSeconds' });
    }

    try {
        const config = {
            threshold: parseInt(threshold),
            windowSeconds: parseInt(windowSeconds),
            updatedAt: new Date().toISOString(),
        };

        await producer.send({
            topic: 'anomaly-config',
            messages: [
                { value: JSON.stringify(config) },
            ],
        });

        console.log('Sent anomaly config update:', config);
        res.json({ message: 'Configuration updated successfully', config });
    } catch (error) {
        console.error('Error sending config to Kafka:', error);
        res.status(500).json({ error: 'Failed to update configuration' });
    }
};
