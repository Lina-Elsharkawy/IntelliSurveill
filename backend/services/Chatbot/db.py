"""
Database connection and schema management
"""
import psycopg2
from psycopg2 import sql
from typing import List, Dict, Any
from config import DB_DSN
from typing import TypedDict

def get_db_connection():
    """Create a database connection"""
    return psycopg2.connect(DB_DSN)

# Cache schema in memory — fetched once per process lifetime
_schema_cache: str | None = None

def get_database_schema() -> str:
    """
    Fetch the database schema as a text description.
    Cached after the first call so the LLM prompt stays fast.
    """
    global _schema_cache
    if _schema_cache is not None:
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
        return _schema_cache
    
    finally:
        cursor.close()
        conn.close()

def execute_sql_safely(sql_query: str, params: tuple = None) -> Dict[str, Any]:
    """
    Execute SQL query with safety checks
    
    Returns:
        dict with 'success', 'data', 'error', 'row_count'
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Execute with timeout
        cursor.execute("SET statement_timeout TO 30000")  # 30 seconds
        cursor.execute(sql_query, params)
        
        # Fetch results if it's a SELECT
        if sql_query.strip().upper().startswith("SELECT"):
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            
            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in rows]
            
            return {
                "success": True,
                "data": data,
                "row_count": len(data),
                "error": None
            }
        else:
            # For non-SELECT queries (shouldn't happen in read-only mode)
            conn.commit()
            return {
                "success": True,
                "data": [],
                "row_count": cursor.rowcount,
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