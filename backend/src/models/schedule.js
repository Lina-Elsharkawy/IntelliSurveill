const { DataTypes } = require('sequelize');
const sequelize = require('../db/connection');

const Schedule = sequelize.define('Schedule', {
  id: { type: DataTypes.BIGINT, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.TEXT, allowNull: false },
  access_start_time: DataTypes.TIME,
  access_end_time: DataTypes.TIME,
  applies_to_weekdays: { type: DataTypes.BOOLEAN, defaultValue: false },
  applies_to_weekends: { type: DataTypes.BOOLEAN, defaultValue: false },
  specific_dates: DataTypes.ARRAY(DataTypes.DATE)
}, { tableName: 'schedules', timestamps: false });

module.exports = Schedule;
