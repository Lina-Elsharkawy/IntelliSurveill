const express = require('express');
const router = express.Router();
const checkJwt = require('../middleware/auth');
const chatbotController = require('../controllers/chatbotController');

router.use(checkJwt);

router.post('/query', chatbotController.query);
router.get('/health', chatbotController.health);
router.get('/schema', chatbotController.schema);

module.exports = router;