const express = require('express');
const router = express.Router();
const checkJwt = require('../middleware/auth');
const anomalyRulesController = require('../controllers/anomalyRulesController');

router.use(checkJwt);

// Mounted at /api/anomaly-rules in app.js, so paths here are relative
router.get('/', anomalyRulesController.listRules);
router.post('/', anomalyRulesController.createRule);
router.patch('/:id/deactivate', anomalyRulesController.deactivateRule);
router.delete('/:id', anomalyRulesController.deleteRule);
router.post('/preview', anomalyRulesController.previewRule);
router.post('/resolve-and-add', anomalyRulesController.resolveAndAdd);
router.post('/resolve-and-reactivate', anomalyRulesController.resolveAndReactivate);
router.post('/reactivate-preview/:id', anomalyRulesController.reactivatePreview);
router.patch('/:id/reactivate', anomalyRulesController.reactivateRule);


module.exports = router;