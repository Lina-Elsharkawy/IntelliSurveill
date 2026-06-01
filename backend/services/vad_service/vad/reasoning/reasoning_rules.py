from __future__ import annotations

from typing import Any

from .reasoning_schema import DeepReasoningContext, VlmVisualReview

RULES_VERSION = "deep_reasoning_rules_v1"

DEFAULT_REASONING_RULES: list[dict[str, Any]] = [
    {
        "id": "suppress_clear_normal_activity",
        "name": "Suppress clear normal or benign activity",
        "rule_type": "suppress",
        "event_types": ["normal_activity", "benign_posture_change", "benign_object_movement"],
        "conditions": {"max_score_ratio": 1.25},
        "effect": {"policy_alert_decision": "NO", "policy_severity": "LOW", "recommended_action": "save_for_dataset"},
    },
    {
        "id": "suppress_camera_or_detection_artifact",
        "name": "Suppress camera or detection artifact",
        "rule_type": "suppress",
        "event_types": ["camera_or_detection_artifact"],
        "conditions": {},
        "effect": {"policy_alert_decision": "NO", "policy_severity": "NONE", "recommended_action": "save_for_dataset"},
    },
    {
        "id": "review_unclear_visual_evidence",
        "name": "Review unclear visual evidence conservatively",
        "rule_type": "suppress",
        "event_types": ["unclear_visual_evidence"],
        "conditions": {},
        "effect": {"policy_alert_decision": "UNCERTAIN", "policy_severity": "LOW", "recommended_action": "review_only"},
    },
    {
        "id": "trigger_fall_or_person_on_floor",
        "name": "Escalate visually supported fall or person-on-floor event",
        "rule_type": "trigger",
        "event_types": ["fall_or_collapse", "person_on_floor"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "HIGH", "recommended_action": "urgent_alert"},
    },
    {
        "id": "trigger_unsafe_equipment_interaction",
        "name": "Escalate visually supported unsafe equipment interaction",
        "rule_type": "trigger",
        "event_types": ["unsafe_equipment_interaction"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"},
    },
    {
        "id": "trigger_possible_security_event",
        "name": "Escalate visually supported suspicious or security event",
        "rule_type": "trigger",
        "event_types": ["possible_intrusion_or_security_event", "suspicious_motion"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"},
    },
]


def load_active_reasoning_rules() -> list[dict[str, Any]]:
    """Return built-in project rules. Later this can be replaced by DB-backed active rules."""
    return [dict(rule) for rule in DEFAULT_REASONING_RULES]


def serialize_rules_for_llm(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep rule payload compact and deterministic for the LLM prompt."""
    out: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("active") is False:
            continue
        out.append(
            {
                "id": rule.get("id"),
                "name": rule.get("name"),
                "rule_type": rule.get("rule_type"),
                "event_types": rule.get("event_types") or [],
                "conditions": rule.get("conditions") or {},
                "effect": rule.get("effect") or {},
            }
        )
    return out


def rule_matches(rule: dict[str, Any], *, ctx: DeepReasoningContext, vlm: VlmVisualReview) -> bool:
    event_types = set(rule.get("event_types") or [])
    if event_types and vlm.event_type not in event_types:
        return False
    conditions = rule.get("conditions") or {}
    ratio = ctx.score_ratio
    min_ratio = conditions.get("min_score_ratio")
    max_ratio = conditions.get("max_score_ratio")
    if min_ratio is not None and ratio is not None and ratio < float(min_ratio):
        return False
    if max_ratio is not None and ratio is not None and ratio > float(max_ratio):
        return False
    if conditions.get("requires_anomaly_evidence") and not vlm.anomaly_evidence:
        return False
    return True


def deterministic_rule_matches(*, ctx: DeepReasoningContext, vlm: VlmVisualReview, rules: list[dict[str, Any]]) -> dict[str, Any]:
    matched_trigger_rules: list[dict[str, Any]] = []
    matched_suppress_rules: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("active") is False:
            continue
        if not rule_matches(rule, ctx=ctx, vlm=vlm):
            continue
        rec = {
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name"),
            "rule_type": rule.get("rule_type"),
            "event_types": rule.get("event_types") or [],
            "effect": rule.get("effect") or {},
            "reason": f"Rule matched VLM event_type={vlm.event_type}.",
        }
        if rule.get("rule_type") == "trigger":
            matched_trigger_rules.append(rec)
        elif rule.get("rule_type") == "suppress":
            matched_suppress_rules.append(rec)
    return {
        "rules_version": RULES_VERSION,
        "matched_trigger_rules": matched_trigger_rules,
        "matched_suppress_rules": matched_suppress_rules,
    }
