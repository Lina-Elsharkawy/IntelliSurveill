-- ==========================
-- Core entity tables
-- ==========================

CREATE TABLE departments (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL
);

CREATE TABLE labs (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL
);

CREATE TABLE schedules (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  access_start_time TIME,
  access_end_time TIME,
  applies_to_weekdays BOOLEAN DEFAULT false,
  applies_to_weekends BOOLEAN DEFAULT false,
  specific_dates DATE[]
);

CREATE TABLE employees (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  department_id BIGINT REFERENCES departments(id)
);

CREATE TABLE visitors (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT NOT NULL,
  visit_date DATE,
  purpose TEXT,
  contact_info TEXT
);

-- Final version of detected_people
CREATE TABLE detected_people (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT,
  additional_info TEXT,
  employee_id BIGINT REFERENCES employees(id),
  visitor BOOLEAN DEFAULT false,
  visitor_id BIGINT REFERENCES visitors(id)
);

-- anomalies table (unchanged except final form)
CREATE TABLE anomalies (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  description TEXT,
  severity_level TEXT
);

-- cameras table with final columns
CREATE TABLE cameras (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  name TEXT,
  location TEXT,
  lab_id BIGINT REFERENCES labs(id)
);

-- join tables with schedules applied
CREATE TABLE department_lab_access (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  department_id BIGINT REFERENCES departments(id),
  lab_id BIGINT REFERENCES labs(id),
  schedule_id BIGINT REFERENCES schedules(id)
);

CREATE TABLE employee_lab_access (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  employee_id BIGINT REFERENCES employees(id),
  lab_id BIGINT REFERENCES labs(id),
  schedule_id BIGINT REFERENCES schedules(id)
);

-- ==========================
-- Logs table (final version)
-- ==========================

CREATE TABLE logs (
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
