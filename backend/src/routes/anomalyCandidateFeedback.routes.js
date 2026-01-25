const express = require('express');
const router = express.Router();

const {
    getAllFeedback,
    getFeedbackByCandidate,
    createFeedback,
    markUsedForRetrain,
} = require('../controllers/anomalyCandidateFeedbackController');

// Get all feedback (decision causes)
router.get('/', getAllFeedback);

// Get feedback by anomaly candidate
router.get('/candidate/:candidateId', getFeedbackByCandidate);

// Create feedback
router.post('/', createFeedback);

// Mark feedback as used for retraining
router.patch('/:id/use-for-retrain', markUsedForRetrain);

module.exports = router;
