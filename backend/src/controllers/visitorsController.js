const Visitors = require('../models/visitor');

// Get all visitors
exports.getVisitors = async (req, res) => {
    try {
        const visitorsList = await Visitors.findAll();
        res.status(200).json(visitorsList);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single visitor by ID
exports.getVisitorById = async (req, res) => {
    try {
        const { id } = req.params;
        const visitor = await Visitors.findByPk(id);
        if (!visitor) return res.status(404).json({ error: 'Visitor not found' });
        res.status(200).json(visitor);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new visitor
exports.createVisitor = async (req, res) => {
    try {
        const { name, visit_date, purpose, contact_info } = req.body;
        const newVisitor = await Visitors.create({
            name,
            visit_date,
            purpose,
            contact_info
        });
        res.status(201).json(newVisitor);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing visitor
exports.updateVisitor = async (req, res) => {
    try {
        const { id } = req.params;
        const { name, visit_date, purpose, contact_info } = req.body;

        const visitor = await Visitors.findByPk(id);
        if (!visitor) return res.status(404).json({ error: 'Visitor not found' });

        await visitor.update({
            name,
            visit_date,
            purpose,
            contact_info
        });
        res.status(200).json(visitor);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a visitor
exports.deleteVisitor = async (req, res) => {
    try {
        const { id } = req.params;
        const visitor = await Visitors.findByPk(id);
        if (!visitor) return res.status(404).json({ error: 'Visitor not found' });

        await visitor.destroy();
        res.status(200).json({ message: 'Visitor deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};