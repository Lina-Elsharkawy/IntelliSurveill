const express = require('express');
const axios = require('axios');
const router = express.Router();

router.post('/login', async (req, res) => {
  console.log('================ LOGIN REQUEST ================');
  console.log('HEADERS:', req.headers);
  console.log('BODY:', req.body);
  console.log('USERNAME:', req.body?.username);
  console.log('PASSWORD EXISTS:', !!req.body?.password);
  console.log('===============================================');

  const { username, password } = req.body || {};

  try {
    const response = await axios.post(
      `https://${process.env.AUTH0_DOMAIN}/oauth/token`,
      {
        grant_type: 'http://auth0.com/oauth/grant-type/password-realm',
        username,
        password,
        client_id: process.env.AUTH0_CLIENT_ID,
        client_secret: process.env.AUTH0_CLIENT_SECRET,
        realm: 'Username-Password-Authentication',
        audience: process.env.AUTH0_AUDIENCE,
        scope: 'openid profile email'
      },
      {
        headers: { 'Content-Type': 'application/json' }
      }
    );

    res.json(response.data);
  } catch (error) {
    console.error('====== AUTH0 LOGIN ERROR ======');
    console.error(error.response?.data || error.message);
    console.error('==============================');

    res.status(error.response?.status || 500).json(
      error.response?.data || { error: 'Login failed' }
    );
  }
});

module.exports = router;
