const axios = require('axios');
const { Sequelize, QueryTypes } = require('sequelize');

// --- Configuration ---
// Create a separate Read-Only connection for safety
const ragSequelize = new Sequelize(
    process.env.POSTGRES_DB,
    process.env.RAG_DB_USER,
    process.env.RAG_DB_PASS,
    {
        host: process.env.POSTGRES_HOST,
        port: process.env.POSTGRES_PORT,
        dialect: 'postgres',
        logging: false,
        dialectOptions: {
            // Ensure we don't convert numbers to strings unnecessarily, though pg does this
        }
    }
);

const LLM_API_URL = process.env.LLM_API_URL;
const LLM_MODEL = process.env.LLM_MODEL_NAME;

// --- Prompt Engineering ---
const SYSTEM_PROMPT = `
You are a PostgreSQL expert. Convert the user's natural language question into a valid SQL query.
Use the following database schema:

Tables:
- employees (id, name, department_id)
- departments (id, name)
- labs (id, name)
- visitors (id, name, visit_date, purpose)
- detected_people (id, name, employee_id, visitor, visitor_id)
- entry_logs (id, timestamp, detected_id, camera_id, authorized, event_type ['Entry', 'Exit'], location)
- anomalies_logs (id, timestamp, detected_id, anomaly_id)
- anomalies (id, description, severity_level)

Relationships:
- entry_logs.detected_id -> detected_people.id
- detected_people.employee_id -> employees.id
- employees.department_id -> departments.id

Rules:
1. Return ONLY the SQL query. No markdown, no explanations.
2. Use ILIKE for text search.
3. For "recent" or "last", use timestamp comparisons with NOW() (e.g., timestamp > NOW() - INTERVAL '1 day').
4. Do not use LIMIT unless asked.

Few-Shot Examples:
User: "Who entered the Robotics Lab today?"
SQL: SELECT d.name, e.timestamp FROM entry_logs e JOIN detected_people d ON e.detected_id = d.id WHERE e.location ILIKE '%Robotics%' AND e.timestamp >= CURRENT_DATE;

User: "How many anomalies were high severity?"
SQL: SELECT COUNT(*) FROM anomalies_logs al JOIN anomalies a ON al.anomaly_id = a.id WHERE a.severity_level = 'High';
`;

// --- Helper Functions ---

/**
 * Clean LLM response to get just the SQL
 */
function extractSQL(llmResponse) {
    // Remove markdown code blocks if present
    let sql = llmResponse.replace(/```sql/g, '').replace(/```/g, '').trim();
    // Remove any leading text like "Here is the SQL:" (simple heuristic)
    const selectIndex = sql.toLowerCase().indexOf('select');
    if (selectIndex > -1) {
        sql = sql.substring(selectIndex);
    }
    return sql;
}

/**
 * Call the LLM API
 */
async function callLLM(prompt) {
    try {
        const response = await axios.post(LLM_API_URL, {
            model: LLM_MODEL,
            prompt: prompt,
            stream: false,
            options: {
                temperature: 0.1 // Low temperature for deterministic code
            }
        });
        // Adjust based on Ollama / generic API response structure
        return response.data.response || response.data.content || "";
    } catch (error) {
        console.error("LLM Call Failed:", error.message);
        throw new Error("Failed to communicate with AI model.");
    }
}

// --- Main Service Methods ---

async function processQuery(userText) {
    // 1. Generate Initial SQL
    const fullPrompt = `${SYSTEM_PROMPT}\n\nUser: "${userText}"\nSQL:`;
    let rawResponse = await callLLM(fullPrompt);
    let sql = extractSQL(rawResponse);

    console.log(`[RAG] Generated SQL: ${sql}`);

    let results = null;
    let errorMsg = null;

    // 2. Execution Loop (with Self-Correction)
    try {
        results = await executeSafeSQL(sql);
    } catch (executionError) {
        console.warn(`[RAG] execution failed: ${executionError.message}. Attempting self-correction...`);

        // Self-Correction Step
        const correctionPrompt = `${SYSTEM_PROMPT}\n\nUser: "${userText}"\nSQL: ${sql}\nError: ${executionError.message}\n\nFix the SQL and return ONLY the fixed SQL:`;
        rawResponse = await callLLM(correctionPrompt);
        sql = extractSQL(rawResponse);
        console.log(`[RAG] Corrected SQL: ${sql}`);

        try {
            results = await executeSafeSQL(sql);
        } catch (retryError) {
            throw new Error("I couldn't generate a valid query for that request. Details: " + retryError.message);
        }
    }

    // 3. Summarize Results
    const summary = await summarizeResults(results, userText);
    return {
        sql,
        results,
        summary
    };
}

async function executeSafeSQL(sql) {
    // Security Checks (Redundant if DB user is read-only, but good practice)
    const forbidden = ['DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE'];
    if (forbidden.some(word => sql.toUpperCase().includes(word))) {
        throw new Error("Security Alert: Modifying queries are not allowed.");
    }

    return await ragSequelize.query(sql, { type: QueryTypes.SELECT });
}

async function summarizeResults(results, userQuery) {
    if (!results || results.length === 0) {
        return "I found no records matching your query.";
    }

    const summaryPrompt = `
    User Question: "${userQuery}"
    Database Results: ${JSON.stringify(results).slice(0, 1000)} ... (truncated if long)
    
    Summarize these results in natural language.Be concise.
  `;

    return await callLLM(summaryPrompt);
}

module.exports = {
    processQuery
};
