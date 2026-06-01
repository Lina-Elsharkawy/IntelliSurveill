
-- 001_create_vad_backend_direct_schema_FINAL_ENV_SAFE.sql
-- Purpose: final clean database foundation for backend-direct RTSP Video Anomaly Detection with env/container-safe artifact references.
-- This file intentionally touches only public.vad_* objects and leaves the existing
-- face access-control tables and old anomaly/Jetson/Kafka tables untouched.
--
-- Development reset note:
-- The VAD service has not gone live yet, so this migration resets only vad_* tables.
-- Do NOT run this on production VAD data unless you intentionally want to delete VAD-only data.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

-- ---------------------------------------------------------------------------
-- Reset only the new VAD namespace.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS public.vad_reasoning_results CASCADE;
DROP TABLE IF EXISTS public.vad_reasoning_jobs CASCADE;
DROP TABLE IF EXISTS public.vad_evidence_items CASCADE;
DROP TABLE IF EXISTS public.vad_media_objects CASCADE;
DROP TABLE IF EXISTS public.vad_case_reviews CASCADE;
DROP TABLE IF EXISTS public.vad_case_gate_events CASCADE;
DROP TABLE IF EXISTS public.vad_anomaly_cases CASCADE;
DROP TABLE IF EXISTS public.vad_gate_events CASCADE;
DROP TABLE IF EXISTS public.vad_gate_scores CASCADE;
DROP TABLE IF EXISTS public.vad_tubelet_embeddings CASCADE;
DROP TABLE IF EXISTS public.vad_tubelets CASCADE;
DROP TABLE IF EXISTS public.vad_detections CASCADE;
DROP TABLE IF EXISTS public.vad_tracks CASCADE;
DROP TABLE IF EXISTS public.vad_sampled_frames CASCADE;
DROP TABLE IF EXISTS public.vad_stream_sessions CASCADE;
DROP TABLE IF EXISTS public.vad_homography_calibrations CASCADE;
DROP TABLE IF EXISTS public.vad_gate_thresholds CASCADE;
DROP TABLE IF EXISTS public.vad_gate_model_versions CASCADE;
DROP TABLE IF EXISTS public.vad_gate_definitions CASCADE;
DROP TABLE IF EXISTS public.vad_streams CASCADE;
DROP TABLE IF EXISTS public.vad_schema_version CASCADE;

-- ---------------------------------------------------------------------------
-- Schema version marker.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_schema_version (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version text NOT NULL UNIQUE,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- Stream/session layer: backend-direct RTSP without storing credentials.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_streams (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_key text NOT NULL UNIQUE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    camera_key text NULL,
    display_name text NULL,
    location text NULL,
    source_type text NOT NULL DEFAULT 'rtsp',
    -- Name of environment variable containing the RTSP URL, e.g. VAD_RTSP_URL_LAB_CAM_02.
    -- The actual URL/password should not be stored here.
    rtsp_url_env_var text NULL,
    target_sample_fps numeric(6,3) NOT NULL DEFAULT 5.0,
    rolling_buffer_sec numeric(8,3) NOT NULL DEFAULT 30.0,
    route_fps_json jsonb NOT NULL DEFAULT '{"pose":5.0,"deep":2.5,"homography_macro":2.5,"raft":2.5}'::jsonb,
    frame_width integer NULL,
    frame_height integer NULL,
    is_active boolean NOT NULL DEFAULT true,
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_streams_source_type_chk CHECK (source_type IN ('rtsp','file','debug')),
    CONSTRAINT vad_streams_positive_sampling_chk CHECK (target_sample_fps > 0 AND rolling_buffer_sec > 0)
);

CREATE TABLE public.vad_stream_sessions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'starting',
    backend_instance_id text NULL,
    process_id integer NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    first_frame_at timestamptz NULL,
    last_frame_at timestamptz NULL,
    stopped_at timestamptz NULL,
    last_heartbeat_at timestamptz NOT NULL DEFAULT now(),
    target_sample_fps numeric(6,3) NOT NULL DEFAULT 5.0,
    actual_sample_fps numeric(8,3) NULL,
    rolling_buffer_sec numeric(8,3) NOT NULL DEFAULT 30.0,
    frame_width integer NULL,
    frame_height integer NULL,
    sampled_frame_count bigint NOT NULL DEFAULT 0,
    dropped_frame_count bigint NOT NULL DEFAULT 0,
    reconnect_count integer NOT NULL DEFAULT 0,
    route_counters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    runtime_stats_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT vad_stream_sessions_status_chk CHECK (status IN ('starting','running','degraded','stopping','stopped','failed')),
    CONSTRAINT vad_stream_sessions_positive_sampling_chk CHECK (target_sample_fps > 0 AND rolling_buffer_sec > 0)
);

-- Metadata only. Do not store full raw frames here. Debug/evidence images go through vad_media_objects.
CREATE TABLE public.vad_sampled_frames (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    sample_index bigint NOT NULL,
    source_frame_index bigint NULL,
    captured_at timestamptz NOT NULL,
    stream_pts_sec numeric(16,6) NULL,
    monotonic_ts_sec numeric(16,6) NULL,
    frame_width integer NULL,
    frame_height integer NULL,
    used_by_pose boolean NOT NULL DEFAULT true,
    used_by_deep boolean NOT NULL DEFAULT false,
    used_by_homography_macro boolean NOT NULL DEFAULT false,
    used_by_raft boolean NOT NULL DEFAULT false,
    debug_media_object_id bigint NULL,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_sampled_frames_unique_sample UNIQUE (session_id, sample_index)
);

-- ---------------------------------------------------------------------------
-- Gate definitions and model/threshold registry.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_gate_definitions (
    gate_name text PRIMARY KEY,
    display_name text NOT NULL,
    route_name text NOT NULL,
    primary_sample_fps numeric(6,3) NOT NULL,
    role text NOT NULL,
    default_trigger_policy text NOT NULL,
    reasoning_policy text NOT NULL,
    is_primary_trigger boolean NOT NULL DEFAULT true,
    is_enabled boolean NOT NULL DEFAULT true,
    config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_gate_definitions_positive_fps_chk CHECK (primary_sample_fps > 0)
);

CREATE TABLE public.vad_gate_model_versions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gate_name text NOT NULL REFERENCES public.vad_gate_definitions(gate_name) ON DELETE CASCADE,
    version text NOT NULL,
    model_name text NOT NULL,
    model_type text NOT NULL,
    feature_dim integer NULL,
    score_direction text NOT NULL DEFAULT 'higher_is_more_anomalous',
    score_method text NULL,
    normalization text NULL,
    distance_metric text NULL,
    sample_fps numeric(6,3) NULL,
    tubelet_frames integer NULL,
    stride integer NULL,
    window_duration_sec numeric(10,4) NULL,
    artifact_base_uri text NULL,
    artifact_refs_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    feature_schema_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    training_config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    inference_config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    validation_report_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes text NULL,
    is_active boolean NOT NULL DEFAULT false,
    activated_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_gate_model_versions_unique_version UNIQUE (gate_name, version),
    CONSTRAINT vad_gate_model_versions_score_direction_chk CHECK (score_direction IN ('higher_is_more_anomalous','lower_is_more_anomalous')),
    CONSTRAINT vad_gate_model_versions_positive_temporal_chk CHECK (
        (feature_dim IS NULL OR feature_dim > 0) AND
        (sample_fps IS NULL OR sample_fps > 0) AND
        (tubelet_frames IS NULL OR tubelet_frames > 0) AND
        (stride IS NULL OR stride > 0) AND
        (window_duration_sec IS NULL OR window_duration_sec > 0)
    )
);

CREATE UNIQUE INDEX vad_gate_model_versions_one_active_per_gate_idx
    ON public.vad_gate_model_versions(gate_name)
    WHERE is_active;

CREATE TABLE public.vad_gate_thresholds (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    gate_model_version_id bigint NOT NULL REFERENCES public.vad_gate_model_versions(id) ON DELETE CASCADE,
    threshold_key text NOT NULL,
    threshold_percentile numeric(7,3) NULL,
    threshold_value double precision NOT NULL,
    score_column text NULL,
    score_direction text NOT NULL DEFAULT 'higher_is_more_anomalous',
    threshold_source text NULL,
    smoothing_method text NOT NULL DEFAULT 'gaussian_then_persistence',
    smoothing_sigma double precision NULL,
    persistence_window integer NULL,
    persistence_required_hits integer NULL,
    min_event_gap_sec numeric(10,4) NULL,
    is_primary boolean NOT NULL DEFAULT false,
    trigger_policy_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    calibration_report_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_gate_thresholds_unique_key UNIQUE (gate_model_version_id, threshold_key),
    CONSTRAINT vad_gate_thresholds_score_direction_chk CHECK (score_direction IN ('higher_is_more_anomalous','lower_is_more_anomalous')),
    CONSTRAINT vad_gate_thresholds_positive_persistence_chk CHECK (
        (smoothing_sigma IS NULL OR smoothing_sigma >= 0) AND
        (persistence_window IS NULL OR persistence_window > 0) AND
        (persistence_required_hits IS NULL OR persistence_required_hits > 0) AND
        (min_event_gap_sec IS NULL OR min_event_gap_sec >= 0)
    )
);

CREATE UNIQUE INDEX vad_gate_thresholds_one_primary_per_model_idx
    ON public.vad_gate_thresholds(gate_model_version_id)
    WHERE is_primary;

-- Homography belongs to the VAD service because the macro gate depends on a camera-specific floor-plane mapping.
CREATE TABLE public.vad_homography_calibrations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    stream_id bigint NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    calibration_name text NOT NULL,
    version text NOT NULL DEFAULT 'v1',
    homography_matrix_json jsonb NOT NULL,
    image_points_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    world_points_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    units text NOT NULL DEFAULT 'meters',
    floor_plane_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active boolean NOT NULL DEFAULT false,
    activated_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_homography_calibrations_unique UNIQUE (camera_id, calibration_name, version)
);

-- ---------------------------------------------------------------------------
-- Runtime detections, tracks, tubelets, and embeddings.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_tracks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    tracker_name text NOT NULL DEFAULT 'unknown',
    tracker_track_id bigint NOT NULL,
    global_track_key text NULL,
    status text NOT NULL DEFAULT 'active',
    first_seen_frame_id bigint NULL REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL,
    last_seen_frame_id bigint NULL REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    detection_count integer NOT NULL DEFAULT 0,
    gap_count integer NOT NULL DEFAULT 0,
    best_confidence double precision NULL,
    last_bbox_xyxy_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    track_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_tracks_unique_tracker_track UNIQUE (session_id, tracker_name, tracker_track_id),
    CONSTRAINT vad_tracks_status_chk CHECK (status IN ('active','lost','closed','merged','debug'))
);

CREATE TABLE public.vad_detections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    frame_id bigint NOT NULL REFERENCES public.vad_sampled_frames(id) ON DELETE CASCADE,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    track_id bigint NULL REFERENCES public.vad_tracks(id) ON DELETE SET NULL,
    detector_name text NOT NULL,
    detector_model_version text NULL,
    class_name text NOT NULL DEFAULT 'person',
    class_id integer NULL,
    confidence double precision NULL,
    bbox_xyxy_json jsonb NOT NULL,
    bbox_norm_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    keypoints_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    ground_point_image_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    ground_point_world_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    detection_features_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.vad_tubelets (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    track_id bigint NULL REFERENCES public.vad_tracks(id) ON DELETE SET NULL,
    route_name text NOT NULL,
    tubelet_key text NULL UNIQUE,
    start_frame_id bigint NULL REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL,
    end_frame_id bigint NULL REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL,
    frame_sample_ids bigint[] NOT NULL DEFAULT ARRAY[]::bigint[],
    detection_ids bigint[] NOT NULL DEFAULT ARRAY[]::bigint[],
    window_start_ts timestamptz NOT NULL,
    window_end_ts timestamptz NOT NULL,
    sample_fps numeric(6,3) NOT NULL,
    tubelet_frames integer NOT NULL,
    stride integer NOT NULL,
    duration_sec numeric(10,4) NULL,
    bbox_sequence_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    trajectory_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    feature_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    dominant_features_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_tubelets_route_name_chk CHECK (route_name IN ('pose','deep','homography_macro','raft','shared','debug')),
    CONSTRAINT vad_tubelets_temporal_chk CHECK (window_end_ts >= window_start_ts AND sample_fps > 0 AND tubelet_frames > 0 AND stride > 0)
);

CREATE TABLE public.vad_tubelet_embeddings (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tubelet_id bigint NOT NULL REFERENCES public.vad_tubelets(id) ON DELETE CASCADE,
    gate_model_version_id bigint NULL REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL,
    embedding_name text NOT NULL DEFAULT 'videomae_cls_mean',
    embedding_dim integer NOT NULL DEFAULT 768,
    embedding vector(768) NULL,
    embedding_json jsonb NOT NULL DEFAULT '[]'::jsonb,
    normalization text NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_tubelet_embeddings_unique UNIQUE (tubelet_id, gate_model_version_id, embedding_name),
    CONSTRAINT vad_tubelet_embeddings_dim_chk CHECK (embedding_dim > 0)
);

-- ---------------------------------------------------------------------------
-- Independent gate scores/events and case grouping.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_gate_scores (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tubelet_id bigint NOT NULL REFERENCES public.vad_tubelets(id) ON DELETE CASCADE,
    gate_name text NOT NULL REFERENCES public.vad_gate_definitions(gate_name) ON DELETE RESTRICT,
    gate_model_version_id bigint NULL REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL,
    threshold_id bigint NULL REFERENCES public.vad_gate_thresholds(id) ON DELETE SET NULL,
    score_ts timestamptz NOT NULL DEFAULT now(),
    raw_score double precision NULL,
    smoothed_score double precision NULL,
    normalized_score double precision NULL,
    threshold_key text NULL,
    threshold_value double precision NULL,
    threshold_percentile numeric(7,3) NULL,
    score_direction text NOT NULL DEFAULT 'higher_is_more_anomalous',
    above_threshold boolean NOT NULL DEFAULT false,
    persistence_window integer NULL,
    persistence_required_hits integer NULL,
    persistence_hits integer NULL,
    persistent boolean NOT NULL DEFAULT false,
    trigger_recommendation text NOT NULL DEFAULT 'none',
    feature_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    dominant_features_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    score_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_gate_scores_trigger_recommendation_chk CHECK (trigger_recommendation IN ('none','evidence_only','reasoning_candidate','reasoning_required')),
    CONSTRAINT vad_gate_scores_score_direction_chk CHECK (score_direction IN ('higher_is_more_anomalous','lower_is_more_anomalous'))
);

CREATE TABLE public.vad_gate_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    track_id bigint NULL REFERENCES public.vad_tracks(id) ON DELETE SET NULL,
    gate_name text NOT NULL REFERENCES public.vad_gate_definitions(gate_name) ON DELETE RESTRICT,
    gate_model_version_id bigint NULL REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL,
    start_tubelet_id bigint NULL REFERENCES public.vad_tubelets(id) ON DELETE SET NULL,
    peak_tubelet_id bigint NULL REFERENCES public.vad_tubelets(id) ON DELETE SET NULL,
    end_tubelet_id bigint NULL REFERENCES public.vad_tubelets(id) ON DELETE SET NULL,
    start_score_id bigint NULL REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL,
    peak_score_id bigint NULL REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL,
    end_score_id bigint NULL REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL,
    event_key text NULL UNIQUE,
    status text NOT NULL DEFAULT 'open',
    severity text NOT NULL DEFAULT 'unknown',
    event_type text NOT NULL DEFAULT 'other',
    start_ts timestamptz NOT NULL,
    peak_ts timestamptz NULL,
    end_ts timestamptz NULL,
    peak_score double precision NULL,
    threshold_value double precision NULL,
    persistence_hits integer NULL,
    persistence_window integer NULL,
    reason_when_fired text NULL,
    trigger_policy_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    feature_values_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    dominant_features_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    quality_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_gate_events_status_chk CHECK (status IN ('open','merged_into_case','closed','discarded','debug')),
    CONSTRAINT vad_gate_events_severity_chk CHECK (severity IN ('unknown','low','medium','high','critical')),
    CONSTRAINT vad_gate_events_temporal_chk CHECK (end_ts IS NULL OR end_ts >= start_ts)
);

CREATE TABLE public.vad_anomaly_cases (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_key text NOT NULL UNIQUE,
    session_id bigint NOT NULL REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE,
    stream_id bigint NOT NULL REFERENCES public.vad_streams(id) ON DELETE CASCADE,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    primary_track_id bigint NULL REFERENCES public.vad_tracks(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'open',
    severity text NOT NULL DEFAULT 'unknown',
    case_type text NOT NULL DEFAULT 'unknown',
    start_ts timestamptz NOT NULL,
    peak_ts timestamptz NULL,
    end_ts timestamptz NULL,
    primary_gate_name text NULL,
    gate_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    score_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    evidence_bundle_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    case_summary text NULL,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_anomaly_cases_status_chk CHECK (status IN ('open','evidence_ready','reasoning_queued','reasoning_done','confirmed','dismissed','needs_review','archived','debug')),
    CONSTRAINT vad_anomaly_cases_severity_chk CHECK (severity IN ('unknown','low','medium','high','critical')),
    CONSTRAINT vad_anomaly_cases_temporal_chk CHECK (end_ts IS NULL OR end_ts >= start_ts)
);

CREATE TABLE public.vad_case_gate_events (
    case_id bigint NOT NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    gate_event_id bigint NOT NULL REFERENCES public.vad_gate_events(id) ON DELETE CASCADE,
    relation text NOT NULL DEFAULT 'member',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, gate_event_id),
    CONSTRAINT vad_case_gate_events_relation_chk CHECK (relation IN ('primary','supporting','overlap','member','debug'))
);

CREATE TABLE public.vad_case_reviews (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id bigint NOT NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    reviewer text NULL,
    decision text NOT NULL,
    corrected_event_type text NULL,
    corrected_severity text NULL,
    notes text NULL,
    review_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_case_reviews_decision_chk CHECK (decision IN ('confirmed','dismissed','uncertain','calibration_feedback','needs_more_evidence'))
);

-- ---------------------------------------------------------------------------
-- Evidence media and reasoning.
-- ---------------------------------------------------------------------------
CREATE TABLE public.vad_media_objects (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id bigint NULL REFERENCES public.vad_stream_sessions(id) ON DELETE SET NULL,
    stream_id bigint NULL REFERENCES public.vad_streams(id) ON DELETE SET NULL,
    camera_id bigint NULL REFERENCES public.cameras(id) ON DELETE SET NULL,
    case_id bigint NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    gate_event_id bigint NULL REFERENCES public.vad_gate_events(id) ON DELETE SET NULL,
    tubelet_id bigint NULL REFERENCES public.vad_tubelets(id) ON DELETE SET NULL,
    frame_id bigint NULL REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL,
    media_role text NOT NULL,
    media_type text NOT NULL,
    storage_backend text NOT NULL DEFAULT 'minio',
    bucket text NULL,
    object_key text NULL,
    uri text NULL,
    content_type text NULL,
    size_bytes bigint NULL,
    width integer NULL,
    height integer NULL,
    duration_sec numeric(10,4) NULL,
    sha256 text NULL,
    captured_at timestamptz NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT vad_media_objects_media_type_chk CHECK (media_type IN ('image','video','json','plot','other')),
    CONSTRAINT vad_media_objects_backend_chk CHECK (storage_backend IN ('minio','local_debug','external','none'))
);

ALTER TABLE public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_debug_media_fk
    FOREIGN KEY (debug_media_object_id) REFERENCES public.vad_media_objects(id) ON DELETE SET NULL;

CREATE TABLE public.vad_evidence_items (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id bigint NOT NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    gate_event_id bigint NULL REFERENCES public.vad_gate_events(id) ON DELETE SET NULL,
    media_object_id bigint NULL REFERENCES public.vad_media_objects(id) ON DELETE SET NULL,
    evidence_role text NOT NULL,
    evidence_rank integer NOT NULL DEFAULT 0,
    description text NULL,
    included_in_reasoning boolean NOT NULL DEFAULT true,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.vad_reasoning_jobs (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_id bigint NOT NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'queued',
    reasoner_type text NOT NULL DEFAULT 'vlm_llm',
    vlm_model text NULL,
    llm_model text NULL,
    priority text NOT NULL DEFAULT 'normal',
    input_bundle_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    prompt_version text NULL,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    queued_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    error_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT vad_reasoning_jobs_status_chk CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    CONSTRAINT vad_reasoning_jobs_priority_chk CHECK (priority IN ('low','normal','high','urgent'))
);

CREATE TABLE public.vad_reasoning_results (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reasoning_job_id bigint NOT NULL REFERENCES public.vad_reasoning_jobs(id) ON DELETE CASCADE,
    case_id bigint NOT NULL REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE,
    alert_decision text NULL,
    severity text NULL,
    event_type text NULL,
    confidence double precision NULL,
    visual_evidence text NULL,
    reasoning_summary text NULL,
    decision_reason text NULL,
    raw_vlm_output text NULL,
    raw_llm_output text NULL,
    structured_output_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    matched_rules_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    uncertainty_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT vad_reasoning_results_alert_chk CHECK (alert_decision IS NULL OR alert_decision IN ('YES','NO','UNCERTAIN')),
    CONSTRAINT vad_reasoning_results_severity_chk CHECK (severity IS NULL OR severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    CONSTRAINT vad_reasoning_results_confidence_chk CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

-- ---------------------------------------------------------------------------
-- Indexes for runtime queries.
-- ---------------------------------------------------------------------------
CREATE INDEX vad_stream_sessions_stream_status_idx ON public.vad_stream_sessions(stream_id, status, started_at DESC);
CREATE INDEX vad_sampled_frames_session_time_idx ON public.vad_sampled_frames(session_id, captured_at DESC);
CREATE INDEX vad_tracks_session_tracker_idx ON public.vad_tracks(session_id, tracker_name, tracker_track_id);
CREATE INDEX vad_tracks_session_time_idx ON public.vad_tracks(session_id, first_seen_at, last_seen_at);
CREATE INDEX vad_detections_frame_idx ON public.vad_detections(frame_id);
CREATE INDEX vad_detections_track_time_idx ON public.vad_detections(track_id, created_at);
CREATE INDEX vad_tubelets_track_route_time_idx ON public.vad_tubelets(track_id, route_name, window_start_ts);
CREATE INDEX vad_gate_scores_tubelet_gate_idx ON public.vad_gate_scores(tubelet_id, gate_name);
CREATE INDEX vad_gate_scores_gate_time_idx ON public.vad_gate_scores(gate_name, score_ts DESC);
CREATE INDEX vad_gate_events_session_time_idx ON public.vad_gate_events(session_id, start_ts DESC);
CREATE INDEX vad_gate_events_gate_time_idx ON public.vad_gate_events(gate_name, start_ts DESC);
CREATE INDEX vad_anomaly_cases_status_time_idx ON public.vad_anomaly_cases(status, start_ts DESC);
CREATE INDEX vad_media_objects_case_role_idx ON public.vad_media_objects(case_id, media_role);
CREATE INDEX vad_evidence_items_case_role_idx ON public.vad_evidence_items(case_id, evidence_role, evidence_rank);
CREATE INDEX vad_reasoning_jobs_status_queue_idx ON public.vad_reasoning_jobs(status, queued_at);

-- JSONB indexes for flexible feature/metadata search.
CREATE INDEX vad_tubelets_feature_values_gin_idx ON public.vad_tubelets USING gin (feature_values_json);
CREATE INDEX vad_gate_scores_dominant_features_gin_idx ON public.vad_gate_scores USING gin (dominant_features_json);
CREATE INDEX vad_gate_events_metadata_gin_idx ON public.vad_gate_events USING gin (metadata_json);
CREATE INDEX vad_anomaly_cases_gate_summary_gin_idx ON public.vad_anomaly_cases USING gin (gate_summary_json);

-- ---------------------------------------------------------------------------
-- Seed gate catalog and currently selected model contracts.
-- ---------------------------------------------------------------------------

INSERT INTO public.vad_gate_definitions
(gate_name, display_name, route_name, primary_sample_fps, role, default_trigger_policy, reasoning_policy, is_primary_trigger, is_enabled, config_json)
VALUES
('deep', 'VideoMAE Deep Gate', 'deep', 2.5, 'semantic_spatiotemporal', 'persistent_above_threshold', 'always_when_persistent', true, true, '{"description":"VideoMAE-based semantic/spatio-temporal anomaly detector"}'::jsonb),
('pose', 'YOLO Pose Micro Gate', 'pose', 5.0, 'pose_articulation', 'persistent_above_threshold', 'reason_when_meaningful_or_severe', true, true, '{"description":"Detects rare pose articulation such as collapse/crouch/reaching/asymmetry/tampering-like motion"}'::jsonb),
('homography_macro', 'Homography Macro Motion Gate', 'homography_macro', 2.5, 'floor_plane_motion', 'persistent_or_severe_or_overlap', 'only_if_severe_persistent_or_overlapping', true, true, '{"description":"Floor-plane speed/acceleration/direction/straightness/pacing gate"}'::jsonb),
('raft', 'RAFT Optical Flow Gate', 'raft', 2.5, 'optical_flow_evidence', 'evidence_only', 'evidence_only_for_now', false, false, '{"description":"Optional optical-flow evidence branch, not a primary trigger yet"}'::jsonb);


INSERT INTO public.vad_gate_model_versions
(gate_name, version, model_name, model_type, feature_dim, score_direction, score_method, normalization, distance_metric, sample_fps, tubelet_frames, stride, window_duration_sec, artifact_refs_json, feature_schema_json, training_config_json, inference_config_json, validation_report_json, notes, is_active, activated_at)
VALUES
('deep', 'deep_branch_artifacts_v3_gaussian_k5_p99_5', 'deep_knn_l2', 'KNN on L2-normalized VideoMAE embeddings', 768, 'higher_is_more_anomalous', 'mean_distance_to_k_neighbors', 'l2', 'euclidean', 2.5, 16, 5, 6.4,
 '{"artifact_group":"deep_branch_artifacts_v3_gaussian","artifact_base_env":"VAD_DEEP_ARTIFACT_DIR","default_container_dir":"/models/vad/deep","mount_note":"Map the host artifact folder into this container path with Docker Compose; do not store host-local Windows paths in the database.","required_files":{"knn_index":"models/03_knn_index.joblib","thresholds":"04_thresholds.json","calibration_scores":"scores/04_calibration_scores.csv","normal_test_scores_raw":"scores/05_normal_test_scores.csv","normal_test_scores_with_gaussian":"scores/05_normal_test_scores_with_gaussian.csv","top_abnormal_normal_tubelets":"06_top_abnormal_normal_tubelets.csv","videomae_suitability_report":"07_videomae_suitability_report.json"}}'::jsonb,
 '{"embedding_dim": 768, "feature_names": ["videomae_embedding_768"], "normalization": "l2"}'::jsonb,
 '{"model_config": {"model_name": "deep_knn_l2", "train_rows": 7921, "embedding_dim": 768, "normalization": "l2", "distance_metric": "euclidean", "k_values": [1, 3, 5, 10, 20], "primary_k": 5, "score_method": "mean_distance_to_k_neighbors", "note": "Thresholds are calibrated on calibration videos only, not train rows."}, "run_config": {"expected_embedding_dim": 768, "split_unit": "video_id", "train_ratio": 0.7, "calibration_ratio": 0.15, "normal_test_ratio": 0.15, "random_seed": 42, "normalization": "l2", "l2_epsilon": 1e-12, "k_values": [1, 3, 5, 10, 20], "primary_k": 5, "distance_metric": "euclidean", "score_method": "mean_distance_to_k_neighbors", "threshold_percentiles": [95.0, 97.5, 99.0, 99.5, 99.7, 99.9], "primary_threshold_percentile": 99.5, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "gaussian_sigmas": [1.0, 2.0, 3.0], "selected_gaussian_sigma": 2.0, "scoring_batch_size": 4096, "top_n_abnormal_normal": 100}, "thresholds": {"k1": {"p95": 0.10558874905109406, "p97_5": 0.11621347814798355, "p99": 0.13479025661945343, "p99_5": 0.1602112501859665, "p99_7": 0.16695861518383026, "p99_9": 0.17240621149539948}, "k3": {"p95": 0.10885053873062134, "p97_5": 0.11875641345977783, "p99": 0.13885599374771118, "p99_5": 0.1647091656923294, "p99_7": 0.1701613962650299, "p99_9": 0.1759432554244995}, "k5": {"p95": 0.11092901974916458, "p97_5": 0.12072882056236267, "p99": 0.141691192984581, "p99_5": 0.16680973768234253, "p99_7": 0.1729036420583725, "p99_9": 0.178872212767601}, "k10": {"p95": 0.1151377335190773, "p97_5": 0.12458942085504532, "p99": 0.1459609568119049, "p99_5": 0.17245981097221375, "p99_7": 0.17805984616279602, "p99_9": 0.18337643146514893}, "k20": {"p95": 0.12067573517560959, "p97_5": 0.13069620728492737, "p99": 0.15375971794128418, "p99_5": 0.17991457879543304, "p99_7": 0.18479764461517334, "p99_9": 0.19080431759357452}}}'::jsonb,
 '{"selected_k": 5, "selected_threshold_key": "p99_5", "smoothing_or_event_logic": {"method": "gaussian_then_persistence", "gaussian_sigma_tubelets": 2.0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0}}'::jsonb,
 '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb,
 'Seeded from uploaded deep gate normal model artifacts. Artifact refs are env/container-safe, not host-local paths.', true, now()),
('pose', 'pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5', 'pose_micro_gmm_gate', 'RobustScaler + GMM on pose micro features', 30, 'higher_is_more_anomalous', 'negative_gmm_log_likelihood', NULL, NULL, 5.0, 24, 6, 4.8,
 '{"artifact_group":"pose_micro_gmm_gate_v2_yolov8s_5fps_24f_s6","artifact_base_env":"VAD_POSE_ARTIFACT_DIR","default_container_dir":"/models/vad/pose","mount_note":"Map the host artifact folder into this container path with Docker Compose; do not store host-local Windows paths in the database.","required_files":{"scaler":"models/pose_robust_scaler.joblib","gmm":"models/pose_gmm_components_5.joblib"},"components":5,"covariance_type":"full","reg_covar":1e-06,"score_definition":"negative GMM log likelihood; higher = more abnormal","threshold":70.18459395136654,"threshold_percentile":99.5}'::jsonb,
 '{"feature_dim": 30, "feature_names": ["pose_valid_frame_ratio", "pose_mean_keypoint_conf", "pose_valid_keypoint_ratio_mean", "pose_wrist_speed_mean", "pose_wrist_speed_p95", "pose_wrist_speed_max", "pose_ankle_speed_mean", "pose_ankle_speed_p95", "pose_ankle_speed_max", "pose_limb_speed_mean", "pose_limb_speed_p95", "pose_limb_speed_max", "pose_limb_accel_mean", "pose_limb_accel_p95", "pose_limb_accel_max", "pose_torso_center_speed_mean", "pose_torso_center_speed_p95", "pose_torso_center_speed_max", "pose_body_angle_change_mean", "pose_body_angle_change_p95", "pose_body_angle_change_max", "pose_crouch_change_mean", "pose_crouch_change_p95", "pose_crouch_change_max", "pose_arm_extension_change_mean", "pose_arm_extension_change_p95", "pose_arm_extension_change_max", "pose_asymmetry_motion_mean", "pose_asymmetry_motion_p95", "pose_asymmetry_motion_max"], "feature_extractor": {"model": "yolov8s-pose.pt", "device_used_for_extraction": "cuda", "imgsz": 256, "conf": 0.25, "kpt_conf": 0.3, "crop_pad_ratio": 0.25, "min_crop_size": 192, "target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8, "feature_dim": 30, "feature_names": ["pose_valid_frame_ratio", "pose_mean_keypoint_conf", "pose_valid_keypoint_ratio_mean", "pose_wrist_speed_mean", "pose_wrist_speed_p95", "pose_wrist_speed_max", "pose_ankle_speed_mean", "pose_ankle_speed_p95", "pose_ankle_speed_max", "pose_limb_speed_mean", "pose_limb_speed_p95", "pose_limb_speed_max", "pose_limb_accel_mean", "pose_limb_accel_p95", "pose_limb_accel_max", "pose_torso_center_speed_mean", "pose_torso_center_speed_p95", "pose_torso_center_speed_max", "pose_body_angle_change_mean", "pose_body_angle_change_p95", "pose_body_angle_change_max", "pose_crouch_change_mean", "pose_crouch_change_p95", "pose_crouch_change_max", "pose_arm_extension_change_mean", "pose_arm_extension_change_p95", "pose_arm_extension_change_max", "pose_asymmetry_motion_mean", "pose_asymmetry_motion_p95", "pose_asymmetry_motion_max"], "important": "Production inference must use the same pose model and feature extraction settings used for calibration."}}'::jsonb,
 '{"thresholds": {"model": "pose_micro_gmm", "feature_source": "artifact://pose_micro_50vid_v2_yolov8s_5fps_24f_s6", "threshold_source": "calibration split only", "threshold_percentile": 99.5, "primary_components": 5, "primary_threshold": 70.18459395136654, "thresholds_by_components": {"1": 270.04709013829245, "2": 118.34844039099255, "3": 82.17522931844896, "5": 70.18459395136654, "8": 67.95033581957631, "10": 69.77673772337575}, "score_definition": "negative GMM log likelihood; higher = more abnormal", "split_info": {"seed": 42, "split_unit": "video_id", "num_videos_total": 44, "num_train_videos": 31, "num_calibration_videos": 7, "num_normal_test_videos": 6, "train_videos": ["20260315_140839_tp00037", "20260315_164044_tp00039", "20260316_091611_tp00040", "20260316_103018_tp00041", "20260316_113834_tp00042", "20260316_135625_tp00044", "20260316_162442_tp00046", "20260317_090032_tp00047", "20260317_132711_tp00051", "20260317_143753_tp00052", "20260317_155412_tp00053", "20260318_081214_tp00054", "20260318_105945_tp00056", "20260318_121418_tp00057", "20260318_144928_tp00059", "20260318_160632_tp00060", "20260319_114626_tp00063", "20260328_083038_tp00068", "20260328_124451_tp00069", "20260329_091145_tp00070", "20260329_102853_tp00071", "20260329_113749_tp00072", "20260329_125235_tp00073", "20260329_140358_tp00074", "20260329_163101_tp00076", "20260330_084016_tp00077", "20260330_113045_tp00079", "20260330_124800_tp00080", "20260330_151820_tp00082", "20260330_163251_tp00083", "20260331_100731_tp00085"], "calibration_videos": ["20260315_093203_tp00034", "20260317_101644_tp00048", "20260317_122808_tp00050", "20260318_094559_tp00055", "20260318_133129_tp00058", "20260330_140516_tp00081", "20260331_083223_tp00084"], "normal_test_videos": ["20260315_104219_tp00035", "20260315_130536_tp00036", "20260316_124453_tp00043", "20260317_112759_tp00049", "20260329_151410_tp00075", "20260330_101231_tp00078"], "tubelets_by_split": {"train": 12451, "calibration": 10931, "normal_test": 9113}}, "cleaning_report": {"total_rows": 32755, "dropped_nonfinite": 0, "dropped_negative": 0, "dropped_all_zero": 135, "dropped_pose_valid_frame_ratio_zero": 260, "kept_rows": 32495}, "feature_names": ["pose_valid_frame_ratio", "pose_mean_keypoint_conf", "pose_valid_keypoint_ratio_mean", "pose_wrist_speed_mean", "pose_wrist_speed_p95", "pose_wrist_speed_max", "pose_ankle_speed_mean", "pose_ankle_speed_p95", "pose_ankle_speed_max", "pose_limb_speed_mean", "pose_limb_speed_p95", "pose_limb_speed_max", "pose_limb_accel_mean", "pose_limb_accel_p95", "pose_limb_accel_max", "pose_torso_center_speed_mean", "pose_torso_center_speed_p95", "pose_torso_center_speed_max", "pose_body_angle_change_mean", "pose_body_angle_change_p95", "pose_body_angle_change_max", "pose_crouch_change_mean", "pose_crouch_change_p95", "pose_crouch_change_max", "pose_arm_extension_change_mean", "pose_arm_extension_change_p95", "pose_arm_extension_change_max", "pose_asymmetry_motion_mean", "pose_asymmetry_motion_p95", "pose_asymmetry_motion_max"], "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8, "extraction_summary_expected_sample_fps": 5.0, "extraction_summary_expected_tubelet_frames": 24, "extraction_summary_expected_stride": 6, "extraction_summary_fps_tolerance": 0.35, "extraction_summary_allow_sample_gaps": false}}, "normality_model": {"scaler": "/models/vad/pose/models/pose_robust_scaler.joblib", "gmm": "/models/vad/pose/models/pose_gmm_components_5.joblib", "components": 5, "covariance_type": "full", "reg_covar": 1e-06, "score_definition": "negative GMM log likelihood; higher = more abnormal", "threshold": 70.18459395136654, "threshold_percentile": 99.5}}'::jsonb,
 '{"postprocessing": {"smoothing_sigma": 2.0, "persistence_hits": 3, "persistence_window": 5, "min_event_gap_sec": 5.0}, "decision": {"gate_fires_if": "smoothed pose score exceeds threshold persistently", "final_pipeline_logic": "Independent gate. Do not fuse raw score with deep or velocity branches yet."}}'::jsonb,
 '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb,
 'Seeded from uploaded pose gate normal model artifacts. Artifact refs are env/container-safe, not host-local paths.', true, now()),
('homography_macro', 'homography_macro_stage3_pose_gmm_c5_p99_5', 'homography_macro_gate', 'RobustScaler + GMM on floor-plane macro motion features', 7, 'higher_is_more_anomalous', 'negative_gmm_log_likelihood', 'robust_scaler', NULL, 2.5, 16, 8, 6.4,
 '{"artifact_group":"homography_macro_gmm_gate_stage3_pose","artifact_base_env":"VAD_HOMOGRAPHY_MACRO_ARTIFACT_DIR","default_container_dir":"/models/vad/homography_macro","mount_note":"Map the host artifact folder into this container path with Docker Compose; do not store host-local Windows paths in the database.","required_files":{"scaler":"models/macro_robust_scaler.joblib","pca":null,"gmm":"models/macro_gmm_components_5.joblib","feature_names":"homography_macro_feature_names.json","recommended_gate":"09_recommended_macro_gate.json","thresholds":"04_macro_thresholds.json"}}'::jsonb,
 '{"selected_features": ["macro_speed_mean_mps", "macro_speed_median_mps", "macro_speed_p95_mps", "macro_accel_p95_mps2", "macro_straightness_ratio", "macro_direction_change_mean_rad", "macro_stationary_step_ratio"], "all_features": {"schema_version": "homography_macro_features_v1.0", "feature_names": ["macro_duration_sec", "macro_displacement_m", "macro_path_length_m", "macro_straightness_ratio", "macro_speed_mean_mps", "macro_speed_median_mps", "macro_speed_std_mps", "macro_speed_max_mps", "macro_speed_p95_mps", "macro_vx_mean_mps", "macro_vy_mean_mps", "macro_vx_std_mps", "macro_vy_std_mps", "macro_accel_mean_mps2", "macro_accel_median_mps2", "macro_accel_max_mps2", "macro_accel_p95_mps2", "macro_direction_change_mean_rad", "macro_direction_change_max_rad", "macro_stationary_step_ratio", "macro_valid_point_ratio", "macro_valid_step_ratio", "macro_mean_dt_sec", "macro_max_dt_sec", "macro_world_x_min_m", "macro_world_x_max_m", "macro_world_y_min_m", "macro_world_y_max_m"], "feature_dim": 28, "units": "meters, seconds, radians where indicated"}, "expected_point_field": "ground_points_xy", "groundpoint_policy": "ankle_midpoint_or_single_ankle_else_freeze_last_valid_else_bbox_bottom"}'::jsonb,
 '{"recommended": {"schema_version": "homography_macro_gmm_gate_stage3_pose_v1.1", "branch_name": "homography_macro_gate", "model_type": "RobustScaler + GMM", "input_features": ["macro_speed_mean_mps", "macro_speed_median_mps", "macro_speed_p95_mps", "macro_accel_p95_mps2", "macro_straightness_ratio", "macro_direction_change_mean_rad", "macro_stationary_step_ratio"], "expected_point_field": "ground_points_xy", "expected_groundpoint_policy": "ankle_midpoint_or_single_ankle_else_freeze_last_valid_else_bbox_bottom", "offline_feature_contract": {"trajectory_smoothing": "median_savgol", "trajectory_smoothing_window": 5, "trajectory_smoothing_polyorder": 2, "max_plausible_speed_mps": 3.0, "max_plausible_accel_mps2": 6.0}, "split_unit": "video_id", "split": {"train": ["20260330_084016_tp00077", "20260316_124453_tp00043", "20260331_100731_tp00085", "20260318_105945_tp00056", "20260316_091611_tp00040", "20260330_163251_tp00083", "20260317_155412_tp00053", "20260316_103018_tp00041", "20260329_091145_tp00070", "20260329_125235_tp00073", "20260318_144928_tp00059", "20260318_133129_tp00058", "20260330_124800_tp00080", "20260328_124451_tp00069", "20260317_090032_tp00047", "20260329_113749_tp00072", "20260329_163101_tp00076", "20260329_151410_tp00075", "20260329_102853_tp00071", "20260316_113834_tp00042", "20260329_140358_tp00074", "20260317_101644_tp00048", "20260328_083038_tp00068", "20260316_162442_tp00046", "20260330_151820_tp00082", "20260318_160632_tp00060", "20260318_121418_tp00057", "20260315_164044_tp00039", "20260315_093203_tp00034"], "calibration": ["20260317_143753_tp00052", "20260318_081214_tp00054", "20260330_113045_tp00079", "20260317_112759_tp00049", "20260317_132711_tp00051", "20260331_083223_tp00084"], "normal_test": ["20260315_130536_tp00036", "20260330_140516_tp00081", "20260330_101231_tp00078", "20260315_104219_tp00035", "20260317_122808_tp00050", "20260316_135625_tp00044"]}, "split_counts": {"train": {"videos": 29, "tubelets": 6411}, "calibration": {"videos": 6, "tubelets": 2045}, "normal_test": {"videos": 6, "tubelets": 4483}}, "primary_components": 5, "covariance_type": "full", "reg_covar": 1e-06, "use_pca": false, "pca_components": null, "smoothing_sigma": 2.0, "threshold_source": "calibration split only", "threshold_percentile": 99.5, "threshold": 12.774831137922204, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "normal_test_result": {"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}, "verdict": "usable_but_needs_visual_review", "model_paths": {"scaler": "/models/vad/homography_macro/models/macro_robust_scaler.joblib", "pca": null, "gmm": "/models/vad/homography_macro/models/macro_gmm_components_5.joblib"}}, "thresholds": {"schema_version": "homography_macro_gmm_gate_stage3_pose_v1.1", "thresholds": {"p95": {"percentile": 95.0, "threshold": 8.735422457226273, "score_source": "calibration_macro_score_smooth"}, "p97_5": {"percentile": 97.5, "threshold": 10.127714039602356, "score_source": "calibration_macro_score_smooth"}, "p99": {"percentile": 99.0, "threshold": 12.039008365136333, "score_source": "calibration_macro_score_smooth"}, "p99_5": {"percentile": 99.5, "threshold": 12.774831137922204, "score_source": "calibration_macro_score_smooth"}, "p99_7": {"percentile": 99.7, "threshold": 14.572581933847824, "score_source": "calibration_macro_score_smooth"}, "p99_9": {"percentile": 99.9, "threshold": 16.587504146641248, "score_source": "calibration_macro_score_smooth"}}, "primary_threshold_key": "p99_5", "primary_threshold_percentile": 99.5, "primary_threshold": 12.774831137922204, "score_direction": "higher_is_more_anomalous", "threshold_source": "calibration_macro_score_smooth"}}'::jsonb,
 '{"offline_feature_contract": {"trajectory_smoothing": "median_savgol", "trajectory_smoothing_window": 5, "trajectory_smoothing_polyorder": 2, "max_plausible_speed_mps": 3.0, "max_plausible_accel_mps2": 6.0}, "smoothing_sigma": 2.0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0}'::jsonb,
 '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb,
 'Seeded from uploaded homography/macro normal model artifacts.', true, now());

INSERT INTO public.vad_gate_thresholds
(gate_model_version_id, threshold_key, threshold_percentile, threshold_value, score_column, score_direction, threshold_source, smoothing_method, smoothing_sigma, persistence_window, persistence_required_hits, min_event_gap_sec, is_primary, trigger_policy_json, calibration_report_json)
VALUES
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p95', 95.0, 0.11092901974916458, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "deep", "threshold_key": "p95", "primary": false}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p97_5', 97.5, 0.12072882056236267, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "deep", "threshold_key": "p97_5", "primary": false}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p99', 99.0, 0.141691192984581, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "deep", "threshold_key": "p99", "primary": false}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p99_5', 99.5, 0.16680973768234253, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, true, '{"gate": "deep", "threshold_key": "p99_5", "primary": true}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p99_7', 99.7, 0.1729036420583725, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "deep", "threshold_key": "p99_7", "primary": false}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='deep' AND version='deep_branch_artifacts_v3_gaussian_k5_p99_5'), 'p99_9', 99.9, 0.178872212767601, 'deep_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "deep", "threshold_key": "p99_9", "primary": false}'::jsonb, '{"k": 5, "score_mode": "gaussian_sigma_2", "gaussian_sigma_tubelets": 2.0, "threshold_percentile": 99.5, "threshold_key": "p99_5", "threshold_value": 0.16680973768234253, "normal_test_tubelets": 5821, "false_alarm_tubelets_before_persistence": 0, "false_alarm_rate_percent_before_persistence": 0.0, "max_false_alarm_streak_before_persistence": 0, "persistence_window": 5, "persistence_required_hits": 3, "min_event_gap_sec": 5.0, "false_alarm_events_after_persistence": 0}'::jsonb);

INSERT INTO public.vad_gate_thresholds
(gate_model_version_id, threshold_key, threshold_percentile, threshold_value, score_column, score_direction, threshold_source, smoothing_method, smoothing_sigma, persistence_window, persistence_required_hits, min_event_gap_sec, is_primary, trigger_policy_json, calibration_report_json)
VALUES
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'p99_5', 99.5, 70.18459395136654, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, true, '{"gate": "pose", "threshold_key": "p99_5", "primary": true}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_1_p99_5', 99.5, 270.04709013829245, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_1_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_2_p99_5', 99.5, 118.34844039099255, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_2_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_3_p99_5', 99.5, 82.17522931844896, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_3_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_5_p99_5', 99.5, 70.18459395136654, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_5_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_8_p99_5', 99.5, 67.95033581957631, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_8_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='pose' AND version='pose_micro_gmm_v2_yolov8s_5fps_24f_s6_c5_p99_5'), 'components_10_p99_5', 99.5, 69.77673772337575, 'pose_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "pose", "threshold_key": "components_10_p99_5", "primary": false}'::jsonb, '{"verdict": "usable_but_needs_visual_review", "important_interpretation": "This only proves behavior on held-out normal videos. It does not prove abnormal detection yet. Next step is visual review of top normal-test pose outliers and abnormal-video testing.", "feature_shape": [32495, 30], "metadata_rows": 32495, "extraction_failed_rows": null, "primary_components": 5, "primary_threshold": 70.18459395136654, "pose_temporal_config": {"target_sample_fps": 5.0, "tubelet_frames": 24, "stride": 6, "target_window_duration_sec": 4.8}, "normal_test_report": {"tubelets": 9113, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 79, "false_alarm_rate_before_persistence": 0.008668934489191265, "false_alarm_tubelets_after_smoothing": 27, "false_alarm_rate_after_smoothing": 0.0029628003950400526, "false_alarm_tubelets_after_persistence": 17, "false_alarm_rate_after_persistence": 0.0018654669153955886, "false_alarm_events_after_persistence": 4, "videos": 6, "tracks": 257}, "calibration_report": {"tubelets": 10931, "threshold": 70.18459395136654, "false_alarm_tubelets_before_persistence": 55, "false_alarm_rate_before_persistence": 0.0050315616137590335, "false_alarm_tubelets_after_smoothing": 45, "false_alarm_rate_after_smoothing": 0.0041167322294392095, "false_alarm_tubelets_after_persistence": 38, "false_alarm_rate_after_persistence": 0.0034763516604153326, "false_alarm_events_after_persistence": 8, "videos": 7, "tracks": 221}, "speed_note": "Pose extraction completed with model=yolov8s-pose.pt, tubelets_per_sec=4.531097406419914.", "pose_quality_note": "Rows with all-zero features or zero pose_valid_frame_ratio were dropped before training. Top outliers must be visually reviewed because pose anomalies can be caused by keypoint noise, occlusion, or bad crops."}'::jsonb);

INSERT INTO public.vad_gate_thresholds
(gate_model_version_id, threshold_key, threshold_percentile, threshold_value, score_column, score_direction, threshold_source, smoothing_method, smoothing_sigma, persistence_window, persistence_required_hits, min_event_gap_sec, is_primary, trigger_policy_json, calibration_report_json)
VALUES
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p95', 95.0, 8.735422457226273, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "homography_macro", "threshold_key": "p95", "primary": false}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p97_5', 97.5, 10.127714039602356, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "homography_macro", "threshold_key": "p97_5", "primary": false}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p99', 99.0, 12.039008365136333, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "homography_macro", "threshold_key": "p99", "primary": false}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p99_5', 99.5, 12.774831137922204, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, true, '{"gate": "homography_macro", "threshold_key": "p99_5", "primary": true}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p99_7', 99.7, 14.572581933847824, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "homography_macro", "threshold_key": "p99_7", "primary": false}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb),
((SELECT id FROM public.vad_gate_model_versions WHERE gate_name='homography_macro' AND version='homography_macro_stage3_pose_gmm_c5_p99_5'), 'p99_9', 99.9, 16.587504146641248, 'calibration_macro_score_smooth', 'higher_is_more_anomalous', 'calibration split only', 'gaussian_then_persistence', 2.0, 5, 3, 5.0, false, '{"gate": "homography_macro", "threshold_key": "p99_9", "primary": false}'::jsonb, '{"threshold_percentile": 99.5, "threshold": 12.774831137922204, "normal_test_tubelets": 4483.0, "false_alarm_tubelets_before_persistence": 30.0, "false_alarm_rate_before_persistence": 0.0066919473566807944, "false_alarm_events_after_persistence": 6.0, "normal_test_videos": 6.0, "normal_test_tracks": 214.0}'::jsonb);


INSERT INTO public.vad_schema_version(version, description, metadata_json)
VALUES (
    'vad_backend_direct_schema_final_v1',
    'Backend-direct RTSP VAD schema with independent deep, pose, homography/macro, and optional RAFT gates.',
    '{"source":"current_schema.sql + uploaded normal gate artifacts","old_kafka_jetson_path":"untouched","raw_frame_policy":"metadata only except anomaly/debug evidence"}'::jsonb
);

COMMIT;
