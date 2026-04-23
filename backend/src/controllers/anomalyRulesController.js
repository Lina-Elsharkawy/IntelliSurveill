const axios = require('axios');
const RULES_SERVICE_URL = process.env.ANOMALY_RULES_SERVICE_URL || 'http://anomaly-rules-service:8000';

exports.listRules = async (req, res) => {
    try {
        const { data } = await axios.get(`${RULES_SERVICE_URL}/rules`);
        res.json(data);
    } catch (err) {
        console.error('List rules error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.createRule = async (req, res) => {
    try {
        const { data } = await axios.post(`${RULES_SERVICE_URL}/rules`, {
            rule_text: req.body.rule_text
        });
        res.json(data);
    } catch (err) {
        console.error('Create rule error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.deactivateRule = async (req, res) => {
    try {
        const { data } = await axios.patch(`${RULES_SERVICE_URL}/rules/${req.params.id}/deactivate`);
        res.json(data);
    } catch (err) {
        console.error('Deactivate rule error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.deleteRule = async (req, res) => {
    try {
        const { data } = await axios.delete(`${RULES_SERVICE_URL}/rules/${req.params.id}`);
        res.json(data);
    } catch (err) {
        console.error('Delete rule error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};
exports.previewRule = async (req, res) => {
    try {
        const { data } = await axios.post(`${RULES_SERVICE_URL}/rules/preview`, {
            rule_text: req.body.rule_text
        });
        res.json(data);
    } catch (err) {
        console.error('Preview rule error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.resolveAndAdd = async (req, res) => {
    try {
        const { data } = await axios.post(`${RULES_SERVICE_URL}/rules/resolve-and-add`, {
            rule_text: req.body.rule_text,
            deactivate_rule_ids: req.body.deactivate_rule_ids
        });
        res.json(data);
    } catch (err) {
        console.error('Resolve and add error:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};
exports.reactivatePreview = async (req, res) => {
    try {
        const { data } = await axios.post(`${RULES_SERVICE_URL}/rules/reactivate-preview`, {
            rule_id: parseInt(req.params.id)
        });
        res.json(data);
    } catch (err) {
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};

exports.reactivateRule = async (req, res) => {
    try {
        const { data } = await axios.patch(`${RULES_SERVICE_URL}/rules/${req.params.id}/reactivate`);
        res.json(data);
    } catch (err) {
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};