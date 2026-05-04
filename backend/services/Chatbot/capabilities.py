"""
Capability contract for the Surveillance Investigation Chatbot.

LangGraph should orchestrate these trusted capabilities first. Generic NL-to-SQL
is kept only as a fallback for low-risk database exploration.
"""
from __future__ import annotations

SUPPORTED_INTENTS: dict[str, dict] = {
    # People / entry-log investigations
    "person_last_seen": {
        "tool": "person_last_seen",
        "tool_type": "normal",
        "required_params": ["name"],
        "description": "Most recent detection of a named person.",
    },
    "person_first_seen": {
        "tool": "person_first_seen",
        "tool_type": "normal",
        "required_params": ["name"],
        "description": "Earliest detection of a named person.",
    },
    "person_timeline": {
        "tool": "person_timeline",
        "tool_type": "normal",
        "required_params": ["name"],
        "description": "Movement timeline for a named person on a date.",
    },
    "people_seen_on_date": {
        "tool": "people_seen_on_date",
        "tool_type": "normal",
        "required_params": ["target_date"],
        "description": "People detected on a specific date.",
    },

    # Unknown-face investigations

    "unknown_detection_count": {
        "tool": "unknown_detection_count",
        "tool_type": "normal",
        "required_params": [],
        "description": "Count unknown face detections/events for a date and optional hour.",
    },
    "known_face_detection_count": {
        "tool": "known_face_detection_count",
        "tool_type": "normal",
        "required_params": [],
        "description": "Count known face detections for a date and optional hour.",
    },
    "face_detection_count": {
        "tool": "face_detection_count",
        "tool_type": "normal",
        "required_params": [],
        "description": "Count all face/person detections for a date and optional hour.",
    },

    "latest_unknown_face_events": {
        "tool": "latest_unknown_face_events",
        "tool_type": "normal",
        "required_params": [],
        "description": "Latest rows from unknown_face_events.",
    },
    "unknown_face_event_details": {
        "tool": "unknown_face_event_details",
        "tool_type": "normal",
        "required_params": ["event_id"],
        "description": "Details for one unknown face event.",
    },
    "repeated_unknown_faces": {
        "tool": "repeated_unknown_faces",
        "tool_type": "normal",
        "required_params": [],
        "description": "Repeated unknown visitors using existing event/log data.",
    },

    # Vector / pgvector investigations
    "similar_unknown_faces": {
        "tool": "similar_unknown_faces",
        "tool_type": "vector",
        "required_params": ["event_id"],
        "description": "Find visually similar unknown faces for an event.",
    },
    "possible_identity_match": {
        "tool": "possible_identity_match",
        "tool_type": "vector",
        "required_params": ["event_id"],
        "description": "Find closest known identities for an unknown face event.",
    },
    "investigate_unknown_face_event": {
        "tool": "investigate_unknown_face_event",
        "tool_type": "vector",
        "required_params": ["event_id"],
        "description": "Complete investigation for an unknown face event.",
    },

    # Anomaly investigations
    "latest_anomalies": {
        "tool": "latest_anomalies",
        "tool_type": "normal",
        "required_params": [],
        "description": "Latest anomaly log entries.",
    },
    "anomalies_near_person": {
        "tool": "anomalies_near_person",
        "tool_type": "normal",
        "required_params": ["name"],
        "description": "Anomalies near the latest detection of a named person.",
    },
    "anomalies_near_unknown_event": {
        "tool": "anomalies_near_unknown_event",
        "tool_type": "normal",
        "required_params": ["event_id"],
        "description": "Anomalies near an unknown-face event timestamp/camera.",
    },

    # Registry lookups
    "all_known_people": {
        "tool": "all_known_people",
        "tool_type": "normal",
        "required_params": [],
        "description": "List all known people (employees + visitors) from the registry.",
    },

    # Summaries / metadata
    "camera_activity_summary": {
        "tool": "camera_activity_summary",
        "tool_type": "normal",
        "required_params": [],
        "description": "Detection counts grouped by camera.",
    },
    "daily_security_summary": {
        "tool": "daily_security_summary",
        "tool_type": "normal",
        "required_params": ["target_date"],
        "description": "Daily counts for detections, unknowns, and anomalies.",
    },
    "table_record_counts": {
        "tool": "table_record_counts",
        "tool_type": "normal",
        "required_params": [],
        "description": "Record counts for all public database tables.",
    },

    # New Admin / System Tables
    "anomaly_candidates": {
        "tool": "anomaly_candidates",
        "tool_type": "normal",
        "required_params": [],
        "description": "Pending and reviewed anomaly candidates.",
    },
    "anomaly_candidate_review": {
        "tool": "anomaly_candidate_review",
        "tool_type": "normal",
        "required_params": [],
        "description": "Decisions on anomaly candidates.",
    },
    "ollama_jobs": {
        "tool": "ollama_jobs",
        "tool_type": "normal",
        "required_params": [],
        "description": "Ollama background job queue status.",
    },
    "scene_window_embeddings": {
        "tool": "scene_window_embeddings",
        "tool_type": "normal",
        "required_params": [],
        "description": "Camera scene windows flagged as anomalous.",
    },
    "anomaly_rules": {
        "tool": "anomaly_rules",
        "tool_type": "normal",
        "required_params": [],
        "description": "Active intrusion/anomaly rules.",
    },
    "edge_devices": {
        "tool": "edge_devices",
        "tool_type": "normal",
        "required_params": [],
        "description": "Registered edge devices.",
    },
    "normal_behavior_models": {
        "tool": "normal_behavior_models",
        "tool_type": "normal",
        "required_params": [],
        "description": "Active normal behavior models.",
    },
    "rule_conflicts": {
        "tool": "rule_conflicts",
        "tool_type": "normal",
        "required_params": [],
        "description": "Pending rule conflicts.",
    },

    # Non-tool routes
    "small_talk": {
        "tool": None,
        "tool_type": "small_talk",
        "required_params": [],
        "description": "Greeting/help/general chatbot text.",
    },
    "sql_fallback": {
        "tool": None,
        "tool_type": "sql",
        "required_params": [],
        "description": "Low-risk read-only database exploration fallback.",
    },
}

INTENT_ALIASES = {
    "list_known_people": "all_known_people",
    "list_employees": "all_known_people",
    "list_visitors": "all_known_people",
    "known_people": "all_known_people",
    # Backward compatibility with older tool names
    "last_seen": "person_last_seen",
    "first_seen": "person_first_seen",
    "timeline": "person_timeline",
    "unknown_face_events": "latest_unknown_face_events",
    "unknown_detections_count": "unknown_detection_count",
    "known_detections_count": "known_face_detection_count",
    "known_faces_count": "known_face_detection_count",
    "detection_count": "face_detection_count",
    "unknown_faces": "latest_unknown_face_events",
    "repeated_unknowns": "repeated_unknown_faces",
    "anomalies_near_face": "anomalies_near_person",
    "people_seen_today": "people_seen_on_date",
    "sql": "sql_fallback",
}


def canonical_intent(intent: str | None) -> str:
    value = (intent or "sql_fallback").strip()
    value = INTENT_ALIASES.get(value, value)
    if value not in SUPPORTED_INTENTS:
        return "sql_fallback"
    return value


def required_params(intent: str) -> list[str]:
    return list(SUPPORTED_INTENTS[canonical_intent(intent)].get("required_params", []))


def tool_type(intent: str) -> str:
    return str(SUPPORTED_INTENTS[canonical_intent(intent)].get("tool_type", "sql"))


def tool_name(intent: str) -> str | None:
    return SUPPORTED_INTENTS[canonical_intent(intent)].get("tool")