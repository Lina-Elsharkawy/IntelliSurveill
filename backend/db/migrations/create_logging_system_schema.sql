CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- Clean Logging System Schema
-- Legacy VAD/anomaly-learning tables removed.
--
-- Removed legacy tables:
-- departments, labs, anomalies, department_lab_access,
-- employee_lab_access, anomalies_logs, normal_behavior_models,
-- normal_behavior_model_artifacts, anomaly_gate_configs,
-- anomaly_thresholds, scene_window_embeddings,
-- anomaly_candidates, candidate_gate_decisions,
-- reasoning_jobs, ollama_jobs,
-- anomaly_candidate_review, anomaly_candidate_feedback.
--
-- NOTE:
-- employees.department_id and cameras.lab_id are kept as plain BIGINT
-- columns for application compatibility, but their foreign keys were removed
-- because departments/labs are no longer part of this schema.
-- ============================================

-- ============================================
-- 1. Schedules
-- ============================================
CREATE TABLE IF NOT EXISTS schedules (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name                 TEXT NOT NULL,
    access_start_time    TIME,
    access_end_time      TIME,
    applies_to_weekdays  BOOLEAN DEFAULT FALSE,
    applies_to_weekends  BOOLEAN DEFAULT FALSE,
    specific_dates       DATE[]
);

-- ============================================
-- 2. Visitors
-- ============================================
CREATE TABLE IF NOT EXISTS visitors (
    id           BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name         TEXT NOT NULL,
    visit_date   DATE,
    purpose      TEXT,
    contact_info TEXT
);

-- ============================================
-- 3. Employees
-- ============================================
CREATE TABLE IF NOT EXISTS employees (
    id            BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name          TEXT NOT NULL,
    department_id BIGINT NULL
);

-- ============================================
-- 4. Cameras
-- ============================================
CREATE TABLE IF NOT EXISTS cameras (
    id       BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name     TEXT,
    location TEXT,
    lab_id   BIGINT NULL
);

-- ============================================
-- 5. Detected People
-- ============================================
CREATE TABLE IF NOT EXISTS detected_people (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name            TEXT,
    additional_info TEXT,
    employee_id     BIGINT REFERENCES employees(id),
    visitor         BOOLEAN DEFAULT FALSE,
    visitor_id      BIGINT REFERENCES visitors(id)
);

-- ============================================
-- 6. Entry Logs
-- ============================================
CREATE TABLE IF NOT EXISTS entry_logs (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp"     TIMESTAMPTZ DEFAULT now(),
    detected_id     BIGINT REFERENCES detected_people(id),
    camera_id       BIGINT REFERENCES cameras(id),
    authorized      BOOLEAN,
    event_type      TEXT,
    location        TEXT,
    device_status   TEXT,
    image_video_ref TEXT,
    processing_time INTERVAL,
    model_version   TEXT
);

-- ============================================
-- 7. Face Embeddings
-- ============================================
CREATE TABLE IF NOT EXISTS face_embeddings (
    id               BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    detected_id      BIGINT NOT NULL REFERENCES detected_people(id) ON DELETE CASCADE,
    entry_log_id     BIGINT NULL REFERENCES entry_logs(id) ON DELETE SET NULL,
    embedding        vector(512) NOT NULL,
    embedding_model  TEXT NOT NULL DEFAULT 'unknown',
    is_authoritative BOOLEAN NOT NULL DEFAULT FALSE,
    quality_score    REAL NULL,
    match_confidence REAL NULL,
    notes            TEXT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS face_embeddings_embedding_hnsw_cosine
ON face_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS face_embeddings_detected_id_idx
ON face_embeddings (detected_id);

CREATE INDEX IF NOT EXISTS face_embeddings_entry_log_id_idx
ON face_embeddings (entry_log_id);

CREATE INDEX IF NOT EXISTS face_embeddings_authoritative_idx
ON face_embeddings (detected_id)
WHERE is_authoritative = TRUE;

CREATE INDEX IF NOT EXISTS face_embeddings_autolearn_idx
ON face_embeddings (detected_id, created_at)
WHERE notes = 'auto_learned';

-- ============================================
-- 8. Unknown Face Events
-- ============================================
CREATE TABLE IF NOT EXISTS unknown_face_events (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    entry_log_id         BIGINT NOT NULL REFERENCES entry_logs(id) ON DELETE CASCADE,
    embedding            vector(512) NOT NULL,
    embedding_model      TEXT NOT NULL DEFAULT 'unknown',
    status               TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending','assigned','discarded')),
    assigned_detected_id BIGINT NULL REFERENCES detected_people(id) ON DELETE SET NULL,
    notes                TEXT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS unknown_face_events_status_idx
ON unknown_face_events (status);

CREATE INDEX IF NOT EXISTS unknown_face_events_embedding_hnsw_cosine
ON unknown_face_events USING hnsw (embedding vector_cosine_ops);

-- ============================================
-- 9. Edge Device Registry
-- ============================================
CREATE TABLE IF NOT EXISTS edge_devices (
    id         BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    device_key TEXT NOT NULL UNIQUE,
    name       TEXT NULL,
    location   TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS edge_devices_device_key_idx
ON edge_devices (device_key);

-- ============================================
-- 10. Anomaly Rules
-- Current rule-management table retained.
-- ============================================
CREATE TABLE IF NOT EXISTS anomaly_rules (
    id          BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    rule_text   TEXT NOT NULL,
    rule_type   VARCHAR(20) NOT NULL CHECK (rule_type IN ('trigger','suppress')),
    event_type  VARCHAR(50) NOT NULL CHECK (
        event_type IN (
            'intrusion',
            'loitering',
            'after_hours',
            'fall_detected',
            'fight_detection',
            'camera_tamper',
            'sudden_movement',
            'smoke_fire',
            'crowd_detection',
            'other'
        )
    ),
    conditions  JSONB NOT NULL,
    source      VARCHAR(50) NOT NULL CHECK (source IN ('Admin','Learned')),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS anomaly_rules_active_idx
ON anomaly_rules (active);

CREATE INDEX IF NOT EXISTS anomaly_rules_event_type_idx
ON anomaly_rules (event_type);

CREATE INDEX IF NOT EXISTS anomaly_rules_created_idx
ON anomaly_rules (created_at DESC);

-- ============================================
-- 11. Rule Conflicts
-- ============================================
CREATE TABLE IF NOT EXISTS rule_conflicts (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    rule_id_1       VARCHAR,
    rule_id_2       VARCHAR,
    conflict_reason TEXT,
    status          VARCHAR DEFAULT 'pending', -- pending, resolved, ignored
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rule_conflicts_status_idx
ON rule_conflicts (status);

CREATE INDEX IF NOT EXISTS rule_conflicts_created_idx
ON rule_conflicts (created_at DESC);

-- ============================================
-- 12. Audit Logs
-- Tracks all user-driven actions in the system.
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id           BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_email   TEXT NOT NULL,
    action       TEXT NOT NULL,        -- e.g. 'CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'LOGOUT'
    resource     TEXT,                 -- e.g. 'camera', 'employee', 'rule'
    resource_id  TEXT,                 -- stringified ID of the affected entity, nullable for login/logout
    details      JSONB,                -- arbitrary context: old/new values, extra info
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_logs_user_idx
ON audit_logs (user_email);

CREATE INDEX IF NOT EXISTS audit_logs_action_idx
ON audit_logs (action);

CREATE INDEX IF NOT EXISTS audit_logs_resource_idx
ON audit_logs (resource);

CREATE INDEX IF NOT EXISTS audit_logs_created_idx
ON audit_logs (created_at DESC);
