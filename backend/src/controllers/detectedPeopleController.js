const DetectedPeople = require('../models/detected_person');

// Get all detected people
exports.getDetectedPeople = async (req, res) => {
    try {
        const detectedPeopleList = await DetectedPeople.findAll();
        res.status(200).json(detectedPeopleList);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single detected person by ID
exports.getDetectedPersonById = async (req, res) => {
    try {
        const { id } = req.params;
        const detectedPerson = await DetectedPeople.findByPk(id);
        if (!detectedPerson) return res.status(404).json({ error: 'Detected person not found' });
        res.status(200).json(detectedPerson);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get detected people by camera ID (optional - useful for filtering)
exports.getDetectedPeopleByCamera = async (req, res) => {
    try {
        const { camera_id } = req.params;
        const detectedPeople = await DetectedPeople.findAll({
            where: { camera_id }
        });
        res.status(200).json(detectedPeople);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get detected people by anomaly ID (optional - useful for filtering)
exports.getDetectedPeopleByAnomaly = async (req, res) => {
    try {
        const { anomaly_id } = req.params;
        const detectedPeople = await DetectedPeople.findAll({
            where: { anomaly_id }
        });
        res.status(200).json(detectedPeople);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};