const sequelize = require('../db/connection');

const Department = require('./department');
const Camera = require('./camera');
const Employee = require('./employee');
const Anomaly = require('./anomaly');
const Log = require('./log');
const Schedule = require('./schedule');
const DetectedPerson = require('./detected_person');
const Lab = require('./lab');
const DepartmentLabAccess = require('./department_lab_access');
const EmployeeLabAccess = require('./employee_lab_access');
const Visitor = require('./visitor');

module.exports = {
  sequelize,
  Department,
  Camera,
  Employee,
    Anomaly,
    Log,
    Schedule,
    DetectedPerson,
    Lab,
    DepartmentLabAccess,
    EmployeeLabAccess,
    Visitor,
};
