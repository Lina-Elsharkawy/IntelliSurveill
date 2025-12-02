const { Sequelize } = require('sequelize');
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

const {
  POSTGRES_USER = 'lina',
  POSTGRES_PASSWORD = '123',
  POSTGRES_DB = 'linadb',
  POSTGRES_HOST = 'localhost',
  POSTGRES_PORT = 5432,
} = process.env;

const sequelize = new Sequelize(
  `postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}`,
  { dialect: 'postgres', logging: false }
);

module.exports = sequelize;
