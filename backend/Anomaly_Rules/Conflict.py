import json
import psycopg
import ollama
from backend.services.anomaly_service.config import DB_DSN, OLLAMA_HOST, LLM_MODEL
def check_conflicts_preview(new_parsed: dict) -> list[dict]:
    """
    Check conflicts for a rule that is NOT yet saved.
    Compares parsed rule against all existing active rules.
    Returns conflict list for frontend to display.
    """
    with psycopg.connect(DB_DSN) as conn:
        existing = conn.execute(
            "SELECT id, rule_text, rule_type, event_type, conditions "
            "FROM AnomalyRules WHERE active = TRUE"
        ).fetchall()

    if not existing:
        return []

    existing_block = "\n".join([
        f"Rule {r[0]}: [{r[2]}] [{r[3]}] \"{r[1]}\" conditions: {r[4]}"
        for r in existing
    ])

    prompt = f"""
You are a rule conflict detector for a surveillance system.

New rule being evaluated (not yet saved):
[{new_parsed['rule_type']}] [{new_parsed['event_type']}] 
"{new_parsed['rule_text']}" 
conditions: {json.dumps(new_parsed['conditions'])}

Existing active rules:
{existing_block}

Check for CONTRADICTION or DUPLICATION.

Contradiction = one triggers alert, another suppresses, same conditions.
Duplication   = two rules do the exact same thing.

Return ONLY a JSON array. Empty array [] if no conflicts.
[
  {{
    "existing_rule_id":   <id of the existing rule>,
    "existing_rule_text": "<text of that rule>",
    "conflict_type":      "contradiction" or "duplication",
    "conflict_reason":    "one sentence explanation"
  }}
]
"""

    resp = client.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"temperature": 0.0}
    )
    raw = resp.get("message") or {}.get("content", "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    return json.loads(raw.strip())


def save_conflicts(new_rule_id: int, conflicts: list[dict]) -> None:
    """Save conflict records to DB after rule is confirmed saved."""
    if not conflicts:
        return
    with psycopg.connect(DB_DSN) as conn:
        for c in conflicts:
            conn.execute(
                """
                INSERT INTO rule_conflicts
                    (rule_id_1, rule_id_2, conflict_reason, status)
                VALUES (%s, %s, %s, 'pending')
                """,
                (
                    str(new_rule_id),
                    str(c["existing_rule_id"]),
                    f"[{c['conflict_type']}] {c['conflict_reason']}"
                )
            )
        conn.commit()