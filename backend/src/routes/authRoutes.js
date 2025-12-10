const express = require('express');
const axios = require('axios');
const router = express.Router();

router.post('/login', async (req, res) => {
    const { username, password } = req.body;

    try {
        const response = await axios.post(`https://${process.env.AUTH0_DOMAIN}/oauth/token`, {
            grant_type: 'password',
            username,
            password,
            audience: process.env.AUTH0_AUDIENCE,
            client_id: process.env.AUTH0_CLIENT_ID,
            client_secret: process.env.AUTH0_CLIENT_SECRET,
            realm: 'Username-Password-Authentication',
            scope: 'openid profile email'
        }, {
            headers: { 'Content-Type': 'application/json' }
        });

        res.json(response.data);
    } catch (error) {
        console.error('Login Error:', error.response?.data || error.message);
        res.status(error.response?.status || 500).json({
            error: error.response?.data?.error_description || 'Login failed'
        });
    }
});

module.exports = router;
