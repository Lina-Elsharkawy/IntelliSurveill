"""
SQL validation and safety checks for the surveillance chatbot.

Two layers of protection:
  1. is_write_intent(question) — checked on the RAW user question before anything runs.
     Only blocks clear imperative COMMANDS ("delete employee 5"), never innocent
     historical questions ("when was X inserted?").

  2. safety_gate(sql) — checked on the LLM-GENERATED SQL, AFTER generation.
     This is the hard wall: if the LLM somehow produced a write query despite
     the read-only prompt, it is silently rejected here before touching the DB.
"""
import re
import sqlparse
from typing import Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — User-intent guard  (question → is this a write COMMAND?)
# ─────────────────────────────────────────────────────────────────────────────

# These patterns ONLY match imperative write COMMANDS.
# They intentionally leave through innocent historical questions such as:
#   "when was X inserted?"  / "how many times was X logged?"
#   "was he added recently?" / "first time she appeared?"
_WRITE_INTENT_PATTERNS = [
    # Imperative destruction: "delete all records", "drop the table", "wipe logs"
    r'\b(delete|drop|truncate|wipe)\b\s+\w',
    # Explicit modification command with object: "update employee", "alter table"
    r'\b(update|alter|modify)\b\s+\w',
    # Clear/remove data commands — broadened to cover bare objects too
    r'\b(clear|remove)\s+(all|the|every)\b',
    r'\b(remove|drop)\s+(table|tables|database|db|records?|data|logs?)\b',
    r'\b(remove|drop)\s+(the\s+)?(anomaly|entry|employee|visitor|camera|rule|schedule)\b',
    r'\b(clear|wipe)\s+(the\s+)?(database|table|log|records?|data|entries|everything)\b',
    # Explicit SQL injection attempts: "insert into" (NOT "inserted" — past tense is a read question)
    r'\binsert\s+into\b',
    r'\badd\s+(a\s+)?(new\s+)?(record|row|entry|employee|visitor|camera)\b',
    # DDL injection: "create table", "create a table"
    r'\bcreate\s+(a\s+)?table\b',
    # Privilege manipulation
    r'\b(grant|revoke)\b\s+\w',
    # Explicit value assignment: "set x to y", "reset password"
    r'\b(reset|set)\s+\w+\s+(to|=)\b',
]

# Questions using past-tense "inserted/added/created" are read-only historical queries.
# e.g. "when was Lina first inserted?" / "how many times was X inserted?"
_WRITE_SAFE_OVERRIDES = [
    re.compile(r'\b(inserted|added|created|logged)\b', re.IGNORECASE),
]

_WRITE_PATTERNS_COMPILED = [
    re.compile(p, re.IGNORECASE) for p in _WRITE_INTENT_PATTERNS
]


def is_write_intent(question: str) -> bool:
    """
    Returns True ONLY when the user is issuing a write COMMAND.

    SAFE (returns False):
      - "when was Ahmed first inserted?"
      - "how many times was Lina logged in?"
      - "was this record added yesterday?"
      - "how many times maged was inserted?"

    BLOCKED (returns True):
      - "delete employee 5"
      - "insert into employees values ..."
      - "drop the anomaly_rules table"
    """
    # If any past-tense historical keyword is present, this is a read question — never block it.
    if any(p.search(question) for p in _WRITE_SAFE_OVERRIDES):
        return False
    return any(p.search(question) for p in _WRITE_PATTERNS_COMPILED)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Post-generation SQL safety gate
# Runs AFTER the LLM produces SQL, BEFORE the DB executes it.
# ─────────────────────────────────────────────────────────────────────────────

_BLOCKED_SQL_KEYWORDS = [
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE",
    "EXECUTE", "EXEC", "CALL", "MERGE",
]

# Word-boundary pattern to avoid false positives on column names like CREATED_AT
_BLOCKED_PATTERNS = [
    re.compile(rf'\b{kw}\b', re.IGNORECASE) for kw in _BLOCKED_SQL_KEYWORDS
]


def safety_gate(sql: str) -> tuple[bool, str]:
    """
    Final guard before SQL execution.

    The old guard used regex over the raw SQL string, which falsely blocked
    safe read-only queries such as:
        SELECT * FROM audit_logs WHERE action = 'CREATE'
    because CREATE appeared inside a string literal. This version uses
    sqlparse tokens and blocks only real SQL command tokens outside comments
    and string literals.
    """
    if not sql or not sql.strip():
        return False, "No SQL was generated."

    statements = [stmt for stmt in sqlparse.parse(sql) if stmt.tokens]
    if len(statements) != 1:
        return False, "Only one read-only SQL statement is allowed."

    stmt = statements[0]
    first_word = stmt.get_type().upper()

    if first_word not in ("SELECT", "UNKNOWN"):
        return False, (
            "I can only run read-only queries. "
            f"The generated statement starts with `{first_word}` which is not allowed."
        )

    stripped = sql.strip().lstrip("(").strip()
    first_token = stripped.split()[0].upper() if stripped else ""
    if first_token not in ("SELECT", "WITH"):
        return False, (
            "I can only run read-only queries. "
            f"The generated statement starts with `{first_token}` which is not allowed."
        )

    blocked = set(_BLOCKED_SQL_KEYWORDS)
    for token in stmt.flatten():
        value = token.value.upper()
        if value in blocked and token.ttype not in (sqlparse.tokens.Literal.String.Single,
                                                    sqlparse.tokens.Literal.String.Symbol):
            return False, (
                f"The generated query contains SQL command `{value}` which is not allowed "
                "in read-only mode. Please rephrase your question."
            )

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# SQL Validation  (structural checks on the LLM output)
# ─────────────────────────────────────────────────────────────────────────────

def validate_sql(sql_query: str) -> Tuple[bool, str]:
    """
    Validate SQL structure after LLM generation.
    Returns (is_valid, error_message).
    """
    sql_stripped = sql_query.strip()
    if not sql_stripped:
        return False, "Empty SQL query"

    first_word = sql_stripped.split()[0].upper()

    # Allow SELECT and WITH (CTEs)
    if first_word not in ("SELECT", "WITH"):
        return False, f"Only SELECT queries are allowed (got {first_word})"

    # Structural parse check
    try:
        parsed = sqlparse.parse(sql_query)
        if not parsed:
            return False, "Invalid SQL syntax"
    except Exception as e:
        return False, f"SQL parsing error: {str(e)}"

    return True, ""


def sanitize_sql(sql_query: str) -> str:
    """
    Strip markdown fences the LLM sometimes wraps around SQL and format nicely.
    """
    sql_query = sql_query.strip()

    # Strip ```sql ... ``` fences
    if sql_query.startswith("```"):
        lines = sql_query.split("\n")
        inner = [l for l in lines if not l.strip().startswith("```")]
        sql_query = "\n".join(inner)

    sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

    formatted = sqlparse.format(
        sql_query,
        reindent=True,
        keyword_case="upper",
        strip_comments=True,
    )
    return formatted.strip()