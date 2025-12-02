const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const DetectedPerson = require('./detected_person');
const Camera = require('./camera');
const Anomaly = require('./anomaly');

const Log = sequelize.define('Log', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  timestamp: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
  detected_id: { type: DataTypes.BIGINT, references: { model: 'detected_people', key: 'id' } },
  camera_id: { type: DataTypes.BIGINT, references: { model: 'cameras', key: 'id' } },
  anomaly_id: { type: DataTypes.BIGINT, references: { model: 'anomalies', key: 'id' } },
  authorized: DataTypes.BOOLEAN,
  confidence_score: DataTypes.FLOAT,
  event_type: DataTypes.TEXT,
  location: DataTypes.TEXT,
  device_status: DataTypes.TEXT,
  image_video_ref: DataTypes.TEXT,
  processing_time: DataTypes.FLOAT,
  model_version: DataTypes.TEXT
}, { tableName: 'logs', timestamps: false });

Log.belongsTo(DetectedPerson, { foreignKey: 'detected_id' });
Log.belongsTo(Camera, { foreignKey: 'camera_id' });
Log.belongsTo(Anomaly, { foreignKey: 'anomaly_id' });

module.exports = Log;
