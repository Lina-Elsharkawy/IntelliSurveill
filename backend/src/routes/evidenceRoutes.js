const express = require('express');
const router = express.Router();
const evidenceController = require('../controllers/evidenceController');

// GET /api/evidence/object?ref=...
router.get('/object', evidenceController.proxyEvidence);

module.exports = router;
