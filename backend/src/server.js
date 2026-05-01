const express = require('express');
const cors = require('cors');
const sequelize = require('./db/connection');
const models = require('./models'); // import model index

const checkJwt = require('./middleware/auth');
const authRouter = require('./routes/authRoutes');
const apiRoutes = require('./routes/index');

const app = express();

app.use(cors());
app.use(express.json());

// Global logging middleware
app.use((req, res, next) => {
  console.log(`[REQUEST] ${req.method} ${req.url}`);
  res.on('finish', () => {
    console.log(`[RESPONSE] ${req.method} ${req.url} ${res.statusCode}`);
  });
  next();
});

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

// Protect all API routes below
app.use('/api', (req, res, next) => {
  console.log(`🔒 [AUTH-CHECK] ${req.method} ${req.url}`);
  next();
}, checkJwt, apiRoutes);

// Global Error Handler
app.use((err, req, res, next) => {
  console.error(`[ERROR] ${err.message}`);
  res.status(err.status || 500).json({
    error: err.message || 'Internal Server Error',
  });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
