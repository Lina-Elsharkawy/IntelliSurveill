-- Idempotent Seeding Script (Schema-aligned)
-- Works with create_logging_system_schema.sql
-- Safe to run multiple times.

CREATE EXTENSION IF NOT EXISTS vector;

-- 1) Departments
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM departments) THEN
        INSERT INTO departments (name) VALUES
            ('Computer Science'),
            ('Electrical Engineering'),
            ('Mechanical Engineering'),
            ('Administration');
    END IF;
END $$;

-- 2) Labs
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM labs) THEN
        INSERT INTO labs (name) VALUES
            ('Robotics Lab'),
            ('AI Research Lab'),
            ('Circuit Design Lab'),
            ('General Computing Lab');
    END IF;
END $$;

-- 3) Schedules
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schedules) THEN
        INSERT INTO schedules (
            name,
            access_start_time,
            access_end_time,
            applies_to_weekdays,
            applies_to_weekends,
            specific_dates
        ) VALUES
            ('Standard Work Hours', '09:00:00', '17:00:00', true, false, NULL),
            ('Extended Access',     '08:00:00', '22:00:00', true, true,  NULL),
            ('Weekend Only',        '10:00:00', '18:00:00', false, true, NULL),
            ('Special Event',       '14:00:00', '20:00:00', false, false, ARRAY['2023-12-25'::DATE]);
    END IF;
END $$;

-- 4) Anomalies (definitions)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM anomalies) THEN
        INSERT INTO anomalies (description, severity_level) VALUES
            ('Unauthorized Access', 'High'),
            ('Tailgating',          'Medium'),
            ('Loitering',           'Low'),
            ('Unattended Object',   'Medium');
    END IF;
END $$;

-- 5) Visitors
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM visitors) THEN
        INSERT INTO visitors (name, visit_date, purpose, contact_info) VALUES
            ('Frank Castle', '2023-10-26', 'Delivery',      '555-0101'),
            ('Grace Hopper', '2023-10-27', 'Guest Lecture', '555-0102'),
            ('Hank Pym',     '2023-10-28', 'Maintenance',   '555-0103');
    END IF;
END $$;

-- 6) Employees
DO $$
DECLARE
    dept_cs_id BIGINT;
    dept_ee_id BIGINT;
    dept_me_id BIGINT;
    dept_admin_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM employees) THEN
        SELECT id INTO dept_cs_id    FROM departments WHERE name = 'Computer Science';
        SELECT id INTO dept_ee_id    FROM departments WHERE name = 'Electrical Engineering';
        SELECT id INTO dept_me_id    FROM departments WHERE name = 'Mechanical Engineering';
        SELECT id INTO dept_admin_id FROM departments WHERE name = 'Administration';

        INSERT INTO employees (name, department_id) VALUES
            ('Alice Johnson',  dept_cs_id),
            ('Bob Smith',      dept_cs_id),
            ('Charlie Brown',  dept_ee_id),
            ('Diana Prince',   dept_me_id),
            ('Evan Wright',    dept_admin_id);
    END IF;
END $$;

-- 7) Detected People
DO $$
DECLARE
    emp_alice_id BIGINT;
    emp_bob_id BIGINT;
    vis_frank_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM detected_people) THEN
        SELECT id INTO emp_alice_id FROM employees WHERE name = 'Alice Johnson';
        SELECT id INTO emp_bob_id   FROM employees WHERE name = 'Bob Smith';
        SELECT id INTO vis_frank_id FROM visitors  WHERE name = 'Frank Castle';

        INSERT INTO detected_people (name, additional_info, employee_id, visitor, visitor_id) VALUES
            ('Alice Johnson', 'Identified via face rec', emp_alice_id, false, NULL),
            ('Bob Smith',     'Identified via face rec', emp_bob_id,   false, NULL),
            ('Frank Castle',  'Visitor badge #123',      NULL,         true,  vis_frank_id);
    END IF;
END $$;

-- 8) Cameras
DO $$
DECLARE
    lab_robotics_id BIGINT;
    lab_ai_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cameras) THEN
        SELECT id INTO lab_robotics_id FROM labs WHERE name = 'Robotics Lab';
        SELECT id INTO lab_ai_id       FROM labs WHERE name = 'AI Research Lab';

        INSERT INTO cameras (name, location, lab_id) VALUES
            ('Cam-01', 'Entrance',    lab_robotics_id),
            ('Cam-02', 'Back Corner', lab_robotics_id),
            ('Cam-03', 'Main Hall',   lab_ai_id);
    END IF;
END $$;

-- 9) Department Lab Access
DO $$
DECLARE
    dept_cs_id BIGINT;
    lab_ai_id BIGINT;
    sched_std_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM department_lab_access) THEN
        SELECT id INTO dept_cs_id   FROM departments WHERE name = 'Computer Science';
        SELECT id INTO lab_ai_id    FROM labs        WHERE name = 'AI Research Lab';
        SELECT id INTO sched_std_id FROM schedules   WHERE name = 'Standard Work Hours';

        INSERT INTO department_lab_access (department_id, lab_id, schedule_id)
        VALUES (dept_cs_id, lab_ai_id, sched_std_id);
    END IF;
END $$;

-- 10) Employee Lab Access
DO $$
DECLARE
    emp_alice_id BIGINT;
    lab_robotics_id BIGINT;
    sched_ext_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM employee_lab_access) THEN
        SELECT id INTO emp_alice_id     FROM employees WHERE name = 'Alice Johnson';
        SELECT id INTO lab_robotics_id  FROM labs      WHERE name = 'Robotics Lab';
        SELECT id INTO sched_ext_id     FROM schedules WHERE name = 'Extended Access';

        INSERT INTO employee_lab_access (employee_id, lab_id, schedule_id)
        VALUES (emp_alice_id, lab_robotics_id, sched_ext_id);
    END IF;
END $$;

-- 11) Seed at least one authoritative face embedding (so /match can return "known")
-- We generate a deterministic vector(512) using SQL (no need to type 512 numbers).
DO $$
DECLARE
    det_alice_id BIGINT;
    det_bob_id BIGINT;
    cam_01_id BIGINT;
    entry_id BIGINT;
    v512 vector;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM face_embeddings) THEN
        SELECT id INTO det_alice_id FROM detected_people WHERE name = 'Alice Johnson';
        SELECT id INTO det_bob_id   FROM detected_people WHERE name = 'Bob Smith';
        SELECT id INTO cam_01_id    FROM cameras         WHERE name = 'Cam-01';

        -- Create one entry_log row to link embedding optionally
        INSERT INTO entry_logs (
            "timestamp",
            detected_id,
            camera_id,
            authorized,
            event_type,
            location,
            device_status,
            image_video_ref,
            processing_time,
            model_version
        ) VALUES (
            now() - interval '10 minutes',
            det_alice_id,
            cam_01_id,
            true,
            'face_detected',
            'Entrance',
            'ok',
            'seed://frame_alice.jpg',
            interval '0.2 seconds',
            'seed-model'
        )
        RETURNING id INTO entry_id;

        -- Build a deterministic 512-d vector literal
        SELECT ('[' || string_agg(to_char((sin(i)::float8 * 0.01), 'FM0.000000'), ',') || ']')::vector
        INTO v512
        FROM generate_series(1,512) AS s(i);

        -- Authoritative embedding for Alice
        INSERT INTO face_embeddings (
            detected_id,
            entry_log_id,
            embedding,
            embedding_model,
            is_authoritative,
            quality_score,
            match_confidence,
            notes
        ) VALUES (
            det_alice_id,
            entry_id,
            v512,
            'seed-model',
            true,
            0.95,
            0.99,
            'Seed authoritative embedding for Alice'
        );

        -- Non-authoritative embedding for Bob (optional)
        SELECT ('[' || string_agg(to_char((cos(i)::float8 * 0.01), 'FM0.000000'), ',') || ']')::vector
        INTO v512
        FROM generate_series(1,512) AS s(i);

        INSERT INTO face_embeddings (
            detected_id,
            entry_log_id,
            embedding,
            embedding_model,
            is_authoritative,
            quality_score,
            match_confidence,
            notes
        ) VALUES (
            det_bob_id,
            NULL,
            v512,
            'seed-model',
            false,
            0.80,
            NULL,
            'Seed non-authoritative embedding for Bob'
        );
    END IF;
END $$;

-- 12) Seed some anomalies logs (uses anomalies_logs, not "logs")
DO $$
DECLARE
    cam_01_id BIGINT;
    det_unknown_id BIGINT;
    anom_unauth_id BIGINT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM anomalies_logs) THEN
        SELECT id INTO cam_01_id      FROM cameras        WHERE name = 'Cam-01';
        SELECT id INTO det_unknown_id FROM detected_people WHERE name = 'Frank Castle';
        SELECT id INTO anom_unauth_id FROM anomalies      WHERE description = 'Unauthorized Access';

        INSERT INTO anomalies_logs ("timestamp", detected_id, camera_id, anomaly_id) VALUES
            (now() - interval '30 minutes', det_unknown_id, cam_01_id, anom_unauth_id);
    END IF;
END $$;
