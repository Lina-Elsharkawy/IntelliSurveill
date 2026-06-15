const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');
const Employee = sequelize.define('Employee', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.TEXT, allowNull: false },
  department_id: { type: DataTypes.BIGINT, references: { model: 'departments', key: 'id' } }
}, { tableName: 'employees', timestamps: false });

module.exports = Employee;
