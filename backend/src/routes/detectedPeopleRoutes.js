const express = require('express');
const router = express.Router();
const detectedPeopleController = require('../controllers/detectedPeopleController');

// Get all detected people
router.get('/get_people', detectedPeopleController.getDetectedPeople);

// Get a single detected person by ID
router.get('/get_person/:id', detectedPeopleController.getDetectedPersonById);

module.exports = router;
