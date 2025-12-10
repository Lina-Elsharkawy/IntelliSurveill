const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../logging.env') });

const {
    POSTGRES_USER,
    POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST = 'localhost',
    POSTGRES_PORT = 5432,
} = process.env;

console.log('POSTGRES_USER:', POSTGRES_USER || 'Undefined');
console.log('POSTGRES_PASSWORD:', POSTGRES_PASSWORD ? 'Set' : 'Undefined');
console.log('POSTGRES_DB:', POSTGRES_DB || 'Undefined');
console.log('POSTGRES_HOST:', POSTGRES_HOST || 'Undefined');
console.log('POSTGRES_PORT:', POSTGRES_PORT || 'Undefined');

const connectionString = `postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD ? '****' : ''}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}`;
console.log('Connection String (masked):', connectionString);