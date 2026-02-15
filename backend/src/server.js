const express = require('express');
const sequelize = require('./db/connection');
const models = require('./models'); // import model index

const app = express();
const cors = require('cors');
app.use(cors());

// Global logging middleware
app.use((req, res, next) => {
  console.log(`[REQUEST] ${req.method} ${req.url}`);
  res.on('finish', () => {
    console.log(`[RESPONSE] ${req.method} ${req.url} ${res.statusCode}`);
  });
  next();
});

const anomaliesRouter = require('./routes/anomaliesRoutes');
const camerasRouter = require('./routes/camerasRoutes');
const departmentsRouter = require('./routes/departmentsRoutes');
const detectedPeopleRouter = require('./routes/detectedPeopleRoutes');
const employeesRouter = require('./routes/employeesRoutes');
const labsRouter = require('./routes/labsRoutes');
const logsRouter = require('./routes/logsRoutes');
const schedulesRouter = require('./routes/schedulesRoutes');
const visitorsRouter = require('./routes/visitorsRoutes');
const llmRouter = require('./services/llm/llmRoutes');
const anomalyCandidatesRouter = require('./routes/anomalyCandidate.routes');
const anomalyFeedbackRouter = require('./routes/anomalyCandidateFeedback.routes');
const ollamaJobsRouter = require('./routes/ollamaJob.routes');
const notificationsRouter = require('./routes/notificationsRoutes');


const checkJwt = require('./middleware/auth');
const authRouter = require('./routes/authRoutes');
const adminRouter = require('./routes/adminRoutes');

app.use(express.json());
app.use('/auth', authRouter); // Public access for login

// Public route
app.get('/health', async (req, res) => {
  try {
    await sequelize.authenticate();
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ status: 'db error', error: err.message });
  }
});

// Protect all API routes below
app.use('/api', (req, res, next) => {
  console.log(`🔒 [AUTH-CHECK] ${req.method} ${req.url}`);
  next();
}, checkJwt);

// ADMIN ROUTES - Moved up for priority
app.use('/api/admin', adminRouter);

app.use('/api/anomalies', anomaliesRouter);
app.use('/api/cameras', camerasRouter);
app.use('/api/departments', departmentsRouter);
app.use('/api/detected-people', detectedPeopleRouter);
app.use('/api/employees', employeesRouter);
app.use('/api/labs', labsRouter);
app.use('/api/logs', logsRouter);
app.use('/api/schedules', schedulesRouter);
app.use('/api/visitors', visitorsRouter);
app.use('/api/llm', llmRouter);
app.use('/llm', llmRouter);
app.use('/api/anomaly-candidates', anomalyCandidatesRouter);
app.use('/api/anomaly-feedback', anomalyFeedbackRouter);
app.use('/api/ollama-jobs', ollamaJobsRouter);
// app.use('/api/admin', adminRouter); // Moved up
app.use('/api/notifications', notificationsRouter);

// DIAGNOSTIC ROUTE
app.post('/api/diag-test', (req, res) => {
  console.log('🔴 DIAGNOSTIC POST SUCCESS');
  res.json({ message: 'Backend reached successfully', body: req.body });
});


const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
