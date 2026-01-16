CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Departments
CREATE TABLE departments (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- 2. Labs
CREATE TABLE labs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- 3. Schedules
CREATE TABLE schedules (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    access_start_time TIME,
    access_end_time TIME,
    applies_to_weekdays BOOLEAN DEFAULT FALSE,
    applies_to_weekends BOOLEAN DEFAULT FALSE,
    specific_dates DATE[]
);

-- 4. Anomalies (Definitions)
CREATE TABLE anomalies (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    description TEXT,
    severity_level TEXT
);

-- 5. Visitors
CREATE TABLE visitors (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    visit_date DATE,
    purpose TEXT,
    contact_info TEXT
);

-- 6. Employees
CREATE TABLE employees (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    department_id BIGINT REFERENCES departments(id)
);

-- 7. Cameras
CREATE TABLE cameras (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT,
    location TEXT,
    lab_id BIGINT REFERENCES labs(id)
);

-- 8. Detected People
CREATE TABLE detected_people (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT,
    additional_info TEXT,
    employee_id BIGINT REFERENCES employees(id),
    visitor BOOLEAN DEFAULT FALSE,
    visitor_id BIGINT REFERENCES visitors(id)
);

-- 9. Department Lab Access
CREATE TABLE department_lab_access (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    department_id BIGINT REFERENCES departments(id),
    lab_id BIGINT REFERENCES labs(id),
    schedule_id BIGINT REFERENCES schedules(id)
);

-- 10. Employee Lab Access
CREATE TABLE employee_lab_access (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    employee_id BIGINT REFERENCES employees(id),
    lab_id BIGINT REFERENCES labs(id),
    schedule_id BIGINT REFERENCES schedules(id)
);

-- 11. Entry Logs
CREATE TABLE entry_logs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp" TIMESTAMPTZ DEFAULT now(),
    detected_id BIGINT REFERENCES detected_people(id),
    camera_id BIGINT REFERENCES cameras(id),
    authorized BOOLEAN,
    event_type TEXT,
    location TEXT,
    device_status TEXT,
    image_video_ref TEXT,
    processing_time INTERVAL,
    model_version TEXT
);

-- 12. Anomalies Logs
CREATE TABLE anomalies_logs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp" TIMESTAMPTZ DEFAULT now(),
    detected_id BIGINT REFERENCES detected_people(id),
    camera_id BIGINT REFERENCES cameras(id),
    anomaly_id BIGINT REFERENCES anomalies(id)
);

-- 13. View
CREATE OR REPLACE VIEW anomalies_logs_view AS
SELECT
    al.id,
    al."timestamp",
    al.detected_id,
    al.camera_id,
    a.description,
    a.severity_level
FROM
    anomalies_logs al
    JOIN anomalies a ON al.anomaly_id = a.id;


-- Face embeddings linked to identities (detected_people)
CREATE TABLE face_embeddings (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    detected_id BIGINT NOT NULL REFERENCES detected_people(id) ON DELETE CASCADE,
    entry_log_id BIGINT NULL REFERENCES entry_logs(id) ON DELETE SET NULL,

    embedding vector(512) NOT NULL,

    embedding_model TEXT NOT NULL DEFAULT 'unknown',
    is_authoritative BOOLEAN NOT NULL DEFAULT FALSE,
    quality_score REAL NULL,
    match_confidence REAL NULL,
    notes TEXT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);




CREATE INDEX face_embeddings_embedding_hnsw_cosine
ON face_embeddings
USING hnsw (embedding vector_cosine_ops);     

CREATE INDEX face_embeddings_detected_id_idx
ON face_embeddings (detected_id);

CREATE INDEX face_embeddings_entry_log_id_idx
ON face_embeddings (entry_log_id);

CREATE INDEX face_embeddings_authoritative_idx
ON face_embeddings (detected_id)
WHERE is_authoritative = TRUE;

-- Speeds up auto-learn cooldown checks
CREATE INDEX face_embeddings_autolearn_idx
ON face_embeddings (detected_id, created_at)
WHERE notes = 'auto_learned';


CREATE TABLE unknown_face_events (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    entry_log_id BIGINT NOT NULL REFERENCES entry_logs(id) ON DELETE CASCADE,

    embedding vector(512) NOT NULL,     -- normalized
    embedding_model TEXT NOT NULL DEFAULT 'unknown',

    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','assigned','discarded')),

    assigned_detected_id BIGINT NULL REFERENCES detected_people(id) ON DELETE SET NULL,

    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX unknown_face_events_status_idx ON unknown_face_events(status);

CREATE INDEX unknown_face_events_embedding_hnsw_cosine
ON unknown_face_events USING hnsw (embedding vector_cosine_ops);

