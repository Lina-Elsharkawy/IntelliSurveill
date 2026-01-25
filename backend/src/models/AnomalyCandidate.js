const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const AnomalyCandidate = sequelize.define('AnomalyCandidate', {
    id: {
        type: DataTypes.BIGINT,
        primaryKey: true,
        autoIncrement: true,
    },
    scene_window_embedding_id: {
        type: DataTypes.BIGINT,
        allowNull: false,
    },
    reason: DataTypes.TEXT,
    status: DataTypes.TEXT,
    image_ref: DataTypes.TEXT,
    video_ref: DataTypes.TEXT,
    created_at: {
        type: DataTypes.DATE,
    },
    updated_at: {
        type: DataTypes.DATE,
    },
}, {
    tableName: 'anomaly_candidates',
    timestamps: false,
});

module.exports = AnomalyCandidate;
