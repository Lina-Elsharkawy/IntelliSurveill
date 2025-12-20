const express = require('express');
const http = require('http');
const { auth } = require('express-oauth2-jwt-bearer');
require('dotenv').config();

const checkJwt = auth({
    audience: process.env.AUTH0_AUDIENCE || 'https://test-audience',
    issuerBaseURL: `https://${process.env.AUTH0_DOMAIN || 'test-domain'}/`,
    tokenSigningAlg: 'RS256'
});

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
    res.status(200).json({ status: 'ok' });
});

app.use('/api', checkJwt);

app.get('/api/protected', (req, res) => {
    res.status(200).json({ message: 'secret' });
});

const server = app.listen(0, () => {
    const port = server.address().port;
    console.log(`Test server running on port ${port}`);

    // Test 1: Public route
    const req1 = http.get(`http://localhost:${port}/health`, (res) => {
        if (res.statusCode === 200) {
            console.log('✅ Public route /health is accessible.');
        } else {
            console.error(`❌ Public route /health failed with status ${res.statusCode}`);
        }

        // Test 2: Protected route
        const req2 = http.get(`http://localhost:${port}/api/protected`, (res) => {
            if (res.statusCode === 401) {
                console.log('✅ Protected route /api/protected correctly returned 401 Unauthorized.');
            } else {
                console.error(`❌ Protected route /api/protected returned status ${res.statusCode} instead of 401.`);
            }
            server.close();
        });
        req2.on('error', (e) => {
            console.error(`❌ Protected route request failed: ${e.message}`);
            server.close();
        });
    });

    req1.on('error', (e) => {
        console.error(`❌ Public route request failed: ${e.message}`);
        server.close();
    });
});
