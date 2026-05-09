const { Op } = require('sequelize');
const AuditLog = require('../models/AuditLog');

// ── Helper: write a log entry (called from middleware or manually) ──────────
exports.writeLog = async ({ user_email, action, resource, resource_id, details, ip_address, user_agent }) => {
    try {
        await AuditLog.create({ user_email, action, resource, resource_id: String(resource_id ?? ''), details, ip_address, user_agent });
    } catch (err) {
        // Never let audit failure crash the main request
        console.error('[AUDIT] Failed to write log:', err.message);
    }
};

// GET /api/audit-logs
// Query params: user_email, action, resource, from, to, limit, offset
exports.getLogs = async (req, res) => {
    try {
        const { user_email, action, resource, from, to, limit = 100, offset = 0 } = req.query;

        const where = {};
        if (user_email) where.user_email = { [Op.iLike]: `%${user_email}%` };
        if (action) where.action = action.toUpperCase();
        if (resource) where.resource = resource;
        if (from || to) {
            where.created_at = {};
            if (from) where.created_at[Op.gte] = new Date(from);
            if (to) where.created_at[Op.lte] = new Date(to);
        }

        const { count, rows } = await AuditLog.findAndCountAll({
            where,
            order: [['created_at', 'DESC']],
            limit: Math.min(Number(limit), 500),
            offset: Number(offset),
        });

        res.status(200).json({ total: count, logs: rows });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// GET /api/audit-logs/:id
exports.getLogById = async (req, res) => {
    try {
        const log = await AuditLog.findByPk(req.params.id);
        if (!log) return res.status(404).json({ error: 'Audit log not found' });
        res.status(200).json(log);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// POST /api/audit-logs  (manual / service-to-service writes)
exports.createLog = async (req, res) => {
    try {
        const { user_email, action, resource, resource_id, details } = req.body;
        if (!user_email || !action) {
            return res.status(400).json({ error: 'user_email and action are required' });
        }

        const ip_address = req.headers['x-forwarded-for'] || req.socket?.remoteAddress;
        const user_agent = req.headers['user-agent'];

        const log = await AuditLog.create({
            user_email,
            action: action.toUpperCase(),
            resource,
            resource_id: resource_id != null ? String(resource_id) : null,
            details,
            ip_address,
            user_agent,
        });
        res.status(201).json(log);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// GET /api/audit-logs/stats  — quick summary counts per action
exports.getStats = async (req, res) => {
    try {
        const sequelize = AuditLog.sequelize;
        const rows = await AuditLog.findAll({
            attributes: [
                'action',
                [sequelize.fn('COUNT', sequelize.col('id')), 'count'],
            ],
            group: ['action'],
            raw: true,
        });

        // Also grab counts by resource
        const byResource = await AuditLog.findAll({
            attributes: [
                'resource',
                [sequelize.fn('COUNT', sequelize.col('id')), 'count'],
            ],
            group: ['resource'],
            raw: true,
        });

        res.status(200).json({ by_action: rows, by_resource: byResource });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// DELETE /api/audit-logs  — clear all logs
exports.clearLogs = async (req, res) => {
    try {
        await AuditLog.destroy({ where: {}, truncate: true });
        res.status(200).json({ message: 'All audit logs cleared' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// DELETE /api/audit-logs/:id  — delete a specific log
exports.deleteLog = async (req, res) => {
    try {
        const deleted = await AuditLog.destroy({ where: { id: req.params.id } });
        if (!deleted) return res.status(404).json({ error: 'Audit log not found' });
        res.status(200).json({ message: 'Audit log deleted' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};