const express = require('express');
const router = express.Router();

const {
    getAllCandidates,
    getCandidateById,
    createCandidate,
    updateCandidate,
    deleteCandidate,
} = require('../controllers/AnomalyCandidateController');

// Get all anomaly candidates
router.get('/', getAllCandidates);

// Get anomaly candidate by ID (with jobs + feedback)
router.get('/:id', getCandidateById);

// Create anomaly candidate
router.post('/', createCandidate);

// Update anomaly candidate
router.put('/:id', updateCandidate);

// Delete anomaly candidate
router.delete('/:id', deleteCandidate);

module.exports = router;
