const axios = require('axios');

const ANOMALY_SERVICE_URL = process.env.ANOMALY_SERVICE_URL || 'http://anomaly-service:8000';

exports.getAnomalies = async (req, res) => {
    try {
        const response = await axios.get(`${ANOMALY_SERVICE_URL}/anomaly-candidates?limit=500`);
        res.json(response.data);
    } catch (err) {
        console.error('Error fetching anomalies from anomaly-service:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.getAnomalyById = async (req, res) => {
    try {
        const { id } = req.params;
        const response = await axios.get(`${ANOMALY_SERVICE_URL}/anomaly-candidates/${id}`);
        res.json(response.data);
    } catch (err) {
        console.error(`Error fetching anomaly ${req.params.id} from anomaly-service:`, err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.reviewAnomaly = async (req, res) => {
    try {
        const { id } = req.params;
        const response = await axios.post(`${ANOMALY_SERVICE_URL}/anomaly-candidates/${id}/review`, req.body);
        res.json(response.data);
    } catch (err) {
        console.error(`Error reviewing anomaly ${req.params.id} via anomaly-service:`, err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};
