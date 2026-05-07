-- ============================================================================
-- Clean VideoMAE Dual-Stream Distribution Schema Migration
-- Purpose:
--   Remove old student/teacher anomaly architecture columns and keep only the
--   new architecture:
--     YOLO tracking -> person/context VideoMAE embeddings -> dual-stream
--     distribution score -> motion gates -> reasoning pipeline.
--
-- IMPORTANT:
--   1) This migration is intentionally destructive for old anomaly columns.
--   2) BACK UP your database before running.
--   3) This script does NOT modify anomaly_rules / Anomaly_Rules / rule_conflicts.
-- ============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. normal_behavior_models
--    Remove old student/teacher model metadata and add new distribution metadata.
-- ============================================================================

-- Remove old constraint that depends on embedding_dim before dropping the column.
ALTER TABLE IF EXISTS normal_behavior_models
    DROP CONSTRAINT IF EXISTS normal_behavior_models_embedding_dim_chk;

-- Drop old student/teacher architecture columns.
ALTER TABLE IF EXISTS normal_behavior_models
    DROP COLUMN IF EXISTS teacher_model,
    DROP COLUMN IF EXISTS extract_layers,
    DROP COLUMN IF EXISTS student_model,
    DROP COLUMN IF EXISTS embedding_dim,
    DROP COLUMN IF EXISTS num_frames,
    DROP COLUMN IF EXISTS window_stride,
    DROP COLUMN IF EXISTS image_size;

-- Add new architecture columns.
ALTER TABLE IF EXISTS normal_behavior_models
    ADD COLUMN IF NOT EXISTS model_type              TEXT NOT NULL DEFAULT 'dual_stream_videomae_distribution',
    ADD COLUMN IF NOT EXISTS video_encoder           TEXT NOT NULL DEFAULT 'MCG-NJU/videomae-base',
    ADD COLUMN IF NOT EXISTS person_embedding_dim    INT  NOT NULL DEFAULT 768,
    ADD COLUMN IF NOT EXISTS context_embedding_dim   INT  NOT NULL DEFAULT 768,
    ADD COLUMN IF NOT EXISTS pca_components          INT  NOT NULL DEFAULT 64,
    ADD COLUMN IF NOT EXISTS covariance_estimator    TEXT NOT NULL DEFAULT 'ledoit_wolf',
    ADD COLUMN IF NOT EXISTS score_method            TEXT NOT NULL DEFAULT 'mahalanobis',
    ADD COLUMN IF NOT EXISTS score_normalization     TEXT NOT NULL DEFAULT 'robust_iqr',
    ADD COLUMN IF NOT EXISTS person_weight           REAL NOT NULL DEFAULT 0.65,
    ADD COLUMN IF NOT EXISTS context_weight          REAL NOT NULL DEFAULT 0.35,
    ADD COLUMN IF NOT EXISTS sample_fps              INT  NOT NULL DEFAULT 8,
    ADD COLUMN IF NOT EXISTS tubelet_frames          INT  NOT NULL DEFAULT 16,
    ADD COLUMN IF NOT EXISTS stride                  INT  NOT NULL DEFAULT 16,
    ADD COLUMN IF NOT EXISTS person_size             INT  NOT NULL DEFAULT 224,
    ADD COLUMN IF NOT EXISTS context_size            INT  NOT NULL DEFAULT 224,
    ADD COLUMN IF NOT EXISTS person_padding          REAL NOT NULL DEFAULT 0.20,
    ADD COLUMN IF NOT EXISTS context_scale           REAL NOT NULL DEFAULT 2.5,
    ADD COLUMN IF NOT EXISTS training_dataset_ref    TEXT NULL,
    ADD COLUMN IF NOT EXISTS thresholds_json         JSONB NULL,
    ADD COLUMN IF NOT EXISTS fusion_config_json      JSONB NULL,
    ADD COLUMN IF NOT EXISTS model_info_json         JSONB NULL,
    ADD COLUMN IF NOT EXISTS activated_at            TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS updated_at              TIMESTAMPTZ NOT NULL DEFAULT now();

-- Add checks for the new architecture.
ALTER TABLE IF EXISTS normal_behavior_models
    DROP CONSTRAINT IF EXISTS normal_behavior_models_new_architecture_chk;

ALTER TABLE IF EXISTS normal_behavior_models
    ADD CONSTRAINT normal_behavior_models_new_architecture_chk
    CHECK (
        person_embedding_dim > 0 AND
        context_embedding_dim > 0 AND
        pca_components > 0 AND
        sample_fps > 0 AND
        tubelet_frames > 0 AND
        stride > 0 AND
        person_size > 0 AND
        context_size > 0 AND
        person_padding >= 0 AND
        context_scale >= 1 AND
        person_weight >= 0 AND
        context_weight >= 0 AND
        (person_weight + context_weight) > 0
    );

-- ============================================================================
-- 2. normal_behavior_model_artifacts
--    Track the actual artifact files used by the backend scorer.
-- ============================================================================

CREATE TABLE IF NOT EXISTS normal_behavior_model_artifacts (
    id            BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id      BIGINT NOT NULL REFERENCES normal_behavior_models(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'person_scaler',
        'person_pca',
        'person_ledoitwolf',
        'context_scaler',
        'context_pca',
        'context_ledoitwolf',
        'thresholds_json',
        'fusion_config_json',
        'model_info_json',
        'score_histogram',
        'training_scores',
        'removed_outliers',
        'other'
    )),
    artifact_uri  TEXT NOT NULL,
    sha256        TEXT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT normal_behavior_model_artifacts_uniq UNIQUE (model_id, artifact_type)
);

CREATE INDEX IF NOT EXISTS nbm_artifacts_model_idx
ON normal_behavior_model_artifacts (model_id);

-- ============================================================================
-- 3. anomaly_thresholds
--    Remove old L2/MSE/Cosine threshold architecture. Store dual-stream percentiles.
-- ============================================================================

ALTER TABLE IF EXISTS anomaly_thresholds
    DROP COLUMN IF EXISTS l2_p95,
    DROP COLUMN IF EXISTS mse_p95,
    DROP COLUMN IF EXISTS cos_p95,
    DROP COLUMN IF EXISTS val_samples,
    DROP COLUMN IF EXISTS min_metrics_agree,
    DROP COLUMN IF EXISTS min_consecutive;

ALTER TABLE IF EXISTS anomaly_thresholds
    ADD COLUMN IF NOT EXISTS person_p90        REAL NULL,
    ADD COLUMN IF NOT EXISTS person_p95        REAL NULL,
    ADD COLUMN IF NOT EXISTS person_p97        REAL NULL,
    ADD COLUMN IF NOT EXISTS person_p99        REAL NULL,
    ADD COLUMN IF NOT EXISTS person_p99_5      REAL NULL,
    ADD COLUMN IF NOT EXISTS context_p90       REAL NULL,
    ADD COLUMN IF NOT EXISTS context_p95       REAL NULL,
    ADD COLUMN IF NOT EXISTS context_p97       REAL NULL,
    ADD COLUMN IF NOT EXISTS context_p99       REAL NULL,
    ADD COLUMN IF NOT EXISTS context_p99_5     REAL NULL,
    ADD COLUMN IF NOT EXISTS person_norm_p90   REAL NULL,
    ADD COLUMN IF NOT EXISTS person_norm_p95   REAL NULL,
    ADD COLUMN IF NOT EXISTS person_norm_p97   REAL NULL,
    ADD COLUMN IF NOT EXISTS person_norm_p99   REAL NULL,
    ADD COLUMN IF NOT EXISTS person_norm_p99_5 REAL NULL,
    ADD COLUMN IF NOT EXISTS context_norm_p90  REAL NULL,
    ADD COLUMN IF NOT EXISTS context_norm_p95  REAL NULL,
    ADD COLUMN IF NOT EXISTS context_norm_p97  REAL NULL,
    ADD COLUMN IF NOT EXISTS context_norm_p99  REAL NULL,
    ADD COLUMN IF NOT EXISTS context_norm_p99_5 REAL NULL,
    ADD COLUMN IF NOT EXISTS final_p90         REAL NULL,
    ADD COLUMN IF NOT EXISTS final_p95         REAL NULL,
    ADD COLUMN IF NOT EXISTS final_p97         REAL NULL,
    ADD COLUMN IF NOT EXISTS final_p99         REAL NULL,
    ADD COLUMN IF NOT EXISTS final_p99_5       REAL NULL,
    ADD COLUMN IF NOT EXISTS recommended_threshold_name  TEXT NOT NULL DEFAULT 'final.p97',
    ADD COLUMN IF NOT EXISTS recommended_threshold_value REAL NULL,
    ADD COLUMN IF NOT EXISTS person_weight     REAL NOT NULL DEFAULT 0.65,
    ADD COLUMN IF NOT EXISTS context_weight    REAL NOT NULL DEFAULT 0.35,
    ADD COLUMN IF NOT EXISTS normalization_method TEXT NOT NULL DEFAULT 'robust_iqr',
    ADD COLUMN IF NOT EXISTS num_valid_samples INT NULL,
    ADD COLUMN IF NOT EXISTS num_removed_outliers INT NULL,
    ADD COLUMN IF NOT EXISTS num_clean_samples INT NULL,
    ADD COLUMN IF NOT EXISTS thresholds_json   JSONB NULL;

ALTER TABLE IF EXISTS anomaly_thresholds
    DROP CONSTRAINT IF EXISTS anomaly_thresholds_distribution_chk;

ALTER TABLE IF EXISTS anomaly_thresholds
    ADD CONSTRAINT anomaly_thresholds_distribution_chk
    CHECK (
        (final_p90 IS NULL OR final_p90 >= 0) AND
        (final_p95 IS NULL OR final_p95 >= 0) AND
        (final_p97 IS NULL OR final_p97 >= 0) AND
        (final_p99 IS NULL OR final_p99 >= 0) AND
        (final_p99_5 IS NULL OR final_p99_5 >= 0) AND
        (recommended_threshold_value IS NULL OR recommended_threshold_value >= 0)
    );

-- ============================================================================
-- 4. scene_window_embeddings
--    Replace old student/teacher embeddings with person/context embeddings and
--    score/gate metadata.
-- ============================================================================

-- Drop indexes/constraints that depend on old columns.
DROP INDEX IF EXISTS scene_window_embeddings_anomalous_idx;
DROP INDEX IF EXISTS scene_window_embeddings_student_embedding_hnsw;
DROP INDEX IF EXISTS scene_window_embeddings_teacher_embedding_hnsw;

ALTER TABLE IF EXISTS scene_window_embeddings
    DROP CONSTRAINT IF EXISTS scene_window_embeddings_scores_chk;

-- Drop old student/teacher architecture columns.
ALTER TABLE IF EXISTS scene_window_embeddings
    DROP COLUMN IF EXISTS student_embedding,
    DROP COLUMN IF EXISTS teacher_embedding,
    DROP COLUMN IF EXISTS frames,
    DROP COLUMN IF EXISTS l2_score,
    DROP COLUMN IF EXISTS mse_score,
    DROP COLUMN IF EXISTS cosine_distance,
    DROP COLUMN IF EXISTS l2_flag,
    DROP COLUMN IF EXISTS mse_flag,
    DROP COLUMN IF EXISTS cos_flag,
    DROP COLUMN IF EXISTS metrics_agreed,
    DROP COLUMN IF EXISTS is_anomalous,
    DROP COLUMN IF EXISTS embedding_model;

-- Add new dual-stream runtime scoring columns.
ALTER TABLE IF EXISTS scene_window_embeddings
    ADD COLUMN IF NOT EXISTS person_embedding       vector(768) NULL,
    ADD COLUMN IF NOT EXISTS context_embedding      vector(768) NULL,
    ADD COLUMN IF NOT EXISTS person_score           REAL NULL,
    ADD COLUMN IF NOT EXISTS context_score          REAL NULL,
    ADD COLUMN IF NOT EXISTS person_score_norm      REAL NULL,
    ADD COLUMN IF NOT EXISTS context_score_norm     REAL NULL,
    ADD COLUMN IF NOT EXISTS final_score            REAL NULL,
    ADD COLUMN IF NOT EXISTS threshold_name         TEXT NULL,
    ADD COLUMN IF NOT EXISTS threshold_value        REAL NULL,
    ADD COLUMN IF NOT EXISTS distribution_gate      BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS high_speed_gate        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS abrupt_direction_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS track_instability_gate BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS candidate_reasons      TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS priority               TEXT NULL CHECK (priority IN ('normal','low','medium','high','very_high','motion_gate')),
    ADD COLUMN IF NOT EXISTS sample_fps             INT NULL,
    ADD COLUMN IF NOT EXISTS tubelet_frames         INT NULL,
    ADD COLUMN IF NOT EXISTS stride                 INT NULL,
    ADD COLUMN IF NOT EXISTS person_bbox_sequence   JSONB NULL,
    ADD COLUMN IF NOT EXISTS motion_stats           JSONB NULL,
    ADD COLUMN IF NOT EXISTS person_clip_ref        TEXT NULL,
    ADD COLUMN IF NOT EXISTS context_clip_ref       TEXT NULL,
    ADD COLUMN IF NOT EXISTS representative_frame_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS video_encoder          TEXT NOT NULL DEFAULT 'MCG-NJU/videomae-base';

ALTER TABLE IF EXISTS scene_window_embeddings
    DROP CONSTRAINT IF EXISTS scene_window_embeddings_new_scores_chk;

ALTER TABLE IF EXISTS scene_window_embeddings
    ADD CONSTRAINT scene_window_embeddings_new_scores_chk
    CHECK (
        (person_score IS NULL OR person_score >= 0) AND
        (context_score IS NULL OR context_score >= 0) AND
        (threshold_value IS NULL OR threshold_value >= 0) AND
        (sample_fps IS NULL OR sample_fps > 0) AND
        (tubelet_frames IS NULL OR tubelet_frames > 0) AND
        (stride IS NULL OR stride > 0)
    );

-- New indexes for runtime queries and dashboard.
CREATE INDEX IF NOT EXISTS scene_window_embeddings_final_score_idx
ON scene_window_embeddings (final_score DESC)
WHERE final_score IS NOT NULL;

CREATE INDEX IF NOT EXISTS scene_window_embeddings_distribution_gate_idx
ON scene_window_embeddings (camera_id, window_start_ts)
WHERE distribution_gate = TRUE;

CREATE INDEX IF NOT EXISTS scene_window_embeddings_candidate_reasons_gin_idx
ON scene_window_embeddings USING GIN (candidate_reasons);

CREATE INDEX IF NOT EXISTS scene_window_embeddings_person_embedding_hnsw_cosine
ON scene_window_embeddings USING hnsw (person_embedding vector_cosine_ops)
WHERE person_embedding IS NOT NULL;

CREATE INDEX IF NOT EXISTS scene_window_embeddings_context_embedding_hnsw_cosine
ON scene_window_embeddings USING hnsw (context_embedding vector_cosine_ops)
WHERE context_embedding IS NOT NULL;

-- ============================================================================
-- 5. anomaly_gate_configs
--    Store gate settings in DB instead of hardcoding them in code.
-- ============================================================================

CREATE TABLE IF NOT EXISTS anomaly_gate_configs (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    model_id         BIGINT NULL REFERENCES normal_behavior_models(id) ON DELETE CASCADE,
    gate_name        TEXT NOT NULL CHECK (gate_name IN (
        'distribution_score',
        'high_speed',
        'abrupt_direction_change',
        'track_instability'
    )),
    is_active        BOOLEAN NOT NULL DEFAULT TRUE,
    threshold_value  REAL NULL,
    params           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT anomaly_gate_configs_uniq UNIQUE (model_id, gate_name)
);

CREATE INDEX IF NOT EXISTS anomaly_gate_configs_active_idx
ON anomaly_gate_configs (model_id, gate_name)
WHERE is_active = TRUE;

-- ============================================================================
-- 6. anomaly_candidates
--    Remove old L2 / single-reason / YES-NO decision fields and store gate-based
--    candidate output for the VLM/LLM reasoning queue.
-- ============================================================================

-- Drop old status check so we can replace it with new statuses.
ALTER TABLE IF EXISTS anomaly_candidates
    DROP CONSTRAINT IF EXISTS anomaly_candidates_status_check;

-- Drop old architecture columns.
ALTER TABLE IF EXISTS anomaly_candidates
    DROP COLUMN IF EXISTS reason,
    DROP COLUMN IF EXISTS image_ref,
    DROP COLUMN IF EXISTS video_ref,
    DROP COLUMN IF EXISTS l2_score,
    DROP COLUMN IF EXISTS alert_decision,
    DROP COLUMN IF EXISTS severity,
    DROP COLUMN IF EXISTS decision_reason;

-- Add new candidate columns.
ALTER TABLE IF EXISTS anomaly_candidates
    ADD COLUMN IF NOT EXISTS candidate_reasons      TEXT[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS primary_reason         TEXT NULL,
    ADD COLUMN IF NOT EXISTS priority               TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low','medium','high','very_high','motion_gate')),
    ADD COLUMN IF NOT EXISTS final_score            REAL NULL,
    ADD COLUMN IF NOT EXISTS person_score           REAL NULL,
    ADD COLUMN IF NOT EXISTS context_score          REAL NULL,
    ADD COLUMN IF NOT EXISTS person_score_norm      REAL NULL,
    ADD COLUMN IF NOT EXISTS context_score_norm     REAL NULL,
    ADD COLUMN IF NOT EXISTS threshold_name         TEXT NULL,
    ADD COLUMN IF NOT EXISTS threshold_value        REAL NULL,
    ADD COLUMN IF NOT EXISTS distribution_gate      BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS high_speed_gate        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS abrupt_direction_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS track_instability_gate BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_speed_norm         REAL NULL,
    ADD COLUMN IF NOT EXISTS max_turn_angle         REAL NULL,
    ADD COLUMN IF NOT EXISTS track_instability_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS person_clip_ref        TEXT NULL,
    ADD COLUMN IF NOT EXISTS context_clip_ref       TEXT NULL,
    ADD COLUMN IF NOT EXISTS representative_frame_ref TEXT NULL,
    ADD COLUMN IF NOT EXISTS sent_to_reasoning_at   TIMESTAMPTZ NULL;

ALTER TABLE IF EXISTS anomaly_candidates
    ADD CONSTRAINT anomaly_candidates_status_check
    CHECK (status IN ('pending','sent_to_reasoning','reasoning_done','resolved','discarded','failed'));

ALTER TABLE IF EXISTS anomaly_candidates
    DROP CONSTRAINT IF EXISTS anomaly_candidates_new_scores_chk;

ALTER TABLE IF EXISTS anomaly_candidates
    ADD CONSTRAINT anomaly_candidates_new_scores_chk
    CHECK (
        (final_score IS NULL OR final_score >= 0) AND
        (person_score IS NULL OR person_score >= 0) AND
        (context_score IS NULL OR context_score >= 0) AND
        (threshold_value IS NULL OR threshold_value >= 0) AND
        (max_speed_norm IS NULL OR max_speed_norm >= 0) AND
        (max_turn_angle IS NULL OR max_turn_angle >= 0)
    );

CREATE INDEX IF NOT EXISTS anomaly_candidates_priority_idx
ON anomaly_candidates (priority, created_at);

CREATE INDEX IF NOT EXISTS anomaly_candidates_final_score_idx
ON anomaly_candidates (final_score DESC)
WHERE final_score IS NOT NULL;

CREATE INDEX IF NOT EXISTS anomaly_candidates_reasons_gin_idx
ON anomaly_candidates USING GIN (candidate_reasons);

CREATE INDEX IF NOT EXISTS anomaly_candidates_gate_idx
ON anomaly_candidates (created_at)
WHERE distribution_gate OR high_speed_gate OR abrupt_direction_gate OR track_instability_gate;

-- ============================================================================
-- 7. candidate_gate_decisions
--    One row per gate per candidate for explainability and debugging.
-- ============================================================================

CREATE TABLE IF NOT EXISTS candidate_gate_decisions (
    id              BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    candidate_id    BIGINT NOT NULL REFERENCES anomaly_candidates(id) ON DELETE CASCADE,
    gate_name        TEXT NOT NULL CHECK (gate_name IN (
        'distribution_score',
        'high_speed',
        'abrupt_direction_change',
        'track_instability'
    )),
    gate_fired       BOOLEAN NOT NULL DEFAULT FALSE,
    score_value      REAL NULL,
    threshold_value  REAL NULL,
    details          JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason           TEXT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT candidate_gate_decisions_uniq UNIQUE (candidate_id, gate_name)
);

CREATE INDEX IF NOT EXISTS candidate_gate_decisions_candidate_idx
ON candidate_gate_decisions (candidate_id);

CREATE INDEX IF NOT EXISTS candidate_gate_decisions_gate_idx
ON candidate_gate_decisions (gate_name, gate_fired);

-- ============================================================================
-- 8. reasoning_jobs
--    General VLM/LLM job queue. This replaces old Ollama-only reasoning flow.
-- ============================================================================

CREATE TABLE IF NOT EXISTS reasoning_jobs (
    id                   BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    anomaly_candidate_id BIGINT NOT NULL REFERENCES anomaly_candidates(id) ON DELETE CASCADE,
    provider             TEXT NOT NULL DEFAULT 'ollama',
    model_name           TEXT NOT NULL,
    job_type             TEXT NOT NULL DEFAULT 'vlm_llm_reasoning'
        CHECK (job_type IN ('vlm_reasoning','llm_reasoning','vlm_llm_reasoning')),
    prompt               TEXT NULL,
    request_json         JSONB NULL,
    status               TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    response_text        TEXT NULL,
    response_json        JSONB NULL,
    error                TEXT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at           TIMESTAMPTZ NULL,
    finished_at          TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS reasoning_jobs_status_idx
ON reasoning_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS reasoning_jobs_candidate_idx
ON reasoning_jobs (anomaly_candidate_id);

-- Drop old Ollama-only job table to avoid mixing architectures.
-- If you need to keep old job history, comment out this DROP before running.
DROP TABLE IF EXISTS ollama_jobs;

-- ============================================================================
-- 9. anomaly_candidate_review
--    Keep review table, but add fields needed for VLM/LLM evaluation feedback.
--    This does not modify anomaly_rules.
-- ============================================================================

ALTER TABLE IF EXISTS anomaly_candidate_review
    ADD COLUMN IF NOT EXISTS reviewed_by          TEXT NULL,
    ADD COLUMN IF NOT EXISTS vlm_was_correct      BOOLEAN NULL,
    ADD COLUMN IF NOT EXISTS false_positive_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS missed_gate_notes    TEXT NULL,
    ADD COLUMN IF NOT EXISTS should_create_rule   BOOLEAN NOT NULL DEFAULT FALSE;

-- ============================================================================
-- 10. Seed recommended default gate configs for the active model.
--     These values are aligned with the current live-test architecture.
-- ============================================================================

INSERT INTO anomaly_gate_configs (model_id, gate_name, is_active, threshold_value, params)
SELECT id, 'distribution_score', TRUE, 2.5629648557563884,
       '{"threshold_name":"final.p97","purpose":"high_recall_candidate_gate"}'::jsonb
FROM normal_behavior_models
WHERE is_active = TRUE
ON CONFLICT (model_id, gate_name) DO UPDATE
SET is_active = EXCLUDED.is_active,
    threshold_value = EXCLUDED.threshold_value,
    params = EXCLUDED.params,
    updated_at = now();

INSERT INTO anomaly_gate_configs (model_id, gate_name, is_active, threshold_value, params)
SELECT id, 'high_speed', TRUE, 0.24,
       '{"high_speed_threshold":0.24,"speed_unit":"frame_diagonal_per_second"}'::jsonb
FROM normal_behavior_models
WHERE is_active = TRUE
ON CONFLICT (model_id, gate_name) DO UPDATE
SET is_active = EXCLUDED.is_active,
    threshold_value = EXCLUDED.threshold_value,
    params = EXCLUDED.params,
    updated_at = now();

INSERT INTO anomaly_gate_configs (model_id, gate_name, is_active, threshold_value, params)
SELECT id, 'abrupt_direction_change', TRUE, 120,
       '{"abrupt_angle_threshold":120,"min_turn_speed":0.08,"angle_unit":"degrees"}'::jsonb
FROM normal_behavior_models
WHERE is_active = TRUE
ON CONFLICT (model_id, gate_name) DO UPDATE
SET is_active = EXCLUDED.is_active,
    threshold_value = EXCLUDED.threshold_value,
    params = EXCLUDED.params,
    updated_at = now();

INSERT INTO anomaly_gate_configs (model_id, gate_name, is_active, threshold_value, params)
SELECT id, 'track_instability', TRUE, 6,
       '{"max_track_gap":6,"lost_reacquire_distance":0.12,"lost_reacquire_time_sec":1.0}'::jsonb
FROM normal_behavior_models
WHERE is_active = TRUE
ON CONFLICT (model_id, gate_name) DO UPDATE
SET is_active = EXCLUDED.is_active,
    threshold_value = EXCLUDED.threshold_value,
    params = EXCLUDED.params,
    updated_at = now();

-- ============================================================================
-- Dashboard / reasoning decision compatibility patch
-- This patch keeps final LLM decisions directly visible on anomaly_candidates.
-- ============================================================================

-- Optional compatibility patch for dashboard-friendly final decisions.
-- Run this AFTER refine_pgvector_schema_videomae_distribution_clean.sql if you want
-- anomaly_candidates to expose the final LLM decision directly.

ALTER TABLE IF EXISTS anomaly_candidates
ADD COLUMN IF NOT EXISTS alert_decision TEXT NULL,
ADD COLUMN IF NOT EXISTS severity TEXT NULL,
ADD COLUMN IF NOT EXISTS decision_reason TEXT NULL,
ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ NULL;

ALTER TABLE IF EXISTS anomaly_candidates
DROP CONSTRAINT IF EXISTS anomaly_candidates_alert_decision_check;

ALTER TABLE IF EXISTS anomaly_candidates
ADD CONSTRAINT anomaly_candidates_alert_decision_check
CHECK (alert_decision IS NULL OR alert_decision IN ('YES','NO'));

ALTER TABLE IF EXISTS anomaly_candidates
DROP CONSTRAINT IF EXISTS anomaly_candidates_severity_check;

ALTER TABLE IF EXISTS anomaly_candidates
ADD CONSTRAINT anomaly_candidates_severity_check
CHECK (severity IS NULL OR severity IN ('LOW','MEDIUM','HIGH'));

COMMIT;
