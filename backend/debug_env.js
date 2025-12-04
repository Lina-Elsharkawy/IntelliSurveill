const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, 'logging.env') });
require('dotenv').config({ path: path.resolve(__dirname, '.env') });

const {
  POSTGRES_USER,
  POSTGRES_PASSWORD,
  POSTGRES_DB,
  POSTGRES_HOST,
  POSTGRES_PORT,
} = process.env;

console.log('POSTGRES_USER:', POSTGRES_USER ? 'Set' : 'Undefined');
console.log('POSTGRES_PASSWORD:', POSTGRES_PASSWORD ? 'Set' : 'Undefined');
console.log('POSTGRES_DB:', POSTGRES_DB ? 'Set' : 'Undefined');
console.log('POSTGRES_HOST:', POSTGRES_HOST ? 'Set' : 'Undefined');
console.log('POSTGRES_PORT:', POSTGRES_PORT ? 'Set' : 'Undefined');

const connectionString = `postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD ? '****' : ''}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}`;
console.log('Connection String (masked):', connectionString);
