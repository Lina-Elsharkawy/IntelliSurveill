const express = require('express');
const router = express.Router();

const adminRouter = require('./adminRoutes');
const anomaliesRouter = require('./anomaliesRoutes');
const camerasRouter = require('./camerasRoutes');
const detectedPeopleRouter = require('./detectedPeopleRoutes');
const employeesRouter = require('./employeesRoutes');
const logsRouter = require('./logsRoutes');
const schedulesRouter = require('./schedulesRoutes');
const visitorsRouter = require('./visitorsRoutes');
const llmRouter = require('../services/llm/llmRoutes');
const notificationsRouter = require('./notificationsRoutes');
const anomalyRulesRouter = require('./anomalyRulesRoutes');
const chatbotRouter = require('./chatbotRoutes');
const evidenceRouter = require('./evidenceRoutes');
const backupRouter = require('./backupRoutes');
const auditLogRouter = require('./Auditlogroutes');

router.use('/audit-logs', auditLogRouter);
router.use('/admin', adminRouter);
router.use('/anomalies', anomaliesRouter);
router.use('/cameras', camerasRouter);
router.use('/detected-people', detectedPeopleRouter);
router.use('/employees', employeesRouter);
router.use('/logs', logsRouter);
router.use('/schedules', schedulesRouter);
router.use('/visitors', visitorsRouter);
router.use('/llm', llmRouter);
router.use('/notifications', notificationsRouter);
router.use('/anomaly-rules', anomalyRulesRouter);
router.use('/chatbot', chatbotRouter);
router.use('/evidence', evidenceRouter);
router.use('/backup', backupRouter);
// DIAGNOSTIC ROUTE
router.post('/diag-test', (req, res) => {
    console.log('🔴 DIAGNOSTIC POST SUCCESS');
    res.json({ message: 'Backend reached successfully', body: req.body });
});

module.exports = router;
