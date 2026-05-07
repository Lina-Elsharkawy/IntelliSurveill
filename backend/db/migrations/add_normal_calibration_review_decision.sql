ALTER TABLE anomaly_candidate_review
DROP CONSTRAINT IF EXISTS anomaly_candidate_review_decision_check;

ALTER TABLE anomaly_candidate_review
ADD CONSTRAINT anomaly_candidate_review_decision_check
CHECK (
  decision IN (
    'confirmed',
    'dismissed',
    'uncertain',
    'normal_calibration'
  )
);