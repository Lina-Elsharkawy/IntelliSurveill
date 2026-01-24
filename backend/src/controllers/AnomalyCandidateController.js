const AnomalyCandidate = require('../models/AnomalyCandidate');
const OllamaJob = require('../models/OllamaJob');
const AnomalyCandidateFeedback = require('../models/AnomalyCandidateFeedback');

// Get all anomaly candidates
exports.getAllCandidates = async (req, res) => {
    try {
        const candidates = await AnomalyCandidate.findAll({
            order: [['id', 'ASC']],
        });
        res.json(candidates);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get anomaly candidate by ID (with jobs + feedback)
exports.getCandidateById = async (req, res) => {
    try {
        const candidate = await AnomalyCandidate.findByPk(req.params.id, {
            include: [OllamaJob, AnomalyCandidateFeedback],
        });

        if (!candidate) {
            return res.status(404).json({ message: 'Anomaly candidate not found' });
        }

        res.json(candidate);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create anomaly candidate
exports.createCandidate = async (req, res) => {
    try {
        const candidate = await AnomalyCandidate.create(req.body);
        res.status(201).json(candidate);
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};

// Update anomaly candidate
exports.updateCandidate = async (req, res) => {
    try {
        const [updated] = await AnomalyCandidate.update(req.body, {
            where: { id: req.params.id },
        });

        if (!updated) {
            return res.status(404).json({ message: 'Anomaly candidate not found' });
        }

        res.json({ message: 'Anomaly candidate updated successfully' });
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};

// Delete anomaly candidate
exports.deleteCandidate = async (req, res) => {
    try {
        const deleted = await AnomalyCandidate.destroy({
            where: { id: req.params.id },
        });

        if (!deleted) {
            return res.status(404).json({ message: 'Anomaly candidate not found' });
        }

        res.json({ message: 'Anomaly candidate deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};
