BEGIN;

-- ============================================================
-- Migration: Add person_interaction anomaly gate
-- Purpose:
--   Allow the backend motion gate layer to emit and store the
--   new person_interaction gate for two-person close interaction
--   / possible fight/contact events.
-- ============================================================


-- ============================================================
-- 1) Update anomaly_gate_configs gate-name constraint
-- ============================================================

ALTER TABLE public.anomaly_gate_configs
DROP CONSTRAINT IF EXISTS anomaly_gate_configs_gate_name_check;

ALTER TABLE public.anomaly_gate_configs
ADD CONSTRAINT anomaly_gate_configs_gate_name_check
CHECK (
    gate_name = ANY (
        ARRAY[
            'distribution_score'::text,
            'high_speed'::text,
            'abrupt_direction_change'::text,
            'track_instability'::text,
            'person_interaction'::text
        ]
    )
);


-- ============================================================
-- 2) Add / update person_interaction gate config
-- ============================================================

INSERT INTO public.anomaly_gate_configs (
    model_id,
    gate_name,
    is_active,
    threshold_value,
    params,
    created_at,
    updated_at
)
VALUES (
    1,
    'person_interaction',
    TRUE,
    0.12,
    '{
        "purpose": "close_person_interaction_gate",
        "close_distance_threshold": 0.12,
        "interaction_iou_threshold": 0.05,
        "uses_fields": [
            "motion_stats.interaction_event",
            "motion_stats.interaction.interaction_event",
            "motion_stats.nearby_person.has_close_person",
            "motion_stats.nearby_person.min_other_person_distance",
            "motion_stats.nearby_person.max_other_person_iou"
        ]
    }'::jsonb,
    now(),
    now()
)
ON CONFLICT (model_id, gate_name)
DO UPDATE SET
    is_active = EXCLUDED.is_active,
    threshold_value = EXCLUDED.threshold_value,
    params = EXCLUDED.params,
    updated_at = now();


-- ============================================================
-- 3) Update candidate_gate_decisions gate-name constraint
-- ============================================================
-- service.py inserts one audit row per gate decision into this
-- table. Without this change, person_interaction candidates can
-- fail during ingest with a 500 error.

ALTER TABLE public.candidate_gate_decisions
DROP CONSTRAINT IF EXISTS candidate_gate_decisions_gate_name_check;

ALTER TABLE public.candidate_gate_decisions
ADD CONSTRAINT candidate_gate_decisions_gate_name_check
CHECK (
    gate_name = ANY (
        ARRAY[
            'distribution_score'::text,
            'high_speed'::text,
            'abrupt_direction_change'::text,
            'track_instability'::text,
            'person_interaction'::text
        ]
    )
);

COMMIT;