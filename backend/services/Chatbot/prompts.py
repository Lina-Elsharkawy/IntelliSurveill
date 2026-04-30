from typing import TypedDict

def get_sql_generation_prompt(user_question: str, schema: str, history: list = None) -> str:
    """
    Generate prompt for converting natural language to SQL

    """
    relevant_tables = _pick_relevant_tables(user_question, schema)
    prompt = f"""You are a PostgreSQL expert. Convert the user's natural language question into a valid SQL query.
DATABASE SCHEMA:
{schema}
SCHEMA Tables Releated:
{relevant_tables}
the old context is:
{history}

RULES:
1. Generate ONLY a SELECT query (no INSERT, UPDATE, DELETE, DROP)
2. Use proper PostgreSQL syntax
3. Include appropriate JOINs if multiple tables are needed
4. Use LIMIT to restrict results when appropriate
5. Return ONLY the SQL query, no explanation, no markdown
6. Do not use semicolons at the end
7. Use double quotes for identifiers if needed (e.g., "table_name")
8. ALWAYS filter by `table_schema = 'public'` when querying `information_schema.tables` or `information_schema.columns`.
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

RESULTS (first 100 rows):
{results[:100]}

TOTAL ROWS: {len(results)}

INSTRUCTIONS:
1. Provide a clear, conversational answer
2. Summarize the key findings
3. If many results, mention the total count
4. Be concise and relevant

ANSWER:"""
    
    return prompt

def _pick_relevant_tables(question: str, schema: str) -> str:
    q = question.lower()
    
    # Map keywords to table names
    table_keywords = {
        "anomaly_rules":          ["rule", "rules", "trigger", "suppress"],
        "rule_conflicts":         ["conflict", "conflicts", "contradict", "contradiction"],
        "anomalies":              ["anomaly", "anomalies", "severity"],
        "anomalies_logs":         ["anomaly log", "anomaly logs", "incident", "incidents"],
        "anomaly_candidates":     ["candidate", "pending", "llm decision"],
        "anomaly_thresholds":     ["threshold", "thresholds"],
        "normal_behavior_models": ["model", "models", "normal behavior"],
        "cameras":                ["camera", "cameras"],
        "employees":              ["employee", "employees", "staff"],
        "visitors":               ["visitor", "visitors"],
        "entry_logs":             ["entry", "access", "entered", "authorized"],
        "detected_people":        ["detected", "people", "person", "face"],
        "unknown_face_events":    ["unknown face", "unknown faces", "stranger", "unidentified", "unreviewed"],
        "face_embeddings":        ["embedding", "embeddings", "face embedding", "face embeddings"],
        "labs":                   ["lab", "laboratory"],
        "departments":            ["department", "departments"],
        "employee_lab_access":    ["employee lab access", "employee access"],
        "department_lab_access":  ["department lab access", "department access"],
        "schedules":              ["schedule", "schedules", "scheduled"],
    "scene_window_embeddings":["scene", "window", "scene embedding", "scene embeddings"],
    }
    
    matched = set()
    for table, keywords in table_keywords.items():
        if any(kw in q for kw in keywords):
            matched.add(table)
    
    # Fallback: send top 3 tables if nothing matched
    if not matched:
        matched = {"anomalies_logs", "cameras", "employees"}
    
    # Extract only matched table sections from schema string
    lines = schema.split("\n")
    result = []
    include = False
    for line in lines:
        if line.startswith("Table: "):
            include = any(t in line for t in matched)
        if include:
            result.append(line)
    
    return "\n".join(result)