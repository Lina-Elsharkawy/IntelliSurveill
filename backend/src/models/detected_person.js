const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const Employee = require('./employee');
const Visitor = require('./visitor');

const DetectedPerson = sequelize.define('DetectedPerson', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: DataTypes.TEXT,
  additional_info: DataTypes.TEXT,
  employee_id: { type: DataTypes.BIGINT, references: { model: 'employees', key: 'id' } },
  visitor: { type: DataTypes.BOOLEAN, defaultValue: false },
  visitor_id: { type: DataTypes.BIGINT, references: { model: 'visitors', key: 'id' } }
}, { tableName: 'detected_people', timestamps: false });

DetectedPerson.belongsTo(Employee, { foreignKey: 'employee_id' });
DetectedPerson.belongsTo(Visitor, { foreignKey: 'visitor_id' });

module.exports = DetectedPerson;
