const express = require('express');
const sequelize = require('./db/connection');
const models = require('./models'); // import model index
const app = express();

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

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server listening on port ${PORT}`));
