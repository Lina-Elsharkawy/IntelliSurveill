"""
Current deterministic chatbot tool capabilities.

This file is intentionally kept in sync with tools.TOOL_MAP and the real
PostgreSQL schema used by current_schema(5).sql. It contains no legacy
references to removed tables such as activity_logs, anomaly_candidates,
ollama_jobs, labs, or departments.
"""

CURRENT_TOOL_CAPABILITIES = {
    # Face / person tracking
    "person_last_seen": {"required": ["name"], "optional": ["target_date"], "tables": ["entry_logs", "detected_people", "employees", "visitors", "cameras"]},
    "person_first_seen": {"required": ["name"], "optional": ["target_date"], "tables": ["entry_logs", "detected_people", "employees", "visitors", "cameras"]},
    "person_timeline": {"required": ["name"], "optional": ["target_date"], "tables": ["entry_logs", "detected_people", "employees", "visitors", "cameras"]},
    "people_seen_on_date": {"required": [], "optional": ["target_date"], "tables": ["entry_logs", "detected_people", "employees", "visitors", "cameras"]},
    "known_people": {"required": [], "optional": ["limit"], "tables": ["employees", "visitors", "detected_people"]},

    # Counts
    "count_unknown_detections": {"required": [], "optional": ["target_date", "days_back", "hour"], "tables": ["unknown_face_events"]},
    "count_known_detections": {"required": [], "optional": ["target_date", "days_back", "hour"], "tables": ["entry_logs", "detected_people"]},
    "count_all_detections": {"required": [], "optional": ["target_date", "days_back", "hour"], "tables": ["entry_logs"]},

    # Unknown face investigation
    "unknown_face_events": {"required": [], "optional": ["status", "target_date", "days_back", "hour", "limit"], "tables": ["unknown_face_events", "entry_logs", "cameras"]},
    "unknown_face_details": {"required": ["event_id"], "optional": [], "tables": ["unknown_face_events", "entry_logs", "cameras"]},
    "similar_unknown_faces": {"required": ["event_id"], "optional": ["threshold", "limit"], "tables": ["unknown_face_events", "entry_logs", "cameras"]},
    "possible_identity_match": {"required": ["event_id"], "optional": ["threshold", "limit"], "tables": ["unknown_face_events", "face_embeddings", "detected_people", "employees", "visitors"]},
    "investigate_unknown_face": {"required": ["event_id"], "optional": [], "tables": ["unknown_face_events", "face_embeddings", "entry_logs", "detected_people", "employees", "visitors", "cameras"]},

    # VAD pipeline
    "vad_cases": {"required": [], "optional": ["status", "severity", "days_back", "camera_id", "limit"], "tables": ["vad_anomaly_cases", "cameras"]},
    "vad_case_details": {"required": ["case_id"], "optional": [], "tables": ["vad_anomaly_cases", "vad_reasoning_results", "cameras"]},
    "vad_gate_events": {"required": [], "optional": ["severity", "status", "camera_id", "days_back", "limit"], "tables": ["vad_gate_events", "cameras"]},
    "vad_reasoning_jobs": {"required": [], "optional": ["status", "limit"], "tables": ["vad_reasoning_jobs"]},
    "vad_reasoning_results": {"required": [], "optional": ["case_id", "alert_decision", "severity", "limit"], "tables": ["vad_reasoning_results"]},
    "vad_case_reviews": {"required": [], "optional": ["decision", "limit"], "tables": ["vad_case_reviews"]},
    "vad_case_gate_events": {"required": ["case_id"], "optional": ["limit"], "tables": ["vad_case_gate_events", "vad_gate_events", "cameras"]},
    "vad_case_evidence": {"required": ["case_id"], "optional": ["limit"], "tables": ["vad_evidence_items", "vad_media_objects"]},
    "vad_gate_scores": {"required": [], "optional": ["case_id", "gate_name", "days_back", "limit"], "tables": ["vad_gate_scores", "vad_gate_events", "vad_case_gate_events"]},
    "vad_streams": {"required": [], "optional": ["is_active", "limit"], "tables": ["vad_streams", "cameras"]},
    "vad_stream_sessions": {"required": [], "optional": ["status", "limit"], "tables": ["vad_stream_sessions", "cameras"]},

    # Admin / system
    "cameras": {"required": [], "optional": ["limit"], "tables": ["cameras"]},
    "edge_devices": {"required": [], "optional": ["limit"], "tables": ["edge_devices"]},
    "anomaly_rules": {"required": [], "optional": ["is_active", "rule_type", "limit"], "tables": ["anomaly_rules"]},
    "reasoning_rules": {"required": [], "optional": ["is_active", "rule_type", "limit"], "tables": ["vad_reasoning_rules"]},
    "rule_conflicts": {"required": [], "optional": ["status", "limit"], "tables": ["rule_conflicts"]},
    "schedules": {"required": [], "optional": ["limit"], "tables": ["schedules"]},
    "audit_logs": {"required": [], "optional": ["limit"], "tables": ["audit_logs"]},

    # Meta
    "table_counts": {"required": [], "optional": [], "tables": ["information_schema.tables"]},
    "daily_summary": {"required": [], "optional": ["target_date"], "tables": ["entry_logs", "unknown_face_events", "vad_anomaly_cases", "vad_reasoning_jobs"]},
    "camera_activity": {"required": [], "optional": ["target_date", "days_back", "limit"], "tables": ["entry_logs", "cameras"]},
}

COMMON_ALIASES = {
    "activity_logs": "audit_logs",
    "user_actions": "audit_logs",
    "unknown_detections_count": "count_unknown_detections",
    "known_detections_count": "count_known_detections",
    "detection_count": "count_all_detections",
}
