const express = require('express');
const router = express.Router();
const ragService = require('../services/ragService');

// POST /api/rag/query
router.post('/query', async (req, res) => {
    try {
        const { text } = req.body;
        if (!text) {
            return res.status(400).json({ error: 'Query text is required' });
        }

        // Call the service
        const result = await ragService.processQuery(text);

        res.json({
            status: 'success',
            data: result
        });

    } catch (error) {
        console.error('[RAG API Error]', error);
        const statusCode = error.message.includes('Security') ? 403 : 500;
        res.status(statusCode).json({
            status: 'error',
            message: error.message
        });
    }
});

module.exports = router;
