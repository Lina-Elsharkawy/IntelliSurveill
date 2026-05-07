const express = require('express');
const router = express.Router();

const adminRouter = require('./adminRoutes');
const anomaliesRouter = require('./anomaliesRoutes');
const camerasRouter = require('./camerasRoutes');
const departmentsRouter = require('./departmentsRoutes');
const detectedPeopleRouter = require('./detectedPeopleRoutes');
const employeesRouter = require('./employeesRoutes');
const labsRouter = require('./labsRoutes');
const logsRouter = require('./logsRoutes');
const schedulesRouter = require('./schedulesRoutes');
const visitorsRouter = require('./visitorsRoutes');
const llmRouter = require('../services/llm/llmRoutes');
const anomalyCandidatesRouter = require('./anomalyCandidateRoutes');
const anomalyFeedbackRouter = require('./anomalyCandidateFeedbackRoutes');
const ollamaJobsRouter = require('./ollamaJobRoutes');
const notificationsRouter = require('./notificationsRoutes');
const anomalyRulesRouter = require('./anomalyRulesRoutes');
const chatbotRouter = require('./chatbotRoutes');
const evidenceRouter = require('./evidenceRoutes');

router.use('/admin', adminRouter);
router.use('/anomalies', anomaliesRouter);
router.use('/cameras', camerasRouter);
router.use('/departments', departmentsRouter);
router.use('/detected-people', detectedPeopleRouter);
router.use('/employees', employeesRouter);
router.use('/labs', labsRouter);
router.use('/logs', logsRouter);
router.use('/schedules', schedulesRouter);
router.use('/visitors', visitorsRouter);
router.use('/llm', llmRouter);
router.use('/anomaly-candidates', anomalyCandidatesRouter);
router.use('/anomaly-feedback', anomalyFeedbackRouter);
router.use('/ollama-jobs', ollamaJobsRouter);
router.use('/notifications', notificationsRouter);
router.use('/anomaly-rules', anomalyRulesRouter);
router.use('/chatbot', chatbotRouter);
router.use('/evidence', evidenceRouter);

// DIAGNOSTIC ROUTE
router.post('/diag-test', (req, res) => {
    console.log('🔴 DIAGNOSTIC POST SUCCESS');
    res.json({ message: 'Backend reached successfully', body: req.body });
});

module.exports = router;
