const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const AnomalyCandidate = require('./AnomalyCandidate');

const AnomalyCandidateFeedback = sequelize.define('AnomalyCandidateFeedback', {
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
    label: DataTypes.TEXT,
    reviewer: DataTypes.TEXT,
    notes: DataTypes.TEXT,
    system_decision: DataTypes.JSONB,
    created_at: DataTypes.DATE,
    used_for_retrain: DataTypes.BOOLEAN,
}, {
    tableName: 'anomaly_candidate_feedback',
    timestamps: false,
});

AnomalyCandidateFeedback.belongsTo(AnomalyCandidate, {
    foreignKey: 'anomaly_candidate_id',
});

AnomalyCandidate.hasMany(AnomalyCandidateFeedback, {
    foreignKey: 'anomaly_candidate_id',
});

module.exports = AnomalyCandidateFeedback;
