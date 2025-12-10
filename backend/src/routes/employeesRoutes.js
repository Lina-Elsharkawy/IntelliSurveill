const express = require('express');
const router = express.Router();
const employeesController = require('../controllers/EmployeeControllers');
// Route to get all employees
router.get('/get_all_employees', employeesController.getEmployees);
// Route to get a single employee by ID
router.get('/get_employee/:id', employeesController.getEmployeeById);
// Route to create a new employee
router.post('/create_employee', employeesController.createEmployee);
// Route to update an existing employee
router.put('/update_employee/:id', employeesController.updateEmployee);
// Route to delete an employee
router.delete('/delete_employee/:id', employeesController.deleteEmployee);
module.exports = router;
