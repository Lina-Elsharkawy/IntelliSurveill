#!/bin/bash

export PGPASSWORD="$POSTGRES_PASSWORD"

# Wait for the database to be ready
until pg_isready -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 2
done

>&2 echo "Postgres is up - checking for 'logs' table."

# Check if the 'logs' table exists and run migration if it doesn't
TABLE_EXISTS=$(psql -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -c "SELECT to_regclass('public.logs');" | tr -d '[:space:]')

if [ "$TABLE_EXISTS" == "logs" ]; then
  >&2 echo "Table 'logs' already exists. No action needed."
else
  >&2 echo "Table 'logs' not found. Running migration..."
  psql -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./create_logging_system_schema.sql
  >&2 echo "Migration script executed."
fi
