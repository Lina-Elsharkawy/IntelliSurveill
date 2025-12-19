const express = require('express');
const router = express.Router();
const controller = require('./controller');

// POST /api/rag/query
router.post('/query', controller.query);

module.exports = router;
