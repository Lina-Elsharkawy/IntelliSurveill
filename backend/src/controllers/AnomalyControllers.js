const Anomalies = require('../models/anomaly');

// Get all anomalies
exports.getAnomalies = async (req, res) => {
    try {
        const anomaliesList = await Anomalies.findAll();
        res.status(200).json(anomaliesList);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};
// Get a single anomaly by ID
exports.getAnomalyById = async (req, res) => {
    try {
        const { id } = req.params;
        const anomaly = await Anomalies.findByPk(id);
        if (!anomaly) return res.status(404).json({ error: 'Anomaly not found' });
        res.status(200).json(anomaly);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete an anomaly
exports.deleteAnomaly = async (req, res) => {
    try {
        const { id } = req.params;
        const anomaly = await Anomalies.findByPk(id);
        if (!anomaly) return res.status(404).json({ error: 'Anomaly not found' });
        
        await anomaly.destroy();
        res.status(200).json({ message: 'Anomaly deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }

};
