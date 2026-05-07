const axios = require('axios');

const EVIDENCE_GATEWAY_URL = process.env.EVIDENCE_GATEWAY_URL || 'http://evidence-gateway:8010';

exports.proxyEvidence = async (req, res) => {
    try {
        const { ref } = req.query;
        if (!ref) {
            return res.status(400).json({ error: 'Missing ref query parameter' });
        }
        
        // Proxy as a stream
        const response = await axios({
            method: 'get',
            url: `${EVIDENCE_GATEWAY_URL}/evidence/object`,
            params: { ref },
            responseType: 'stream'
        });

        // Set the appropriate content-type from the gateway response
        res.set('Content-Type', response.headers['content-type'] || 'application/octet-stream');
        
        response.data.pipe(res);
    } catch (err) {
        console.error('Error proxying evidence from gateway:', err.message);
        res.status(err.response?.status || 500).json({ error: err.message });
    }
};
