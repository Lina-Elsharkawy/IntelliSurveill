const express = require('express');
const router = express.Router();
const visitorsController = require('../controllers/visitorsController');
// Route to get all visitors
router.get('/get_all_visitors', visitorsController.getVisitors);
// Route to get a single visitor by ID
router.get('/get_visitor/:id', visitorsController.getVisitorById);
// Route to create a new visitor
router.post('/create_visitor', visitorsController.createVisitor);
// Route to update an existing visitor
router.put('/update_visitor/:id', visitorsController.updateVisitor);
// Route to delete a visitor
router.delete('/delete_visitor/:id', visitorsController.deleteVisitor);
module.exports = router;
