"""
vad_anomaly_rules.py
====================
Connects the Anomaly_Rules table (managed by anomaly-rules-service) to
the VAD reasoning pipeline.

This is the ONLY rule source. The vad_reasoning_rules table is empty and
unused — all rules live in Anomaly_Rules, added by admins via the
anomaly-rules-service UI (app.py / Add_Rules.py).

How admin rules reach the reasoning pipeline:
  Admin adds rule via UI
       -> anomaly-rules-service (llm_service.py) parses it into structured JSON
       -> Anomaly_Rules table in PostgreSQL (shared DB)
       -> load_anomaly_rules(conn) reads it here
       -> LLM prompt receives the full active rule list
       -> deterministic_rule_matches() verifies the LLM decision in Python

Paper basis:
  AnomalyRuler (ECCV 2024, arXiv:2407.10299): +26.2% accuracy with rule-constrained LLM.
  Unified Framework (NeurIPS 2025, arXiv:2511.00962): unrestricted reasoning increases FP.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("vad.anomaly_rules")

RULES_VERSION = "anomaly_rules_v1"

_VLM_TO_ANOMALY_EVENT: dict[str, set[str]] = {
    "fall_or_collapse":                     {"fall_detected"},
    "person_on_floor":                      {"fall_detected"},
    "physical_altercation":                 {"fight_detection"},
    "fighting":                             {"fight_detection"},
    "pushing_or_shoving":                   {"fight_detection"},
    "grappling_or_wrestling":               {"fight_detection"},
    "aggressive_contact":                   {"fight_detection"},
    "rapid_unusual_movement":               {"sudden_movement"},
    "suspicious_motion":                    {"intrusion", "loitering", "after_hours"},
    "possible_intrusion_or_security_event": {"intrusion", "after_hours", "unauthorized_access", "restricted_entry", "weapon", "weapon_detection", "theft", "stealing"},
    "unsafe_equipment_interaction":         {"other", "equipment", "unsafe_equipment_interaction"},
    "deep_semantic_spatiotemporal_anomaly": {"other"},
    "normal_activity":                      set(),
    "benign_object_movement":               set(),
    "benign_posture_change":                set(),
    "camera_or_detection_artifact":         set(),
    "unclear_visual_evidence":              set(),
}

_BENIGN_VLM_TYPES = {
    "normal_activity", "benign_object_movement",
    "benign_posture_change", "camera_or_detection_artifact",
}


def load_anomaly_rules(conn: Any) -> list[dict[str, Any]]:
    """Load all active rules from Anomaly_Rules. Never raises."""
    try:
        rows = conn.execute(
            """
            SELECT id, rule_text, rule_type, event_type, conditions, source, active
            FROM Anomaly_Rules
            WHERE active = TRUE
            ORDER BY id ASC
            """
        ).fetchall()
    except Exception as e:
        log.warning("Could not load Anomaly_Rules: %s", e)
        return []

    rules: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row) if hasattr(row, "keys") else {
            "id": row[0], "rule_text": row[1], "rule_type": row[2],
            "event_type": row[3], "conditions": row[4],
            "source": row[5], "active": row[6],
        }
        rule_type  = str(r.get("rule_type") or "trigger").strip().lower()
        if rule_type in {"alert", "detect", "detection", "positive", "trigger_rule"}:
            rule_type = "trigger"
        elif rule_type in {"ignore", "benign", "normal", "negative", "suppress_rule"}:
            rule_type = "suppress"
        elif rule_type not in {"trigger", "suppress"}:
            rule_type = "trigger"
        conditions = r.get("conditions") or {}
        if not isinstance(conditions, dict):
            conditions = {}

        # Build effect — suppress rules need this or they silently do nothing
        if rule_type == "suppress":
            effect = {
                "policy_alert_decision": "NO",
                "policy_severity": "NONE",
                "recommended_action": "ignore",
            }
        else:
            effect = {
                "minimum_severity": "MEDIUM",
                "recommended_action": "alert_operator",
            }

        event_type = r.get("event_type") or "other"
        rules.append({
            "id":          f"anomaly_rule_{r.get('id')}",
            "rule_id":     f"anomaly_rule_{r.get('id')}",
            "rule_name":   r.get("rule_text") or "",
            "rule_type":   rule_type,
            "event_type":  event_type,
            "event_types": [event_type],
            "conditions":  conditions,
            "description": r.get("rule_text") or "",
            "effect":      effect,
            "active":      True,
            "source":      r.get("source") or "admin",
        })

    log.info("Loaded %d active rules from Anomaly_Rules", len(rules))
    return rules


# Stubs — keep imports in reasoning_policy.py working without changes
def load_active_vad_rules(db: Any, conn: Any) -> list[dict[str, Any]]:
    """No-op — vad_reasoning_rules table is unused."""
    return []


def serialize_rules_for_llm(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """No-op — Anomaly_Rules rows are already in the correct format."""
    return rules


def _location_matches(rule_location: str | None, scene_key: str | None) -> bool:
    loc = str(rule_location or "").strip().lower()
    if not loc or loc in {"all", "any", "anywhere", ""}:
        return True
    scene = str(scene_key or "").strip().lower()
    if not scene:
        return True
    return loc in scene or scene in loc


def _event_type_matches(rule_event_type: str, vlm_event_type: str) -> bool:
    rule_et = str(rule_event_type or "").strip().lower()
    vlm_et  = str(vlm_event_type  or "").strip().lower()
    if not rule_et or rule_et == "other":
        return vlm_et not in {e.lower() for e in _BENIGN_VLM_TYPES}
    if rule_et == vlm_et:
        return True
    return rule_et in _VLM_TO_ANOMALY_EVENT.get(vlm_et, set())


_STOPWORDS = {
    "a", "an", "the", "if", "is", "are", "was", "were", "be", "being", "been",
    "person", "people", "someone", "subject", "there", "visible", "video", "frame",
    "scene", "alert", "notify", "tell", "me", "when", "with", "and", "or", "to",
    "in", "on", "near", "at", "from", "of", "for", "any", "all", "rule",
}

def _tokenize_keywords(text: Any) -> set[str]:
    import re
    words = re.findall(r"[a-zA-Z_]{3,}", str(text or "").lower())
    return {w for w in words if w not in _STOPWORDS}

def _rule_text_matches_visual(rule: dict[str, Any], evidence_text: str) -> bool:
    rule_text = " ".join(str(rule.get(k) or "") for k in ("rule_name", "description", "event_type"))
    rule_tokens = _tokenize_keywords(rule_text)
    if not rule_tokens:
        return False
    visual_tokens = _tokenize_keywords(evidence_text)
    if not visual_tokens:
        return False
    # Any high-signal token overlap is enough for admin rules like weapon/fall/fight/intrusion.
    # This avoids treating event_type='other' as a universal match.
    return bool(rule_tokens & visual_tokens)

def deterministic_rule_matches(
    *,
    ctx: Any,
    vlm: Any,
    rules: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Python-side rule verification — no LLM. (AnomalyRuler, ECCV 2024)"""
    vlm_event_type   = str(getattr(vlm, "event_type", "") or "")
    anomaly_evidence = list(getattr(vlm, "anomaly_evidence", []) or [])
    visual_decision  = str(getattr(vlm, "visual_alert_decision", "UNCERTAIN") or "UNCERTAIN")
    image_quality    = str(getattr(vlm, "image_quality", "FAIR") or "FAIR")

    if image_quality == "UNUSABLE":
        return {"matched_trigger_rules": [], "matched_suppress_rules": []}

    scene_key: str | None = None
    for attr in ("stream_key", "camera_key"):
        val = getattr(ctx, attr, None)
        if val:
            scene_key = str(val)
            break

    matched_triggers: list[dict[str, Any]] = []
    matched_suppress: list[dict[str, Any]] = []

    for rule in rules:
        if rule.get("active") is False:
            continue

        rule_type  = str(rule.get("rule_type") or "trigger").lower()
        rule_id    = str(rule.get("rule_id") or rule.get("id") or "?")
        conditions = rule.get("conditions") or {}

        if not _location_matches(conditions.get("location"), scene_key):
            continue

        rule_et     = str(rule.get("event_type") or "").strip().lower()
        event_types = [str(e).lower() for e in (rule.get("event_types") or []) if e]
        all_ets     = list({rule_et} | set(event_types)) if rule_et else event_types
        evidence_text = " ".join(anomaly_evidence + [getattr(vlm, "person_observation", ""), getattr(vlm, "motion_observation", "")])
        event_match = bool(all_ets and any(_event_type_matches(et, vlm_event_type) for et in all_ets))
        text_match = _rule_text_matches_visual(rule, evidence_text)
        if not (event_match or text_match):
            continue

        match_entry = {
            "rule_id":    rule_id,
            "rule_name":  rule.get("rule_name") or rule.get("description") or "",
            "rule_type":  rule_type,
            "event_type": rule.get("event_type") or "",
            "conditions": conditions,
            "effect":     rule.get("effect") or {},
            "reason": (
                f"Python match: VLM event_type='{vlm_event_type}' matched "
                f"rule '{rule_id}' (event='{rule.get('event_type')}') "
                f"with {len(anomaly_evidence)} evidence item(s)."
            ),
            "applied": True,
            "source":  rule.get("source") or "admin",
        }

        if rule_type == "trigger":
            if anomaly_evidence and visual_decision in {"YES", "UNCERTAIN"}:
                matched_triggers.append(match_entry)
        elif rule_type == "suppress":
            matched_suppress.append(match_entry)

    log.debug(
        "Deterministic match: vlm_event=%s triggers=%d suppress=%d",
        vlm_event_type, len(matched_triggers), len(matched_suppress),
    )
    return {
        "matched_trigger_rules":  matched_triggers,
        "matched_suppress_rules": matched_suppress,
    }