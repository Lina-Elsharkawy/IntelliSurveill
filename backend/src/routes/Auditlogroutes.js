const express = require('express');
const router = express.Router();
const checkJwt = require('../middleware/auth');
const auditLogController = require('../controllers/auditLogController');

// All audit routes require authentication
router.use(checkJwt);

// GET /api/audit-logs/stats
router.get('/stats', auditLogController.getStats);

// GET /api/audit-logs
router.get('/', auditLogController.getLogs);

// GET /api/audit-logs/:id
router.get('/:id', auditLogController.getLogById);

// POST /api/audit-logs  (manual write by a service)
router.post('/', auditLogController.createLog);

// Middleware to check if user is admin
const requireAdmin = (req, res, next) => {
    // Check both standard roles and namespace roles
    const roles = req.auth?.payload?.['https://myapp.com/roles'] || req.auth?.payload?.roles || [];
    if (!roles.includes('admin')) {
        return res.status(403).json({ error: 'Admin privileges required' });
    }
    next();
};

// DELETE /api/audit-logs  (Clear all logs)
router.delete('/', requireAdmin, auditLogController.clearLogs);

// DELETE /api/audit-logs/:id  (Delete specific log)
router.delete('/:id', requireAdmin, auditLogController.deleteLog);

module.exports = router;