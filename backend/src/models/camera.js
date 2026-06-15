const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const Camera = sequelize.define('Camera', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: DataTypes.TEXT,
  location: DataTypes.TEXT,
  lab_id: { type: DataTypes.BIGINT, references: { model: 'labs', key: 'id' } },
  stream_url: DataTypes.TEXT
}, { tableName: 'cameras', timestamps: false });

module.exports = Camera;