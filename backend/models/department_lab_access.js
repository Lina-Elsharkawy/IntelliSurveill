const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const DepartmentLabAccess = sequelize.define('DepartmentLabAccess', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  department_id: DataTypes.BIGINT,
  lab_id: DataTypes.BIGINT,
  schedule_id: DataTypes.BIGINT
}, { tableName: 'department_lab_access', timestamps: false });

module.exports = DepartmentLabAccess;
