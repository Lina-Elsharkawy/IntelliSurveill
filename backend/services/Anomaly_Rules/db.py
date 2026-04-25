import json
import psycopg
from typing import Literal
from config import DB_DSN

def add_rule(
    rule_text: str,
    rule_type: Literal["trigger", "suppress"],
    event_type: str,
    conditions: dict,
    source: str = "Admin",
    active: bool = True
) -> dict:
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        row = conn.execute(
            """
            INSERT INTO Anomaly_Rules (
                rule_text, rule_type, event_type,
                conditions, source, active
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, %s)
            RETURNING id
            """,
            (
                rule_text,  
                rule_type,                                  
                event_type,
                json.dumps(conditions or {}),
                source,
                active
            )
        ).fetchone()
        rule_id = row[0]
        conn.execute("COMMIT")

    return {
        "rule_id":    rule_id,
        "rule_text":  rule_text,
        "rule_type":  rule_type,
        "event_type": event_type,
        "conditions": conditions,
        "source":     source,
        "active":     active
    }

def inactive_rule(rule_id: int) -> dict:
    """
    Deactivate a rule by its ID.
    """
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE Anomaly_Rules
            SET active = FALSE
            WHERE id = %s
            """,
            (rule_id,)
        )
        conn.execute("COMMIT")
    return {"rule_id": rule_id, "active": False}

def set_rule_active(rule_id: int, active: bool) -> dict:
    """
    Set a rule's active status by its ID.
    """
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE Anomaly_Rules
            SET active = %s
            WHERE id = %s
            """,
            (active, rule_id)
        )
        conn.execute("COMMIT")
    return {"rule_id": rule_id, "active": active}

def delete_rule(rule_id: int) -> dict:
    """
    Delete a rule by its ID.
    """
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        conn.execute(
            """
            DELETE FROM Anomaly_Rules
            WHERE id = %s
            """,
            (rule_id,)
        )
        conn.execute("COMMIT")
    return {"rule_id": rule_id, "deleted": True}

def delete_all_rules() -> dict:
    """
    Delete all rules from the database.
    """
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM Anomaly_Rules")
        conn.execute("COMMIT")
    return {"deleted_all": True}

def get_all_rules() -> list[dict]:
    """
    Get all rules from the database.
    """
    with psycopg.connect(DB_DSN) as conn:
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, event_type, conditions, source, active
            FROM Anomaly_Rules
            ORDER BY id ASC
            """
        ).fetchall()
    return [
        {
            "rule_id":           row[0],
            "rule_text":         row[1],
            "rule_type":         row[2],
            "event_type":        row[3],
            "conditions":        row[4],
            "source":            row[5],
            "active":            row[6]
        }
        for row in rows
    ]

def get_all_active_rules() -> list[tuple]:
    """
    Get all active rules from the database as tuples.
    Returns: list of (id, rule_text, rule_type, event_type, conditions, active)
    """
    with psycopg.connect(DB_DSN) as conn:
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, event_type, conditions, active
            FROM Anomaly_Rules
            WHERE active = TRUE
            """
        ).fetchall()
    return rows

def get_rule_by_id(rule_id: int) -> dict | None:
    with psycopg.connect(DB_DSN) as conn:
        row = conn.execute(
            "SELECT id, rule_text, rule_type, event_type, conditions, source, active FROM Anomaly_Rules WHERE id = %s",
            (rule_id,)
        ).fetchone()

    if not row:
        return None

    return {
        "rule_id":    row[0],
        "rule_text":  row[1],
        "rule_type":  row[2],
        "event_type": row[3],
        "conditions": row[4],
        "source":     row[5],
        "active":     row[6]
    }
