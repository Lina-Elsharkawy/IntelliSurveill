-- CAMERAS TABLE
create table cameras (
  id bigint primary key generated always as identity,
  name text,
  location text,
  lab_id bigint,
  lab_name text
);

-- DETECTED PEOPLE TABLE 
create table detected_people (
  id bigint primary key generated always as identity,
  name text,
  additional_info text
);

-- ANOMALIES TABLE
create table anomalies (
  id bigint primary key generated always as identity,
  description text,
  severity_level text
);

-- LOGS TABLE 
create table logs (
  id bigint primary key generated always as identity,
  "timestamp" timestamptz not null default now(),
  detected_id bigint,
  camera_id bigint,
  anomaly_id bigint,
  authorized boolean,
  confidence_score real,
  event_type text,
  location text,
  device_status text,
  image_video_ref text,
  processing_time interval,
  model_version text,

  constraint fk_camera foreign key (camera_id) references cameras (id),
  constraint fk_detected_person foreign key (detected_id) references detected_people (id),
  constraint fk_anomaly foreign key (anomaly_id) references anomalies (id)
);
