const ragService = require('../../src/services/ragService');
const adminSequelize = require('../../src/db/connection'); // Use admin conn for Gold SQL
const { QueryTypes } = require('sequelize');
const fs = require('fs');
const path = require('path');

const DATASET_PATH = path.join(__dirname, 'eval_dataset.json');

async function runEvaluation() {
    console.log('--- Starting RAG Evaluation ---');

    // 1. Load Dataset
    if (!fs.existsSync(DATASET_PATH)) {
        console.error('Dataset not found:', DATASET_PATH);
        process.exit(1);
    }
    const dataset = JSON.parse(fs.readFileSync(DATASET_PATH, 'utf8'));
    console.log(`Loaded ${dataset.length} test cases.\n`);

    let passedCount = 0;
    let validSqlCount = 0;
    let totalLatency = 0;

    for (const testCase of dataset) {
        console.log(`Testing [${testCase.id}]: "${testCase.question}"`);
        const startTime = Date.now();

        try {
            // 2. Generate and Execute Candidate SQL
            // ragService.processQuery returns { sql, results, summary }
            const candidateResponse = await ragService.processQuery(testCase.question);
            const candidateSql = candidateResponse.sql;
            const candidateRows = candidateResponse.results; // executed results

            validSqlCount++; // If processQuery didn't throw, it's valid/executable

            // 3. Execute Gold SQL (Ground Truth)
            // We use adminSequelize to run the gold SQL to ensure it works even if it uses "admin" features (though it shouldn't)
            const goldRows = await adminSequelize.query(testCase.gold_sql, { type: QueryTypes.SELECT });

            // 4. Compare Results
            const isMatch = compareResults(candidateRows, goldRows);

            const duration = Date.now() - startTime;
            totalLatency += duration;

            if (isMatch) {
                console.log(`✅ PASS (${duration}ms)`);
                passedCount++;
            } else {
                console.log(`❌ FAIL (${duration}ms)`);
                console.log(`   Gold SQL: ${testCase.gold_sql}`);
                console.log(`   Gen  SQL: ${candidateSql}`);
                console.log(`   Gold Rows: ${goldRows.length}, Gen Rows: ${candidateRows ? candidateRows.length : 0}`);
            }

        } catch (error) {
            console.log(`❌ ERROR: ${error.message}`);
        }
        console.log('--------------------------------------------------');
    }

    // 5. Report
    const accuracy = ((passedCount / dataset.length) * 100).toFixed(1);
    const validity = ((validSqlCount / dataset.length) * 100).toFixed(1);
    const avgLatency = (totalLatency / dataset.length).toFixed(0);

    console.log('\n--- Final Results ---');
    console.log(`Total Tests: ${dataset.length}`);
    console.log(`Execution Accuracy (EX): ${accuracy}%`);
    console.log(`Valid SQL Rate (VA):     ${validity}%`);
    console.log(`Avg Latency:             ${avgLatency}ms`);

    process.exit(0);
}

/**
 * Compare two arrays of objects.
 * We convert to set of strings to be order-independent.
 */
function compareResults(rowsA, rowsB) {
    if (!rowsA || !rowsB) return false;
    if (rowsA.length !== rowsB.length) return false;
    if (rowsA.length === 0 && rowsB.length === 0) return true;

    // Simple normalization: JSON stringify each row, sort keys to ensure consistency
    const setA = new Set(rowsA.map(r => JSON.stringify(sortObj(r))));
    const setB = new Set(rowsB.map(r => JSON.stringify(sortObj(r))));

    if (setA.size !== setB.size) return false;
    for (const item of setA) {
        if (!setB.has(item)) return false;
    }
    return true;
}

function sortObj(obj) {
    return Object.keys(obj).sort().reduce((result, key) => {
        result[key] = obj[key];
        return result;
    }, {});
}

// Start
runEvaluation();
