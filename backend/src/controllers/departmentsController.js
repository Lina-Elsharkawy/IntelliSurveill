const Department = require('../models/department');

// Get all departments
exports.getDepartments = async (req, res) => {
    try {
        const departments = await Department.findAll();
        res.status(200).json(departments);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single department by ID (ADDED - optional but useful)
exports.getDepartmentById = async (req, res) => {
    try {
        const { id } = req.params;
        const department = await Department.findByPk(id);
        if (!department) return res.status(404).json({ error: 'Department not found' });
        res.status(200).json(department);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new department
exports.createDepartment = async (req, res) => {
    try {
        const { name } = req.body;
        const newDepartment = await Department.create({ name });
        res.status(201).json(newDepartment);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing department
exports.updateDepartment = async (req, res) => {
    try {
        const { id } = req.params;
        const { name } = req.body;
        const department = await Department.findByPk(id);
        if (!department) return res.status(404).json({ error: 'Department not found' });
        await department.update({ name });
        res.status(200).json(department);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a department
exports.deleteDepartment = async (req, res) => {
    try {
        const { id } = req.params;
        const department = await Department.findByPk(id);
        if (!department) return res.status(404).json({ error: 'Department not found' });
        await department.destroy();
        res.status(200).json({ message: 'Department deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};