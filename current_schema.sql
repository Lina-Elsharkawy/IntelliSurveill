--
-- PostgreSQL database dump
--

\restrict xqtEDfS5bkevWwWbHEGbN6zYFRHq1r89YVJmJQCjhuqe7gq3DiQCD1RI7T1LJEb

-- Dumped from database version 16.11 (Debian 16.11-1.pgdg12+1)
-- Dumped by pg_dump version 16.11 (Debian 16.11-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: anomaly_candidates_set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.anomaly_candidates_set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: anomaly_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.anomaly_rules (
    id bigint NOT NULL,
    rule_text text NOT NULL,
    rule_type text DEFAULT 'anomalous'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_type text DEFAULT 'intrusion'::text,
    conditions jsonb DEFAULT '{}'::jsonb,
    source text DEFAULT 'Admin'::text,
    active boolean NOT NULL,
    CONSTRAINT anomaly_rules_rule_type_check CHECK ((rule_type = ANY (ARRAY['anomalous'::text, 'normal'::text, 'trigger'::text, 'suppress'::text])))
);


--
-- Name: anomaly_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.anomaly_rules ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.anomaly_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_logs (
    id bigint NOT NULL,
    user_email text NOT NULL,
    action text NOT NULL,
    resource text,
    resource_id text,
    details jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.audit_logs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cameras; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cameras (
    id bigint NOT NULL,
    name text,
    location text,
    stream_url text,
    lab_id integer
);


--
-- Name: cameras_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cameras ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.cameras_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: detected_people; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detected_people (
    id bigint NOT NULL,
    name text,
    additional_info text,
    employee_id bigint,
    visitor boolean DEFAULT false,
    visitor_id bigint
);


--
-- Name: detected_people_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.detected_people ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.detected_people_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: edge_devices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.edge_devices (
    id bigint NOT NULL,
    device_key text NOT NULL,
    name text,
    location text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: edge_devices_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.edge_devices ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.edge_devices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: employees; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.employees (
    id bigint NOT NULL,
    name text NOT NULL
);


--
-- Name: employees_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.employees ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.employees_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: entry_logs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entry_logs (
    id bigint NOT NULL,
    "timestamp" timestamp with time zone DEFAULT now(),
    detected_id bigint,
    camera_id bigint,
    authorized boolean,
    event_type text,
    location text,
    device_status text,
    image_video_ref text,
    processing_time interval,
    model_version text,
    quality_score double precision,
    best_similarity double precision,
    second_similarity double precision,
    margin double precision
);


--
-- Name: entry_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.entry_logs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.entry_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: face_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.face_embeddings (
    id bigint NOT NULL,
    detected_id bigint NOT NULL,
    entry_log_id bigint,
    embedding public.vector(512) NOT NULL,
    embedding_model text DEFAULT 'unknown'::text NOT NULL,
    is_authoritative boolean DEFAULT false NOT NULL,
    quality_score real,
    match_confidence real,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: face_embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.face_embeddings ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.face_embeddings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: rule_conflicts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.rule_conflicts (
    id integer NOT NULL,
    rule_id_1 character varying,
    rule_id_2 character varying,
    conflict_reason text,
    status character varying DEFAULT 'pending'::character varying,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: rule_conflicts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.rule_conflicts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rule_conflicts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.rule_conflicts_id_seq OWNED BY public.rule_conflicts.id;


--
-- Name: schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schedules (
    id bigint NOT NULL,
    name text NOT NULL,
    access_start_time time without time zone,
    access_end_time time without time zone,
    applies_to_weekdays boolean DEFAULT false,
    applies_to_weekends boolean DEFAULT false,
    specific_dates date[]
);


--
-- Name: schedules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.schedules ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.schedules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: unknown_face_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unknown_face_events (
    id bigint NOT NULL,
    entry_log_id bigint NOT NULL,
    embedding public.vector(512) NOT NULL,
    embedding_model text DEFAULT 'unknown'::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    assigned_detected_id bigint,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    quality_score double precision,
    best_similarity double precision,
    second_similarity double precision,
    margin double precision,
    CONSTRAINT unknown_face_events_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'assigned'::text, 'discarded'::text])))
);


--
-- Name: unknown_face_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.unknown_face_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.unknown_face_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_anomaly_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_anomaly_cases (
    id bigint NOT NULL,
    case_key text NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    primary_track_id bigint,
    status text DEFAULT 'open'::text NOT NULL,
    severity text DEFAULT 'unknown'::text NOT NULL,
    case_type text DEFAULT 'unknown'::text NOT NULL,
    start_ts timestamp with time zone NOT NULL,
    peak_ts timestamp with time zone,
    end_ts timestamp with time zone,
    primary_gate_name text,
    gate_summary_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    score_summary_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    evidence_bundle_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    case_summary text,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_anomaly_cases_severity_chk CHECK ((severity = ANY (ARRAY['unknown'::text, 'low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT vad_anomaly_cases_status_chk CHECK ((status = ANY (ARRAY['open'::text, 'evidence_ready'::text, 'reasoning_queued'::text, 'reasoning_done'::text, 'confirmed'::text, 'dismissed'::text, 'needs_review'::text, 'archived'::text, 'debug'::text]))),
    CONSTRAINT vad_anomaly_cases_temporal_chk CHECK (((end_ts IS NULL) OR (end_ts >= start_ts)))
);


--
-- Name: vad_anomaly_cases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_anomaly_cases ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_anomaly_cases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_case_gate_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_case_gate_events (
    case_id bigint NOT NULL,
    gate_event_id bigint NOT NULL,
    relation text DEFAULT 'member'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_case_gate_events_relation_chk CHECK ((relation = ANY (ARRAY['primary'::text, 'supporting'::text, 'overlap'::text, 'member'::text, 'debug'::text])))
);


--
-- Name: vad_case_reviews; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_case_reviews (
    id bigint NOT NULL,
    case_id bigint NOT NULL,
    reviewer text,
    decision text NOT NULL,
    corrected_event_type text,
    corrected_severity text,
    notes text,
    review_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_case_reviews_decision_chk CHECK ((decision = ANY (ARRAY['confirmed'::text, 'dismissed'::text, 'uncertain'::text, 'calibration_feedback'::text, 'needs_more_evidence'::text])))
);


--
-- Name: vad_case_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_case_reviews ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_case_reviews_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_detections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_detections (
    id bigint NOT NULL,
    frame_id bigint NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    track_id bigint,
    detector_name text NOT NULL,
    detector_model_version text,
    class_name text DEFAULT 'person'::text NOT NULL,
    class_id integer,
    confidence double precision,
    bbox_xyxy_json jsonb NOT NULL,
    bbox_norm_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    keypoints_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    ground_point_image_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    ground_point_world_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    detection_features_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vad_detections_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_detections ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_detections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_evidence_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_evidence_items (
    id bigint NOT NULL,
    case_id bigint NOT NULL,
    gate_event_id bigint,
    media_object_id bigint,
    evidence_role text NOT NULL,
    evidence_rank integer DEFAULT 0 NOT NULL,
    description text,
    included_in_reasoning boolean DEFAULT true NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vad_evidence_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_evidence_items ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_evidence_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_gate_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_gate_definitions (
    gate_name text NOT NULL,
    display_name text NOT NULL,
    route_name text NOT NULL,
    primary_sample_fps numeric(6,3) NOT NULL,
    role text NOT NULL,
    default_trigger_policy text NOT NULL,
    reasoning_policy text NOT NULL,
    is_primary_trigger boolean DEFAULT true NOT NULL,
    is_enabled boolean DEFAULT true NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_gate_definitions_positive_fps_chk CHECK ((primary_sample_fps > (0)::numeric))
);


--
-- Name: vad_gate_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_gate_events (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    track_id bigint,
    gate_name text NOT NULL,
    gate_model_version_id bigint,
    start_tubelet_id bigint,
    peak_tubelet_id bigint,
    end_tubelet_id bigint,
    start_score_id bigint,
    peak_score_id bigint,
    end_score_id bigint,
    event_key text,
    status text DEFAULT 'open'::text NOT NULL,
    severity text DEFAULT 'unknown'::text NOT NULL,
    event_type text DEFAULT 'other'::text NOT NULL,
    start_ts timestamp with time zone NOT NULL,
    peak_ts timestamp with time zone,
    end_ts timestamp with time zone,
    peak_score double precision,
    threshold_value double precision,
    persistence_hits integer,
    persistence_window integer,
    reason_when_fired text,
    trigger_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    feature_values_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    dominant_features_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_gate_events_severity_chk CHECK ((severity = ANY (ARRAY['unknown'::text, 'low'::text, 'medium'::text, 'high'::text, 'critical'::text]))),
    CONSTRAINT vad_gate_events_status_chk CHECK ((status = ANY (ARRAY['open'::text, 'merged_into_case'::text, 'closed'::text, 'discarded'::text, 'debug'::text]))),
    CONSTRAINT vad_gate_events_temporal_chk CHECK (((end_ts IS NULL) OR (end_ts >= start_ts)))
);


--
-- Name: vad_gate_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_gate_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_gate_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_gate_model_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_gate_model_versions (
    id bigint NOT NULL,
    gate_name text NOT NULL,
    version text NOT NULL,
    model_name text NOT NULL,
    model_type text NOT NULL,
    feature_dim integer,
    score_direction text DEFAULT 'higher_is_more_anomalous'::text NOT NULL,
    score_method text,
    normalization text,
    distance_metric text,
    sample_fps numeric(6,3),
    tubelet_frames integer,
    stride integer,
    window_duration_sec numeric(10,4),
    artifact_base_uri text,
    artifact_refs_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    feature_schema_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    training_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    inference_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    validation_report_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    notes text,
    is_active boolean DEFAULT false NOT NULL,
    activated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_gate_model_versions_positive_temporal_chk CHECK ((((feature_dim IS NULL) OR (feature_dim > 0)) AND ((sample_fps IS NULL) OR (sample_fps > (0)::numeric)) AND ((tubelet_frames IS NULL) OR (tubelet_frames > 0)) AND ((stride IS NULL) OR (stride > 0)) AND ((window_duration_sec IS NULL) OR (window_duration_sec > (0)::numeric)))),
    CONSTRAINT vad_gate_model_versions_score_direction_chk CHECK ((score_direction = ANY (ARRAY['higher_is_more_anomalous'::text, 'lower_is_more_anomalous'::text])))
);


--
-- Name: vad_gate_model_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_gate_model_versions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_gate_model_versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_gate_scores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_gate_scores (
    id bigint NOT NULL,
    tubelet_id bigint NOT NULL,
    gate_name text NOT NULL,
    gate_model_version_id bigint,
    threshold_id bigint,
    score_ts timestamp with time zone DEFAULT now() NOT NULL,
    raw_score double precision,
    smoothed_score double precision,
    normalized_score double precision,
    threshold_key text,
    threshold_value double precision,
    threshold_percentile numeric(7,3),
    score_direction text DEFAULT 'higher_is_more_anomalous'::text NOT NULL,
    above_threshold boolean DEFAULT false NOT NULL,
    persistence_window integer,
    persistence_required_hits integer,
    persistence_hits integer,
    persistent boolean DEFAULT false NOT NULL,
    trigger_recommendation text DEFAULT 'none'::text NOT NULL,
    feature_values_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    dominant_features_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    score_metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_gate_scores_score_direction_chk CHECK ((score_direction = ANY (ARRAY['higher_is_more_anomalous'::text, 'lower_is_more_anomalous'::text]))),
    CONSTRAINT vad_gate_scores_trigger_recommendation_chk CHECK ((trigger_recommendation = ANY (ARRAY['none'::text, 'evidence_only'::text, 'reasoning_candidate'::text, 'reasoning_required'::text])))
);


--
-- Name: vad_gate_scores_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_gate_scores ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_gate_scores_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_gate_thresholds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_gate_thresholds (
    id bigint NOT NULL,
    gate_model_version_id bigint NOT NULL,
    threshold_key text NOT NULL,
    threshold_percentile numeric(7,3),
    threshold_value double precision NOT NULL,
    score_column text,
    score_direction text DEFAULT 'higher_is_more_anomalous'::text NOT NULL,
    threshold_source text,
    smoothing_method text DEFAULT 'gaussian_then_persistence'::text NOT NULL,
    smoothing_sigma double precision,
    persistence_window integer,
    persistence_required_hits integer,
    min_event_gap_sec numeric(10,4),
    is_primary boolean DEFAULT false NOT NULL,
    trigger_policy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    calibration_report_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_gate_thresholds_positive_persistence_chk CHECK ((((smoothing_sigma IS NULL) OR (smoothing_sigma >= (0)::double precision)) AND ((persistence_window IS NULL) OR (persistence_window > 0)) AND ((persistence_required_hits IS NULL) OR (persistence_required_hits > 0)) AND ((min_event_gap_sec IS NULL) OR (min_event_gap_sec >= (0)::numeric)))),
    CONSTRAINT vad_gate_thresholds_score_direction_chk CHECK ((score_direction = ANY (ARRAY['higher_is_more_anomalous'::text, 'lower_is_more_anomalous'::text])))
);


--
-- Name: vad_gate_thresholds_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_gate_thresholds ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_gate_thresholds_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_homography_calibrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_homography_calibrations (
    id bigint NOT NULL,
    stream_id bigint,
    camera_id bigint,
    calibration_name text NOT NULL,
    version text DEFAULT 'v1'::text NOT NULL,
    homography_matrix_json jsonb NOT NULL,
    image_points_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    world_points_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    units text DEFAULT 'meters'::text NOT NULL,
    floor_plane_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    activated_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vad_homography_calibrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_homography_calibrations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_homography_calibrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_media_objects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_media_objects (
    id bigint NOT NULL,
    session_id bigint,
    stream_id bigint,
    camera_id bigint,
    case_id bigint,
    gate_event_id bigint,
    tubelet_id bigint,
    frame_id bigint,
    media_role text NOT NULL,
    media_type text NOT NULL,
    storage_backend text DEFAULT 'minio'::text NOT NULL,
    bucket text,
    object_key text,
    uri text,
    content_type text,
    size_bytes bigint,
    width integer,
    height integer,
    duration_sec numeric(10,4),
    sha256 text,
    captured_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT vad_media_objects_backend_chk CHECK ((storage_backend = ANY (ARRAY['minio'::text, 'local_debug'::text, 'external'::text, 'none'::text]))),
    CONSTRAINT vad_media_objects_media_type_chk CHECK ((media_type = ANY (ARRAY['image'::text, 'video'::text, 'json'::text, 'plot'::text, 'other'::text])))
);


--
-- Name: vad_media_objects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_media_objects ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_media_objects_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_reasoning_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_reasoning_jobs (
    id bigint NOT NULL,
    case_id bigint NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    reasoner_type text DEFAULT 'vlm_llm'::text NOT NULL,
    vlm_model text,
    llm_model text,
    priority text DEFAULT 'normal'::text NOT NULL,
    input_bundle_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    prompt_version text,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    queued_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT vad_reasoning_jobs_priority_chk CHECK ((priority = ANY (ARRAY['low'::text, 'normal'::text, 'high'::text, 'urgent'::text]))),
    CONSTRAINT vad_reasoning_jobs_status_chk CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text])))
);


--
-- Name: vad_reasoning_jobs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_reasoning_jobs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_reasoning_jobs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_reasoning_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_reasoning_results (
    id bigint NOT NULL,
    reasoning_job_id bigint NOT NULL,
    case_id bigint NOT NULL,
    alert_decision text,
    severity text,
    event_type text,
    confidence double precision,
    visual_evidence text,
    reasoning_summary text,
    decision_reason text,
    raw_vlm_output text,
    raw_llm_output text,
    structured_output_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    matched_rules_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    uncertainty_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    vlm_visual_review_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    llm_policy_review_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    python_final_result_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    policy_version text,
    rules_version text,
    CONSTRAINT vad_reasoning_results_alert_chk CHECK (((alert_decision IS NULL) OR (alert_decision = ANY (ARRAY['YES'::text, 'NO'::text, 'UNCERTAIN'::text])))),
    CONSTRAINT vad_reasoning_results_confidence_chk CHECK (((confidence IS NULL) OR ((confidence >= (0)::double precision) AND (confidence <= (1)::double precision)))),
    CONSTRAINT vad_reasoning_results_severity_chk CHECK (((severity IS NULL) OR (severity = ANY (ARRAY['NONE'::text, 'LOW'::text, 'MEDIUM'::text, 'HIGH'::text, 'CRITICAL'::text]))))
);


--
-- Name: vad_reasoning_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_reasoning_results ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_reasoning_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_reasoning_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_reasoning_rules (
    id integer NOT NULL,
    rule_name text NOT NULL,
    rule_type text NOT NULL,
    event_types jsonb DEFAULT '[]'::jsonb NOT NULL,
    conditions jsonb DEFAULT '{}'::jsonb NOT NULL,
    effect jsonb DEFAULT '{}'::jsonb NOT NULL,
    source text DEFAULT 'admin'::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    priority integer DEFAULT 50 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_reasoning_rules_rule_type_check CHECK ((rule_type = ANY (ARRAY['trigger'::text, 'suppress'::text])))
);


--
-- Name: vad_reasoning_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.vad_reasoning_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: vad_reasoning_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.vad_reasoning_rules_id_seq OWNED BY public.vad_reasoning_rules.id;


--
-- Name: vad_sampled_frames; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_sampled_frames (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    sample_index bigint NOT NULL,
    source_frame_index bigint,
    captured_at timestamp with time zone NOT NULL,
    stream_pts_sec numeric(16,6),
    monotonic_ts_sec numeric(16,6),
    frame_width integer,
    frame_height integer,
    used_by_pose boolean DEFAULT true NOT NULL,
    used_by_deep boolean DEFAULT false NOT NULL,
    used_by_homography_macro boolean DEFAULT false NOT NULL,
    used_by_raft boolean DEFAULT false NOT NULL,
    debug_media_object_id bigint,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: vad_sampled_frames_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_sampled_frames ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_sampled_frames_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_schema_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_schema_version (
    id bigint NOT NULL,
    version text NOT NULL,
    description text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: vad_schema_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_schema_version ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_schema_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_stream_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_stream_sessions (
    id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    status text DEFAULT 'starting'::text NOT NULL,
    backend_instance_id text,
    process_id integer,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    first_frame_at timestamp with time zone,
    last_frame_at timestamp with time zone,
    stopped_at timestamp with time zone,
    last_heartbeat_at timestamp with time zone DEFAULT now() NOT NULL,
    target_sample_fps numeric(6,3) DEFAULT 5.0 NOT NULL,
    actual_sample_fps numeric(8,3),
    rolling_buffer_sec numeric(8,3) DEFAULT 30.0 NOT NULL,
    frame_width integer,
    frame_height integer,
    sampled_frame_count bigint DEFAULT 0 NOT NULL,
    dropped_frame_count bigint DEFAULT 0 NOT NULL,
    reconnect_count integer DEFAULT 0 NOT NULL,
    route_counters_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    runtime_stats_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT vad_stream_sessions_positive_sampling_chk CHECK (((target_sample_fps > (0)::numeric) AND (rolling_buffer_sec > (0)::numeric))),
    CONSTRAINT vad_stream_sessions_status_chk CHECK ((status = ANY (ARRAY['starting'::text, 'running'::text, 'degraded'::text, 'stopping'::text, 'stopped'::text, 'failed'::text])))
);


--
-- Name: vad_stream_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_stream_sessions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_stream_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_streams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_streams (
    id bigint NOT NULL,
    stream_key text NOT NULL,
    camera_id bigint,
    camera_key text,
    display_name text,
    location text,
    source_type text DEFAULT 'rtsp'::text NOT NULL,
    rtsp_url_env_var text,
    target_sample_fps numeric(6,3) DEFAULT 5.0 NOT NULL,
    rolling_buffer_sec numeric(8,3) DEFAULT 30.0 NOT NULL,
    route_fps_json jsonb DEFAULT '{"deep": 2.5, "pose": 5.0, "raft": 2.5, "homography_macro": 2.5}'::jsonb NOT NULL,
    frame_width integer,
    frame_height integer,
    is_active boolean DEFAULT true NOT NULL,
    config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_streams_positive_sampling_chk CHECK (((target_sample_fps > (0)::numeric) AND (rolling_buffer_sec > (0)::numeric))),
    CONSTRAINT vad_streams_source_type_chk CHECK ((source_type = ANY (ARRAY['rtsp'::text, 'file'::text, 'debug'::text])))
);


--
-- Name: vad_streams_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_streams ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_streams_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_tracks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_tracks (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    tracker_name text DEFAULT 'unknown'::text NOT NULL,
    tracker_track_id bigint NOT NULL,
    global_track_key text,
    status text DEFAULT 'active'::text NOT NULL,
    first_seen_frame_id bigint,
    last_seen_frame_id bigint,
    first_seen_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    detection_count integer DEFAULT 0 NOT NULL,
    gap_count integer DEFAULT 0 NOT NULL,
    best_confidence double precision,
    last_bbox_xyxy_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    track_summary_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_tracks_status_chk CHECK ((status = ANY (ARRAY['active'::text, 'lost'::text, 'closed'::text, 'merged'::text, 'debug'::text])))
);


--
-- Name: vad_tracks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_tracks ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_tracks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_tubelet_embeddings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_tubelet_embeddings (
    id bigint NOT NULL,
    tubelet_id bigint NOT NULL,
    gate_model_version_id bigint,
    embedding_name text DEFAULT 'videomae_cls_mean'::text NOT NULL,
    embedding_dim integer DEFAULT 768 NOT NULL,
    embedding public.vector(768),
    embedding_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    normalization text,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_tubelet_embeddings_dim_chk CHECK ((embedding_dim > 0))
);


--
-- Name: vad_tubelet_embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_tubelet_embeddings ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_tubelet_embeddings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: vad_tubelets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vad_tubelets (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    stream_id bigint NOT NULL,
    camera_id bigint,
    track_id bigint,
    route_name text NOT NULL,
    tubelet_key text,
    start_frame_id bigint,
    end_frame_id bigint,
    frame_sample_ids bigint[] DEFAULT ARRAY[]::bigint[] NOT NULL,
    detection_ids bigint[] DEFAULT ARRAY[]::bigint[] NOT NULL,
    window_start_ts timestamp with time zone NOT NULL,
    window_end_ts timestamp with time zone NOT NULL,
    sample_fps numeric(6,3) NOT NULL,
    tubelet_frames integer NOT NULL,
    stride integer NOT NULL,
    duration_sec numeric(10,4),
    bbox_sequence_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    trajectory_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    feature_values_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    dominant_features_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    quality_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    metadata_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT vad_tubelets_route_name_chk CHECK ((route_name = ANY (ARRAY['pose'::text, 'deep'::text, 'homography_macro'::text, 'raft'::text, 'shared'::text, 'debug'::text]))),
    CONSTRAINT vad_tubelets_temporal_chk CHECK (((window_end_ts >= window_start_ts) AND (sample_fps > (0)::numeric) AND (tubelet_frames > 0) AND (stride > 0)))
);


--
-- Name: vad_tubelets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.vad_tubelets ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.vad_tubelets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: visitors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.visitors (
    id bigint NOT NULL,
    name text NOT NULL,
    visit_date date,
    purpose text,
    contact_info text
);


--
-- Name: visitors_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.visitors ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.visitors_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: rule_conflicts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rule_conflicts ALTER COLUMN id SET DEFAULT nextval('public.rule_conflicts_id_seq'::regclass);


--
-- Name: vad_reasoning_rules id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_rules ALTER COLUMN id SET DEFAULT nextval('public.vad_reasoning_rules_id_seq'::regclass);


--
-- Name: anomaly_rules anomaly_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anomaly_rules
    ADD CONSTRAINT anomaly_rules_pkey PRIMARY KEY (id);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: cameras cameras_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cameras
    ADD CONSTRAINT cameras_pkey PRIMARY KEY (id);


--
-- Name: detected_people detected_people_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detected_people
    ADD CONSTRAINT detected_people_pkey PRIMARY KEY (id);


--
-- Name: edge_devices edge_devices_device_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.edge_devices
    ADD CONSTRAINT edge_devices_device_key_key UNIQUE (device_key);


--
-- Name: edge_devices edge_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.edge_devices
    ADD CONSTRAINT edge_devices_pkey PRIMARY KEY (id);


--
-- Name: employees employees_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (id);


--
-- Name: entry_logs entry_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entry_logs
    ADD CONSTRAINT entry_logs_pkey PRIMARY KEY (id);


--
-- Name: face_embeddings face_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.face_embeddings
    ADD CONSTRAINT face_embeddings_pkey PRIMARY KEY (id);


--
-- Name: rule_conflicts rule_conflicts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.rule_conflicts
    ADD CONSTRAINT rule_conflicts_pkey PRIMARY KEY (id);


--
-- Name: schedules schedules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schedules
    ADD CONSTRAINT schedules_pkey PRIMARY KEY (id);


--
-- Name: unknown_face_events unknown_face_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unknown_face_events
    ADD CONSTRAINT unknown_face_events_pkey PRIMARY KEY (id);


--
-- Name: vad_anomaly_cases vad_anomaly_cases_case_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_case_key_key UNIQUE (case_key);


--
-- Name: vad_anomaly_cases vad_anomaly_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_pkey PRIMARY KEY (id);


--
-- Name: vad_case_gate_events vad_case_gate_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_case_gate_events
    ADD CONSTRAINT vad_case_gate_events_pkey PRIMARY KEY (case_id, gate_event_id);


--
-- Name: vad_case_reviews vad_case_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_case_reviews
    ADD CONSTRAINT vad_case_reviews_pkey PRIMARY KEY (id);


--
-- Name: vad_detections vad_detections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_pkey PRIMARY KEY (id);


--
-- Name: vad_evidence_items vad_evidence_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_evidence_items
    ADD CONSTRAINT vad_evidence_items_pkey PRIMARY KEY (id);


--
-- Name: vad_gate_definitions vad_gate_definitions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_definitions
    ADD CONSTRAINT vad_gate_definitions_pkey PRIMARY KEY (gate_name);


--
-- Name: vad_gate_events vad_gate_events_event_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_event_key_key UNIQUE (event_key);


--
-- Name: vad_gate_events vad_gate_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_pkey PRIMARY KEY (id);


--
-- Name: vad_gate_model_versions vad_gate_model_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_model_versions
    ADD CONSTRAINT vad_gate_model_versions_pkey PRIMARY KEY (id);


--
-- Name: vad_gate_model_versions vad_gate_model_versions_unique_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_model_versions
    ADD CONSTRAINT vad_gate_model_versions_unique_version UNIQUE (gate_name, version);


--
-- Name: vad_gate_scores vad_gate_scores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_scores
    ADD CONSTRAINT vad_gate_scores_pkey PRIMARY KEY (id);


--
-- Name: vad_gate_thresholds vad_gate_thresholds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_thresholds
    ADD CONSTRAINT vad_gate_thresholds_pkey PRIMARY KEY (id);


--
-- Name: vad_gate_thresholds vad_gate_thresholds_unique_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_thresholds
    ADD CONSTRAINT vad_gate_thresholds_unique_key UNIQUE (gate_model_version_id, threshold_key);


--
-- Name: vad_homography_calibrations vad_homography_calibrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_homography_calibrations
    ADD CONSTRAINT vad_homography_calibrations_pkey PRIMARY KEY (id);


--
-- Name: vad_homography_calibrations vad_homography_calibrations_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_homography_calibrations
    ADD CONSTRAINT vad_homography_calibrations_unique UNIQUE (camera_id, calibration_name, version);


--
-- Name: vad_media_objects vad_media_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_pkey PRIMARY KEY (id);


--
-- Name: vad_reasoning_jobs vad_reasoning_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_jobs
    ADD CONSTRAINT vad_reasoning_jobs_pkey PRIMARY KEY (id);


--
-- Name: vad_reasoning_results vad_reasoning_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_results
    ADD CONSTRAINT vad_reasoning_results_pkey PRIMARY KEY (id);


--
-- Name: vad_reasoning_rules vad_reasoning_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_rules
    ADD CONSTRAINT vad_reasoning_rules_pkey PRIMARY KEY (id);


--
-- Name: vad_sampled_frames vad_sampled_frames_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_pkey PRIMARY KEY (id);


--
-- Name: vad_sampled_frames vad_sampled_frames_unique_sample; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_unique_sample UNIQUE (session_id, sample_index);


--
-- Name: vad_schema_version vad_schema_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_schema_version
    ADD CONSTRAINT vad_schema_version_pkey PRIMARY KEY (id);


--
-- Name: vad_schema_version vad_schema_version_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_schema_version
    ADD CONSTRAINT vad_schema_version_version_key UNIQUE (version);


--
-- Name: vad_stream_sessions vad_stream_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_stream_sessions
    ADD CONSTRAINT vad_stream_sessions_pkey PRIMARY KEY (id);


--
-- Name: vad_streams vad_streams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_streams
    ADD CONSTRAINT vad_streams_pkey PRIMARY KEY (id);


--
-- Name: vad_streams vad_streams_stream_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_streams
    ADD CONSTRAINT vad_streams_stream_key_key UNIQUE (stream_key);


--
-- Name: vad_tracks vad_tracks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_pkey PRIMARY KEY (id);


--
-- Name: vad_tracks vad_tracks_unique_tracker_track; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_unique_tracker_track UNIQUE (session_id, tracker_name, tracker_track_id);


--
-- Name: vad_tubelet_embeddings vad_tubelet_embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelet_embeddings
    ADD CONSTRAINT vad_tubelet_embeddings_pkey PRIMARY KEY (id);


--
-- Name: vad_tubelet_embeddings vad_tubelet_embeddings_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelet_embeddings
    ADD CONSTRAINT vad_tubelet_embeddings_unique UNIQUE (tubelet_id, gate_model_version_id, embedding_name);


--
-- Name: vad_tubelets vad_tubelets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_pkey PRIMARY KEY (id);


--
-- Name: vad_tubelets vad_tubelets_tubelet_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_tubelet_key_key UNIQUE (tubelet_key);


--
-- Name: visitors visitors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.visitors
    ADD CONSTRAINT visitors_pkey PRIMARY KEY (id);


--
-- Name: anomaly_rules_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX anomaly_rules_active_idx ON public.anomaly_rules USING btree (active);


--
-- Name: anomaly_rules_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX anomaly_rules_created_idx ON public.anomaly_rules USING btree (created_at DESC);


--
-- Name: anomaly_rules_event_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX anomaly_rules_event_type_idx ON public.anomaly_rules USING btree (event_type);


--
-- Name: audit_logs_action_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_logs_action_idx ON public.audit_logs USING btree (action);


--
-- Name: audit_logs_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_logs_created_idx ON public.audit_logs USING btree (created_at DESC);


--
-- Name: audit_logs_resource_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_logs_resource_idx ON public.audit_logs USING btree (resource);


--
-- Name: audit_logs_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_logs_user_idx ON public.audit_logs USING btree (user_email);


--
-- Name: edge_devices_device_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX edge_devices_device_key_idx ON public.edge_devices USING btree (device_key);


--
-- Name: face_embeddings_authoritative_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX face_embeddings_authoritative_idx ON public.face_embeddings USING btree (detected_id) WHERE (is_authoritative = true);


--
-- Name: face_embeddings_autolearn_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX face_embeddings_autolearn_idx ON public.face_embeddings USING btree (detected_id, created_at) WHERE (notes = 'auto_learned'::text);


--
-- Name: face_embeddings_detected_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX face_embeddings_detected_id_idx ON public.face_embeddings USING btree (detected_id);


--
-- Name: face_embeddings_embedding_hnsw_cosine; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX face_embeddings_embedding_hnsw_cosine ON public.face_embeddings USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: face_embeddings_entry_log_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX face_embeddings_entry_log_id_idx ON public.face_embeddings USING btree (entry_log_id);


--
-- Name: idx_vad_reasoning_jobs_metadata_jsonb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vad_reasoning_jobs_metadata_jsonb ON public.vad_reasoning_jobs USING gin (metadata_json);


--
-- Name: idx_vad_reasoning_rules_active_priority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_vad_reasoning_rules_active_priority ON public.vad_reasoning_rules USING btree (active, priority, id);


--
-- Name: rule_conflicts_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX rule_conflicts_created_idx ON public.rule_conflicts USING btree (created_at DESC);


--
-- Name: rule_conflicts_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX rule_conflicts_status_idx ON public.rule_conflicts USING btree (status);


--
-- Name: unknown_face_events_embedding_hnsw_cosine; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX unknown_face_events_embedding_hnsw_cosine ON public.unknown_face_events USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: unknown_face_events_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX unknown_face_events_status_idx ON public.unknown_face_events USING btree (status);


--
-- Name: vad_anomaly_cases_gate_summary_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_anomaly_cases_gate_summary_gin_idx ON public.vad_anomaly_cases USING gin (gate_summary_json);


--
-- Name: vad_anomaly_cases_status_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_anomaly_cases_status_time_idx ON public.vad_anomaly_cases USING btree (status, start_ts DESC);


--
-- Name: vad_detections_frame_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_detections_frame_idx ON public.vad_detections USING btree (frame_id);


--
-- Name: vad_detections_track_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_detections_track_time_idx ON public.vad_detections USING btree (track_id, created_at);


--
-- Name: vad_evidence_items_case_role_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_evidence_items_case_role_idx ON public.vad_evidence_items USING btree (case_id, evidence_role, evidence_rank);


--
-- Name: vad_gate_events_gate_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_events_gate_time_idx ON public.vad_gate_events USING btree (gate_name, start_ts DESC);


--
-- Name: vad_gate_events_metadata_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_events_metadata_gin_idx ON public.vad_gate_events USING gin (metadata_json);


--
-- Name: vad_gate_events_session_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_events_session_time_idx ON public.vad_gate_events USING btree (session_id, start_ts DESC);


--
-- Name: vad_gate_model_versions_one_active_per_gate_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX vad_gate_model_versions_one_active_per_gate_idx ON public.vad_gate_model_versions USING btree (gate_name) WHERE is_active;


--
-- Name: vad_gate_scores_dominant_features_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_scores_dominant_features_gin_idx ON public.vad_gate_scores USING gin (dominant_features_json);


--
-- Name: vad_gate_scores_gate_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_scores_gate_time_idx ON public.vad_gate_scores USING btree (gate_name, score_ts DESC);


--
-- Name: vad_gate_scores_tubelet_gate_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_gate_scores_tubelet_gate_idx ON public.vad_gate_scores USING btree (tubelet_id, gate_name);


--
-- Name: vad_gate_thresholds_one_primary_per_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX vad_gate_thresholds_one_primary_per_model_idx ON public.vad_gate_thresholds USING btree (gate_model_version_id) WHERE is_primary;


--
-- Name: vad_media_objects_case_role_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_media_objects_case_role_idx ON public.vad_media_objects USING btree (case_id, media_role);


--
-- Name: vad_reasoning_jobs_status_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_reasoning_jobs_status_queue_idx ON public.vad_reasoning_jobs USING btree (status, queued_at);


--
-- Name: vad_reasoning_results_final_json_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_reasoning_results_final_json_gin_idx ON public.vad_reasoning_results USING gin (python_final_result_json);


--
-- Name: vad_reasoning_results_llm_json_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_reasoning_results_llm_json_gin_idx ON public.vad_reasoning_results USING gin (llm_policy_review_json);


--
-- Name: vad_reasoning_results_vlm_json_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_reasoning_results_vlm_json_gin_idx ON public.vad_reasoning_results USING gin (vlm_visual_review_json);


--
-- Name: vad_sampled_frames_session_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_sampled_frames_session_time_idx ON public.vad_sampled_frames USING btree (session_id, captured_at DESC);


--
-- Name: vad_stream_sessions_stream_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_stream_sessions_stream_status_idx ON public.vad_stream_sessions USING btree (stream_id, status, started_at DESC);


--
-- Name: vad_tracks_session_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_tracks_session_time_idx ON public.vad_tracks USING btree (session_id, first_seen_at, last_seen_at);


--
-- Name: vad_tracks_session_tracker_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_tracks_session_tracker_idx ON public.vad_tracks USING btree (session_id, tracker_name, tracker_track_id);


--
-- Name: vad_tubelets_feature_values_gin_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_tubelets_feature_values_gin_idx ON public.vad_tubelets USING gin (feature_values_json);


--
-- Name: vad_tubelets_track_route_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX vad_tubelets_track_route_time_idx ON public.vad_tubelets USING btree (track_id, route_name, window_start_ts);


--
-- Name: detected_people detected_people_employee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detected_people
    ADD CONSTRAINT detected_people_employee_id_fkey FOREIGN KEY (employee_id) REFERENCES public.employees(id);


--
-- Name: detected_people detected_people_visitor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detected_people
    ADD CONSTRAINT detected_people_visitor_id_fkey FOREIGN KEY (visitor_id) REFERENCES public.visitors(id);


--
-- Name: entry_logs entry_logs_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entry_logs
    ADD CONSTRAINT entry_logs_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id);


--
-- Name: entry_logs entry_logs_detected_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entry_logs
    ADD CONSTRAINT entry_logs_detected_id_fkey FOREIGN KEY (detected_id) REFERENCES public.detected_people(id);


--
-- Name: face_embeddings face_embeddings_detected_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.face_embeddings
    ADD CONSTRAINT face_embeddings_detected_id_fkey FOREIGN KEY (detected_id) REFERENCES public.detected_people(id) ON DELETE CASCADE;


--
-- Name: face_embeddings face_embeddings_entry_log_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.face_embeddings
    ADD CONSTRAINT face_embeddings_entry_log_id_fkey FOREIGN KEY (entry_log_id) REFERENCES public.entry_logs(id) ON DELETE SET NULL;


--
-- Name: unknown_face_events unknown_face_events_assigned_detected_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unknown_face_events
    ADD CONSTRAINT unknown_face_events_assigned_detected_id_fkey FOREIGN KEY (assigned_detected_id) REFERENCES public.detected_people(id) ON DELETE SET NULL;


--
-- Name: unknown_face_events unknown_face_events_entry_log_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unknown_face_events
    ADD CONSTRAINT unknown_face_events_entry_log_id_fkey FOREIGN KEY (entry_log_id) REFERENCES public.entry_logs(id) ON DELETE CASCADE;


--
-- Name: vad_anomaly_cases vad_anomaly_cases_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_anomaly_cases vad_anomaly_cases_primary_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_primary_track_id_fkey FOREIGN KEY (primary_track_id) REFERENCES public.vad_tracks(id) ON DELETE SET NULL;


--
-- Name: vad_anomaly_cases vad_anomaly_cases_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_anomaly_cases vad_anomaly_cases_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_anomaly_cases
    ADD CONSTRAINT vad_anomaly_cases_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_case_gate_events vad_case_gate_events_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_case_gate_events
    ADD CONSTRAINT vad_case_gate_events_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_case_gate_events vad_case_gate_events_gate_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_case_gate_events
    ADD CONSTRAINT vad_case_gate_events_gate_event_id_fkey FOREIGN KEY (gate_event_id) REFERENCES public.vad_gate_events(id) ON DELETE CASCADE;


--
-- Name: vad_case_reviews vad_case_reviews_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_case_reviews
    ADD CONSTRAINT vad_case_reviews_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_detections vad_detections_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_detections vad_detections_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_frame_id_fkey FOREIGN KEY (frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE CASCADE;


--
-- Name: vad_detections vad_detections_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_detections vad_detections_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_detections vad_detections_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_detections
    ADD CONSTRAINT vad_detections_track_id_fkey FOREIGN KEY (track_id) REFERENCES public.vad_tracks(id) ON DELETE SET NULL;


--
-- Name: vad_evidence_items vad_evidence_items_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_evidence_items
    ADD CONSTRAINT vad_evidence_items_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_evidence_items vad_evidence_items_gate_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_evidence_items
    ADD CONSTRAINT vad_evidence_items_gate_event_id_fkey FOREIGN KEY (gate_event_id) REFERENCES public.vad_gate_events(id) ON DELETE SET NULL;


--
-- Name: vad_evidence_items vad_evidence_items_media_object_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_evidence_items
    ADD CONSTRAINT vad_evidence_items_media_object_id_fkey FOREIGN KEY (media_object_id) REFERENCES public.vad_media_objects(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_end_score_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_end_score_id_fkey FOREIGN KEY (end_score_id) REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_end_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_end_tubelet_id_fkey FOREIGN KEY (end_tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_gate_model_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_gate_model_version_id_fkey FOREIGN KEY (gate_model_version_id) REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_gate_name_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_gate_name_fkey FOREIGN KEY (gate_name) REFERENCES public.vad_gate_definitions(gate_name) ON DELETE RESTRICT;


--
-- Name: vad_gate_events vad_gate_events_peak_score_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_peak_score_id_fkey FOREIGN KEY (peak_score_id) REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_peak_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_peak_tubelet_id_fkey FOREIGN KEY (peak_tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_gate_events vad_gate_events_start_score_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_start_score_id_fkey FOREIGN KEY (start_score_id) REFERENCES public.vad_gate_scores(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_start_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_start_tubelet_id_fkey FOREIGN KEY (start_tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE SET NULL;


--
-- Name: vad_gate_events vad_gate_events_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_gate_events vad_gate_events_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_events
    ADD CONSTRAINT vad_gate_events_track_id_fkey FOREIGN KEY (track_id) REFERENCES public.vad_tracks(id) ON DELETE SET NULL;


--
-- Name: vad_gate_model_versions vad_gate_model_versions_gate_name_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_model_versions
    ADD CONSTRAINT vad_gate_model_versions_gate_name_fkey FOREIGN KEY (gate_name) REFERENCES public.vad_gate_definitions(gate_name) ON DELETE CASCADE;


--
-- Name: vad_gate_scores vad_gate_scores_gate_model_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_scores
    ADD CONSTRAINT vad_gate_scores_gate_model_version_id_fkey FOREIGN KEY (gate_model_version_id) REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL;


--
-- Name: vad_gate_scores vad_gate_scores_gate_name_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_scores
    ADD CONSTRAINT vad_gate_scores_gate_name_fkey FOREIGN KEY (gate_name) REFERENCES public.vad_gate_definitions(gate_name) ON DELETE RESTRICT;


--
-- Name: vad_gate_scores vad_gate_scores_threshold_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_scores
    ADD CONSTRAINT vad_gate_scores_threshold_id_fkey FOREIGN KEY (threshold_id) REFERENCES public.vad_gate_thresholds(id) ON DELETE SET NULL;


--
-- Name: vad_gate_scores vad_gate_scores_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_scores
    ADD CONSTRAINT vad_gate_scores_tubelet_id_fkey FOREIGN KEY (tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE CASCADE;


--
-- Name: vad_gate_thresholds vad_gate_thresholds_gate_model_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_gate_thresholds
    ADD CONSTRAINT vad_gate_thresholds_gate_model_version_id_fkey FOREIGN KEY (gate_model_version_id) REFERENCES public.vad_gate_model_versions(id) ON DELETE CASCADE;


--
-- Name: vad_homography_calibrations vad_homography_calibrations_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_homography_calibrations
    ADD CONSTRAINT vad_homography_calibrations_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_homography_calibrations vad_homography_calibrations_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_homography_calibrations
    ADD CONSTRAINT vad_homography_calibrations_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_media_objects vad_media_objects_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_media_objects vad_media_objects_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_media_objects vad_media_objects_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_frame_id_fkey FOREIGN KEY (frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL;


--
-- Name: vad_media_objects vad_media_objects_gate_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_gate_event_id_fkey FOREIGN KEY (gate_event_id) REFERENCES public.vad_gate_events(id) ON DELETE SET NULL;


--
-- Name: vad_media_objects vad_media_objects_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE SET NULL;


--
-- Name: vad_media_objects vad_media_objects_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE SET NULL;


--
-- Name: vad_media_objects vad_media_objects_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_media_objects
    ADD CONSTRAINT vad_media_objects_tubelet_id_fkey FOREIGN KEY (tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE SET NULL;


--
-- Name: vad_reasoning_jobs vad_reasoning_jobs_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_jobs
    ADD CONSTRAINT vad_reasoning_jobs_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_reasoning_results vad_reasoning_results_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_results
    ADD CONSTRAINT vad_reasoning_results_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.vad_anomaly_cases(id) ON DELETE CASCADE;


--
-- Name: vad_reasoning_results vad_reasoning_results_reasoning_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_reasoning_results
    ADD CONSTRAINT vad_reasoning_results_reasoning_job_id_fkey FOREIGN KEY (reasoning_job_id) REFERENCES public.vad_reasoning_jobs(id) ON DELETE CASCADE;


--
-- Name: vad_sampled_frames vad_sampled_frames_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_sampled_frames vad_sampled_frames_debug_media_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_debug_media_fk FOREIGN KEY (debug_media_object_id) REFERENCES public.vad_media_objects(id) ON DELETE SET NULL;


--
-- Name: vad_sampled_frames vad_sampled_frames_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_sampled_frames vad_sampled_frames_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_sampled_frames
    ADD CONSTRAINT vad_sampled_frames_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_stream_sessions vad_stream_sessions_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_stream_sessions
    ADD CONSTRAINT vad_stream_sessions_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_stream_sessions vad_stream_sessions_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_stream_sessions
    ADD CONSTRAINT vad_stream_sessions_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_streams vad_streams_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_streams
    ADD CONSTRAINT vad_streams_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_tracks vad_tracks_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_tracks vad_tracks_first_seen_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_first_seen_frame_id_fkey FOREIGN KEY (first_seen_frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL;


--
-- Name: vad_tracks vad_tracks_last_seen_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_last_seen_frame_id_fkey FOREIGN KEY (last_seen_frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL;


--
-- Name: vad_tracks vad_tracks_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_tracks vad_tracks_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tracks
    ADD CONSTRAINT vad_tracks_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_tubelet_embeddings vad_tubelet_embeddings_gate_model_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelet_embeddings
    ADD CONSTRAINT vad_tubelet_embeddings_gate_model_version_id_fkey FOREIGN KEY (gate_model_version_id) REFERENCES public.vad_gate_model_versions(id) ON DELETE SET NULL;


--
-- Name: vad_tubelet_embeddings vad_tubelet_embeddings_tubelet_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelet_embeddings
    ADD CONSTRAINT vad_tubelet_embeddings_tubelet_id_fkey FOREIGN KEY (tubelet_id) REFERENCES public.vad_tubelets(id) ON DELETE CASCADE;


--
-- Name: vad_tubelets vad_tubelets_camera_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_camera_id_fkey FOREIGN KEY (camera_id) REFERENCES public.cameras(id) ON DELETE SET NULL;


--
-- Name: vad_tubelets vad_tubelets_end_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_end_frame_id_fkey FOREIGN KEY (end_frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL;


--
-- Name: vad_tubelets vad_tubelets_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.vad_stream_sessions(id) ON DELETE CASCADE;


--
-- Name: vad_tubelets vad_tubelets_start_frame_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_start_frame_id_fkey FOREIGN KEY (start_frame_id) REFERENCES public.vad_sampled_frames(id) ON DELETE SET NULL;


--
-- Name: vad_tubelets vad_tubelets_stream_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_stream_id_fkey FOREIGN KEY (stream_id) REFERENCES public.vad_streams(id) ON DELETE CASCADE;


--
-- Name: vad_tubelets vad_tubelets_track_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vad_tubelets
    ADD CONSTRAINT vad_tubelets_track_id_fkey FOREIGN KEY (track_id) REFERENCES public.vad_tracks(id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--

\unrestrict xqtEDfS5bkevWwWbHEGbN6zYFRHq1r89YVJmJQCjhuqe7gq3DiQCD1RI7T1LJEb

