// services/llmClient.js
const axios = require('axios');

const ENABLED = process.env.LLM_ENABLED === 'true';

const client = axios.create({
  baseURL: process.env.OLLAMA_BASE_URL,
  timeout: Number(process.env.OLLAMA_TIMEOUT_MS || 5000),
});

async function warmup() {
  if (!ENABLED) return;
  try {
    await client.post('/api/generate', {
      model: process.env.OLLAMA_MODEL,
      prompt: 'Output exactly this string and nothing else: OK',
      num_predict: 2,
      temperature: 0,
      stream: false,
    });
  } catch (_) {}
}


async function explainAnomaly(payload) {
  if (!ENABLED) return null;

  const prompt =
    'Return ONLY valid minified JSON with keys: summary,severity,action,confidence. No extra text.\n' +
    'Input:' + JSON.stringify(payload);

  const res = await client.post('/api/generate', {
    model: process.env.OLLAMA_MODEL,
    prompt,
    temperature: Number(process.env.LLM_TEMPERATURE || 0),
    num_predict: Number(process.env.LLM_MAX_TOKENS || 120),
    stream: false,
  });

  return res.data.response;
}


module.exports = {
  warmup,
  explainAnomaly,
};
