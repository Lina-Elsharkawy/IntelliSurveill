const express = require('express');
const router = express.Router();
const logsController = require('../controllers/logsController');

router.get('/logs', logsController.getLogs);                           // GET /api/logs
router.get('/log:id', logsController.getLogById);                     // GET /api/logs/:id
router.get('/cameralogs/:camera_id', logsController.getLogsByCamera);  // GET /api/logs/camera/:camera_id
router.get('/event/:event_type', logsController.getLogsByEventType); // GET /api/logs/event/:event_type
router.get('/authorized/:authorized', logsController.getLogsByAuthorization); // GET /api/logs/authorized/true
router.get('/location/:location', logsController.getLogsByLocation); // GET /api/logs/location/:location
router.get('/anomaly/:anomaly_id', logsController.getLogsByAnomaly); // GET /api/logs/anomaly/:anomaly_id

module.exports = router;