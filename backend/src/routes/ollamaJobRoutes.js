const express = require('express');
const router = express.Router();

const {
    getAllJobs,
    getJobsByCandidate,
    createJob,
    updateJob,
} = require('../controllers/ollamaJobController');

// Get all jobs
router.get('/', getAllJobs);

// Get jobs by anomaly candidate
router.get('/candidate/:candidateId', getJobsByCandidate);

// Create job
router.post('/', createJob);

// Update job
router.put('/:id', updateJob);

module.exports = router;
