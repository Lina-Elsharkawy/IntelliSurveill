const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Department = sequelize.define('Department', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.TEXT, allowNull: false }
}, { tableName: 'departments', timestamps: false });

module.exports = Department;
