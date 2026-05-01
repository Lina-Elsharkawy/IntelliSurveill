const express = require('express');
const router = express.Router();

const {
    getAllCandidates,
    getCandidateById,
    deleteCandidate,
} = require('../controllers/anomalyCandidateController');

// Get all anomaly candidates
router.get('/', getAllCandidates);

// Get anomaly candidate by ID (with jobs + feedback)
router.get('/:id', getCandidateById);

// Delete anomaly candidate
router.delete('/:id', deleteCandidate);

module.exports = router;
