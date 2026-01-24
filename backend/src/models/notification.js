const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Notification = sequelize.define('Notification', {
    id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
    title: { type: DataTypes.TEXT, allowNull: false },
    message: { type: DataTypes.TEXT },
    type: { type: DataTypes.TEXT }, // e.g., 'motion', 'camera_offline', 'low_battery', 'anomaly'
    source: { type: DataTypes.TEXT }, // e.g., 'camera', 'system', 'anomaly' (for future data sources)
    source_id: { type: DataTypes.BIGINT }, // reference to source entity (nullable)
    severity: { type: DataTypes.TEXT, defaultValue: 'low' }, // 'high', 'medium', 'low'
    is_read: { type: DataTypes.BOOLEAN, defaultValue: false },
    created_at: { type: DataTypes.DATE, defaultValue: DataTypes.NOW }
}, { tableName: 'notifications', timestamps: false });

module.exports = Notification;
