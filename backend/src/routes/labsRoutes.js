const express = require('express');
const router = express.Router();
const labsController = require('../controllers/labsController');

// Route to get all labs
router.get('/get_all_labs', labsController.getLabs);
// Route to get a single lab by ID
router.get('/get_lab/:id', labsController.getLabById);
// Route to create a new lab
router.post('/create_lab', labsController.createLab);
// Route to update an existing lab
router.put('/update_lab/:id', labsController.updateLab);
// Route to delete a lab
router.delete('/delete_lab/:id', labsController.deleteLab);
module.exports = router;
