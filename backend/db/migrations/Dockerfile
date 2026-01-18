FROM pgvector/pgvector:pg16

WORKDIR /app
COPY ./create_logging_system_schema.sql .
COPY run-migrations.sh /app/run-migrations.sh
RUN chmod +x /app/run-migrations.sh

CMD ["./run-migrations.sh"]
