const express = require('express');
const router = express.Router();
const anomalyProxyController = require('../controllers/anomalyProxyController');

// GET /api/anomalies
router.get('/', anomalyProxyController.getAnomalies);

// GET /api/anomalies/:id
router.get('/:id', anomalyProxyController.getAnomalyById);

// POST /api/anomalies/:id/review
router.post('/:id/review', anomalyProxyController.reviewAnomaly);

module.exports = router;
