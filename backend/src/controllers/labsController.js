const Labs = require('../models/lab');

// Get all labs
exports.getLabs = async (req, res) => {
    try {
        const labs = await Labs.findAll();
        res.status(200).json(labs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single lab by ID (ADDED - useful for details page)
exports.getLabById = async (req, res) => {
    try {
        const { id } = req.params;
        const lab = await Labs.findByPk(id);
        if (!lab) return res.status(404).json({ error: 'Lab not found' });
        res.status(200).json(lab);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new lab
exports.createLab = async (req, res) => {
    try {
        const { name, location } = req.body;
        const newLab = await Labs.create({ name, location });
        res.status(201).json(newLab);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing lab
exports.updateLab = async (req, res) => {
    try {
        const { id } = req.params;
        const { name, location } = req.body;
        const lab = await Labs.findByPk(id);
        if (!lab) return res.status(404).json({ error: 'Lab not found' });
        await lab.update({ name, location });
        res.status(200).json(lab);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a lab
exports.deleteLab = async (req, res) => {
    try {
        const { id } = req.params;
        const lab = await Labs.findByPk(id);
        if (!lab) return res.status(404).json({ error: 'Lab not found' });
        await lab.destroy();
        res.status(200).json({ message: 'Lab deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};