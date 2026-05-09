const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const AuditLog = sequelize.define('AuditLog', {
    id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
    user_email: { type: DataTypes.TEXT, allowNull: false },
    action: { type: DataTypes.TEXT, allowNull: false }, // CREATE | UPDATE | DELETE | LOGIN | LOGOUT
    resource: { type: DataTypes.TEXT },                   // camera | employee | anomaly_candidate | rule …
    resource_id: { type: DataTypes.TEXT },                   // stringified entity PK
    details: { type: DataTypes.JSONB },                  // freeform context object
    created_at: { type: DataTypes.DATE, defaultValue: DataTypes.NOW },
}, { tableName: 'audit_logs', timestamps: false });

module.exports = AuditLog;


