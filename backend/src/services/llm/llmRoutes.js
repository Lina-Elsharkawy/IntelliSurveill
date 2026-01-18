const express = require('express');
const router = express.Router();
const { warmup, explainAnomaly } = require('./llmclient');

router.get('/health', async (req, res) => {
  try {
    await warmup();
    res.json({ status: 'ok' });
  } catch (e) {
    res.status(500).json({ status: 'error' });
  }
});

router.post('/explain', async (req, res) => {
  // IMPORTANT: async, not awaited by anomaly pipeline
  explainAnomaly(req.body).catch(() => {});
  res.json({ queued: true });
});

module.exports = router;
