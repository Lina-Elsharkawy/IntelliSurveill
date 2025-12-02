#!/bin/bash

export PGPASSWORD="$POSTGRES_PASSWORD"

# Wait for the database to be ready
until pg_isready -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 2
done

>&2 echo "Postgres is up - running migrations."
psql -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./create_logging_system_schema.sql
>&2 echo "Migration script executed."

if [ -f ./seed.sql ]; then
  >&2 echo "Running seed script..."
  psql -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./seed.sql
  >&2 echo "Seed script executed."
else
  >&2 echo "No seed script found."
fi
