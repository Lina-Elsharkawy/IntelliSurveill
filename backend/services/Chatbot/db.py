"""
Database connection and schema management
"""
import time
import logging
import psycopg2
from psycopg2 import sql
from typing import List, Dict, Any
from config import DB_DSN, CHATBOT_TIMEZONE
from typing import TypedDict

logger = logging.getLogger(__name__)

def get_db_connection():
    """Create a database connection"""
    conn = psycopg2.connect(DB_DSN)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s", (CHATBOT_TIMEZONE,))
    return conn

# Cache schema in memory with TTL — refreshes every 5 minutes so new tables
# are picked up without a service restart.
_schema_cache: str | None = None
_schema_cache_time: float = 0.0
_SCHEMA_TTL_SECONDS = 300  # 5 minutes

def get_database_schema() -> str:
    """
    Fetch the database schema as a text description.
    Cached with a 5-minute TTL so schema changes are picked up eventually.
    """
    global _schema_cache, _schema_cache_time
    if _schema_cache is not None and (time.time() - _schema_cache_time) < _SCHEMA_TTL_SECONDS:
        return _schema_cache

    conn = get_db_connection()
    cursor = conn.cursor()
    
    schema_description = []
    
    try:
        # Get all PUBLIC tables only
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        for (table_name,) in tables:
            schema_description.append(f"\nTable: {table_name}")
            
            # FIXED: also filter by table_schema here — without this, postgres returns
            # columns for the same table_name from ALL schemas (pg_catalog, etc.),
            # which is why the schema was bloating to 238 "tables".
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s
                  AND table_schema = 'public'
                ORDER BY ordinal_position
            """, (table_name,))
            
            columns = cursor.fetchall()
            for col_name, data_type, is_nullable in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                schema_description.append(f"  - {col_name}: {data_type} ({nullable})")
        
        _schema_cache = "\n".join(schema_description)
        _schema_cache_time = time.time()
        logger.info("Schema cache refreshed (%d tables)", len(tables))
        return _schema_cache
    
    finally:
        cursor.close()
        conn.close()

def execute_sql_safely(sql_query: str, params: tuple = None) -> Dict[str, Any]:
    """
    Execute read-only SQL query safely.
    Supports SELECT and WITH queries only.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SET statement_timeout TO 30000")

        stripped = sql_query.strip()
        first_word = stripped.split()[0].upper() if stripped else ""

        # Defensive guard for callers that use execute_sql_safely directly.
        # The LangGraph path already runs validators.safety_gate first, but this
        # keeps the DB helper read-only by itself too.
        if ";" in stripped.rstrip(";"):
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": "Only one read-only SQL statement is allowed."
            }

        if first_word not in ("SELECT", "WITH"):
            return {
                "success": False,
                "data": [],
                "row_count": 0,
                "error": f"Only SELECT/WITH read-only queries are allowed, got: {first_word}"
            }

        cursor.execute(sql_query, params)

        if cursor.description is None:
            return {
                "success": True,
                "data": [],
                "row_count": 0,
                "error": None
            }

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        data = [dict(zip(columns, row)) for row in rows]

        return {
            "success": True,
            "data": data,
            "row_count": len(data),
            "error": None
        }

    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "data": [],
            "row_count": 0,
            "error": str(e)
        }

    finally:
        cursor.close()
        conn.close()

def test_connection() -> bool:
    """Test database connection"""
    try:
        conn = get_db_connection()
        conn.close()
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False