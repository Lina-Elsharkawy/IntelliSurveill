"""VAD Anomaly Rules — DB-backed rule engine for the Deep Gate reasoning pipeline.

This module replaces the previous compile-time hardcoded rule list in
``reasoning/reasoning_rules.py`` with a live-queryable Postgres table
(``vad_reasoning_rules``).

Design
------
Rules are stored per-row in ``vad_reasoning_rules``.  Each row maps directly
to the rule dict structure consumed by the reasoning policy:

    id            – surrogate PK
    rule_name     – human-readable display name
    rule_type     – "trigger" | "suppress"
    event_types   – JSONB array of VLM event_type strings this rule targets
    conditions    – JSONB object: {min_score_ratio?, max_score_ratio?,
                                    requires_anomaly_evidence?}
    effect        – JSONB object: see below per rule_type
    active        – bool; inactive rules are never loaded
    source        – "builtin" | "admin" | "learned"
    description   – optional free-text description

Effect schema (trigger rules):
    {minimum_severity: str, recommended_action: str}

Effect schema (suppress rules):
    {policy_alert_decision: str, policy_severity: str, recommended_action: str}

Fallback
--------
If the DB table does not exist yet (migration not run) or the query fails,
the engine falls back to a safe set of built-in default rules so the
reasoning pipeline keeps working without a schema migration.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

log = logging.getLogger("vad.vad_anomaly_rules")

RULES_VERSION = "vad_reasoning_rules_db_v1"

# ---------------------------------------------------------------------------
# Built-in fallback rules — used when the DB table is unavailable.
# These mirror the original hardcoded defaults in reasoning_rules.py.
# ---------------------------------------------------------------------------

_BUILTIN_FALLBACK_RULES: list[dict[str, Any]] = [
    {
        "id": "builtin_suppress_clear_normal_activity",
        "rule_name": "Suppress clear normal or benign activity",
        "rule_type": "suppress",
        "event_types": ["normal_activity", "benign_posture_change", "benign_object_movement"],
        "conditions": {"max_score_ratio": 1.25},
        "effect": {
            "policy_alert_decision": "NO",
            "policy_severity": "LOW",
            "recommended_action": "save_for_dataset",
        },
        "source": "builtin",
        "active": True,
        "description": "Do not alert on clearly normal or benign events with a low score ratio.",
    },
    {
        "id": "builtin_suppress_camera_or_detection_artifact",
        "rule_name": "Suppress camera or detection artifact",
        "rule_type": "suppress",
        "event_types": ["camera_or_detection_artifact"],
        "conditions": {},
        "effect": {
            "policy_alert_decision": "NO",
            "policy_severity": "NONE",
            "recommended_action": "save_for_dataset",
        },
        "source": "builtin",
        "active": True,
        "description": "Suppress events caused by camera noise, glare, or detector instability.",
    },
    {
        "id": "builtin_review_unclear_visual_evidence",
        "rule_name": "Review unclear visual evidence conservatively",
        "rule_type": "suppress",
        "event_types": ["unclear_visual_evidence"],
        "conditions": {},
        "effect": {
            "policy_alert_decision": "UNCERTAIN",
            "policy_severity": "LOW",
            "recommended_action": "review_only",
        },
        "source": "builtin",
        "active": True,
        "description": "Flag events with unclear visual evidence for manual review rather than alerting.",
    },
    {
        "id": "builtin_trigger_fall_or_person_on_floor",
        "rule_name": "Escalate visually supported fall or person-on-floor event",
        "rule_type": "trigger",
        "event_types": ["fall_or_collapse", "person_on_floor"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "HIGH", "recommended_action": "urgent_alert"},
        "source": "builtin",
        "active": True,
        "description": "Urgent alert for any confirmed fall or person-on-floor visual event.",
    },
    {
        "id": "builtin_trigger_unsafe_equipment_interaction",
        "rule_name": "Escalate visually supported unsafe equipment interaction",
        "rule_type": "trigger",
        "event_types": ["unsafe_equipment_interaction"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"},
        "source": "builtin",
        "active": True,
        "description": "Alert operator when someone is visually confirmed to interact unsafely with lab equipment.",
    },
    {
        "id": "builtin_trigger_possible_security_event",
        "rule_name": "Escalate visually supported suspicious or security event",
        "rule_type": "trigger",
        "event_types": ["possible_intrusion_or_security_event", "suspicious_motion"],
        "conditions": {"requires_anomaly_evidence": True},
        "effect": {"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"},
        "source": "builtin",
        "active": True,
        "description": "Alert operator for any visually confirmed intrusion or suspicious motion.",
    },
]


# ---------------------------------------------------------------------------
# DB loader
# ---------------------------------------------------------------------------

def load_active_vad_rules(db: Any, conn: "psycopg.Connection") -> list[dict[str, Any]]:
    """Return active rules from the DB, falling back to built-ins on failure.

    Parameters
    ----------
    db:
        A ``VadDB`` instance that exposes ``get_active_vad_reasoning_rules(conn)``.
    conn:
        An open psycopg connection (inside a transaction is fine).

    Returns
    -------
    list[dict[str, Any]]
        Normalised rule dicts ready for use in the reasoning policy.
    """
    try:
        rows = db.get_active_vad_reasoning_rules(conn)
        if not rows:
            log.debug("No active VAD reasoning rules found in DB; using built-in fallback rules.")
            return list(_BUILTIN_FALLBACK_RULES)
        rules = [_normalise_db_row(r) for r in rows]
        log.debug("Loaded %d active VAD reasoning rules from DB.", len(rules))
        return rules
    except Exception as exc:
        log.warning(
            "Failed to load VAD reasoning rules from DB (%s); using built-in fallback rules.", exc
        )
        return list(_BUILTIN_FALLBACK_RULES)


def _normalise_db_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row into the canonical rule dict consumed by the engine."""
    event_types = row.get("event_types") or []
    if isinstance(event_types, str):
        import json
        try:
            event_types = json.loads(event_types)
        except Exception:
            event_types = [event_types] if event_types else []

    conditions = row.get("conditions") or {}
    effect = row.get("effect") or {}

    return {
        "id": str(row.get("id") or row.get("rule_id") or ""),
        "rule_name": str(row.get("rule_name") or row.get("name") or ""),
        "rule_type": str(row.get("rule_type") or "suppress"),
        "event_types": list(event_types),
        "conditions": dict(conditions),
        "effect": dict(effect),
        "source": str(row.get("source") or "db"),
        "active": bool(row.get("active", True)),
        "description": str(row.get("description") or ""),
    }


# ---------------------------------------------------------------------------
# Rule matching engine
# ---------------------------------------------------------------------------

def rule_matches(
    rule: dict[str, Any],
    *,
    ctx: Any,
    vlm: Any,
) -> bool:
    """Return True if the rule conditions are satisfied by ``ctx`` and ``vlm``.

    Parameters
    ----------
    rule:
        A normalised rule dict (from ``load_active_vad_rules``).
    ctx:
        A ``DeepReasoningContext`` instance.
    vlm:
        A ``VlmVisualReview`` instance.
    """
    if rule.get("active") is False:
        return False

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


def deterministic_rule_matches(
    *,
    ctx: Any,
    vlm: Any,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate all rules and return lists of matched triggers and suppressors.

    Returns
    -------
    dict with keys:
        ``rules_version``, ``matched_trigger_rules``, ``matched_suppress_rules``
    """
    matched_trigger_rules: list[dict[str, Any]] = []
    matched_suppress_rules: list[dict[str, Any]] = []

    for rule in rules:
        if rule.get("active") is False:
            continue
        if not rule_matches(rule, ctx=ctx, vlm=vlm):
            continue
        rec = {
            "rule_id": rule.get("id"),
            "rule_name": rule.get("rule_name"),
            "rule_type": rule.get("rule_type"),
            "event_types": rule.get("event_types") or [],
            "effect": rule.get("effect") or {},
            "reason": f"Rule matched VLM event_type={vlm.event_type}.",
            "source": rule.get("source", "db"),
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


def serialize_rules_for_llm(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact, deterministic rule representation for the LLM policy prompt."""
    out: list[dict[str, Any]] = []
    for rule in rules:
        if rule.get("active") is False:
            continue
        out.append(
            {
                "id": rule.get("id"),
                "name": rule.get("rule_name"),
                "rule_type": rule.get("rule_type"),
                "event_types": rule.get("event_types") or [],
                "conditions": rule.get("conditions") or {},
                "effect": rule.get("effect") or {},
            }
        )
    return out
