"""
SQL validation and safety checks
"""
import sqlparse
from typing import Tuple


# Dangerous SQL keywords (not allowed)
DANGEROUS_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", 
    "TRUNCATE", "CREATE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL"
]

def validate_sql(sql_query: str) -> Tuple[bool, str]:
    """
    Validate SQL query for safety.
    
    Returns:
        (is_valid, error_message)
    """
    sql_upper = sql_query.upper().strip()
    
    # Check 1: Must be a SELECT statement
    if not sql_upper.startswith("SELECT"):
        return False, "Only SELECT queries are allowed"
    
    # Check 2: Check for dangerous keywords
    for keyword in DANGEROUS_KEYWORDS:
        if keyword in sql_upper:
            return False, f"Dangerous keyword '{keyword}' is not allowed"
    
    # Check 3: Validate SQL syntax
    try:
        parsed = sqlparse.parse(sql_query)
        if not parsed:
            return False, "Invalid SQL syntax"
    except Exception as e:
        return False, f"SQL parsing error: {str(e)}"
    
    # Check 4: No semicolons (prevents multiple statements)
    if ";" in sql_query.rstrip().rstrip(";"):
        return False, "Multiple statements not allowed"
    
    return True, ""

def sanitize_sql(sql_query: str) -> str:
    """
    Clean up SQL query formatting
    """
    # Remove markdown code fences if present
    sql_query = sql_query.strip()
    if sql_query.startswith("```"):
        lines = sql_query.split("\n")
        sql_query = "\n".join(lines[1:-1]) if len(lines) > 2 else sql_query
    
    sql_query = sql_query.replace("```sql", "").replace("```", "")
    
    # Format SQL nicely
    formatted = sqlparse.format(
        sql_query,
        reindent=True,
        keyword_case='upper'
    )
    
    return formatted.strip()