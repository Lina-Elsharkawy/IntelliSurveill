#!/bin/bash

set -e

export PGPASSWORD="$POSTGRES_PASSWORD"

until pg_isready -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
  >&2 echo "Postgres is unavailable - sleeping"
  sleep 2
done

>&2 echo "Postgres is up - running migrations."

>&2 echo "Running main schema..."
psql -v ON_ERROR_STOP=1 -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./create_logging_system_schema.sql
>&2 echo "Main schema executed."

if [ -f ./db_cleanup.sql ]; then
  >&2 echo "Running DB cleanup..."
  psql -v ON_ERROR_STOP=1 -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./db_cleanup.sql
  >&2 echo "DB cleanup executed."
else
  >&2 echo "ERROR: db_cleanup.sql not found inside db-migrator container."
  exit 1
fi

if [ -f ./seed.sql ]; then
  >&2 echo "Running seed script..."
  psql -v ON_ERROR_STOP=1 -h postgres-db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f ./seed.sql
  >&2 echo "Seed script executed."
else
  >&2 echo "No seed script found."
fi