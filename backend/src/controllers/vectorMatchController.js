const axios = require('axios');

const VECTOR_MATCH_URL = process.env.VECTOR_MATCH_URL || 'http://vector-match:8000';
const EVIDENCE_GATEWAY_URL = process.env.EVIDENCE_GATEWAY_URL || 'http://evidence-gateway:8010';
const sharp = require('sharp');

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

exports.getEntryLogImage = async (req, res) => {
    try {
        const { id } = req.params;

        const { data: log } = await axios.get(`${VECTOR_MATCH_URL}/admin/entry-logs/${id}`);

        if (!log || !log.image_video_ref) {
            return res.status(404).json({ error: 'No image for this entry log' });
        }
        const evidenceUrl = `${EVIDENCE_GATEWAY_URL}/evidence/object`;
        const upstream = await axios.get(evidenceUrl, {
            params: { ref: log.image_video_ref },
                responseType: 'stream'
             }
        );

        if (upstream.headers['content-type']) {
            res.setHeader('Content-Type', upstream.headers['content-type']);
        }

        upstream.data.pipe(res);
    } catch (err) {
        const status = err.response?.status || 500;
        const message = err.response?.data?.detail || err.message || 'Image fetch failed';
        res.status(status).json({ error: message });
    }
};

exports.getEntryLogThumbnail = async (req, res) => {
    try {
        const { id } = req.params;

        const { data: log } = await axios.get(
            `${VECTOR_MATCH_URL}/admin/entry-logs/${id}`
        );

        if (!log || !log.image_video_ref) {
            return res.status(404).json({ error: 'No image for this entry log' });
        }

        const evidenceUrl = `${EVIDENCE_GATEWAY_URL}/evidence/object`;

        const upstream = await axios.get(evidenceUrl, {
            params: { ref: log.image_video_ref },
            responseType: 'arraybuffer'
        });

        // 🔥 Resize with sharp
        const resized = await sharp(upstream.data)
            .resize(160, 160, { fit: 'cover' })
            .jpeg({ quality: 70 })
            .toBuffer();

        res.setHeader('Content-Type', 'image/jpeg');
        res.send(resized);

    } catch (err) {
        const status = err.response?.status || 500;
        const message = err.response?.data?.detail || err.message || 'Thumbnail failed';
        res.status(status).json({ error: message });
    }
};

exports.getCounts = async (req, res) => {
    forward(res, async () => {
        const { data } = await axios.get(`${VECTOR_MATCH_URL}/admin/counts`);
        res.json(data);
    });
};