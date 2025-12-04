const Camera = require('../models/camera');

// Get all cameras
exports.getCameras = async (req, res) => {
    try {
        const cameras = await Camera.findAll();
        res.status(200).json(cameras);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};
// Get a single camera by ID (ADDED - optional but useful)
exports.getCameraById = async (req, res) => {
    try {
        const { id } = req.params;
        const camera = await Camera.findByPk(id);
        if (!camera) return res.status(404).json({ error: 'Camera not found' });
        res.status(200).json(camera);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new camera
exports.createCamera = async (req, res) => {
    try {
        const { name, location, lab_id } = req.body;
        const newCamera = await Camera.create({ name, location, lab_id });
        res.status(201).json(newCamera);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing camera
exports.updateCamera = async (req, res) => {
    try {
        const { id } = req.params;
        const { name, location, lab_id } = req.body;

        const camera = await Camera.findByPk(id);
        if (!camera) return res.status(404).json({ error: 'Camera not found' });

        await camera.update({ name, location, lab_id });
        res.status(200).json(camera);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a camera
exports.deleteCamera = async (req, res) => {
    try {
        const { id } = req.params;
        const camera = await Camera.findByPk(id);
        if (!camera) return res.status(404).json({ error: 'Camera not found' });

        await camera.destroy();
        res.status(200).json({ message: 'Camera deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }

};
