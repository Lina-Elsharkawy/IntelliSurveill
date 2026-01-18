CREATE DATABASE airflow;
CREATE DATABASE logging_db;

\c logging_db
GRANT ALL ON SCHEMA public TO public;
