"""
prompts.py — Prompts for the SQL fallback path.

Only used when the LLM understanding layer (intent_router.py) routes a
question to "sql_fallback" — i.e. no deterministic tool matched.

Schema: rewritten for the VAD-based surveillance schema (see tools.py header
for the full table group breakdown). The old anomaly_candidates / ollama_jobs /
labs / departments tables no longer exist — do not reintroduce them here.

Token budget for qwen2.5-coder:7b at 8192 tokens:
  Prompt overhead          ~250 tokens
  Schema (hard-capped)    ~1500 tokens
  History (2 turns)        ~200 tokens
  Question                  ~50 tokens
  Response (num_predict)   ~400 tokens
  ──────────────────────────────────────
  Total                   ~2400 tokens  ← well under 8192

NEVER pass the full raw schema — always pass relevant_tables only.
"""

_MAX_SCHEMA_CHARS = 6_000


def get_sql_generation_prompt(user_question: str, schema: str, history: list = None) -> str:
    relevant_tables = _pick_relevant_tables(user_question, schema)
    if len(relevant_tables) > _MAX_SCHEMA_CHARS:
        relevant_tables = relevant_tables[:_MAX_SCHEMA_CHARS] + "\n  ...(schema truncated)"

    history_str = ""
    if history:
        last = history[-2:]
        history_str = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
            for m in last
        )

    return f"""You are a PostgreSQL expert. Convert the user's natural language question into a valid SQL query.

RECENT CONVERSATION:
{history_str or 'None'}

DATABASE SCHEMA (relevant tables only):
{relevant_tables}

RULES:
1. Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
2. Use proper PostgreSQL syntax
3. Include appropriate JOINs if multiple tables are needed
4. Use LIMIT to restrict results when appropriate
5. Think step-by-step. First, write your reasoning in SQL comments starting with `-- `. Then, write the final SQL query. Do not use markdown backticks.
6. Do not use semicolons at the end
7. Use double quotes for identifiers that need them (e.g. "timestamp")
8. ONLY add `table_schema = 'public'` when querying `information_schema.tables` or `information_schema.columns`
9. If you need to count tables, your query MUST exactly be: `SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'`

TIME COLUMN RULES — do not guess, use exactly these:
  * entry_logs              → "timestamp"
  * unknown_face_events      → created_at
  * vad_anomaly_cases        → start_ts (also peak_ts, end_ts)
  * vad_gate_events          → start_ts (also peak_ts, end_ts)
  * vad_reasoning_jobs       → queued_at (also started_at, finished_at)
  * vad_reasoning_results    → created_at
  * vad_case_reviews         → created_at
  * vad_stream_sessions      → started_at
  * anomaly_rules            → created_at
  * activity_logs            → "timestamp"
  * audit_logs               → created_at
  * face_embeddings          → created_at

- "latest" / "last" / "most recent" → ORDER BY the correct time column DESC
- "first" / "earliest" / "oldest" → ORDER BY the correct time column ASC
- "latest N" / "last N" → ORDER BY ... DESC LIMIT N
- If no N is specified for "latest"/"recent"/"last" → LIMIT 1
- If no time column applies, order by id DESC for latest, id ASC for first.

KEY SCHEMA NOTES:
- anomaly_rules.active is boolean — column name is "active", NOT "is_active"
- vad_anomaly_cases.status ∈ {{open, evidence_ready, reasoning_queued, reasoning_done, confirmed, dismissed, needs_review, archived, debug}}
- vad_anomaly_cases.severity ∈ {{unknown, low, medium, high, critical}}
- vad_gate_events.severity ∈ {{unknown, low, medium, high, critical}}
- vad_reasoning_jobs.status ∈ {{queued, running, succeeded, failed, cancelled}}
- vad_reasoning_results.alert_decision ∈ {{YES, NO, UNCERTAIN}}
- vad_case_reviews.decision ∈ {{confirmed, dismissed, uncertain, calibration_feedback, needs_more_evidence}}
- unknown_face_events.status ∈ {{pending, assigned, discarded}}
- A person can be an employee, a visitor, or just a name in detected_people with no FK — always COALESCE(e.name, v.name, dp.name)

FILTERING RULES:
- Name filter → WHERE name ILIKE '%value%'
- Status/type filter → WHERE column = 'value' (use exact enum values above)
- Numeric threshold → convert directly to SQL comparison
- Multiple filters → combine with AND

EXAMPLES (Few-Shot):

Question: "Who was the last person seen by camera 3?"
-- Latest detection on a specific camera. Join entry_logs, detected_people, cameras.
SELECT COALESCE(e.name, v.name, dp.name) AS person_name, el."timestamp"
FROM entry_logs el
JOIN detected_people dp ON el.detected_id = dp.id
LEFT JOIN employees e ON dp.employee_id = e.id
LEFT JOIN visitors v ON dp.visitor_id = v.id
JOIN cameras c ON el.camera_id = c.id
WHERE c.id = 3
ORDER BY el."timestamp" DESC
LIMIT 1

Question: "Show me the 3 highest severity open VAD cases."
-- Open cases ordered by severity. severity is text, so order with a CASE map.
SELECT id, case_key, severity, case_type, start_ts
FROM vad_anomaly_cases
WHERE status = 'open'
ORDER BY
  CASE severity
    WHEN 'critical' THEN 4 WHEN 'high' THEN 3
    WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0
  END DESC
LIMIT 3

Question: "How many reasoning jobs failed in the last 7 days?"
SELECT COUNT(*)
FROM vad_reasoning_jobs
WHERE status = 'failed'
  AND queued_at >= NOW() - INTERVAL '7 days'

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
- Use double quotes for the "timestamp" column where it exists.
- anomaly_rules uses column "active", not "is_active".

CORRECTED SQL:"""


def get_result_formatting_prompt(question: str, sql: str, results: list) -> str:
    _SKIP_COLS = {
        "embedding", "face_embedding", "vector", "encoding",
        "scene_embedding", "image_data", "thumbnail",
        "embedding_json", "metadata_json", "feature_values_json",
        "dominant_features_json", "bbox_xyxy_json", "bbox_norm_json",
        "keypoints_json", "ground_point_image_json", "ground_point_world_json",
    }

    def _strip(row):
        if not isinstance(row, dict):
            return row
        return {k: v for k, v in row.items() if k.lower() not in _SKIP_COLS}

    display = [_strip(r) for r in results[:20]]
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
        # Face / person tracking
        "entry_logs":              ["entry", "access", "entered", "authorized", "detected", "seen", "timestamp"],
        "detected_people":         ["detected", "people", "person", "face"],
        "employees":               ["employee", "employees", "staff"],
        "visitors":                ["visitor", "visitors"],
        "face_embeddings":         ["embedding", "embeddings", "biometric"],
        "unknown_face_events":     ["unknown face", "unknown faces", "stranger", "unidentified", "unreviewed"],
        "cameras":                 ["camera", "cameras"],
        "edge_devices":            ["edge device", "device", "jetson", "rockpi", "hardware"],

        # VAD anomaly pipeline
        "vad_anomaly_cases":       ["case", "cases", "anomaly case", "vad case", "incident"],
        "vad_gate_events":         ["gate event", "gate events", "gate trigger"],
        "vad_reasoning_jobs":      ["reasoning job", "llm job", "job queue", "reasoning queue"],
        "vad_reasoning_results":   ["reasoning result", "alert decision", "llm decision"],
        "vad_case_reviews":        ["case review", "human review", "reviewer"],
        "vad_streams":             ["stream", "streams", "camera stream"],
        "vad_stream_sessions":     ["session", "sessions", "stream session"],
        "vad_reasoning_rules":     ["reasoning rule", "vad rule"],
        "vad_tracks":              ["track", "tracks", "tracking"],
        "vad_gate_definitions":    ["gate definition", "gate config"],
        "vad_gate_model_versions": ["gate model", "model version"],
        "vad_homography_calibrations": ["homography", "calibration"],
        "vad_media_objects":       ["media object", "evidence media", "video clip"],
        "vad_evidence_items":      ["evidence item", "evidence"],

        # Admin / system
        "anomaly_rules":           ["anomaly rule", "trigger rule", "suppress rule"],
        "rule_conflicts":          ["conflict", "conflicts", "contradict"],
        "schedules":               ["schedule", "schedules", "access schedule"],
        "activity_logs":           ["activity log", "user action"],
        "audit_logs":              ["audit log", "system audit"],
    }

    matched = set()
    for table, keywords in table_keywords.items():
        if any(kw in q for kw in keywords):
            matched.add(table)

    if not matched:
        # Sensible default: most commonly queried tables
        matched = {"entry_logs", "detected_people", "cameras", "vad_anomaly_cases"}

    lines = schema.split("\n")
    result = []
    include = False
    for line in lines:
        if line.startswith("Table: "):
            include = any(t in line for t in matched)
        if include:
            result.append(line)

    return "\n".join(result)