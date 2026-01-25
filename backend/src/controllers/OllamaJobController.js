const OllamaJob = require('../models/OllamaJob');

// Get all jobs
exports.getAllJobs = async (req, res) => {
    try {
        const jobs = await OllamaJob.findAll({
            order: [['id', 'ASC']],
        });
        res.json(jobs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Get jobs by anomaly candidate ID
exports.getJobsByCandidate = async (req, res) => {
    try {
        const jobs = await OllamaJob.findAll({
            where: { anomaly_candidate_id: req.params.candidateId },
        });
        res.json(jobs);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
};

// Create ollama job
exports.createJob = async (req, res) => {
    try {
        const job = await OllamaJob.create(req.body);
        res.status(201).json(job);
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};

// Update job status / response
exports.updateJob = async (req, res) => {
    try {
        const [updated] = await OllamaJob.update(req.body, {
            where: { id: req.params.id },
        });

        if (!updated) {
            return res.status(404).json({ message: 'Job not found' });
        }

        res.json({ message: 'Job updated successfully' });
    } catch (err) {
        res.status(400).json({ error: err.message });
    }
};
