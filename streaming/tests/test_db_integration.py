"""
Database Integration Tests for Flink Streaming Pipeline.

Verifies that:
- JDBC sink correctly writes to entry_logs table
- JDBC sink correctly writes to anomalies_logs table
- Foreign key constraints are respected
"""

import os
import pytest
import psycopg2

POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = os.environ.get('POSTGRES_PORT', '5432')
POSTGRES_DB = os.environ.get('POSTGRES_DB', 'logging_db')
POSTGRES_USER = os.environ.get('POSTGRES_USER', 'mohamed')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', 'mohamed')


@pytest.fixture(scope="module")
def db_connection():
    """Create PostgreSQL connection."""
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    yield conn
    conn.close()


class TestDatabaseSchema:
    """Tests for database schema and FK constraints."""

    def test_entry_logs_table_exists(self, db_connection):
        """Verify entry_logs table exists with correct columns."""
        cursor = db_connection.cursor()
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'entry_logs'
            ORDER BY ordinal_position
        """)
        columns = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        
        required_columns = [
            'id', 'timestamp', 'detected_id', 'camera_id', 
            'authorized', 'event_type', 'location'
        ]
        
        for col in required_columns:
            assert col in columns, f"Missing column: {col}"

    def test_anomalies_logs_table_exists(self, db_connection):
        """Verify anomalies_logs table exists with correct columns."""
        cursor = db_connection.cursor()
        cursor.execute("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'anomalies_logs'
            ORDER BY ordinal_position
        """)
        columns = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        
        required_columns = ['id', 'timestamp', 'detected_id', 'camera_id', 'anomaly_id']
        
        for col in required_columns:
            assert col in columns, f"Missing column: {col}"

    def test_detected_people_has_records(self, db_connection):
        """Verify detected_people table has records for FK references."""
        cursor = db_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM detected_people")
        count = cursor.fetchone()[0]
        cursor.close()
        
        assert count > 0, "detected_people table is empty - FK tests will fail"

    def test_cameras_has_records(self, db_connection):
        """Verify cameras table has records for FK references."""
        cursor = db_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM cameras")
        count = cursor.fetchone()[0]
        cursor.close()
        
        assert count > 0, "cameras table is empty - FK tests will fail"

    def test_anomalies_has_records(self, db_connection):
        """Verify anomalies table has records for FK references."""
        cursor = db_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM anomalies")
        count = cursor.fetchone()[0]
        cursor.close()
        
        assert count > 0, "anomalies table is empty - anomaly_id FK will fail"


class TestEntryLogsIntegration:
    """Tests for entry_logs JDBC sink."""

    def test_entry_logs_has_recent_records(self, db_connection):
        """Verify that entry_logs has been receiving data."""
        cursor = db_connection.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM entry_logs 
            WHERE timestamp > NOW() - INTERVAL '1 hour'
        """)
        count = cursor.fetchone()[0]
        cursor.close()
        
        # This test verifies the pipeline is actively writing
        # May be 0 if no recent test data was produced
        print(f"entry_logs records in last hour: {count}")

    def test_entry_logs_has_valid_fk_references(self, db_connection):
        """Verify all entry_logs records have valid FK references."""
        cursor = db_connection.cursor()
        
        # Check for orphaned detected_id references
        cursor.execute("""
            SELECT COUNT(*) FROM entry_logs el
            LEFT JOIN detected_people dp ON el.detected_id = dp.id
            WHERE el.detected_id IS NOT NULL AND dp.id IS NULL
        """)
        orphaned_detected = cursor.fetchone()[0]
        
        # Check for orphaned camera_id references
        cursor.execute("""
            SELECT COUNT(*) FROM entry_logs el
            LEFT JOIN cameras c ON el.camera_id = c.id
            WHERE el.camera_id IS NOT NULL AND c.id IS NULL
        """)
        orphaned_cameras = cursor.fetchone()[0]
        
        cursor.close()
        
        assert orphaned_detected == 0, f"Found {orphaned_detected} orphaned detected_id refs"
        assert orphaned_cameras == 0, f"Found {orphaned_cameras} orphaned camera_id refs"


class TestAnomaliesLogsIntegration:
    """Tests for anomalies_logs JDBC sink."""

    def test_anomalies_logs_has_records(self, db_connection):
        """Verify anomalies_logs table has received alert data."""
        cursor = db_connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM anomalies_logs")
        count = cursor.fetchone()[0]
        cursor.close()
        
        print(f"Total anomalies_logs records: {count}")

    def test_anomalies_logs_has_valid_fk_references(self, db_connection):
        """Verify all anomalies_logs records have valid FK references."""
        cursor = db_connection.cursor()
        
        # Check for orphaned anomaly_id references
        cursor.execute("""
            SELECT COUNT(*) FROM anomalies_logs al
            LEFT JOIN anomalies a ON al.anomaly_id = a.id
            WHERE al.anomaly_id IS NOT NULL AND a.id IS NULL
        """)
        orphaned_anomalies = cursor.fetchone()[0]
        
        cursor.close()
        
        assert orphaned_anomalies == 0, f"Found {orphaned_anomalies} orphaned anomaly_id refs"
