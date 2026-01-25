from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import psycopg
from pgvector.psycopg import register_vector

import ollama

from config import DB_DSN, OLLAMA_HOST, VLM_MODEL, LLM_MODEL


def _jsonb(value: Any) -> str:
    """
    psycopg3 will NOT adapt dict -> jsonb automatically.
    Always pass JSON as a STRING and cast to ::jsonb in SQL.
    """
    return json.dumps(value, ensure_ascii=False)


def _get_ollama_client() -> ollama.Client:
    # OLLAMA_HOST should be like: "http://127.0.0.1:11434"  OR  "http://ollama:11434"
    # The official client accepts `host=...`.
    return ollama.Client(host=OLLAMA_HOST)


def ollama_generate(client: ollama.Client, model: str, prompt: str, images: Optional[List[bytes]] = None) -> str:
    """
    VLM (e.g. llava): uses generate with images bytes.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if images:
        kwargs["images"] = images

    resp = client.generate(**kwargs)
    # `resp` is dict-like
    return (resp.get("response") or "").strip()


def ollama_chat(client: ollama.Client, model: str, prompt: str) -> str:
    """
    Text LLM reasoning via /api/chat behind the scenes.
    """
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
    )
    msg = (resp.get("message") or {})
    return (msg.get("content") or "").strip()


def build_reasoning_prompts(narrative: str, rule_metadata: Dict[str, Any]) -> Dict[str, str]:
    norm_prompt = f"""You are a surveillance normalcy analyst.

Rule metadata:
{rule_metadata}

Narrative:
{narrative}

Question:
Is this consistent with normal activity patterns? Explain briefly.
"""

    intent_prompt = f"""You are a surveillance intent analyst.

Rule metadata:
{rule_metadata}

Narrative:
{narrative}

Question:
Does the behavior suggest malicious intent, negligence, or normal activity? Explain briefly.
"""

    risk_prompt = f"""You are a risk assessment officer.

Rule metadata:
{rule_metadata}

Narrative:
{narrative}

Question:
Assess the risk level (low, medium, high) and justify briefly.
"""

    judge_prompt = """You are the final decision authority.

You will receive 3 short analyses: norm, intent, risk.

Task:
Decide whether to trigger an alert.

Respond EXACTLY in this format:
ALERT: YES or NO
SEVERITY: LOW / MEDIUM / HIGH
REASON: one sentence
"""
    return {
        "norm": norm_prompt,
        "intent": intent_prompt,
        "risk": risk_prompt,
        "judge": judge_prompt,
    }


def resolve_frames_to_bytes(frames: List[str]) -> List[bytes]:
    """
    Placeholder. Later: resolve Kafka/Flink frame references to actual bytes.
    For now:
      - if frames contain local file paths, read them
      - otherwise return empty
    """
    out: List[bytes] = []
    for ref in frames:
        try:
            with open(ref, "rb") as f:
                out.append(f.read())
        except Exception:
            continue
    return out


def main():
    print(f"[worker] DB_DSN={DB_DSN}")
    print(f"[worker] OLLAMA_HOST={OLLAMA_HOST} VLM_MODEL={VLM_MODEL} LLM_MODEL={LLM_MODEL}")

    client = _get_ollama_client()

    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)

        while True:
            # Lock exactly one queued job safely
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

            # Normalize request_json
            if request_json is None:
                request_json = {}
            elif isinstance(request_json, str):
                try:
                    request_json = json.loads(request_json)
                except Exception:
                    request_json = {"raw": request_json}

            job_type = str(request_json.get("job_type") or "").strip()

            # Mark job as running
            conn.execute(
                "UPDATE ollama_jobs SET status='running', started_at=now() WHERE id=%s",
                (job_id,),
            )
            conn.execute("COMMIT")

            try:
                if job_type == "vlm_describe":
                    frames = request_json.get("frames") or []
                    images_bytes = resolve_frames_to_bytes(frames)

                    # HARD GUARD: never call VLM without images
                    if not images_bytes:
                        conn.execute("BEGIN")
                        conn.execute(
                            """
                            UPDATE ollama_jobs
                            SET status='failed',
                                finished_at=now(),
                                error=%s
                            WHERE id=%s
                            """,
                            ("No frames/images provided (frames list empty or refs not readable).", job_id),
                        )
                        conn.execute("COMMIT")
                        continue

                    narrative = ollama_generate(
                        client=client,
                        model=(model_name or VLM_MODEL),
                        prompt=prompt,
                        images=images_bytes,
                    )

                    resp_json = {
                        "job_type": "vlm_describe",
                        "narrative": narrative,
                        "frames_count": len(frames),
                        "rule_metadata": request_json.get("rule_metadata"),
                    }

                    # Enqueue next job: llm_reason
                    next_request = {
                        "job_type": "llm_reason",
                        "narrative": narrative,
                        "rule_metadata": request_json.get("rule_metadata") or {},
                    }

                    conn.execute("BEGIN")

                    # IMPORTANT: response_json must be a JSON string + ::jsonb cast
                    conn.execute(
                        """
                        UPDATE ollama_jobs
                        SET status='succeeded',
                            finished_at=now(),
                            response_text=%s,
                            response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (narrative, _jsonb(resp_json), job_id),
                    )

                    # IMPORTANT: request_json must be a JSON string + ::jsonb cast
                    llm_prompt = "You will be provided with a narrative and metadata. Follow the instructions in the next messages."
                    conn.execute(
                        """
                        INSERT INTO ollama_jobs (anomaly_candidate_id, model_name, prompt, request_json, status)
                        VALUES (%s, %s, %s, %s::jsonb, 'queued')
                        """,
                        (candidate_id, LLM_MODEL, llm_prompt, _jsonb(next_request)),
                    )

                    conn.execute("COMMIT")

                elif job_type == "llm_reason":
                    narrative = request_json.get("narrative", "")
                    rule_metadata = request_json.get("rule_metadata") or {}

                    prompts = build_reasoning_prompts(narrative, rule_metadata)

                    norm = ollama_chat(client, LLM_MODEL, prompts["norm"])
                    intent = ollama_chat(client, LLM_MODEL, prompts["intent"])
                    risk = ollama_chat(client, LLM_MODEL, prompts["risk"])

                    judge_prompt = f"""{prompts["judge"]}

Norm analysis:
{norm}

Intent analysis:
{intent}

Risk analysis:
{risk}
"""
                    decision = ollama_chat(client, LLM_MODEL, judge_prompt)

                    resp_json = {
                        "job_type": "llm_reason",
                        "narrative": narrative,
                        "norm": norm,
                        "intent": intent,
                        "risk": risk,
                        "decision": decision,
                        "rule_metadata": rule_metadata,
                    }

                    conn.execute("BEGIN")

                    conn.execute(
                        """
                        UPDATE ollama_jobs
                        SET status='succeeded',
                            finished_at=now(),
                            response_text=%s,
                            response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (decision, _jsonb(resp_json), job_id),
                    )

                    conn.execute(
                        "UPDATE anomaly_candidates SET status='resolved' WHERE id=%s",
                        (candidate_id,),
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
