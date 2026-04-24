from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import psycopg
from config import DB_DSN
from typing import Literal
from Add_Rules import add_rule, get_all_rules, inactive_rule, delete_rule, check_conflicts_preview, parse_rule_with_llm

app = FastAPI(title="Anomaly Rules Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class RuleRequest(BaseModel):
    rule_text: str
    rule_type: Literal["trigger", "suppress"]

class ResolveConflictRequest(BaseModel):
    rule_text: str
    rule_type: Literal["trigger", "suppress"]  # ← add this
    deactivate_rule_ids: list[int]

class ReactivateRequest(BaseModel):
    rule_id: int

@app.get("/rules")
def list_rules():
    return get_all_rules()

@app.post("/rules/preview")
def preview_rule(req: RuleRequest):
    parsed = parse_rule_with_llm(req.rule_text, rule_type=req.rule_type)  # ← pass rule_type
    parsed["rule_type"] = req.rule_type  # ← always override with user's choice
    conflicts = check_conflicts_preview(parsed)
    return {
        "parsed": parsed,
        "conflicts": conflicts,
        "has_conflicts": len(conflicts) > 0
    }

@app.post("/rules")
def create_rule(req: RuleRequest):
    return add_rule(req.rule_text, rule_type=req.rule_type)  # ← pass rule_type

@app.post("/rules/resolve-and-add")
def resolve_and_add(req: ResolveConflictRequest):
    for rule_id in req.deactivate_rule_ids:
        inactive_rule(rule_id)
    return add_rule(req.rule_text, rule_type=req.rule_type)  # ← pass rule_type

@app.patch("/rules/{rule_id}/deactivate")
def deactivate_rule(rule_id: int):
    return inactive_rule(rule_id)

@app.delete("/rules/{rule_id}")
def remove_rule(rule_id: int):
    return delete_rule(rule_id)

@app.post("/rules/reactivate-preview/{rule_id}")
def reactivate_preview(rule_id: int):
    with psycopg.connect(DB_DSN) as conn:
        row = conn.execute(
            "SELECT id, rule_text, rule_type, event_type, conditions FROM Anomaly_Rules WHERE id = %s",
            (rule_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    parsed = {
        "rule_type":  row[2],
        "event_type": row[3],
        "conditions": row[4],
        "rule_text":  row[1],
    }

    # Pass exclude_rule_id so the rule being reactivated never conflicts with itself
    conflicts = check_conflicts_preview(parsed, exclude_rule_id=rule_id)

    return {
        "rule_id":       row[0],
        "rule_text":     row[1],
        "parsed":        parsed,
        "conflicts":     conflicts,
        "has_conflicts": len(conflicts) > 0
    }

@app.patch("/rules/{rule_id}/reactivate")
def reactivate_rule(rule_id: int):
    with psycopg.connect(DB_DSN) as conn:
        conn.execute("BEGIN")
        conn.execute("UPDATE Anomaly_Rules SET active = TRUE WHERE id = %s", (rule_id,))
        conn.execute("COMMIT")
    return {"rule_id": rule_id, "active": True}