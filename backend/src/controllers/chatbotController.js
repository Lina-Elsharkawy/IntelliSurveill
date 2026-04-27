const axios = require('axios');

const CHATBOT_SERVICE_URL = process.env.CHATBOT_SERVICE_URL || 'http://chatbot-service:8000';

exports.query = async (req, res) => {
    try {
        const { data } = await axios.post(`${CHATBOT_SERVICE_URL}/query`, {
            question: req.body.question
        });
        res.json(data);
    } catch (err) {
        console.error('Chatbot query error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.health = async (req, res) => {
    try {
        const { data } = await axios.get(`${CHATBOT_SERVICE_URL}/health`);
        res.json(data);
    } catch (err) {
        console.error('Chatbot health error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.schema = async (req, res) => {
    try {
        const { data } = await axios.get(`${CHATBOT_SERVICE_URL}/schema`);
        res.json(data);
    } catch (err) {
        console.error('Chatbot schema error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};