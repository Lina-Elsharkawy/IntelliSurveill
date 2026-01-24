const { Kafka } = require('kafkajs');

const kafka = new Kafka({
    clientId: 'backend-config-producer',
    brokers: [process.env.KAFKA_BOOTSTRAP_SERVERS || 'kafka:9092'],
});

const producer = kafka.producer();
let isConnected = false;

/**
 * Ensure the producer is connected before sending messages.
 * Uses lazy initialization with automatic reconnection.
 */
const ensureConnected = async () => {
    if (!isConnected) {
        try {
            await producer.connect();
            isConnected = true;
            console.log('Connected to Kafka for config updates');

            // Handle disconnection events
            producer.on('producer.disconnect', () => {
                console.log('Kafka producer disconnected');
                isConnected = false;
            });
        } catch (error) {
            console.error('Error connecting to Kafka:', error.message);
            throw new Error('Failed to connect to Kafka');
        }
    }
};

exports.updateConfig = async (req, res) => {
    const { threshold, windowSeconds } = req.body;

    if (!threshold || !windowSeconds) {
        return res.status(400).json({ error: 'Missing threshold or windowSeconds' });
    }

    try {
        // Ensure connection before sending
        await ensureConnected();

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
        // Reset connection state on error so next request will try to reconnect
        isConnected = false;
        res.status(500).json({ error: 'Failed to update configuration. Kafka may be unavailable.' });
    }
};

