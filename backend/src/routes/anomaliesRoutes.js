const express = require('express');
const router = express.Router();
const configController = require('../controllers/configController');
// Route to update anomaly detection configuration
router.post('/config', configController.updateConfig);



module.exports = router;