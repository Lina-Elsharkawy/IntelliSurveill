const express = require('express');
const router = express.Router();
const departmentsController = require('../controllers/departmentsController');
// Route to get all departments
router.get('/get_all_departments', departmentsController.getDepartments);
// Route to get a single department by ID
router.get('/get_department/:id', departmentsController.getDepartmentById);
// Route to create a new department
router.post('/create_department', departmentsController.createDepartment);
// Route to update an existing department
router.put('/update_department/:id', departmentsController.updateDepartment);
// Route to delete a department
router.delete('/delete_department/:id', departmentsController.deleteDepartment);
module.exports = router;
