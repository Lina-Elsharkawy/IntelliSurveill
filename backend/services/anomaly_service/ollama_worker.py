from __future__ import annotations

import io
import json
import re
import time
from typing import Any, Dict, List, Optional

import psycopg
from pgvector.psycopg import register_vector
from minio import Minio
from PIL import Image
import ollama

from config import (
    DB_DSN,
    OLLAMA_HOST,
    VLM_MODEL,
    LLM_MODEL,
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    S3_BUCKET,
)


def _jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _get_ollama_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST)


def _get_minio() -> Minio:
    ep   = MINIO_ENDPOINT
    host = ep[len("http://"):] if ep.startswith("http://") else \
           ep[len("https://"):] if ep.startswith("https://") else ep
    return Minio(host, access_key=MINIO_ACCESS_KEY,
                 secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)


# ---------------------------------------------------------------------------
# Frame resolution
# ---------------------------------------------------------------------------

def resolve_frames_to_bytes(frames: List[str]) -> List[bytes]:
    """
    Fetch frames from MinIO (s3:// refs) or local paths (dev fallback).
    Returns JPEG bytes suitable for the Ollama VLM.
    """
    if not frames:
        return []

    s3_refs    = [f for f in frames if f.startswith("s3://")]
    local_refs = [f for f in frames if not f.startswith("s3://")]
    out: List[bytes] = []

    if s3_refs:
        try:
            client = _get_minio()
            for ref in s3_refs:
                try:
                    key      = ref.split("/", 3)[-1]
                    response = client.get_object(S3_BUCKET, key)
                    data     = response.read()
                    response.close()
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=85)
                    out.append(buf.getvalue())
                except Exception as e:
                    print(f"[worker] failed to fetch {ref}: {e}")
        except Exception as e:
            print(f"[worker] MinIO connection failed: {e}")

    for ref in local_refs:
        try:
            with open(ref, "rb") as f:
                out.append(f.read())
        except Exception as e:
            print(f"[worker] failed to read {ref}: {e}")

    return out


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------

def ollama_generate(
    client: ollama.Client,
    model:  str,
    prompt: str,
    images: Optional[List[bytes]] = None,
) -> str:
    kwargs: Dict[str, Any] = {
        "model":   model,
        "prompt":  prompt,
        "stream":  False,
        "options": {
            "temperature":    0.1,
            "top_p":          0.9,
            "repeat_penalty": 1.1,
            "num_predict":    150,
        },
    }
    if images:
        kwargs["images"] = images
    resp = client.generate(**kwargs)
    return (resp.get("response") or "").strip()


def ollama_chat(
    client: ollama.Client,
    model:  str,
    prompt: str,
) -> str:
    resp = client.chat(
        model    = model,
        messages = [{"role": "user", "content": prompt}],
        stream   = False,
        options  = {"temperature": 0.0},
    )
    return ((resp.get("message") or {}).get("content") or "").strip()


# ---------------------------------------------------------------------------
# Reasoning prompts — rules injected here
# ---------------------------------------------------------------------------

def _fmt_metric(value) -> str:
    try:
        if value is None:
            return "N/A"
        return f"{float(value):.4f}"
    except Exception:
        return "N/A"


def parse_final_decision(decision_text: str) -> dict:
    decision_text = decision_text or ""
    alert_match = re.search(r"ALERT\s*:\s*(YES|NO)", decision_text, flags=re.IGNORECASE)
    severity_match = re.search(
        r"SEVERITY\s*:\s*(LOW|MEDIUM|HIGH)",
        decision_text,
        flags=re.IGNORECASE,
    )
    reason_match = re.search(r"REASON\s*:\s*(.+)", decision_text, flags=re.IGNORECASE)

    alert = alert_match.group(1).upper() if alert_match else None
    severity = severity_match.group(1).upper() if severity_match else None
    reason = reason_match.group(1).strip() if reason_match else None
    return {
        "alert_decision": alert,
        "severity": severity,
        "decision_reason": reason,
    }


def build_reasoning_prompts(
    narrative:      str,
    rule_metadata:  Dict[str, Any],
) -> Dict[str, str]:
    """
    Build the four reasoning prompts.
    rule_metadata now contains:
        anomalous_rules : list of rule_text strings (flag if seen)
        normal_rules    : list of rule_text strings (do NOT flag if seen)
        + scoring info (l2_score, mse_score, etc.)
    """
    anomalous_rules = rule_metadata.get("anomalous_rules") or []
    normal_rules    = rule_metadata.get("normal_rules")    or []

    # Format rules as numbered lists for the LLM
    anomalous_block = (
        "\n".join(f"  {i+1}. {r}" for i, r in enumerate(anomalous_rules))
        if anomalous_rules else "  (none defined)"
    )
    normal_block = (
        "\n".join(f"  {i+1}. {r}" for i, r in enumerate(normal_rules))
        if normal_rules else "  (none defined)"
    )

    scoring_block = (
        f"  L2 score: {_fmt_metric(rule_metadata.get('l2_score'))}  "
        f"(threshold: {rule_metadata.get('l2_threshold', 'N/A')})\n"
        f"  MSE score: {_fmt_metric(rule_metadata.get('mse_score'))}  "
        f"(threshold: {rule_metadata.get('mse_threshold', 'N/A')})\n"
        f"  Cosine distance: {_fmt_metric(rule_metadata.get('cosine_distance'))}  "
        f"(threshold: {rule_metadata.get('cos_threshold', 'N/A')})\n"
        f"  Metrics agreed: {rule_metadata.get('metrics_agreed', 'N/A')}/3"
    ) if any(
        rule_metadata.get(k) is not None
        for k in ("l2_score", "mse_score", "cosine_distance")
    ) else "  (no scores available)"

    norm_prompt = f"""You are a surveillance normalcy analyst.

Anomaly scoring:
{scoring_block}

Admin-defined rules for ANOMALOUS behavior (flag if seen):
{anomalous_block}

Admin-defined rules for NORMAL behavior (do NOT flag if seen):
{normal_block}

Scene narrative:
{narrative}

Question:
Is this scene consistent with normal activity? Consider the admin-defined rules above.
Explain briefly.
"""

    intent_prompt = f"""You are a surveillance intent analyst.

Admin-defined rules for ANOMALOUS behavior:
{anomalous_block}

Admin-defined rules for NORMAL behavior:
{normal_block}

Scene narrative:
{narrative}

Question:
Does the observed behavior match any anomalous rule? Does it match any normal rule?
Does it suggest malicious intent, negligence, or normal activity?
Explain briefly.
"""

    risk_prompt = f"""You are a risk assessment officer.

Admin-defined rules for ANOMALOUS behavior:
{anomalous_block}

Admin-defined rules for NORMAL behavior:
{normal_block}

Anomaly scoring:
{scoring_block}

Scene narrative:
{narrative}

Question:
Assess the risk level (low, medium, high). Consider both the scoring and the admin rules.
Justify briefly.
"""

    judge_prompt = """You are the final decision authority for a surveillance system.

You will receive 3 short analyses: norm, intent, risk.
The analyses already account for admin-defined rules.

Task:
Decide whether to trigger an alert.

Respond EXACTLY in this format:
ALERT: YES or NO
SEVERITY: LOW / MEDIUM / HIGH
REASON: one sentence
"""

    return {
        "norm":   norm_prompt,
        "intent": intent_prompt,
        "risk":   risk_prompt,
        "judge":  judge_prompt,
    }


# ---------------------------------------------------------------------------
# Main worker loop
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[worker] DB_DSN={DB_DSN}")
    print(f"[worker] OLLAMA_HOST={OLLAMA_HOST} VLM={VLM_MODEL} LLM={LLM_MODEL}")
    print(f"[worker] MINIO={MINIO_ENDPOINT} BUCKET={S3_BUCKET}")

    client = _get_ollama_client()

    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)

        while True:
            conn.execute("BEGIN")
            job = conn.execute(
                """
                SELECT id, anomaly_candidate_id, model_name, prompt, request_json
                FROM ollama_jobs
                WHERE status = 'queued'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()

            if not job:
                conn.execute("COMMIT")
                time.sleep(0.75)
                continue

            job_id, candidate_id, model_name, prompt, request_json = job

            if request_json is None:
                request_json = {}
            elif isinstance(request_json, str):
                try:
                    request_json = json.loads(request_json)
                except Exception:
                    request_json = {"raw": request_json}

            job_type = str(request_json.get("job_type") or "").strip()

            conn.execute(
                "UPDATE ollama_jobs SET status='running', started_at=now() WHERE id=%s",
                (job_id,),
            )
            conn.execute("COMMIT")

            try:
                # ----------------------------------------------------------
                # VLM: describe the scene
                # ----------------------------------------------------------
                if job_type == "vlm_describe":
                    frames       = request_json.get("frames") or []
                    image_bytes  = resolve_frames_to_bytes(frames)

                    if not image_bytes:
                        conn.execute("BEGIN")
                        conn.execute(
                            "UPDATE ollama_jobs SET status='failed', finished_at=now(), error=%s WHERE id=%s",
                            ("No frames fetched — check MinIO refs.", job_id),
                        )
                        conn.execute("COMMIT")
                        continue

                    narrative = ollama_generate(
                        client = client,
                        model  = model_name or VLM_MODEL,
                        prompt = (
                            prompt or
                            "Describe what is happening in this image. "
                            "Focus on people, actions and movements. "
                            "Be factual and concise."
                        ),
                        images = image_bytes,
                    )

                    resp_json = {
                        "job_type":      "vlm_describe",
                        "narrative":     narrative,
                        "frames_count":  len(frames),
                        "rule_metadata": request_json.get("rule_metadata"),
                    }

                    next_request = {
                        "job_type":      "llm_reason",
                        "narrative":     narrative,
                        "rule_metadata": request_json.get("rule_metadata") or {},
                    }

                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        UPDATE ollama_jobs
                        SET status='succeeded', finished_at=now(),
                            response_text=%s, response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (narrative, _jsonb(resp_json), job_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO ollama_jobs
                            (anomaly_candidate_id, model_name, prompt, request_json, status)
                        VALUES (%s, %s, %s, %s::jsonb, 'queued')
                        """,
                        (
                            candidate_id, LLM_MODEL,
                            "Follow the instructions in the next messages.",
                            _jsonb(next_request),
                        ),
                    )
                    conn.execute("COMMIT")

                # ----------------------------------------------------------
                # LLM: multi-step reasoning with admin rules
                # ----------------------------------------------------------
                elif job_type == "llm_reason":
                    narrative     = request_json.get("narrative", "")
                    rule_metadata = request_json.get("rule_metadata") or {}

                    prompts = build_reasoning_prompts(narrative, rule_metadata)

                    norm   = ollama_chat(client, LLM_MODEL, prompts["norm"])
                    intent = ollama_chat(client, LLM_MODEL, prompts["intent"])
                    risk   = ollama_chat(client, LLM_MODEL, prompts["risk"])

                    judge_prompt = (
                        f"{prompts['judge']}\n\n"
                        f"Norm analysis:\n{norm}\n\n"
                        f"Intent analysis:\n{intent}\n\n"
                        f"Risk analysis:\n{risk}\n"
                    )
                    decision = ollama_chat(client, LLM_MODEL, judge_prompt)

                    parsed_decision = parse_final_decision(decision)

                    resp_json = {
                        "job_type":      "llm_reason",
                        "narrative":     narrative,
                        "norm":          norm,
                        "intent":        intent,
                        "risk":          risk,
                        "decision":      decision,
                        "parsed_decision": parsed_decision,
                        "rule_metadata": rule_metadata,
                    }

                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        UPDATE ollama_jobs
                        SET status='succeeded', finished_at=now(),
                            response_text=%s, response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (decision, _jsonb(resp_json), job_id),
                    )
                    conn.execute(
                        '''
                        UPDATE anomaly_candidates
                        SET status='resolved',
                            alert_decision=%s,
                            severity=%s,
                            decision_reason=%s,
                            resolved_at=now()
                        WHERE id=%s
                        ''',
                        (
                            parsed_decision.get("alert_decision"),
                            parsed_decision.get("severity"),
                            parsed_decision.get("decision_reason"),
                            candidate_id,
                        ),
                    )
                    conn.execute("COMMIT")

                else:
                    conn.execute("BEGIN")
                    conn.execute(
                        "UPDATE ollama_jobs SET status='failed', finished_at=now(), error=%s WHERE id=%s",
                        (f"Unknown job_type: {job_type}", job_id),
                    )
                    conn.execute("COMMIT")

            except Exception as e:
                conn.execute("BEGIN")
                conn.execute(
                    "UPDATE ollama_jobs SET status='failed', finished_at=now(), error=%s WHERE id=%s",
                    (str(e), job_id),
                )
                conn.execute("COMMIT")


if __name__ == "__main__":
    main()