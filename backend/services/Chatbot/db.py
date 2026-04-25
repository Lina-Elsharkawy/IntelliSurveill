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

def get_database_schema() -> str:
    """
    Fetch the database schema as a text description.
    This will be provided to the LLM for SQL generation.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    schema_description = []
    
    try:
        # Get all tables
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        for (table_name,) in tables:
            schema_description.append(f"\nTable: {table_name}")
            
            # Get columns for this table
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table_name,))
            
            columns = cursor.fetchall()
            for col_name, data_type, is_nullable in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                schema_description.append(f"  - {col_name}: {data_type} ({nullable})")
        
        return "\n".join(schema_description)
    
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