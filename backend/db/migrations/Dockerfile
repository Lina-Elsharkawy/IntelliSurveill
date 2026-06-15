FROM pgvector/pgvector:pg16

WORKDIR /app

COPY ./create_logging_system_schema.sql /app/create_logging_system_schema.sql
COPY ./db_cleanup.sql /app/db_cleanup.sql
COPY ./run-migrations.sh /app/run-migrations.sh

RUN chmod +x /app/run-migrations.sh

CMD ["./run-migrations.sh"]