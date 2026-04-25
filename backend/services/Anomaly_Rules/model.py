from pydantic import BaseModel
from typing import Literal

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