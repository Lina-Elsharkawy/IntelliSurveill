const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Lab = sequelize.define('Lab', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.TEXT, allowNull: false }
}, { tableName: 'labs', timestamps: false });

module.exports = Lab;
