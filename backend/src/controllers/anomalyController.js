const Anomalies = require('../models/anomaly');
const asyncHandler = require('../middleware/asyncHandler');

// Get all anomalies
exports.getAnomalies = asyncHandler(async (req, res) => {
    const anomaliesList = await Anomalies.findAll();
    res.status(200).json(anomaliesList);
});

// Get a single anomaly by ID
exports.getAnomalyById = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const anomaly = await Anomalies.findByPk(id);
    if (!anomaly) return res.status(404).json({ error: 'Anomaly not found' });
    res.status(200).json(anomaly);
});

// Delete an anomaly
exports.deleteAnomaly = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const anomaly = await Anomalies.findByPk(id);
    if (!anomaly) return res.status(404).json({ error: 'Anomaly not found' });
    
    await anomaly.destroy();
    res.status(200).json({ message: 'Anomaly deleted successfully' });
});
