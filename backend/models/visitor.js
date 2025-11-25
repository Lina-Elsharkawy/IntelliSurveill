const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Visitor = sequelize.define('Visitor', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.TEXT, allowNull: false },
  visit_date: DataTypes.DATE,
  purpose: DataTypes.TEXT,
  contact_info: DataTypes.TEXT
}, { tableName: 'visitors', timestamps: false });

module.exports = Visitor;
