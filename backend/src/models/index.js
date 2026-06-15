const sequelize = require('../db/connection');

const Camera = require('./camera');
const Employee = require('./employee');
const Log = require('./log');
const Schedule = require('./schedule');
const DetectedPerson = require('./detected_person');
const Visitor = require('./visitor');
const Notification = require('./notification');
const AuditLog = require('./AuditLog');

module.exports = {
  sequelize,
  AuditLog,
  Camera,
  Employee,
  Log,
  Schedule,
  DetectedPerson,
  Visitor,
  Notification,
};
