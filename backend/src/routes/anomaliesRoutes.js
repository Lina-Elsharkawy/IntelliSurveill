const express = require('express');
const router = express.Router();
const anomaliesController = require('../controllers/anomalyController');
const configController = require('../controllers/configController');

// Route to get all anomalies
router.get('/get_all_anomalies', anomaliesController.getAnomalies);
// Route to get a single anomaly by ID
router.get('/get_anomaly/:id', anomaliesController.getAnomalyById);
// Route to delete an anomaly
router.delete('/delete_anomaly/:id', anomaliesController.deleteAnomaly);

// Route to update anomaly detection configuration
router.post('/config', configController.updateConfig);

module.exports = router;