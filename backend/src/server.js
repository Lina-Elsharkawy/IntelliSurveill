const express = require('express');
const sequelize = require('./db/connection');
const models = require('./models'); // import model index

const app = express();
const anomaliesRouter = require('./routes/anomaliesRoutes');
const camerasRouter = require('./routes/camerasRoutes');
const departmentsRouter = require('./routes/departmentsRoutes');
const detectedPeopleRouter = require('./routes/detectedPeopleRoutes');
const employeesRouter = require('./routes/employeesRoutes');
const labsRouter = require('./routes/labsRoutes');
const logsRouter = require('./routes/logsRoutes');
const schedulesRouter = require('./routes/schedulesRoutes');
const visitorsRouter = require('./routes/visitorsRoutes');


app.use(express.json());

app.get('/health', async (req, res) => {
  try {
    await sequelize.authenticate();
    res.json({ status: 'ok' });
  } catch (err) {
    res.status(500).json({ status: 'db error', error: err.message });
  }
});

// Example: GET all cameras
app.get('/cameras', async (req, res) => {
  const cameras = await models.Camera.findAll();
  res.json(cameras);
});

app.use('/api/anomalies', anomaliesRouter);
app.use('/api/cameras', camerasRouter);
app.use('/api/departments', departmentsRouter);
app.use('/api/detected-people', detectedPeopleRouter);
app.use('/api/employees', employeesRouter);
app.use('/api/labs', labsRouter);
app.use('/api/logs', logsRouter);
app.use('/api/schedules', schedulesRouter);
app.use('/api/visitors', visitorsRouter);
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
