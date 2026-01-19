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



-- ============================================
-- Anomaly / Normal Behavior Model Registry
-- ============================================

CREATE TABLE normal_behavior_models (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    name TEXT NOT NULL DEFAULT 'scene_anomaly_model',
    version TEXT NOT NULL,                        -- e.g. 'v1', '2026-01-18_01'
    embedding_model TEXT NOT NULL DEFAULT 'resnet18',
    embedding_dim INT NOT NULL DEFAULT 512,
    pca_dim INT NOT NULL DEFAULT 128,
    n_clusters INT NOT NULL,

    -- Where the model artifact lives (pickle/onnx/etc). Store file path or object storage key
    artifact_uri TEXT NULL,
    artifact_sha256 TEXT NULL,

    -- Model parameters you want to track
    window_size INT NOT NULL DEFAULT 8,
    stride INT NOT NULL DEFAULT 16,
    sample_frames INT NOT NULL DEFAULT 8,
    radius_percentile INT NOT NULL DEFAULT 95,

    -- lifecycle
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes TEXT NULL,

    -- sanity checks (keep clustering space consistent with vector(128))
    CONSTRAINT normal_behavior_models_dims_chk CHECK (embedding_dim > 0 AND pca_dim = 128),
    CONSTRAINT normal_behavior_models_clusters_chk CHECK (n_clusters > 0),
    CONSTRAINT normal_behavior_models_params_chk CHECK (
        window_size > 0 AND stride > 0 AND sample_frames > 0
        AND radius_percentile BETWEEN 1 AND 100
    ),
    CONSTRAINT normal_behavior_models_name_version_uniq UNIQUE (name, version)
);

-- Exactly one active model is typical (optional constraint style)
CREATE UNIQUE INDEX normal_behavior_models_one_active_idx
ON normal_behavior_models (is_active)
WHERE is_active = TRUE;


-- ============================================
-- Normal Clusters (Centroids + Radii)
-- ============================================

CREATE TABLE normal_clusters (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    model_id BIGINT NOT NULL REFERENCES normal_behavior_models(id) ON DELETE CASCADE,
    cluster_index INT NOT NULL,                               -- 0..k-1

    centroid vector(128) NOT NULL,                            -- PCA space centroid (L2-normalized)
    radius_p95 REAL NOT NULL DEFAULT 0,                       -- cosine distance radius threshold
    count_train BIGINT NOT NULL DEFAULT 0,                    -- how many train points assigned

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (model_id, cluster_index),
    CONSTRAINT normal_clusters_cluster_index_chk CHECK (cluster_index >= 0),
    CONSTRAINT normal_clusters_radius_chk CHECK (radius_p95 >= 0),
    CONSTRAINT normal_clusters_count_chk CHECK (count_train >= 0)
);

-- Fast nearest centroid search (cosine)
CREATE INDEX normal_clusters_centroid_hnsw_cosine
ON normal_clusters
USING hnsw (centroid vector_cosine_ops);

CREATE INDEX normal_clusters_model_idx
ON normal_clusters (model_id);



-- ============================================
-- Edge Device Registry (optional but recommended)
-- ============================================

CREATE TABLE edge_devices (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    device_key TEXT NOT NULL UNIQUE,           -- edge identifier / API key name
    name TEXT NULL,
    location TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- (Optional but useful if you often search by key)
CREATE INDEX edge_devices_device_key_idx
ON edge_devices (device_key);



-- ============================================
-- Scene/Behavior Window Embeddings (from edge)
-- ============================================

CREATE TABLE scene_window_embeddings (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    model_id BIGINT NOT NULL REFERENCES normal_behavior_models(id) ON DELETE RESTRICT,
    device_id BIGINT NULL REFERENCES edge_devices(id) ON DELETE SET NULL,

    camera_id BIGINT NULL REFERENCES cameras(id) ON DELETE SET NULL,
    entry_log_id BIGINT NULL REFERENCES entry_logs(id) ON DELETE SET NULL,

    window_start_ts TIMESTAMPTZ NOT NULL,
    window_end_ts TIMESTAMPTZ NULL,

    -- Idempotency key from edge (UUID or deterministic hash)
    event_key TEXT NULL,

    -- Embeddings:
    embedding_pca vector(128) NOT NULL,           -- normalized
    embedding_raw vector(512) NULL,               -- optional

    -- Decision fields:
    nearest_cluster_index INT NULL,               -- which centroid was closest (denormalized)
    nearest_cluster_id BIGINT NULL REFERENCES normal_clusters(id) ON DELETE SET NULL, -- authoritative FK
    cosine_distance REAL NULL,                    -- 1 - cosine similarity
    radius_threshold REAL NULL,                   -- radius_p95 used for decision
    is_normal BOOLEAN NULL,                       -- decision
    score REAL NULL,                              -- optional: distance / radius

    -- For traceability / debugging
    embedding_model TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT scene_window_embeddings_time_chk CHECK (window_end_ts IS NULL OR window_end_ts >= window_start_ts),
    CONSTRAINT scene_window_embeddings_metrics_chk CHECK (
        (cosine_distance IS NULL OR cosine_distance >= 0)
        AND (radius_threshold IS NULL OR radius_threshold >= 0)
        AND (score IS NULL OR score >= 0)
    )
);

-- Enforce that nearest_cluster_id belongs to the same model_id; also auto-sync nearest_cluster_index.
CREATE OR REPLACE FUNCTION scene_window_embeddings_cluster_guard()
RETURNS TRIGGER AS $$
DECLARE
  cm BIGINT;
  ci INT;
BEGIN
  IF NEW.nearest_cluster_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT model_id, cluster_index INTO cm, ci
  FROM normal_clusters
  WHERE id = NEW.nearest_cluster_id;

  IF cm IS NULL THEN
    RAISE EXCEPTION 'nearest_cluster_id % does not exist', NEW.nearest_cluster_id;
  END IF;

  IF cm <> NEW.model_id THEN
    RAISE EXCEPTION 'nearest_cluster_id % belongs to model_id %, but row model_id is %',
      NEW.nearest_cluster_id, cm, NEW.model_id;
  END IF;

  -- keep denormalized index consistent
  NEW.nearest_cluster_index = ci;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_scene_window_embeddings_cluster_guard
BEFORE INSERT OR UPDATE ON scene_window_embeddings
FOR EACH ROW
EXECUTE FUNCTION scene_window_embeddings_cluster_guard();

-- Indexes
CREATE INDEX scene_window_embeddings_ts_idx
ON scene_window_embeddings (window_start_ts);

CREATE INDEX scene_window_embeddings_model_idx
ON scene_window_embeddings (model_id);

CREATE INDEX scene_window_embeddings_camera_ts_idx
ON scene_window_embeddings (camera_id, window_start_ts);

-- Optional: similarity search over incoming windows
CREATE INDEX scene_window_embeddings_pca_hnsw_cosine
ON scene_window_embeddings
USING hnsw (embedding_pca vector_cosine_ops);

-- Idempotency: prevent duplicates on retries
CREATE UNIQUE INDEX scene_window_embeddings_event_key_uniq
ON scene_window_embeddings (event_key)
WHERE event_key IS NOT NULL;



-- ============================================
-- Anomaly Candidates (created when not normal)
-- ============================================

CREATE TABLE anomaly_candidates (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    scene_window_embedding_id BIGINT NOT NULL
        REFERENCES scene_window_embeddings(id) ON DELETE CASCADE,

    reason TEXT NOT NULL DEFAULT 'outside_cluster_radius',
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','sent_to_llm','resolved','discarded','failed')),

    -- Optional payload references
    image_ref TEXT NULL,               -- path/url to representative frame(s)
    video_ref TEXT NULL,               -- path/url to clip

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX anomaly_candidates_status_idx
ON anomaly_candidates (status);

-- Ensure updated_at actually updates (namespaced to avoid collisions)
CREATE OR REPLACE FUNCTION anomaly_candidates_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_anomaly_candidates_updated
BEFORE UPDATE ON anomaly_candidates
FOR EACH ROW
EXECUTE FUNCTION anomaly_candidates_set_updated_at();




-- ============================================
-- Human Feedback (admin review)
-- ============================================

CREATE TABLE anomaly_candidate_feedback (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    anomaly_candidate_id BIGINT NOT NULL
        REFERENCES anomaly_candidates(id) ON DELETE CASCADE,

    -- Admin label
    label TEXT NOT NULL CHECK (label IN ('true_anomaly','false_positive','uncertain')),

    reviewer TEXT NULL,
    notes TEXT NULL,

    -- Optional snapshot of the system decision at review time
    system_decision JSONB NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    used_for_retrain BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX anomaly_candidate_feedback_candidate_idx
ON anomaly_candidate_feedback (anomaly_candidate_id);

CREATE INDEX anomaly_candidate_feedback_label_idx
ON anomaly_candidate_feedback (label, created_at);

-- ============================================
-- Ollama Jobs
-- ============================================

CREATE TABLE ollama_jobs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    anomaly_candidate_id BIGINT NOT NULL
        REFERENCES anomaly_candidates(id) ON DELETE CASCADE,

    model_name TEXT NOT NULL DEFAULT 'llama3.2:1b',
    prompt TEXT NOT NULL,
    request_json JSONB NULL,

    status TEXT NOT NULL DEFAULT 'queued'
      CHECK (status IN ('queued','running','succeeded','failed')),

    response_text TEXT NULL,
    response_json JSONB NULL,

    error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL
);

CREATE INDEX ollama_jobs_status_idx
ON ollama_jobs (status);

CREATE INDEX ollama_jobs_created_idx
ON ollama_jobs (created_at);

-- Efficient "fetch next queued job"
CREATE INDEX ollama_jobs_queue_idx
ON ollama_jobs (status, created_at);


CREATE INDEX anomaly_candidates_pending_idx
ON anomaly_candidates (created_at)
WHERE status = 'pending';

