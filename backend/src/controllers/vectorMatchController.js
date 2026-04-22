const axios = require('axios');

const VECTOR_MATCH_URL = process.env.VECTOR_MATCH_URL || 'http://vector-match:8000';

// Helper: forward errors cleanly
const forward = async (res, fn) => {
    try {
        await fn();
    } catch (err) {
        const status = err.response?.status || 500;
        const message = err.response?.data?.detail || err.message || 'Vector match service error';
        res.status(status).json({ error: message });
    }
};

exports.listIdentities = async (req, res) => {
    forward(res, async () => {
        const { limit = 100, offset = 0 } = req.query;
        const { data } = await axios.get(`${VECTOR_MATCH_URL}/admin/identities`, {
            params: { limit, offset }
        });
        res.json(data);
    });
};

exports.listPendingUnknowns = async (req, res) => {
    forward(res, async () => {
        const { limit = 50, offset = 0 } = req.query;
        const { data } = await axios.get(`${VECTOR_MATCH_URL}/admin/pending-unknowns`, {
            params: { limit, offset }
        });
        res.json(data);
    });
};

exports.listRecentEntryLogs = async (req, res) => {
    forward(res, async () => {
        const { limit = 100, offset = 0 } = req.query;
        const { data } = await axios.get(`${VECTOR_MATCH_URL}/admin/recent-entry-logs`, {
            params: { limit, offset }
        });
        res.json(data);
    });
};

exports.assignUnknown = async (req, res) => {
    forward(res, async () => {
        const { data } = await axios.post(
            `${VECTOR_MATCH_URL}/admin/assign-unknown`,
            req.body
        );
        res.json(data);
    });
};

exports.createIdentityFromUnknown = async (req, res) => {
    forward(res, async () => {
        const { data } = await axios.post(
            `${VECTOR_MATCH_URL}/admin/create-identity-from-unknown`,
            req.body
        );
        res.json(data);
    });
};