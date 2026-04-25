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