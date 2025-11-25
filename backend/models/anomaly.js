const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Anomaly = sequelize.define('Anomaly', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  description: DataTypes.TEXT,
  severity_level: DataTypes.TEXT
}, { tableName: 'anomalies', timestamps: false });

module.exports = Anomaly;
