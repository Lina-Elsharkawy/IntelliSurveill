const express = require('express');
const cors = require('cors');
const sequelize = require('./db/connection');
const models = require('./models'); // import model index
const checkJwt = require('./middleware/auth');
const authRouter = require('./routes/authRoutes');
const apiRoutes = require('./routes/index');
const { auditMiddleware } = require('./middleware/auditMiddleware');
const app = express();


app.use(cors({
  origin: ['http://localhost:8080', 'http://127.0.0.1:8000', 'http://localhost:8000'],
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
  credentials: true
}));
app.use(express.json());
// Global logging middleware
app.use((req, res, next) => {
  console.log(`[REQUEST] ${req.method} ${req.url}`);
  res.on('finish', () => {
    console.log(`[RESPONSE] ${req.method} ${req.url} ${res.statusCode}`);
  });
  next();
});
// Audit middleware is placed AFTER checkJwt (see below) so req.auth is populated
// Public access for login
app.use('/auth', authRouter);

// Public health route
app.get('/health', async (req, res) => {
  try {
    await sequelize.authenticate();
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ status: 'db error', error: err.message });
  }
});

// Legacy /llm route mapped to the same router if external services need it without /api
const llmRouter = require('./services/llm/llmRoutes');
app.use('/llm', llmRouter);

// Protect all API routes — checkJwt first, then audit, then routes
app.use('/api', (req, res, next) => {
  if (req.url.startsWith('/evidence')) {
    // Bypass auth for evidence proxy so <img src> and <a href> work
    return next();
  }
  console.log(`🔒 [AUTH-CHECK] ${req.method} ${req.url}`);
  checkJwt(req, res, next);
}, auditMiddleware, apiRoutes);

// Global Error Handler
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.message}`);
  res.status(err.status || 500).json({
    error: err.message || 'Internal Server Error',
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
