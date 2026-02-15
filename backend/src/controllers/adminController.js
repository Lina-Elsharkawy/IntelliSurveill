const axios = require('axios');

let managementToken = null;
let tokenExpiry = null;

const getManagementApiToken = async () => {
    if (managementToken && tokenExpiry && Date.now() < tokenExpiry) {
        return managementToken;
    }

    try {
        const domain = process.env.AUTH0_DOMAIN.replace('https://', '').replace('/', '');

        const response = await axios.post(`https://${domain}/oauth/token`, {
            client_id: process.env.AUTH0_CLIENT_ID,
            client_secret: process.env.AUTH0_CLIENT_SECRET,
            audience: `https://${domain}/api/v2/`,
            grant_type: 'client_credentials'
        });

        managementToken = response.data.access_token;
        tokenExpiry = Date.now() + (response.data.expires_in * 1000) - 60000;
        return managementToken;
    } catch (error) {
        throw new Error('Failed to authenticate with Auth0 Management API');
    }
};

const getBaseUrl = () => {
    const domain = process.env.AUTH0_DOMAIN.replace('https://', '').replace('/', '');
    return `https://${domain}`;
};

exports.getUsers = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const response = await axios.get(`${getBaseUrl()}/api/v2/users`, {
            headers: { Authorization: `Bearer ${token}` },
            params: { q: req.query.q, search_engine: 'v3' }
        });
        res.json(response.data);
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: 'Failed to fetch users' });
    }
};

exports.getUserRoles = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { id } = req.params;
        const response = await axios.get(`${getBaseUrl()}/api/v2/users/${encodeURIComponent(id)}/roles`, {
            headers: { Authorization: `Bearer ${token}` }
        });
        res.json(response.data);
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: error.response?.data?.message || 'Failed to fetch user roles' });
    }
};

exports.assignRoles = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { id } = req.params;
        const { roles } = req.body;
        await axios.post(`${getBaseUrl()}/api/v2/users/${encodeURIComponent(id)}/roles`, { roles }, {
            headers: { Authorization: `Bearer ${token}` }
        });
        res.json({ message: 'Roles assigned successfully' });
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: error.response?.data?.message || 'Failed to assign roles' });
    }
};

exports.removeRoles = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { id } = req.params;
        const { roles } = req.body;
        await axios.delete(`${getBaseUrl()}/api/v2/users/${encodeURIComponent(id)}/roles`, {
            headers: { Authorization: `Bearer ${token}` },
            data: { roles }
        });
        res.json({ message: 'Roles removed successfully' });
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: error.response?.data?.message || 'Failed to remove roles' });
    }
};

exports.deleteUser = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { id } = req.params;
        await axios.delete(`${getBaseUrl()}/api/v2/users/${encodeURIComponent(id)}`, {
            headers: { Authorization: `Bearer ${token}` }
        });
        res.json({ message: 'User deleted successfully' });
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: error.response?.data?.message || 'Failed to delete user' });
    }
};

exports.getAllRoles = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const response = await axios.get(`${getBaseUrl()}/api/v2/roles`, {
            headers: { Authorization: `Bearer ${token}` }
        });
        res.json(response.data);
    } catch (error) {
        res.status(error.response?.status || 500).json({ error: 'Failed to fetch roles' });
    }
};

exports.createUser = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { email, password, name } = req.body;

        if (!email || !password) {
            return res.status(400).json({ error: 'Email and password are required' });
        }

        const connection = process.env.AUTH0_CONNECTION || 'Username-Password-Authentication';
        const payload = {
            email,
            password,
            connection: connection,
            email_verified: false
        };

        if (name) {
            payload.name = name;
        }

        const url = `${getBaseUrl()}/api/v2/users`;

        const response = await axios.post(url, payload, {
            headers: { Authorization: `Bearer ${token}` }
        });

        res.json(response.data);
    } catch (error) {
        res.status(error.response?.status || 500).json({
            error: error.response?.data?.message || 'Failed to create user',
            details: error.response?.data
        });
    }
};

exports.updateUser = async (req, res) => {
    try {
        const token = await getManagementApiToken();
        const { id } = req.params;
        const { email, password, name } = req.body;

        const updateData = {};
        if (email) updateData.email = email;
        if (password) updateData.password = password;
        if (name) updateData.name = name;

        if (Object.keys(updateData).length === 0) {
            return res.status(400).json({ error: 'No data to update' });
        }

        // Clean user ID just in case
        const userId = id.trim();
        const url = `${getBaseUrl()}/api/v2/users/${encodeURIComponent(userId)}`;

        const response = await axios.patch(url, updateData, {
            headers: { Authorization: `Bearer ${token}` }
        });

        res.json(response.data);
    } catch (error) {
        res.status(error.response?.status || 500).json({
            error: error.response?.data?.message || 'Failed to update user',
            details: error.response?.data
        });
    }
};