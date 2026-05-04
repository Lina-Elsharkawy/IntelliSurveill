"""
Prompts for the SQL fallback path.
Only used when no deterministic tool matched the question.
Kept intentionally short — small (7B) models perform better with focused prompts.

Token budget for qwen2.5-coder:7b at 4096 tokens:
  Prompt overhead          ~200 tokens
  Schema (hard-capped)    ~1500 tokens  (≈ 6000 chars)
  History (2 turns)        ~200 tokens
  Question                  ~50 tokens
  Response (num_predict)   ~350 tokens
  ──────────────────────────────────────
  Total                   ~2300 tokens  ← well under 4096

NEVER pass the full raw schema — always pass relevant_tables only.
"""

# Hard cap on schema characters sent to the LLM.
# 6000 chars ≈ 1500 tokens. Enough for 3-5 tables.
_MAX_SCHEMA_CHARS = 6_000


def get_sql_generation_prompt(user_question: str, schema: str, history: list = None) -> str:
    relevant_tables = _pick_relevant_tables(user_question, schema)
    # Hard cap — prevents context overflow even when many tables match
    if len(relevant_tables) > _MAX_SCHEMA_CHARS:
        relevant_tables = relevant_tables[:_MAX_SCHEMA_CHARS] + "\n  ...(schema truncated)"

    history_str = ""
    if history:
        last = history[-2:]  # 2 turns only — saves ~150 tokens
        history_str = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in last
        )

    return f"""You are a PostgreSQL expert. Convert the user's natural language question into a valid SQL query.

the old context is:
{history_str or 'None'}

RULES:
1. Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
2. Use proper PostgreSQL syntax
3. Include appropriate JOINs if multiple tables are needed
4. Use LIMIT to restrict results when appropriate
5. Think step-by-step. First, write your reasoning in SQL comments starting with `-- `. Then, write the final SQL query. Do not use markdown backticks.
6. Do not use semicolons at the end
7. Use double quotes for identifiers if needed (e.g., "table_name")
8. ONLY add `table_schema = 'public'` when querying `information_schema.tables` or `information_schema.columns`
9. If you need to count tables, your query MUST exactly be: `SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'`

You must correctly interpret temporal intent:

- Do NOT assume every table has created_at.
- For ordering by time, use the actual timestamp/date column shown in the schema.
- Prefer these known columns:
  * entry_logs: "timestamp"
  * anomalies_logs: "timestamp"
  * unknown_face_events: created_at if available, otherwise "timestamp" if available
  * anomaly_candidates: created_at
  * anomaly_candidate_review: reviewed_at or created_at if available
  * anomaly_rules: created_at
  * ollama_jobs: created_at if available
- "latest" / "last" / "most recent" → ORDER BY the correct time column DESC
- "first" / "earliest" / "oldest" → ORDER BY the correct time column ASC
- "latest N" / "last N" / "most recent N" → ORDER BY the correct time column DESC LIMIT N
- If no time column exists, order by id DESC for latest and id ASC for first.

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
Surveillance System: Compact Schema Reference
1. Core Entities (Identity & Location)
departments (id, name)

Organizational units used to group employees and define access rights.  

labs (id, name)

Specific physical rooms or zones where cameras are installed.  

cameras (id, name, location, lab_id)

Individual video sources mapped to a specific lab and physical location.  

edge_devices (id, device_key, name, location, created_at)

Registry for hardware units (e.g., Jetson/RockPI) processing video at the source.  

visitors (id, name, visit_date, purpose, contact_info)

Temporary guest records, tracking their purpose and date of visit.  

employees (id, name, department_id)

Staff records linked to departments for authorization.  

2. Access & Scheduling (Authorization Logic)
schedules (id, name, access_start/end_time, applies_to_weekdays/weekends, specific_dates)

Defines the "When" for authorized entry.  

department_lab_access (id, department_id, lab_id, schedule_id)

Broad access permissions for entire departments.  

employee_lab_access (id, employee_id, lab_id, schedule_id)

Granular access permissions for individual staff members.  

3. Detection & Biometrics (The "Who" and "When")
detected_people (id, name, additional_info, employee_id, visitor, visitor_id)

Links a physical sighting to a known identity or marks them as "Visitor".  

entry_logs (id, timestamp, detected_id, camera_id, authorized [bool], event_type, location, device_status, image_video_ref)

The primary audit trail for every sighting and authorization check.  

face_embeddings (id, detected_id, entry_log_id, embedding [vector 512], embedding_model, is_authoritative, quality_score)

Biometric data for rapid comparison and identity verification.  

unknown_face_events (id, entry_log_id, embedding [vector 512], status [pending/assigned/discarded])

Holding area for faces the system could not identify automatically.  

4. Anomaly Pipeline (The "What" - VideoMAE)
normal_behavior_models (id, name, version, teacher_model, student_model, embedding_dim, is_active)

Registry for the AI models scoring video for behavioral anomalies.  

anomaly_thresholds (id, model_id, l2_p95, mse_p95, cos_p95, val_samples)

Statistical cut-offs (e.g., p95 scores) used to trigger anomaly alerts.  

scene_window_embeddings (id, model_id, camera_id, track_id, window_start/end_ts, student/teacher_embedding [vector 2304], l2_score, is_anomalous)

High-dimensional vectors representing specific video clips for behavioral analysis.  

5. Reasoning, Rules, & Review (Human-in-the-Loop)
anomaly_candidates (id, scene_window_embedding_id, reason, status, severity, alert_decision [YES/NO], decision_reason)

Events flagged by the AI awaiting LLM or Admin validation.  

anomaly_rules (id, rule_text, rule_type [trigger/suppress], event_type [intrusion/loitering/fight/etc.], conditions [JSONB], source [Admin/Learned], active [BOOLEAN] -- NOTE: column is "active" NOT "is_active")

Natural language rules that guide the LLM's reasoning process.  

anomaly_candidate_review (id, anomaly_candidate_id, decision [confirmed/dismissed], rule_text, created_rule_id, reviewer)

Logs of human feedback used to refine the system and generate new rules.  

rule_conflicts (id, rule_id_1, rule_id_2, conflict_reason, status)

Tracks contradictions between different monitoring rules.  

ollama_jobs (id, anomaly_candidate_id, model_name, prompt, status, response_text)

Queue management for the local LLM reasoning tasks.

----------------------------------------
EXAMPLES (Few-Shot)
----------------------------------------

Question: "Who was the last person seen by the front door camera?"
-- I need the latest person seen by a specific camera.
-- Join entry_logs with detected_people and cameras.
-- Filter camera location and order by timestamp DESC.
SELECT d.name, e.timestamp 
FROM entry_logs e
JOIN cameras c ON e.camera_id = c.id
JOIN detected_people d ON e.detected_id = d.id
WHERE c.location ILIKE '%front door%'
ORDER BY e.timestamp DESC
LIMIT 1

Question: "How many employees are in the IT department?"
-- Count the employees that belong to the IT department.
-- Join employees and departments.
SELECT COUNT(*) 
FROM employees e
JOIN departments d ON e.department_id = d.id
WHERE d.name ILIKE '%IT%'

Question: "Show me the 3 most severe anomalies."
-- The user wants anomaly_candidates ordered by severity.
SELECT id, reason, severity, status
FROM anomaly_candidates
ORDER BY severity DESC
LIMIT 3

----------------------------------------

USER QUESTION: {user_question}

SQL QUERY:"""


def get_error_correction_prompt(original_question: str, failed_sql: str,
                                error_message: str, schema: str) -> str:
    relevant_tables = _pick_relevant_tables(original_question, schema)
    if len(relevant_tables) > _MAX_SCHEMA_CHARS:
        relevant_tables = relevant_tables[:_MAX_SCHEMA_CHARS] + "\n  ...(schema truncated)"

    return f"""Fix this broken PostgreSQL SELECT query.

SCHEMA:
{relevant_tables}

ORIGINAL QUESTION: {original_question}

BROKEN SQL:
{failed_sql}

ERROR:
{error_message}

RULES:
- Return ONLY the corrected SQL query.
- No explanation, no markdown, no backticks, no semicolons.
- Must be a SELECT or WITH query only.
- Use double quotes for "timestamp" column.

CORRECTED SQL:"""


def get_result_formatting_prompt(question: str, sql: str, results: list) -> str:
    # Strip embedding/binary columns — they are 512-float vectors that add
    # ~3K chars per row and are meaningless to the LLM for formatting.
    _SKIP_COLS = {"embedding", "face_embedding", "vector", "encoding",
                  "scene_embedding", "image_data", "thumbnail"}

    def _strip(row):
        if not isinstance(row, dict):
            return row
        return {k: v for k, v in row.items() if k.lower() not in _SKIP_COLS}

    display = [_strip(r) for r in results[:20]]  # cap at 20 stripped rows
    total = len(results)

    return f"""You are a surveillance assistant. Answer the user's question based on these database results.

USER QUESTION: {question}

SQL USED: {sql}

RESULTS ({total} total rows, showing first {len(display)}):
{display}

INSTRUCTIONS:
- Give a clear, conversational answer in 2-4 sentences.
- Mention the total count if relevant.
- If no results, say so clearly.
- Do not make up information not in the results.

ANSWER:"""


def _pick_relevant_tables(question: str, schema: str) -> str:
    """Extract only the schema sections relevant to this question."""
    q = question.lower()

    table_keywords = {
        "anomaly_rules":          ["rule", "rules", "trigger", "suppress"],
        "rule_conflicts":         ["conflict", "conflicts", "contradict"],
        "anomalies":              ["anomaly", "anomalies", "severity"],
        "anomalies_logs":         ["anomaly log", "anomaly logs", "incident", "incidents", "alert"],
        "anomaly_candidates":     ["candidate", "pending", "llm decision"],
        "anomaly_thresholds":     ["threshold", "thresholds"],
        "normal_behavior_models": ["model", "models", "normal behavior"],
        "cameras":                ["camera", "cameras"],
        "employees":              ["employee", "employees", "staff"],
        "visitors":               ["visitor", "visitors"],
        "entry_logs":             ["entry", "access", "entered", "authorized", "detected", "seen"],
        "detected_people":        ["detected", "people", "person", "face"],
        "unknown_face_events":    ["unknown face", "unknown faces", "stranger", "unidentified", "unreviewed"],
        "face_embeddings":        ["embedding", "embeddings"],
        "labs":                   ["lab", "laboratory"],
        "departments":            ["department", "departments"],
        "employee_lab_access":    ["employee lab access", "employee access"],
        "department_lab_access":  ["department lab access", "department access"],
        "schedules":              ["schedule", "schedules"],
        "scene_window_embeddings": ["scene", "window", "scene embedding"],
    }

    matched = set()
    for table, keywords in table_keywords.items():
        if any(kw in q for kw in keywords):
            matched.add(table)

    if not matched:
        matched = {"anomalies_logs", "cameras", "employees", "entry_logs"}

    lines = schema.split("\n")
    result = []
    include = False
    for line in lines:
        if line.startswith("Table: "):
            include = any(t in line for t in matched)
        if include:
            result.append(line)

    return "\n".join(result)