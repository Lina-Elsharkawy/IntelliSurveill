-- ==========================
-- Core entity tables
-- ==========================

CREATE TABLE IF NOT EXISTS departments (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labs (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  access_start_time TIME,
  access_end_time TIME,
  applies_to_weekdays BOOLEAN DEFAULT false,
  applies_to_weekends BOOLEAN DEFAULT false,
  specific_dates DATE[]
);

CREATE TABLE IF NOT EXISTS employees (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  department_id BIGINT REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS visitors (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  visit_date DATE,
  purpose TEXT,
  contact_info TEXT
);

-- Final version of detected_people
CREATE TABLE IF NOT EXISTS detected_people (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT,
  additional_info TEXT,
  employee_id BIGINT REFERENCES employees(id),
  visitor BOOLEAN DEFAULT false,
  visitor_id BIGINT REFERENCES visitors(id)
);

-- anomalies table (unchanged except final form)
CREATE TABLE IF NOT EXISTS anomalies (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  description TEXT,
  severity_level TEXT
);

-- cameras table with final columns
CREATE TABLE IF NOT EXISTS cameras (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT,
  location TEXT,
  lab_id BIGINT REFERENCES labs(id)
);

-- join tables with schedules applied
CREATE TABLE IF NOT EXISTS department_lab_access (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  department_id BIGINT REFERENCES departments(id),
  lab_id BIGINT REFERENCES labs(id),
  schedule_id BIGINT REFERENCES schedules(id)
);

CREATE TABLE IF NOT EXISTS employee_lab_access (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  employee_id BIGINT REFERENCES employees(id),
  lab_id BIGINT REFERENCES labs(id),
  schedule_id BIGINT REFERENCES schedules(id)
);

-- ==========================
-- Logs table (final version)
-- ==========================

CREATE TABLE IF NOT EXISTS logs (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  "timestamp" TIMESTAMPTZ NOT NULL DEFAULT now(),
  detected_id BIGINT REFERENCES detected_people(id),
  camera_id BIGINT REFERENCES cameras(id),
  anomaly_id BIGINT REFERENCES anomalies(id),
  authorized BOOLEAN,
  confidence_score REAL,
  event_type TEXT,
  location TEXT,
  device_status TEXT,
  image_video_ref TEXT,
  processing_time INTERVAL,
  model_version TEXT
);

-- ==========================
-- Indexes
-- ==========================

CREATE INDEX IF NOT EXISTS idx_employees_department_id ON employees(department_id);
CREATE INDEX IF NOT EXISTS idx_detected_people_employee_id ON detected_people(employee_id);
CREATE INDEX IF NOT EXISTS idx_detected_people_visitor_id ON detected_people(visitor_id);
CREATE INDEX IF NOT EXISTS idx_cameras_lab_id ON cameras(lab_id);
CREATE INDEX IF NOT EXISTS idx_department_lab_access_department_id ON department_lab_access(department_id);
CREATE INDEX IF NOT EXISTS idx_department_lab_access_lab_id ON department_lab_access(lab_id);
CREATE INDEX IF NOT EXISTS idx_department_lab_access_schedule_id ON department_lab_access(schedule_id);
CREATE INDEX IF NOT EXISTS idx_employee_lab_access_employee_id ON employee_lab_access(employee_id);
CREATE INDEX IF NOT EXISTS idx_employee_lab_access_lab_id ON employee_lab_access(lab_id);
CREATE INDEX IF NOT EXISTS idx_employee_lab_access_schedule_id ON employee_lab_access(schedule_id);
CREATE INDEX IF NOT EXISTS idx_logs_detected_id ON logs(detected_id);
CREATE INDEX IF NOT EXISTS idx_logs_camera_id ON logs(camera_id);
CREATE INDEX IF NOT EXISTS idx_logs_anomaly_id ON logs(anomaly_id);

