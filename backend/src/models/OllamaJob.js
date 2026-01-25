const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const AnomalyCandidate = require('./AnomalyCandidate');

const OllamaJob = sequelize.define('OllamaJob', {
    id: {
        type: DataTypes.BIGINT,
        primaryKey: true,
        autoIncrement: true,
    },
    anomaly_candidate_id: {
        type: DataTypes.BIGINT,
        references: {
            model: 'anomaly_candidates',
            key: 'id',
        },
    },
    model_name: DataTypes.TEXT,
    prompt: DataTypes.TEXT,
    request_json: DataTypes.JSONB,
    status: DataTypes.TEXT,
    response_text: DataTypes.TEXT,
    response_json: DataTypes.JSONB,
    error: DataTypes.TEXT,
    created_at: DataTypes.DATE,
    started_at: DataTypes.DATE,
    finished_at: DataTypes.DATE,
}, {
    tableName: 'ollama_jobs',
    timestamps: false,
});

OllamaJob.belongsTo(AnomalyCandidate, {
    foreignKey: 'anomaly_candidate_id',
});

AnomalyCandidate.hasMany(OllamaJob, {
    foreignKey: 'anomaly_candidate_id',
});

module.exports = OllamaJob;
