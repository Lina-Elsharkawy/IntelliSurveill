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
