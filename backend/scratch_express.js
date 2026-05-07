const express = require('express');
const app = express();

const anomaliesRouter = express.Router();
anomaliesRouter.get('/', (req, res) => res.json({ matched: 'slash' }));
anomaliesRouter.get('/test', (req, res) => res.json({ matched: 'test' }));

const apiRoutes = express.Router();
apiRoutes.use('/anomalies', anomaliesRouter);

app.use('/api', (req, res, next) => {
    console.log(`[AUTH] ${req.url}`);
    next();
}, apiRoutes);

app.use((req, res) => {
    console.log(`[404] ${req.url}`);
    res.status(404).json({ error: 'not found' });
});

app.listen(3001, () => console.log('test server running'));
