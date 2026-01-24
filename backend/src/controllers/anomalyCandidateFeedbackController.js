const AnomalyCandidateFeedback = require('../models/AnomalyCandidateFeedback');

// Get all feedback
exports.getAllFeedback = async (req, res) => {
    try {
        const feedback = await AnomalyCandidateFeedback.findAll({
            order: [['id', 'ASC']],
        });
        res.json(feedback);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get feedback for specific anomaly candidate
exports.getFeedbackByCandidate = async (req, res) => {
    try {
        const feedback = await AnomalyCandidateFeedback.findAll({
            where: { anomaly_candidate_id: req.params.candidateId },
        });
        res.json(feedback);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Add feedback
exports.createFeedback = async (req, res) => {
    try {
        const feedback = await AnomalyCandidateFeedback.create(req.body);
        res.status(201).json(feedback);
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};

// Mark feedback as used for retraining
exports.markUsedForRetrain = async (req, res) => {
    try {
        const [updated] = await AnomalyCandidateFeedback.update(
            { used_for_retrain: true },
            { where: { id: req.params.id } }
        );

        if (!updated) {
            return res.status(404).json({ message: 'Feedback not found' });
        }

        res.json({ message: 'Feedback marked for retraining' });
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};
