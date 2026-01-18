const { Sequelize } = require('sequelize');
const path = require('path');

require('dotenv').config({ path: path.resolve(__dirname, '../../.env') }); // only backend .env

const {
  POSTGRES_USER,
  POSTGRES_PASSWORD,
  POSTGRES_DB,
  POSTGRES_HOST = 'localhost',
  POSTGRES_PORT = 5432,
} = process.env;
console.log("DB ENV VARS:", {
  POSTGRES_USER,
  POSTGRES_PASSWORD,
  POSTGRES_DB,
  POSTGRES_HOST,
  POSTGRES_PORT,
});

if (!POSTGRES_USER || !POSTGRES_PASSWORD || !POSTGRES_DB) {
  console.error('Missing required environment variables for database connection.');
  process.exit(1);
}

const sequelize = new Sequelize(
  `postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}`,
  { dialect: 'postgres', logging: false }
);

module.exports = sequelize;
