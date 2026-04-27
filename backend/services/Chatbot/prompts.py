from typing import TypedDict

def get_sql_generation_prompt(user_question: str, schema: str) -> str:
    """
    Generate prompt for converting natural language to SQL
    """
    prompt = f"""You are a PostgreSQL expert. Convert the user's natural language question into a valid SQL query.

DATABASE SCHEMA:
{schema}

RULES:
1. Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
2. Use proper PostgreSQL syntax
3. Include appropriate JOINs if multiple tables are needed
4. Use LIMIT to restrict results when appropriate
5. Return ONLY the SQL query, no explanation, no markdown
6. Do not use semicolons at the end
7. Use double quotes for identifiers if needed (e.g., "table_name")

TABLE HINTS — read carefully before choosing a table:

ANOMALY RULES & DETECTION:
- "anomaly rules" / "rules" / "how many rules"     → use `anomaly_rules` (natural-language NL rules written by admins, has rule_text, rule_type IN ('anomalous','normal'), is_active, camera_id, lab_id)
- "Anomaly_Rules" / "trigger rules" / "suppress"   → use `Anomaly_Rules` (structured rules with rule_type IN ('trigger','suppress'), event_type like 'intrusion','fight_detection', conditions JSONB, source IN ('Admin','Learned'))
- NOTE: There are TWO rule tables. `anomaly_rules` = NL admin rules. `Anomaly_Rules` = structured event rules.
- "anomaly detection rules" / "anomaly_detection_rules" → use `anomaly_detection_rules`
- "anomalyrules"                                    → use `anomalyrules`

ANOMALY EVENTS & LOGS:
- "anomaly definitions" / "anomaly types" / "severity" → use `anomalies` (just id, description, severity_level)
- "anomaly logs" / "anomaly events" / "when was anomaly detected" → use `anomalies_logs` (has timestamp, camera_id, anomaly_id)
- "anomaly logs with description" / "anomaly logs with severity"  → use `anomalies_logs_view` (view joining anomalies_logs + anomalies, has description & severity_level)

ANOMALY PIPELINE:
- "anomaly candidates" / "pending anomalies" / "LLM decisions" → use `anomaly_candidates` (has status IN ('pending','sent_to_llm','resolved','discarded','failed'), alert_decision, severity IN ('LOW','MEDIUM','HIGH'), l2_score)
- "candidate reviews" / "admin confirmed" / "admin dismissed"  → use `anomaly_candidate_review` (has decision IN ('confirmed','dismissed','uncertain'))
- "candidate feedback"                                         → use `anomaly_candidate_feedback`
- "candidate rules" / "rules from candidates"                  → use `anomaly_candidate_rules`
- "ollama jobs" / "LLM jobs" / "model processing"             → use `ollama_jobs` (has status IN ('queued','running','succeeded','failed'), model_name, prompt)
- "thresholds" / "l2 threshold" / "anomaly thresholds"        → use `anomaly_thresholds` (has l2_p95, mse_p95, cos_p95)

PEOPLE & ACCESS:
- "employees" / "staff"                   → use `employees` (name, department_id)
- "visitors"                              → use `visitors` (name, visit_date, purpose)
- "detected people" / "detected persons"  → use `detected_people` (links employee_id or visitor_id)
- "employee lab access" / "who can access lab" → use `employee_lab_access`
- "department lab access"                 → use `department_lab_access`

ENTRY & ACCESS LOGS:
- "entry logs" / "access logs" / "who entered" / "authorized" → use `entry_logs` (has authorized BOOLEAN, event_type, location, timestamp)
- "unknown faces" / "unrecognized people"  → use `unknown_face_events` (has status IN ('pending','assigned','discarded'))
- "face embeddings" / "face vectors"       → use `face_embeddings`

INFRASTRUCTURE:
- "cameras" / "which camera"     → use `cameras` (name, location, lab_id)
- "labs" / "laboratory"          → use `labs`
- "departments"                  → use `departments`
- "schedules" / "access times"   → use `schedules` (access_start_time, access_end_time, weekdays/weekends)
- "edge devices" / "devices"     → use `edge_devices`
- "scene windows" / "video windows" / "embeddings" → use `scene_window_embeddings` (has is_anomalous, l2_score, cosine_distance)
- "behavior models" / "normal models" / "AI models" → use `normal_behavior_models` (has is_active, version)
- "rule conflicts"               → use `rule_conflicts`
You must correctly interpret temporal intent:

- "latest" / "last" → ORDER BY created_at DESC LIMIT 1
- "first" → ORDER BY created_at ASC LIMIT 1
- "last N" → ORDER BY created_at DESC LIMIT N
- "first N" → ORDER BY created_at ASC LIMIT N
- "top N" → ORDER BY created_at DESC LIMIT N
- "most recent N" → ORDER BY created_at DESC LIMIT N
- "recent" → ORDER BY created_at DESC
- "oldest" → ORDER BY created_at ASC

If no N is specified, default:
- "latest", "recent", "last" → LIMIT 1

----------------------------------------
FILTERING INTELLIGENCE RULES
----------------------------------------

1. NAME FILTER
- If user mentions name or keyword:
  → WHERE name ILIKE '%value%'

2. TYPE FILTER
- If user mentions type:
  → WHERE type = 'value'

3. THRESHOLD FILTER
- If user gives numeric condition:
  Examples:
  - "threshold > 10"
  - "threshold below 5"
  → Convert into proper SQL comparison

4. COMBINING FILTERS
- Always use AND for multiple conditions
- Example:
  WHERE type = 'error' AND threshold > 10
USER QUESTION: {user_question}

SQL QUERY:"""
    
    return prompt

def get_error_correction_prompt(
    original_question: str,
    failed_sql: str,
    error_message: str,
    schema: str
) -> str:
    """
    Generate prompt for correcting failed SQL queries
    """
    prompt = f"""The previous SQL query failed. Please fix it.

USER QUESTION: {original_question}

DATABASE SCHEMA:
{schema}

FAILED SQL QUERY:
{failed_sql}

ERROR MESSAGE:
{error_message}

INSTRUCTIONS:
1. Analyze the error message
2. Fix the SQL query
3. Return ONLY the corrected SQL query
4. Do not add explanations or markdown

CORRECTED SQL QUERY:"""
    
    return prompt

def get_result_formatting_prompt(question: str, sql: str, results: list) -> str:
    """
    Generate prompt for formatting results in natural language
    """
    prompt = f"""Format the SQL query results into a natural language response.

USER QUESTION: {question}

SQL QUERY EXECUTED:
{sql}

RESULTS (first 5 rows):
{results[:5]}

TOTAL ROWS: {len(results)}

INSTRUCTIONS:
1. Provide a clear, conversational answer
2. Summarize the key findings
3. If many results, mention the total count
4. Be concise and relevant

ANSWER:"""
    
    return prompt