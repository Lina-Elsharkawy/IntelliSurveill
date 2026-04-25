from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal

from db import (
    get_all_rules,
    add_rule,
    inactive_rule,
    delete_rule,
    get_rule_by_id,
    set_rule_active
)
from llm_service import parse_rule_with_llm
from rules_engine import check_conflicts_preview, check_duplicate_active_rule

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
    rule_type: Literal["trigger", "suppress"]
    deactivate_rule_ids: list[int]

class ResolveReactivateRequest(BaseModel):
    rule_id: int
    deactivate_rule_ids: list[int]

class ReactivateRequest(BaseModel):
    rule_id: int

@app.get("/rules")
def list_rules():
    return get_all_rules()

@app.post("/rules/preview")
def preview_rule(req: RuleRequest):
    parsed = parse_rule_with_llm(req.rule_text, rule_type=req.rule_type)
    parsed["rule_type"] = req.rule_type

    duplicate = check_duplicate_active_rule(parsed)
    conflicts = check_conflicts_preview(parsed)

    return {
        "parsed": parsed,
        "duplicate": duplicate,
        "has_duplicate": duplicate is not None,
        "conflicts": conflicts,
        "has_conflicts": len(conflicts) > 0
    }

@app.post("/rules")
def create_rule(req: RuleRequest):
    parsed = parse_rule_with_llm(req.rule_text, rule_type=req.rule_type)
    parsed["rule_type"] = req.rule_type

    duplicate = check_duplicate_active_rule(parsed)
    if duplicate:
        raise HTTPException(status_code=409, detail={
            "message": "Duplicate active rule",
            "duplicate": duplicate
        })

    conflicts = check_conflicts_preview(parsed)
    if conflicts:
        raise HTTPException(status_code=409, detail={
            "message": "Rule conflicts with active rules",
            "conflicts": conflicts
        })

    return add_rule(
        rule_text=req.rule_text,
        rule_type=req.rule_type,
        event_type=parsed.get("event_type", "intrusion"),
        conditions=parsed.get("conditions", {})
    )

@app.post("/rules/resolve-and-add")
def resolve_and_add(req: ResolveConflictRequest):
    for rule_id in req.deactivate_rule_ids:
        inactive_rule(rule_id)
        
    parsed = parse_rule_with_llm(req.rule_text, rule_type=req.rule_type)
    return add_rule(
        rule_text=req.rule_text,
        rule_type=req.rule_type,
        event_type=parsed.get("event_type", "intrusion"),
        conditions=parsed.get("conditions", {})
    )

@app.post("/rules/resolve-and-reactivate")
def resolve_and_reactivate(req: ResolveReactivateRequest):
    for rule_id in req.deactivate_rule_ids:
        inactive_rule(rule_id)
    return set_rule_active(req.rule_id, True)

@app.patch("/rules/{rule_id}/deactivate")
def deactivate_rule(rule_id: int):
    return inactive_rule(rule_id)

@app.delete("/rules/{rule_id}")
def remove_rule(rule_id: int):
    return delete_rule(rule_id)

@app.post("/rules/reactivate-preview/{rule_id}")
def reactivate_preview(rule_id: int):
    rule = get_rule_by_id(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    parsed = {
        "rule_type":  rule["rule_type"],
        "event_type": rule["event_type"],
        "conditions": rule["conditions"],
        "rule_text":  rule["rule_text"],
    }

    # Pass exclude_rule_id so the rule being reactivated never conflicts with itself
    conflicts = check_conflicts_preview(parsed, exclude_rule_id=rule_id)
    duplicate = check_duplicate_active_rule(parsed)

    return {
        "rule_id":       rule["rule_id"],
        "rule_text":     rule["rule_text"],
        "parsed":        parsed,
        "conflicts":     conflicts,
        "has_conflicts": len(conflicts) > 0,
        "duplicate":     duplicate,
        "has_duplicate": duplicate is not None
    }

@app.patch("/rules/{rule_id}/reactivate")
def reactivate_rule(rule_id: int):
    return set_rule_active(rule_id, True)