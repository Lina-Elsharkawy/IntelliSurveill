import json
import psycopg
import ollama
from backend.services.anomaly_service.config import DB_DSN, OLLAMA_HOST, LLM_MODEL

ALLOWED_EVENT_TYPES = [
    "intrusion", "loitering", "after_hours", "fall_detected", 
    "fight_detection", "camera_tamper", "sudden_movement", 
    "smoke_fire", "crowd_detection"
]
def parse_rule_with_llm(rule_text: str) -> dict:
    """
    Call LLM once to convert natural language rule into structured JSON.
    """
    client = ollama.Client(host=OLLAMA_HOST)

    prompt = f"""You are a rule parser for a surveillance system.
    Convert the following admin rule into a structured JSON object.

    RULE TYPE DETECTION (read this first):
    - If the rule contains words like "do not", "don't", "ignore", "suppress", 
    "no alert", "never alert" → rule_type MUST be "suppress"
    - Otherwise → rule_type is "trigger"

    ALLOWED event_type values (choose the BEST match):
    - "intrusion"         → unauthorized access, trespassing, entering restricted area
    - "loitering"         → hanging around, standing still, suspicious waiting  
    - "after_hours"       → presence outside business hours, after 5pm, late night
    - "fall_detected"     → person falling down, collapse, trip
    - "fight_detection"   → fighting, physical altercation, violence, brawl, combat
    - "camera_tamper"     → camera blocked, covered, moved, vandalized
    - "sudden_movement"   → running, sprinting, rapid movement
    - "smoke_fire"        → smoke, fire, flames, burning
    - "crowd_detection"   → crowd, gathering, large group, many people

    If no time range → set time_range to null
    If no location → set location to "All"  
    If no person type → set person_type to null

    EXAMPLES:

    Example 1 - trigger rule:
    Admin rule: "Alert me if someone enters the server room after 5 PM"
    Output:
    {{
    "rule_type": "trigger",
    "event_type": "intrusion",
  "conditions": {{
    "location": "server room",
    "time_range": {{"after": "17:00"}},
    "person_type": "anyone"
  }}
}}

Example 2 - suppress rule:
Admin rule: "Do not alert if there is a fight"
Output:
{{
  "rule_type": "suppress",
  "event_type": "fight_detection",
  "conditions": {{
    "location": "All",
    "time_range": null,
    "person_type": null
  }}
}}

Example 3 - suppress rule with location:
Admin rule: "Ignore crowd alerts in the cafeteria between 12 PM and 2 PM"
Output:
{{
  "rule_type": "suppress",
  "event_type": "crowd_detection",
  "conditions": {{
    "location": "cafeteria",
    "time_range": {{"after": "12:00", "before": "14:00"}},
    "person_type": null
  }}
}}

Output ONLY valid JSON. No explanation. No markdown.

Admin rule: "{rule_text}"
"""
    resp = client.chat(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"temperature": 0.0}
    )

    raw = (resp.get("message") or {}).get("content", "").strip()

    # Strip markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    parsed = json.loads(raw)

    # Validate event_type is from allowed list
    if parsed.get("event_type") not in ALLOWED_EVENT_TYPES:
        parsed["event_type"] = "intrusion"  # safe fallback
        parsed["parser_confidence"] = 0.3   # flag low confidence

    return parsed


def add_rule(
    rule_text: str,
    source: str = "Admin",
    active: bool = True
    ) -> dict:
    """
    Full pipeline: parse NL → JSON, save to DB, return result.
    """
    structured = parse_rule_with_llm(rule_text)

    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")

        row = conn.execute(
            """
            INSERT INTO Anomaly_Rules (
                rule_text, rule_type, event_type,
                conditions, source, active
            )
            VALUES (%s, %s, %s, %s::jsonb, %s, TRUE)
            RETURNING id
            """,
            (
                rule_text,
                structured.get("rule_type", "trigger"),
                structured.get("event_type", "intrusion"),
                json.dumps(structured.get("conditions", {})),
                source
            )
        ).fetchone()

        rule_id = row[0]
        conn.execute("COMMIT")

    return {
        "rule_id":           rule_id,
        "rule_text":         rule_text,
        "rule_type":         structured.get("rule_type"),
        "event_type":        structured.get("event_type"),
        "conditions":        structured.get("conditions"),
        "source":            source,
        "active":            active
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
        conn.execute("BEGIN")
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, event_type, conditions, source, active
            FROM Anomaly_Rules
            """
        ).fetchall()
        conn.execute("COMMIT")
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
# def Auto_Genration_Rules(source:str="Learned",active:bool=True,rule_text:str):

    

if __name__ == "__main__":
    # Clean up existing rules to avoid duplicates during testing
    print("=== CLEANING UP ===")
    delete_all_rules()

    rule1 = "Alert me if someone enters the server room after 5 PM"
    rule2 = "Donot alert if there is fight"
    rule3="Tell me if there is Crowd in Room5"

    
    print("=== ADDING RULES ===")
    result1 = add_rule(rule1)
    result2 = add_rule(rule2)
    result3 = add_rule(rule3)

    print(f"Added Rule 1: {result1['rule_id']}")
    print(f"Added Rule 2: {result2['rule_id']}")
    print(f"Added Rule 3: {result3['rule_id']}")

    print("\n=== ALL RULES ===")
    for rule in get_all_rules():
        print(rule)

    print("\n=== DEACTIVATING RULE ===")
    inactive_rule(result1['rule_id'])
    
    print("\n=== DELETING RULE ===")
    delete_rule(result1['rule_id'])

    print("\n=== FINAL RULES LIST ===")
    for rule in get_all_rules():
        print(rule)
