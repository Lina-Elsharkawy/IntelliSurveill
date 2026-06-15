const Log = require('../models/log');

// Get all logs
exports.getLogs = async (req, res) => {
    try {
        const logsList = await Log.findAll();
        res.status(200).json(logsList);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single log by ID
exports.getLogById = async (req, res) => {
    try {
        const { id } = req.params;
        const log = await Log.findByPk(id);
        if (!log) return res.status(404).json({ error: 'Log not found' });
        res.status(200).json(log);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get logs by camera ID
exports.getLogsByCamera = async (req, res) => {
    try {
        const { camera_id } = req.params;
        const logs = await Log.findAll({
            where: { camera_id }
        });
        res.status(200).json(logs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get logs by event type
exports.getLogsByEventType = async (req, res) => {
    try {
        const { event_type } = req.params;
        const logs = await Log.findAll({
            where: { event_type }
        });
        res.status(200).json(logs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get logs by authorization status
exports.getLogsByAuthorization = async (req, res) => {
    try {
        const { authorized } = req.params; // true or false
        const logs = await Log.findAll({
            where: { authorized: authorized === 'true' }
        });
        res.status(200).json(logs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get logs by location
exports.getLogsByLocation = async (req, res) => {
    try {
        const { location } = req.params;
        const logs = await Log.findAll({
            where: { location }
        });
        res.status(200).json(logs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};
