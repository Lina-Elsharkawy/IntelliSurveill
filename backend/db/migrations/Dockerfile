FROM postgres:18

# Set the working directory
WORKDIR /app

# Copy the migration script and the SQL schema file
COPY ./create_logging_system_schema.sql .
COPY ./run-migrations.sh .

# Make the script executable
RUN chmod +x ./run-migrations.sh

# Set the command to run the script
CMD ["./run-migrations.sh"]
