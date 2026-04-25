from db import get_all_active_rules
from llm_service import _llm_same_subject

def normalize_text(text: str) -> str:
    return " ".join((text or "").lower().strip().split())

def check_conflicts_preview(new_parsed: dict, exclude_rule_id: int = None) -> list[dict]:
    """
    Conflict detection with minimal LLM dependency.
    Uses deterministic logic for structured event types.
    Only calls LLM for the ambiguous 'other' event type bucket.
    """
    rows = get_all_active_rules()

    new_rule_type = new_parsed.get("rule_type")
    new_event_type = new_parsed.get("event_type")
    new_location = (new_parsed.get("conditions") or {}).get("location", "All")

    confirmed = []
    for row in rows:
        rule_id = row[0]
        if exclude_rule_id and rule_id == exclude_rule_id:
            continue

        ex_rule_type = row[2]
        ex_event_type = row[3]
        ex_conditions = row[4] or {}
        ex_location = ex_conditions.get("location", "All")

        # ── Filter 1: structured events with same intent → no conflict ──
        # If they are standard events (not "other") and have the same intent, they do not conflict.
        # But if one is "other", we must check for semantic overlap or contradiction.
        if ex_rule_type == new_rule_type and ex_event_type != "other" and new_event_type != "other":
            continue

        # ── Filter 2: different event_type → usually no conflict ──
        # EXCEPT: if one of them is "other", it might semantically overlap with anything.
        if ex_event_type != new_event_type and ex_event_type != "other" and new_event_type != "other":
            continue

        # ── Filter 3: locations must overlap ──
        locations_overlap = (
            new_location == "All"
            or ex_location == "All"
            or new_location.lower().strip() == ex_location.lower().strip()
        )
        if not locations_overlap:
            continue

        # At this point: opposite intent OR (same intent but "other" event), overlapping location
        candidate = {
            "rule_id":          row[0],
            "rule_text":        row[1],
            "rule_type":        ex_rule_type,
            "event_type":       ex_event_type,
            "conditions":       ex_conditions,
            "location":         ex_location,
            "has_type_conflict": True,
            "shared_keywords":  [],
        }

        if new_event_type != "other" and ex_event_type != "other":
            # ── Both are standard structured event types (e.g. intrusion vs intrusion) ──
            # They must have opposite intents to reach here (due to Filter 1).
            # No LLM needed — the structured data is unambiguous.
            candidate["llm_reason"] = (
                f"Opposite intents for same event ({ex_event_type}) "
                f"in overlapping location"
            )
            confirmed.append(candidate)
        else:
            # ── At least one is "other" event type (catch-all) ──
            # We must check if their semantic meaning overlaps (e.g., drinks/food vs drinking)
            is_same, reason = _llm_same_subject(new_parsed, candidate)
            if is_same:
                if ex_rule_type != new_rule_type:
                    candidate["llm_reason"] = reason
                else:
                    candidate["llm_reason"] = f"Contradictory or overlapping conditions: {reason}"
                confirmed.append(candidate)

    return confirmed

def check_duplicate_active_rule(new_parsed: dict) -> dict | None:
    new_text = normalize_text(new_parsed.get("rule_text", ""))
    new_type = new_parsed.get("rule_type")
    new_event = new_parsed.get("event_type")
    new_location = ((new_parsed.get("conditions") or {}).get("location") or "All").lower().strip()

    rows = get_all_active_rules()

    for row in rows:
        ex_location = ((row[4] or {}).get("location") or "All").lower().strip()

        if (
            normalize_text(row[1]) == new_text
            and row[2] == new_type
            and row[3] == new_event
            and ex_location == new_location
        ):
            return {
                "rule_id": row[0],
                "rule_text": row[1],
                "rule_type": row[2],
                "event_type": row[3],
                "conditions": row[4],
                "reason": "Duplicate active rule"
            }

    return None
