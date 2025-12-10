const express = require('express');
const router = express.Router();
const schedulesController = require('../controllers/schedulesController');
// Route to get all schedules
router.get('/get_all_schedules', schedulesController.getSchedules);
// Route to get a single schedule by ID
router.get('/get_schedule/:id', schedulesController.getScheduleById);
// Route to create a new schedule
router.post('/create_schedule', schedulesController.createSchedule);
// Route to update an existing schedule
router.put('/update_schedule/:id', schedulesController.updateSchedule);
// Route to delete a schedule
router.delete('/delete_schedule/:id', schedulesController.deleteSchedule);
module.exports = router;
