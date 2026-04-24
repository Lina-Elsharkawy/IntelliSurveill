-- =========================================
-- Fix Anomaly_Rules schema to match API
-- =========================================

-- 1. Add missing columns
ALTER TABLE Anomaly_Rules
ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'intrusion',
ADD COLUMN IF NOT EXISTS conditions JSONB DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS source VARCHAR(50) DEFAULT 'Admin',
ADD COLUMN IF NOT EXISTS active BOOLEAN,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

-- 2. Backfill existing data safely
UPDATE Anomaly_Rules SET event_type = 'intrusion' WHERE event_type IS NULL;
UPDATE Anomaly_Rules SET conditions = '{}'::jsonb WHERE conditions IS NULL;
UPDATE Anomaly_Rules SET source = 'Admin' WHERE source IS NULL;

-- Map old is_active → new active
UPDATE Anomaly_Rules SET active = is_active WHERE active IS NULL;
UPDATE Anomaly_Rules SET active = TRUE WHERE active IS NULL;

-- 3. Make columns NOT NULL
ALTER TABLE Anomaly_Rules
ALTER COLUMN event_type SET NOT NULL,
ALTER COLUMN conditions SET NOT NULL,
ALTER COLUMN source SET NOT NULL,
ALTER COLUMN active SET NOT NULL,
ALTER COLUMN updated_at SET NOT NULL;

-- 4. Fix constraints (match create_logging_system_schema.sql exactly)
ALTER TABLE Anomaly_Rules DROP CONSTRAINT IF EXISTS anomaly_rules_rule_type_check;
ALTER TABLE Anomaly_Rules DROP CONSTRAINT IF EXISTS anomaly_rules_event_type_check;
ALTER TABLE Anomaly_Rules DROP CONSTRAINT IF EXISTS anomaly_rules_source_check;

ALTER TABLE Anomaly_Rules ADD CONSTRAINT anomaly_rules_rule_type_check
CHECK (rule_type IN ('trigger', 'suppress'));

ALTER TABLE Anomaly_Rules ADD CONSTRAINT anomaly_rules_event_type_check
CHECK (event_type IN ('intrusion', 'loitering', 'after_hours', 'fall_detected', 'fight_detection', 'camera_tamper', 'sudden_movement', 'smoke_fire', 'crowd_detection', 'other'));

ALTER TABLE Anomaly_Rules ADD CONSTRAINT anomaly_rules_source_check
CHECK (source IN ('Admin', 'Learned'));

-- 5. Drop obsolete columns
ALTER TABLE Anomaly_Rules
DROP COLUMN IF EXISTS is_active CASCADE,
DROP COLUMN IF EXISTS reviewer CASCADE,
DROP COLUMN IF EXISTS source_candidate_id CASCADE,
DROP COLUMN IF EXISTS camera_id CASCADE,
DROP COLUMN IF EXISTS lab_id CASCADE;