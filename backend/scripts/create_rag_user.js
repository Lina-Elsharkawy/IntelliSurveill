const sequelize = require('../src/db/connection');

async function createRagUser() {
    try {
        await sequelize.authenticate();
        console.log('Connected as admin.');

        const dbName = process.env.POSTGRES_DB;
        const ragUser = 'rag_readonly';
        const ragPass = 'rag_secure_pass_123'; // In production, use a strong generated password

        console.log(`Creating user ${ragUser} for database ${dbName}...`);

        // 1. Create Role (Using raw query because Sequelize doesn't have user management methods)
        try {
            await sequelize.query(`CREATE ROLE ${ragUser} WITH LOGIN PASSWORD '${ragPass}';`);
            console.log('Role created.');
        } catch (e) {
            // Postgres error code 42710 means object already exists
            if (e.original && e.original.code === '42710') {
                console.log('Role already exists, skipping creation.');
            } else {
                throw e;
            }
        }

        // 2. Grant Connect
        await sequelize.query(`GRANT CONNECT ON DATABASE ${dbName} TO ${ragUser};`);
        console.log('Granted CONNECT.');

        // 3. Grant Usage on Public Schema
        await sequelize.query(`GRANT USAGE ON SCHEMA public TO ${ragUser};`);
        console.log('Granted USAGE on public schema.');

        // 4. Grant Select on All Tables
        await sequelize.query(`GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${ragUser};`);
        console.log('Granted SELECT on all tables.');

        // 5. Alter Default Privileges (for future tables)
        await sequelize.query(`ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ${ragUser};`);
        console.log('Altered default privileges.');

        console.log('Read-Only user configured successfully.');
        process.exit(0);

    } catch (err) {
        console.error('Failed to create user:', err);
        process.exit(1);
    }
}

createRagUser();
