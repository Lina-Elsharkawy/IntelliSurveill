/**
 * Backup proxy routes.
 * Forwards /api/backup/* requests to the s3-backup service.
 */

const express = require('express');
const router = express.Router();

const S3_BACKUP_URL = process.env.S3_BACKUP_URL || 'http://s3-backup:8020';

/**
 * Generic proxy helper — forwards request to the s3-backup service.
 */
async function proxyToBackup(req, res, method, path, body) {
    try {
        const url = `${S3_BACKUP_URL}${path}`;
        const options = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body && Object.keys(body).length > 0) {
            options.body = JSON.stringify(body);
        }

        const response = await fetch(url, options);
        const data = await response.json();

        if (!response.ok) {
            return res.status(response.status).json(data);
        }

        return res.json(data);
    } catch (err) {
        console.error(`[BACKUP PROXY] ${method} ${path} error:`, err.message);
        return res.status(502).json({
            error: 'Backup service unavailable',
            detail: err.message,
        });
    }
}

// GET /api/backup/config
router.get('/config', (req, res) => proxyToBackup(req, res, 'GET', '/backup/config'));

// PUT /api/backup/config
router.put('/config', (req, res) => proxyToBackup(req, res, 'PUT', '/backup/config', req.body));

// GET /api/backup/status
router.get('/status', (req, res) => proxyToBackup(req, res, 'GET', '/backup/status'));

// POST /api/backup/trigger
router.post('/trigger', (req, res) => proxyToBackup(req, res, 'POST', '/backup/trigger'));

module.exports = router;