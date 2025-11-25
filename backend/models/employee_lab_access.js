const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const EmployeeLabAccess = sequelize.define('EmployeeLabAccess', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  employee_id: DataTypes.BIGINT,
  lab_id: DataTypes.BIGINT,
  schedule_id: DataTypes.BIGINT
}, { tableName: 'employee_lab_access', timestamps: false });

module.exports = EmployeeLabAccess;
