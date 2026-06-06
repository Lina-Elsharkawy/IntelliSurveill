-- Migration: Add vad_reasoning_rules table for DB-backed Deep Gate reasoning rules.
--
-- This table replaces the compile-time hardcoded rules in
-- backend/services/vad_service/vad/reasoning/reasoning_rules.py.
-- Rules are now live-editable at runtime through the admin API.
--
-- Run this migration once against the surveillance database.
-- It is idempotent: wrapped in DO $$ ... END so re-running is safe.

DO $$
BEGIN

-- ──────────────────────────────────────────────────────────────────────────────
-- 1. Create the table if it does not exist.
-- ──────────────────────────────────────────────────────────────────────────────
IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'vad_reasoning_rules'
) THEN

    CREATE TABLE public.vad_reasoning_rules (
        id              SERIAL PRIMARY KEY,

        -- Human-readable label displayed in admin UI and reasoning result JSON.
        rule_name       TEXT NOT NULL,

        -- "trigger" → escalates severity/action when conditions match.
        -- "suppress" → downgrades or suppresses the alert when conditions match.
        rule_type       TEXT NOT NULL CHECK (rule_type IN ('trigger', 'suppress')),

        -- JSONB array of VLM event_type strings this rule targets.
        -- Example: ["fall_or_collapse", "person_on_floor"]
        -- Empty array [] means the rule applies to ALL event types.
        event_types     JSONB NOT NULL DEFAULT '[]'::jsonb,

        -- JSONB object with optional numeric constraints and flags:
        --   min_score_ratio          FLOAT  – fire only if score/threshold >= this
        --   max_score_ratio          FLOAT  – fire only if score/threshold <= this
        --   requires_anomaly_evidence BOOL  – only if VLM produced anomaly_evidence
        conditions      JSONB NOT NULL DEFAULT '{}'::jsonb,

        -- JSONB effect payload.
        -- For "trigger" rules:
        --   { "minimum_severity": "HIGH", "recommended_action": "urgent_alert" }
        -- For "suppress" rules:
        --   { "policy_alert_decision": "NO", "policy_severity": "LOW",
        --     "recommended_action": "save_for_dataset" }
        effect          JSONB NOT NULL DEFAULT '{}'::jsonb,

        -- "builtin"  – shipped with the codebase (hardcoded fallback equivalent)
        -- "admin"    – created by a human operator
        -- "learned"  – created automatically by the system
        source          TEXT NOT NULL DEFAULT 'admin',

        -- Soft-delete flag.  Only active=TRUE rules are loaded by the worker.
        active          BOOLEAN NOT NULL DEFAULT TRUE,

        -- Free-text description shown in the admin UI.
        description     TEXT NOT NULL DEFAULT '',

        -- Lower priority value = evaluated first.  Use gaps (10, 20, …) to
        -- leave room for insertion.  Suppress rules should run before trigger rules
        -- so we default suppress at 10 and trigger at 50.
        priority        INTEGER NOT NULL DEFAULT 50,

        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    -- Index for the most common query pattern: active rules ordered by priority.
    CREATE INDEX idx_vad_reasoning_rules_active_priority
        ON public.vad_reasoning_rules (active, priority, id);

    RAISE NOTICE 'Created table vad_reasoning_rules';
ELSE
    RAISE NOTICE 'Table vad_reasoning_rules already exists, skipping creation';
END IF;

-- ──────────────────────────────────────────────────────────────────────────────
-- 2. Seed the built-in default rules (skip if already present).
-- ──────────────────────────────────────────────────────────────────────────────

-- Suppress: clear normal or benign activity
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Suppress clear normal or benign activity',
    'suppress',
    '["normal_activity", "benign_posture_change", "benign_object_movement"]'::jsonb,
    '{"max_score_ratio": 1.25}'::jsonb,
    '{"policy_alert_decision": "NO", "policy_severity": "LOW", "recommended_action": "save_for_dataset"}'::jsonb,
    'builtin', TRUE,
    'Do not alert on clearly normal or benign events with a low score ratio. Save for dataset retraining.',
    10
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Suppress clear normal or benign activity'
);

-- Suppress: camera or detection artifact
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Suppress camera or detection artifact',
    'suppress',
    '["camera_or_detection_artifact"]'::jsonb,
    '{}'::jsonb,
    '{"policy_alert_decision": "NO", "policy_severity": "NONE", "recommended_action": "save_for_dataset"}'::jsonb,
    'builtin', TRUE,
    'Suppress events caused by camera noise, glare, or YOLO detector instability.',
    15
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Suppress camera or detection artifact'
);

-- Suppress: unclear visual evidence
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Review unclear visual evidence conservatively',
    'suppress',
    '["unclear_visual_evidence"]'::jsonb,
    '{}'::jsonb,
    '{"policy_alert_decision": "UNCERTAIN", "policy_severity": "LOW", "recommended_action": "review_only"}'::jsonb,
    'builtin', TRUE,
    'Flag events with unclear visual evidence for manual review instead of alerting.',
    20
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Review unclear visual evidence conservatively'
);

-- Trigger: fall or person on floor
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Escalate visually supported fall or person-on-floor event',
    'trigger',
    '["fall_or_collapse", "person_on_floor"]'::jsonb,
    '{"requires_anomaly_evidence": true}'::jsonb,
    '{"minimum_severity": "HIGH", "recommended_action": "urgent_alert"}'::jsonb,
    'builtin', TRUE,
    'Immediately alert with HIGH severity for any visually confirmed fall or person-on-floor event in the lab.',
    50
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Escalate visually supported fall or person-on-floor event'
);

-- Trigger: unsafe equipment interaction
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Escalate visually supported unsafe equipment interaction',
    'trigger',
    '["unsafe_equipment_interaction"]'::jsonb,
    '{"requires_anomaly_evidence": true}'::jsonb,
    '{"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"}'::jsonb,
    'builtin', TRUE,
    'Alert operator when a person is visually confirmed to interact unsafely with lab equipment.',
    55
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Escalate visually supported unsafe equipment interaction'
);

-- Trigger: possible security event
INSERT INTO public.vad_reasoning_rules
    (rule_name, rule_type, event_types, conditions, effect, source, active, description, priority)
SELECT
    'Escalate visually supported suspicious or security event',
    'trigger',
    '["possible_intrusion_or_security_event", "suspicious_motion"]'::jsonb,
    '{"requires_anomaly_evidence": true}'::jsonb,
    '{"minimum_severity": "MEDIUM", "recommended_action": "alert_operator"}'::jsonb,
    'builtin', TRUE,
    'Alert operator for any visually confirmed intrusion attempt or suspicious movement in the lab.',
    60
WHERE NOT EXISTS (
    SELECT 1 FROM public.vad_reasoning_rules
    WHERE source = 'builtin' AND rule_name = 'Escalate visually supported suspicious or security event'
);

END $$;

-- ──────────────────────────────────────────────────────────────────────────────
-- 3. Grant SELECT to the application role (adjust role name if needed).
-- ──────────────────────────────────────────────────────────────────────────────
-- GRANT SELECT, INSERT, UPDATE, DELETE ON public.vad_reasoning_rules TO vad_app;
-- GRANT USAGE, SELECT ON SEQUENCE public.vad_reasoning_rules_id_seq TO vad_app;
