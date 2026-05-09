const Department = require('../models/department');
const asyncHandler = require('../middleware/asyncHandler');

// Get all departments
exports.getDepartments = asyncHandler(async (req, res) => {
    const departments = await Department.findAll();
    res.status(200).json(departments);
});

// Get a single department by ID (ADDED - optional but useful)
exports.getDepartmentById = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const department = await Department.findByPk(id);
    if (!department) return res.status(404).json({ error: 'Department not found' });
    res.status(200).json(department);
});

// Create a new department
exports.createDepartment = asyncHandler(async (req, res) => {
    const { name } = req.body;
    const newDepartment = await Department.create({ name });
    res.status(201).json(newDepartment);
});

// Update an existing department
exports.updateDepartment = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const { name } = req.body;
    const department = await Department.findByPk(id);
    if (!department) return res.status(404).json({ error: 'Department not found' });
    await department.update({ name });
    res.status(200).json(department);
});

// Delete a department
exports.deleteDepartment = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const department = await Department.findByPk(id);
    if (!department) return res.status(404).json({ error: 'Department not found' });
    await department.destroy();
    res.status(200).json({ message: 'Department deleted successfully' });
});