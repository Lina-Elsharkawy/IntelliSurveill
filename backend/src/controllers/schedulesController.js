const Schedules = require('../models/schedule');

// Get all schedules
exports.getSchedules = async (req, res) => {
    try {
        const schedulesList = await Schedules.findAll();
        res.status(200).json(schedulesList);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get a single schedule by ID
exports.getScheduleById = async (req, res) => {
    try {
        const { id } = req.params;
        const schedule = await Schedules.findByPk(id);
        if (!schedule) return res.status(404).json({ error: 'Schedule not found' });
        res.status(200).json(schedule);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create a new schedule
exports.createSchedule = async (req, res) => {
    try {
        const { name, access_start_time, access_end_time, applies_to_weekdays, applies_to_weekends, specific_dates } = req.body;
        const newSchedule = await Schedules.create({
            name,
            access_start_time,
            access_end_time,
            applies_to_weekdays,
            applies_to_weekends,
            specific_dates
        });
        res.status(201).json(newSchedule);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Update an existing schedule
exports.updateSchedule = async (req, res) => {
    try {
        const { id } = req.params;
        const { name, access_start_time, access_end_time, applies_to_weekdays, applies_to_weekends, specific_dates } = req.body;
        
        const schedule = await Schedules.findByPk(id);
        if (!schedule) return res.status(404).json({ error: 'Schedule not found' });
        
        await schedule.update({
            name,
            access_start_time,
            access_end_time,
            applies_to_weekdays,
            applies_to_weekends,
            specific_dates
        });
        res.status(200).json(schedule);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Delete a schedule
exports.deleteSchedule = async (req, res) => {
    try {
        const { id } = req.params;
        const schedule = await Schedules.findByPk(id);
        if (!schedule) return res.status(404).json({ error: 'Schedule not found' });
        
        await schedule.destroy();
        res.status(200).json({ message: 'Schedule deleted successfully' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};