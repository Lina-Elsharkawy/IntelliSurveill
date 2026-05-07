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

const anomalyProxyController = require('../controllers/anomalyProxyController');

// Proxy routes for anomaly-service
router.get('/', (req, res, next) => {
    console.log('HIT PROXY /');
    next();
}, anomalyProxyController.getAnomalies);

router.get('/:id', (req, res, next) => {
    console.log('HIT PROXY /:id with id=', req.params.id);
    next();
}, anomalyProxyController.getAnomalyById);

router.post('/:id/review', anomalyProxyController.reviewAnomaly);

module.exports = router;