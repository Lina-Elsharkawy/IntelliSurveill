/**
 * auditMiddleware.js
 * Logs CREATE (POST) and DELETE actions with real user email.
 * Resolves Auth0 sub -> email via Management API (cached in-memory).
 */

const axios = require('axios');
const { writeLog } = require('../controllers/auditLogController');

// ── Auth0 Management API token (shared cache) ──────────────────────────────
let _mgmtToken = null;
let _mgmtExpiry = 0;

async function getMgmtToken() {
    if (_mgmtToken && Date.now() < _mgmtExpiry) return _mgmtToken;
    const domain = (process.env.AUTH0_DOMAIN || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
    const res = await axios.post(`https://${domain}/oauth/token`, {
        client_id: process.env.AUTH0_CLIENT_ID,
        client_secret: process.env.AUTH0_CLIENT_SECRET,
        audience: `https://${domain}/api/v2/`,
        grant_type: 'client_credentials',
    });
    _mgmtToken = res.data.access_token;
    _mgmtExpiry = Date.now() + res.data.expires_in * 1000 - 60_000;
    return _mgmtToken;
}

// ── Sub → email cache (lives for the process lifetime) ─────────────────────
const subEmailCache = new Map();

async function resolveEmail(sub) {
    if (!sub) return 'unknown';
    if (subEmailCache.has(sub)) return subEmailCache.get(sub);
    try {
        const domain = (process.env.AUTH0_DOMAIN || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
        const token = await getMgmtToken();
        const res = await axios.get(
            `https://${domain}/api/v2/users/${encodeURIComponent(sub)}`,
            { headers: { Authorization: `Bearer ${token}` } }
        );
        const email = res.data.email || sub;
        subEmailCache.set(sub, email);
        return email;
    } catch {
        return sub; // fall back to sub if lookup fails
    }
}

// ── Path helpers ───────────────────────────────────────────────────────────
const SKIP_PATHS = ['/evidence', '/health', '/diag-test', '/backup', '/chatbot', '/config', '/login', '/audit-logs'];

const RESOURCE_LABELS = {
    admin: 'User',
    cameras: 'Camera',
    employees: 'Employee',
    'anomaly-rules': 'Rule',
    'anomaly-candidates': 'Anomaly',
    departments: 'Department',
    labs: 'Lab',
};

const resourceFromPath = (url) => {
    const segment = url.replace(/^\/+/, '').split('/')[0] || 'unknown';
    return RESOURCE_LABELS[segment] || segment;
};

// Match Auth0 user IDs (auth0|xxx) as well as plain digits
const idFromPath = (url) => {
    const m = url.match(/\/(auth0\|[^/?#]+|\d+)(?:[/?#]|$)/);
    return m ? m[1] : null;
};

const buildDescription = (action, resource, resourceId, body) => {
    let verb = action === 'CREATE' ? 'Created' : action === 'DELETE' ? 'Deleted' : 'Updated';
    
    // For roles, use more specific verbs
    if (resource === 'User Role') {
        verb = action === 'CREATE' ? 'Assigned' : action === 'DELETE' ? 'Removed' : 'Updated';
    }

    const name = body?.name || body?.email || body?.username || '';
    let targetStr = name ? `: ${name}` : (resourceId ? ` (ID: ${resourceId})` : '');

    // For updates, describe what was updated if possible
    if (action === 'UPDATE' && body && typeof body === 'object') {
        const keys = Object.keys(body).filter(k => k !== 'id' && body[k] !== undefined && body[k] !== null && body[k] !== '');
        
        const updates = keys.filter(k => k !== 'password').map(k => `${k} to ${body[k]}`).join(', ');
        const pwdStr = body.password ? 'updated password' : '';
        
        let changes = [updates, pwdStr].filter(Boolean).join(', ');
        if (changes) {
            return `${verb} ${resource}${targetStr} - changes: ${changes}`;
        }
    }

    return `${verb} ${resource}${targetStr}`;
};

// ── Middleware ─────────────────────────────────────────────────────────────
exports.auditMiddleware = (req, res, next) => {
    const method = req.method.toUpperCase();

    if (!['POST', 'DELETE', 'PUT', 'PATCH'].includes(method)) return next();
    if (req.url.includes('/review')) return next();
    if (req.url.includes('/reactivate')) return next();
    if (req.url.includes('/preview')) return next();
    if (req.url.includes('/resolve')) return next();
    if (req.url.includes('/use-for-retrain')) return next();
    if (SKIP_PATHS.some(s => req.url.startsWith(s))) return next();

    let action = (method === 'POST') ? 'CREATE' : (method === 'DELETE') ? 'DELETE' : 'UPDATE';
    let resourceOverride = null;

    // Special case for role management so it doesn't look like we deleted the user
    // We will keep action as CREATE/DELETE but override resource to "User Role"
    if (req.url.match(/\/roles\/?(\?.*)?$/)) {
        action = method === 'POST' ? 'CREATE' : method === 'DELETE' ? 'DELETE' : 'UPDATE';
        resourceOverride = 'User Role';
    }

    // Capture body NOW (before response is sent)
    const bodySnapshot = { ...req.body };

    res.on('finish', async () => {
        if (res.statusCode < 200 || res.statusCode >= 300) return;

        const payload = req.auth?.payload || {};
        const sub = payload.sub || null;
        // Resolve real email via Auth0 Management API (cached)
        const user_email = await resolveEmail(sub);

        const resource = resourceOverride || resourceFromPath(req.url);
        const resourceId = idFromPath(req.url) || (bodySnapshot?.id ? String(bodySnapshot.id) : null);
        const description = req.auditDescription || buildDescription(action, resource, resourceId, bodySnapshot);

        writeLog({ user_email, action, resource, resource_id: resourceId, details: { description } });
    });

    next();
};