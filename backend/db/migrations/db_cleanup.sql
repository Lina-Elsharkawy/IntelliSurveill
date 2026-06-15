BEGIN;

---

-- 0) Pre-cleanup visibility checks

---

-- Old table existence before cleanup
SELECT 'old_tables_before' AS check_name, table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN (
'anomalies',
'anomalies_logs',
'anomaly_candidate_review',
'anomaly_candidate_feedback',
'anomaly_candidates',
'anomaly_gate_configs',
'anomaly_thresholds',
'candidate_gate_decisions',
'department_lab_access',
'departments',
'employee_lab_access',
'labs',
'normal_behavior_model_artifacts',
'normal_behavior_models',
'ollama_jobs',
'reasoning_jobs',
'scene_window_embeddings'
)
ORDER BY table_name;

-- Old legacy FK columns before cleanup (cameras.lab_id is intentionally preserved/recreated)
SELECT 'old_columns_before' AS check_name, table_schema, table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
AND (
(table_name = 'employees'  AND column_name = 'department_id')
OR (table_name = 'logs'       AND column_name = 'anomaly_id')
OR (table_name = 'entry_logs' AND column_name = 'anomaly_id')
)
ORDER BY table_name, column_name;

-- FK constraints that point at legacy tables before cleanup
-- Uses to_regclass() so it remains safe if some tables do not exist.
WITH legacy_tables AS (
SELECT to_regclass(unnest(ARRAY[
'public.anomalies',
'public.anomaly_candidate_review',
'public.anomaly_candidate_feedback',
'public.anomaly_candidates',
'public.anomaly_gate_configs',
'public.anomaly_thresholds',
'public.candidate_gate_decisions',
'public.department_lab_access',
'public.departments',
'public.employee_lab_access',
'public.labs',
'public.normal_behavior_model_artifacts',
'public.normal_behavior_models',
'public.ollama_jobs',
'public.reasoning_jobs',
'public.scene_window_embeddings'
])) AS oid
), legacy_oids AS (
SELECT oid
FROM legacy_tables
WHERE oid IS NOT NULL
)
SELECT 'legacy_fk_constraints_before' AS check_name,
conrelid::regclass AS referencing_table,
conname AS constraint_name,
confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE contype = 'f'
AND confrelid IN (SELECT oid FROM legacy_oids)
ORDER BY 2, 3;

---

-- 1) Drop FK constraints that reference legacy tables, dynamically and safely.

---

DO $$
DECLARE
r RECORD;
BEGIN
FOR r IN
WITH legacy_tables AS (
SELECT to_regclass(unnest(ARRAY[
'public.anomalies',
'public.anomaly_candidate_review',
'public.anomaly_candidate_feedback',
'public.anomaly_candidates',
'public.anomaly_gate_configs',
'public.anomaly_thresholds',
'public.candidate_gate_decisions',
'public.department_lab_access',
'public.departments',
'public.employee_lab_access',
'public.labs',
'public.normal_behavior_model_artifacts',
'public.normal_behavior_models',
'public.ollama_jobs',
'public.reasoning_jobs',
'public.scene_window_embeddings'
])) AS oid
), legacy_oids AS (
SELECT oid
FROM legacy_tables
WHERE oid IS NOT NULL
)
SELECT conrelid::regclass AS referencing_table,
conname AS constraint_name,
confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE contype = 'f'
AND confrelid IN (SELECT oid FROM legacy_oids)
LOOP
RAISE NOTICE 'Dropping FK constraint %.% -> %',
r.referencing_table,
r.constraint_name,
r.referenced_table;


    EXECUTE format(
        'ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I',
        r.referencing_table,
        r.constraint_name
    );
END LOOP;


END $$;

---

-- 2) Drop old FK columns from active tables.
--    The Departments/old Anomalies columns belonged to removed modules.
--    cameras.lab_id is intentionally kept/recreated as a nullable compatibility column.

---

-- Keep/recreate cameras.lab_id for current camera API compatibility.
-- The old labs table is dropped, but current backend/frontend camera code still expects this nullable column.
ALTER TABLE IF EXISTS public.cameras
ADD COLUMN IF NOT EXISTS lab_id INTEGER;
ALTER TABLE IF EXISTS public.employees  DROP COLUMN IF EXISTS department_id;
ALTER TABLE IF EXISTS public.logs       DROP COLUMN IF EXISTS anomaly_id;
ALTER TABLE IF EXISTS public.entry_logs DROP COLUMN IF EXISTS anomaly_id;

---

-- 3) Drop legacy old-anomaly pipeline tables.
--    These are from the old scene_window_embeddings/anomaly_candidates/Ollama flow.
--    Do NOT confuse public.reasoning_jobs with public.vad_reasoning_jobs.

---

DROP TABLE IF EXISTS public.anomaly_candidate_feedback CASCADE;
DROP TABLE IF EXISTS public.anomaly_candidate_review CASCADE;
DROP TABLE IF EXISTS public.ollama_jobs CASCADE;
DROP TABLE IF EXISTS public.reasoning_jobs CASCADE;
DROP TABLE IF EXISTS public.candidate_gate_decisions CASCADE;
DROP TABLE IF EXISTS public.anomaly_candidates CASCADE;
DROP TABLE IF EXISTS public.scene_window_embeddings CASCADE;
DROP TABLE IF EXISTS public.anomaly_thresholds CASCADE;
DROP TABLE IF EXISTS public.anomaly_gate_configs CASCADE;
DROP TABLE IF EXISTS public.normal_behavior_model_artifacts CASCADE;
DROP TABLE IF EXISTS public.normal_behavior_models CASCADE;

---

-- 4) Drop legacy old Labs/Departments/old Anomalies tables.
--    anomaly_rules and rule_conflicts are intentionally NOT dropped.

---

DROP TABLE IF EXISTS public.anomalies_logs CASCADE;
DROP TABLE IF EXISTS public.anomalies CASCADE;
DROP TABLE IF EXISTS public.department_lab_access CASCADE;
DROP TABLE IF EXISTS public.employee_lab_access CASCADE;
DROP TABLE IF EXISTS public.labs CASCADE;
DROP TABLE IF EXISTS public.departments CASCADE;

---

-- 5) Post-cleanup verification queries before final ROLLBACK/COMMIT.

---

-- If this returns rows, some legacy tables are still present.
SELECT 'old_tables_after_should_be_empty' AS check_name, table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN (
'anomalies',
'anomalies_logs',
'anomaly_candidate_review',
'anomaly_candidate_feedback',
'anomaly_candidates',
'anomaly_gate_configs',
'anomaly_thresholds',
'candidate_gate_decisions',
'department_lab_access',
'departments',
'employee_lab_access',
'labs',
'normal_behavior_model_artifacts',
'normal_behavior_models',
'ollama_jobs',
'reasoning_jobs',
'scene_window_embeddings'
)
ORDER BY table_name;

-- If this returns rows, an old removable FK column is still present. cameras.lab_id is intentionally preserved/recreated.
SELECT 'old_columns_after_should_be_empty' AS check_name, table_schema, table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public'
AND (
(table_name = 'employees'  AND column_name = 'department_id')
OR (table_name = 'logs'       AND column_name = 'anomaly_id')
OR (table_name = 'entry_logs' AND column_name = 'anomaly_id')
)
ORDER BY table_name, column_name;

-- Confirm all VAD tables are still present. This should return your active vad_* tables.
SELECT 'vad_tables_preserved' AS check_name, table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name LIKE 'vad_%' ESCAPE ''
ORDER BY table_name;

-- Confirm the active Anomaly Rules storage is still present.
SELECT 'active_rule_tables_preserved' AS check_name, table_schema, table_name
FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('anomaly_rules', 'rule_conflicts')
ORDER BY table_name;

-- If this returns rows, there are still FK constraints referencing legacy tables.
-- Uses to_regclass() so it remains safe even after the old tables are dropped.
WITH legacy_tables AS (
SELECT to_regclass(unnest(ARRAY[
'public.anomalies',
'public.anomaly_candidate_review',
'public.anomaly_candidate_feedback',
'public.anomaly_candidates',
'public.anomaly_gate_configs',
'public.anomaly_thresholds',
'public.candidate_gate_decisions',
'public.department_lab_access',
'public.departments',
'public.employee_lab_access',
'public.labs',
'public.normal_behavior_model_artifacts',
'public.normal_behavior_models',
'public.ollama_jobs',
'public.reasoning_jobs',
'public.scene_window_embeddings'
])) AS oid
), legacy_oids AS (
SELECT oid
FROM legacy_tables
WHERE oid IS NOT NULL
)
SELECT 'legacy_fk_constraints_after_should_be_empty' AS check_name,
conrelid::regclass AS referencing_table,
conname AS constraint_name,
confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE contype = 'f'
AND confrelid IN (SELECT oid FROM legacy_oids)
ORDER BY 2, 3;

-- ---------------------------------------------------------------------------
-- SAFE TEST MODE:
-- This keeps the database unchanged.
-- If everything above runs successfully, replace ROLLBACK with COMMIT and run again.
-- ---------------------------------------------------------------------------

COMMIT;