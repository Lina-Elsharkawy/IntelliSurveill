const Labs = require('../models/lab');
const asyncHandler = require('../middleware/asyncHandler');

// Get all labs
exports.getLabs = asyncHandler(async (req, res) => {
    const labs = await Labs.findAll();
    res.status(200).json(labs);
});

// Get a single lab by ID (ADDED - useful for details page)
exports.getLabById = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const lab = await Labs.findByPk(id);
    if (!lab) return res.status(404).json({ error: 'Lab not found' });
    res.status(200).json(lab);
});

// Create a new lab
exports.createLab = asyncHandler(async (req, res) => {
    const { name, location } = req.body;
    const newLab = await Labs.create({ name, location });
    res.status(201).json(newLab);
});

// Update an existing lab
exports.updateLab = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const { name, location } = req.body;
    const lab = await Labs.findByPk(id);
    if (!lab) return res.status(404).json({ error: 'Lab not found' });
    await lab.update({ name, location });
    res.status(200).json(lab);
});

// Delete a lab
exports.deleteLab = asyncHandler(async (req, res) => {
    const { id } = req.params;
    const lab = await Labs.findByPk(id);
    if (!lab) return res.status(404).json({ error: 'Lab not found' });
    await lab.destroy();
    res.status(200).json({ message: 'Lab deleted successfully' });
});