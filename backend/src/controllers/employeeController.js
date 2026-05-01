const Employee = require('../models/employee');

// Get all employees
exports.getEmployees = async (req, res) => {
    try {
        const employees = await Employee.findAll();
        res.status(200).json(employees);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single employee by ID (ADDED - optional but useful)
exports.getEmployeeById = async (req, res) => {
    try {
        const { id } = req.params;
        const employee = await Employee.findByPk(id);
        if (!employee) return res.status(404).json({ error: 'Employee not found' });
        res.status(200).json(employee);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new employee
exports.createEmployee = async (req, res) => {
    try {
        const { name, department_id } = req.body;
        const newEmployee = await Employee.create({ name, department_id });
        res.status(201).json(newEmployee);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing employee
exports.updateEmployee = async (req, res) => {
    try {
        const { id } = req.params;
        const { name, department_id } = req.body;

        const employee = await Employee.findByPk(id);
        if (!employee) return res.status(404).json({ error: 'Employee not found' });

        await employee.update({ name, department_id });
        res.status(200).json(employee);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete an employee
exports.deleteEmployee = async (req, res) => {
    try {
        const { id } = req.params;

        const employee = await Employee.findByPk(id);
        if (!employee) return res.status(404).json({ error: 'Employee not found' });

        await employee.destroy();
        res.status(200).json({ message: 'Employee deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};