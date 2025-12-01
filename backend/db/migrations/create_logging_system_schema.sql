-- 1. Departments
CREATE TABLE departments (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- 2. Labs
CREATE TABLE labs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL
);

-- 3. Schedules
CREATE TABLE schedules (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    access_start_time TIME,
    access_end_time TIME,
    applies_to_weekdays BOOLEAN DEFAULT FALSE,
    applies_to_weekends BOOLEAN DEFAULT FALSE,
    specific_dates DATE[]
);

-- 4. Anomalies (Definitions)
CREATE TABLE anomalies (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    description TEXT,
    severity_level TEXT
);

-- 5. Visitors
CREATE TABLE visitors (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    visit_date DATE,
    purpose TEXT,
    contact_info TEXT
);

-- 6. Employees
CREATE TABLE employees (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    department_id BIGINT REFERENCES departments(id)
);

-- 7. Cameras
CREATE TABLE cameras (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT,
    location TEXT,
    lab_id BIGINT REFERENCES labs(id)
);

-- 8. Detected People
CREATE TABLE detected_people (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT,
    additional_info TEXT,
    employee_id BIGINT REFERENCES employees(id),
    visitor BOOLEAN DEFAULT FALSE,
    visitor_id BIGINT REFERENCES visitors(id)
);

-- 9. Department Lab Access
CREATE TABLE department_lab_access (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    department_id BIGINT REFERENCES departments(id),
    lab_id BIGINT REFERENCES labs(id),
    schedule_id BIGINT REFERENCES schedules(id)
);

-- 10. Employee Lab Access
CREATE TABLE employee_lab_access (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    employee_id BIGINT REFERENCES employees(id),
    lab_id BIGINT REFERENCES labs(id),
    schedule_id BIGINT REFERENCES schedules(id)
);

-- 11. Entry Logs
CREATE TABLE entry_logs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp" TIMESTAMPTZ DEFAULT now(),
    detected_id BIGINT REFERENCES detected_people(id),
    camera_id BIGINT REFERENCES cameras(id),
    authorized BOOLEAN,
    event_type TEXT,
    location TEXT,
    device_status TEXT,
    image_video_ref TEXT,
    processing_time INTERVAL,
    model_version TEXT
);

-- 12. Anomalies Logs
CREATE TABLE anomalies_logs (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    "timestamp" TIMESTAMPTZ DEFAULT now(),
    detected_id BIGINT REFERENCES detected_people(id),
    camera_id BIGINT REFERENCES cameras(id),
    anomaly_id BIGINT REFERENCES anomalies(id)
);

-- 13. View
CREATE OR REPLACE VIEW anomalies_logs_view AS
SELECT
    al.id,
    al."timestamp",
    al.detected_id,
    al.camera_id,
    a.description,
    a.severity_level
FROM
    anomalies_logs al
    JOIN anomalies a ON al.anomaly_id = a.id;
