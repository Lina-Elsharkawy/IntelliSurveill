CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- 1. Departments
-- ============================================
CREATE TABLE IF NOT EXISTS departments (
    id   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- ============================================
-- 2. Labs
-- ============================================
CREATE TABLE IF NOT EXISTS labs (
    id   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- ============================================
-- 3. Schedules
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
-- 4. Anomaly Definitions
-- ============================================
CREATE TABLE IF NOT EXISTS anomalies (
    id             BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    description    TEXT,
    severity_level TEXT
);

-- ============================================
-- 5. Visitors
-- ============================================
CREATE TABLE IF NOT EXISTS visitors (
    id           BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name         TEXT NOT NULL,
    visit_date   DATE,
    purpose      TEXT,
    contact_info TEXT
);

-- ============================================
-- 6. Employees
-- ============================================
CREATE TABLE IF NOT EXISTS employees (
    id            BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name          TEXT NOT NULL,
    department_id BIGINT REFERENCES departments(id)
);

-- ============================================
-- 7. Cameras
-- ============================================
CREATE TABLE IF NOT EXISTS cameras (
    id       BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name     TEXT,
    location TEXT,
    lab_id   BIGINT REFERENCES labs(id)
);

-- ============================================
-- 8. Detected People
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
-- 9. Department Lab Access
-- ============================================
CREATE TABLE IF NOT EXISTS department_lab_access (
    id            BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    department_id BIGINT REFERENCES departments(id),
    lab_id        BIGINT REFERENCES labs(id),
    schedule_id   BIGINT REFERENCES schedules(id)
);

-- ============================================
-- 10. Employee Lab Access
-- ============================================
CREATE TABLE IF NOT EXISTS employee_lab_access (
    id          BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    employee_id BIGINT REFERENCES employees(id),
    lab_id      BIGINT REFERENCES labs(id),
    schedule_id BIGINT REFERENCES schedules(id)
);

-- ============================================
-- 11. Entry Logs
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
-- 12. Anomalies Logs
-- ============================================
CREATE TABLE IF NOT EXISTS anomalies_logs (
    id          BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp" TIMESTAMPTZ DEFAULT now(),
    detected_id BIGINT REFERENCES detected_people(id),
    camera_id   BIGINT REFERENCES cameras(id),
    anomaly_id  BIGINT REFERENCES anomalies(id)
);

CREATE OR REPLACE VIEW anomalies_logs_view AS
SELECT
    al.id,
    al."timestamp",
    al.detected_id,
    al.camera_id,
    a.description,
    a.severity_level
FROM anomalies_logs al
JOIN anomalies a ON al.anomaly_id = a.id;

-- ============================================
-- 13. Face Embeddings
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
-- 14. Unknown Face Events
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
-- 15. Edge Device Registry
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
-- 16. Normal Behavior Model Registry
-- ============================================
CREATE TABLE IF NOT EXISTS normal_behavior_models (
    id             BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name           TEXT NOT NULL DEFAULT 'videomae_student_v3',
    version        TEXT NOT NULL,
    teacher_model  TEXT NOT NULL DEFAULT 'MCG-NJU/videomae-base',
    extract_layers TEXT NOT NULL DEFAULT '4,8,12',
    student_model  TEXT NOT NULL DEFAULT 'student-v3-multiscale',
    embedding_dim  INT  NOT NULL DEFAULT 2304,
    num_frames     INT  NOT NULL DEFAULT 16,
    window_stride  INT  NOT NULL DEFAULT 8,
    image_size     INT  NOT NULL DEFAULT 224,
    artifact_uri   TEXT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes          TEXT NULL,
    CONSTRAINT normal_behavior_models_embedding_dim_chk CHECK (embedding_dim > 0),
    CONSTRAINT normal_behavior_models_name_version_uniq UNIQUE (name, version)
);

-- Only one active model at a time
CREATE UNIQUE INDEX IF NOT EXISTS normal_behavior_models_one_active_idx
ON normal_behavior_models (is_active)
WHERE is_active = TRUE;

-- ============================================
-- 17. Anomaly Thresholds
--     p95 thresholds from offline val set scoring.
--     Stored here so the backend service can read
--     them without hardcoding.
-- ============================================
CREATE TABLE IF NOT EXISTS anomaly_thresholds (
    id                BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id          BIGINT NOT NULL REFERENCES normal_behavior_models(id) ON DELETE CASCADE,
    l2_p95            REAL NOT NULL,
    mse_p95           REAL NOT NULL,
    cos_p95           REAL NOT NULL,
    val_samples       INT  NOT NULL DEFAULT 0,
    min_metrics_agree INT  NOT NULL DEFAULT 2,
    min_consecutive   INT  NOT NULL DEFAULT 2,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes             TEXT NULL,
    CONSTRAINT anomaly_thresholds_model_uniq UNIQUE (model_id)
);

-- ============================================
-- 18. Scene Window Embeddings
--     One row per tubelet received from edge.
-- ============================================
CREATE TABLE IF NOT EXISTS scene_window_embeddings (
    id        BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id  BIGINT NOT NULL REFERENCES normal_behavior_models(id) ON DELETE RESTRICT,
    device_id BIGINT NULL     REFERENCES edge_devices(id)            ON DELETE SET NULL,
    camera_id BIGINT NULL     REFERENCES cameras(id)                 ON DELETE SET NULL,
    track_id  INT NULL,
    window_start_ts   TIMESTAMPTZ NOT NULL,
    window_end_ts     TIMESTAMPTZ NULL,
    event_key         TEXT NULL,
    student_embedding vector(2304) NOT NULL,
    teacher_embedding vector(2304) NULL,
    frames            TEXT[] NULL,
    l2_score          REAL NULL,
    mse_score         REAL NULL,
    cosine_distance   REAL NULL,
    l2_flag           BOOLEAN NULL,
    mse_flag          BOOLEAN NULL,
    cos_flag          BOOLEAN NULL,
    metrics_agreed    INT NULL,
    is_anomalous      BOOLEAN NULL,
    embedding_model   TEXT NOT NULL DEFAULT 'student-v3-multiscale',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT scene_window_embeddings_time_chk
        CHECK (window_end_ts IS NULL OR window_end_ts >= window_start_ts),
    CONSTRAINT scene_window_embeddings_scores_chk
        CHECK (
            (l2_score        IS NULL OR l2_score        >= 0) AND
            (mse_score       IS NULL OR mse_score        >= 0) AND
            (cosine_distance IS NULL OR cosine_distance  >= 0)
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS scene_window_embeddings_event_key_uniq
ON scene_window_embeddings (event_key)
WHERE event_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS scene_window_embeddings_ts_idx
ON scene_window_embeddings (window_start_ts);

CREATE INDEX IF NOT EXISTS scene_window_embeddings_model_idx
ON scene_window_embeddings (model_id);

CREATE INDEX IF NOT EXISTS scene_window_embeddings_camera_track_ts_idx
ON scene_window_embeddings (camera_id, track_id, window_start_ts);

CREATE INDEX IF NOT EXISTS scene_window_embeddings_anomalous_idx
ON scene_window_embeddings (camera_id, track_id, window_start_ts)
WHERE is_anomalous = TRUE;

-- ============================================
-- 19. Anomaly Candidates
--     Created when a window passes all filtering
--     stages and is sent to Ollama for reasoning.
-- ============================================
CREATE TABLE IF NOT EXISTS anomaly_candidates (
    id                        BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    scene_window_embedding_id BIGINT NOT NULL
        REFERENCES scene_window_embeddings(id) ON DELETE CASCADE,
    reason     TEXT NOT NULL DEFAULT 'student_teacher_l2_distance',
    status     TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','sent_to_llm','resolved','discarded','failed')),
    image_ref  TEXT NULL,
    video_ref  TEXT NULL,
    run_id     TEXT NULL,
    l2_score   REAL NULL,
    alert_decision TEXT NULL CHECK (alert_decision IN ('YES','NO')),
    severity   TEXT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH')),
    decision_reason TEXT NULL,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS anomaly_candidates_status_idx
ON anomaly_candidates (status);

CREATE INDEX IF NOT EXISTS anomaly_candidates_pending_idx
ON anomaly_candidates (created_at)
WHERE status = 'pending';

CREATE OR REPLACE FUNCTION anomaly_candidates_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_anomaly_candidates_updated ON anomaly_candidates;
CREATE TRIGGER trg_anomaly_candidates_updated
BEFORE UPDATE ON anomaly_candidates
FOR EACH ROW EXECUTE FUNCTION anomaly_candidates_set_updated_at();

-- ============================================
-- 20. Anomaly Rules
--     Natural language rules written by admins
--     during candidate review or proactively.
--     Injected into the LLM reasoning prompt so
--     the model evaluates future candidates
--     against admin-defined expectations.
--
--     anomaly_candidates must exist before this
--     table so source_candidate_id FK is valid.
-- ============================================
-- CREATE TABLE IF NOT EXISTS anomaly_rules (
--     id          BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

--     -- The rule itself — natural language
--     rule_text   TEXT NOT NULL,

--     -- Who wrote it and why (traceability)
--     reviewer    TEXT NULL,
--     source_candidate_id BIGINT NULL
--         REFERENCES anomaly_candidates(id) ON DELETE SET NULL,

--     -- Scope — NULL means global (applies everywhere)
--     camera_id   BIGINT NULL REFERENCES cameras(id) ON DELETE SET NULL,
--     lab_id      BIGINT NULL REFERENCES labs(id)    ON DELETE SET NULL,

--     -- Whether this rule describes anomalous OR normal behavior:
--     --   'anomalous' -> LLM should alert if this is seen
--     --   'normal'    -> LLM should NOT alert if this is seen
--     rule_type   TEXT NOT NULL DEFAULT 'anomalous'
--                   CHECK (rule_type IN ('anomalous', 'normal')),

--     is_active   BOOLEAN NOT NULL DEFAULT TRUE,
--     created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
-- );

CREATE INDEX IF NOT EXISTS anomaly_rules_active_idx
ON anomaly_rules (is_active, camera_id);

CREATE INDEX IF NOT EXISTS anomaly_rules_camera_idx
ON anomaly_rules (camera_id)
WHERE is_active = TRUE;

-- ============================================
-- 21. Anomaly Candidate Review
--     Admin review of a specific candidate.
--     Admin confirms/dismisses AND optionally
--     writes a rule that guides future LLM
--     reasoning for similar events.
-- ============================================
CREATE TABLE IF NOT EXISTS anomaly_candidate_review (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    anomaly_candidate_id BIGINT NOT NULL
        REFERENCES anomaly_candidates(id) ON DELETE CASCADE,

    -- Admin decision on this specific candidate
    decision    TEXT NOT NULL
                  CHECK (decision IN ('confirmed','dismissed','uncertain')),

    -- Optional rule text + FK to the rule row that was created
    rule_text        TEXT NULL,
    created_rule_id  BIGINT NULL
        REFERENCES anomaly_rules(id) ON DELETE SET NULL,

    reviewer    TEXT NULL,
    notes       TEXT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS anomaly_candidate_review_candidate_idx
ON anomaly_candidate_review (anomaly_candidate_id);

CREATE INDEX IF NOT EXISTS anomaly_candidate_review_decision_idx
ON anomaly_candidate_review (decision, created_at);

-- ============================================
-- 22. Ollama Jobs
-- ============================================
CREATE TABLE IF NOT EXISTS ollama_jobs (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    anomaly_candidate_id BIGINT NOT NULL
        REFERENCES anomaly_candidates(id) ON DELETE CASCADE,
    model_name           TEXT NOT NULL DEFAULT 'llama3.2:1b',
    prompt               TEXT NOT NULL,
    request_json         JSONB NULL,
    status               TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed')),
    response_text        TEXT NULL,
    response_json        JSONB NULL,
    error                TEXT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at           TIMESTAMPTZ NULL,
    finished_at          TIMESTAMPTZ NULL
);

-- ============================================
-- 23. Anomaly Rules
-- ============================================
CREATE TABLE IF NOT EXISTS Anomaly_Rules (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    rule_text            TEXT NOT NULL,
    rule_type            VARCHAR(20) NOT NULL CHECK (rule_type IN ('trigger','suppress')),
    event_type           VARCHAR(50) NOT NULL CHECK (event_type IN ('intrusion', 'loitering', 'after_hours', 'fall_detected', 'fight_detection', 'camera_tamper', 'sudden_movement', 'smoke_fire', 'crowd_detection')),
    conditions           JSONB NOT NULL,
    source               VARCHAR(50) NOT NULL CHECK (source IN ('Admin','Learned')),
    active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- ============================================
-- 24. Rule Conflicts
-- ============================================
CREATE TABLE rule_conflicts (
    id SERIAL PRIMARY KEY,
    rule_id_1 VARCHAR,
    rule_id_2 VARCHAR,
    conflict_reason TEXT,
    status VARCHAR DEFAULT 'pending', -- pending, resolved, ignored
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ollama_jobs_status_idx
ON ollama_jobs (status);

CREATE INDEX IF NOT EXISTS ollama_jobs_queue_idx
ON ollama_jobs (status, created_at);