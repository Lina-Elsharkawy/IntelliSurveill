from __future__ import annotations

import io
import json
import logging
import re
import time
from typing import Any

import ollama
import psycopg
from pgvector.psycopg import register_vector
from PIL import Image

from config import DB_DSN, OLLAMA_HOST, VLM_MODEL, LLM_MODEL
from evidence_io import fetch_clip_frames, fetch_image_rgb, fetch_jpeg_bytes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("reasoning_worker")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {"raw": value}
    return dict(value)


def image_array_to_jpeg_bytes(frame) -> bytes:
    img = Image.fromarray(frame).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def make_temporal_strip(frames_bytes: list[bytes], max_frames: int = 4) -> bytes:
    """
    Concatenate up to max_frames person-crop JPEGs side-by-side into a single
    horizontal strip so the VLM sees the motion sequence as one image.
    """
    imgs = []
    for b in frames_bytes[:max_frames]:
        try:
            imgs.append(Image.open(io.BytesIO(b)).convert("RGB"))
        except Exception:
            continue
    if not imgs:
        return b""
    max_h = max(img.height for img in imgs)
    # Resize each frame to the same height preserving aspect ratio
    resized = []
    for img in imgs:
        scale = max_h / img.height
        resized.append(img.resize((int(img.width * scale), max_h), Image.LANCZOS))
    strip = Image.new("RGB", (sum(r.width for r in resized), max_h))
    x = 0
    for r in resized:
        strip.paste(r, (x, 0))
        x += r.width
    buf = io.BytesIO()
    strip.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def resolve_candidate_images(request_json: dict[str, Any]) -> tuple[list[bytes], list[bytes]]:
    """
    Resolve visual evidence for the VLM step.

    Returns (person_frames_bytes, context_frames_bytes) separately so the caller
    can compose a temporal strip from person crops and pass context as ancillary.

    Priority order for person frames:
      1. person_frames refs  (individual crop JPEGs — most informative for score)
      2. person_clip_ref     (sampled from clip as fallback)

    Priority order for context frames:
      1. representative_frame_ref  (single key frame anchor)
      2. context_frames refs
      3. context_clip_ref
    """
    MAX_PERSON = 4
    MAX_CONTEXT = 2

    # ── Person crop frames ──
    person_bytes: list[bytes] = []
    for ref in (request_json.get("person_frames") or []):
        if len(person_bytes) >= MAX_PERSON:
            break
        try:
            b = fetch_jpeg_bytes(ref)
            if b:
                person_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch person frame %s: %s", ref, e)

    if len(person_bytes) < MAX_PERSON and request_json.get("person_clip_ref"):
        try:
            frames = fetch_clip_frames(request_json["person_clip_ref"], n=MAX_PERSON - len(person_bytes))
            person_bytes.extend(image_array_to_jpeg_bytes(f) for f in frames[: MAX_PERSON - len(person_bytes)])
        except Exception as e:
            log.warning("Could not fetch person clip %s: %s", request_json.get("person_clip_ref"), e)

    # ── Context / scene frames ──
    context_bytes: list[bytes] = []
    if request_json.get("representative_frame_ref"):
        try:
            b = fetch_jpeg_bytes(request_json["representative_frame_ref"])
            if b:
                context_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch representative frame: %s", e)

    for ref in (request_json.get("context_frames") or []):
        if len(context_bytes) >= MAX_CONTEXT:
            break
        try:
            b = fetch_jpeg_bytes(ref)
            if b:
                context_bytes.append(b)
        except Exception as e:
            log.warning("Could not fetch context frame %s: %s", ref, e)

    if len(context_bytes) < MAX_CONTEXT and request_json.get("context_clip_ref"):
        try:
            frames = fetch_clip_frames(request_json["context_clip_ref"], n=MAX_CONTEXT - len(context_bytes))
            context_bytes.extend(image_array_to_jpeg_bytes(f) for f in frames[: MAX_CONTEXT - len(context_bytes)])
        except Exception as e:
            log.warning("Could not fetch context clip %s: %s", request_json.get("context_clip_ref"), e)

    return person_bytes, context_bytes


def compose_vlm_images(person_bytes: list[bytes], context_bytes: list[bytes]) -> list[bytes]:
    """
    Build the final image list sent to the VLM:
    - A single temporal strip of person crop frames (shows motion arc)
    - Followed by individual context/scene frames
    """
    result: list[bytes] = []
    if person_bytes:
        strip = make_temporal_strip(person_bytes, max_frames=4)
        if strip:
            result.append(strip)
    result.extend(context_bytes)
    return result[:6]  # hard cap — most VLMs handle ≤6 images reliably


def ollama_generate(client: ollama.Client, *, model: str, prompt: str, images: list[bytes] | None = None) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.9, "repeat_penalty": 1.1, "num_predict": 512, "num_ctx": 4096},
    }
    if images:
        kwargs["images"] = images
    resp = client.generate(**kwargs)
    return (resp.get("response") or "").strip()


def ollama_chat(client: ollama.Client, *, model: str, prompt: str) -> str:
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        options={"temperature": 0.0, "num_ctx": 8192},
    )
    return ((resp.get("message") or {}).get("content") or "").strip()


def parse_final_decision(text: str) -> dict[str, str | None]:
    text = text or ""
    alert = re.search(r"ALERT\s*:\s*(YES|NO)", text, flags=re.IGNORECASE)
    severity = re.search(r"SEVERITY\s*:\s*(LOW|MEDIUM|HIGH)", text, flags=re.IGNORECASE)
    reason = re.search(r"REASON\s*:\s*(.+)", text, flags=re.IGNORECASE)
    return {
        "alert_decision": alert.group(1).upper() if alert else None,
        "severity": severity.group(1).upper() if severity else None,
        "decision_reason": reason.group(1).strip() if reason else None,
    }


def format_rules(rules: list[dict[str, Any]], kind: str) -> str:
    subset = [r for r in rules if r.get("rule_type") == kind]
    if not subset:
        return "  (none defined)"
    lines = []
    for i, r in enumerate(subset, 1):
        cond = r.get("conditions") or {}
        lines.append(f"  {i}. [{r.get('event_type', 'other')}] {r.get('rule_text')} | conditions={json.dumps(cond, ensure_ascii=False)}")
    return "\n".join(lines)


def fetch_active_rules(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, rule_text, rule_type, event_type, conditions, source
        FROM Anomaly_Rules
        WHERE active = TRUE
        ORDER BY id ASC
        """
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "rule_text": r[1],
            "rule_type": r[2],
            "event_type": r[3],
            "conditions": r[4] or {},
            "source": r[5],
        }
        for r in rows
    ]


def build_vlm_prompt(candidate_metadata: dict[str, Any]) -> str:
    score = candidate_metadata.get('final_score')
    threshold = candidate_metadata.get('threshold_value')
    reasons = candidate_metadata.get('candidate_reasons') or []
    motion = candidate_metadata.get('motion_stats') or {}

    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
    threshold_str = f"{threshold:.4f}" if isinstance(threshold, (int, float)) else str(threshold)
    ratio_str = ""
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)) and threshold > 0:
        ratio = score / threshold
        ratio_str = f" ({ratio:.2f}× threshold)"

    # Pull out the most relevant motion fields for the prompt
    motion_summary_keys = ["max_speed_norm", "avg_speed_norm", "max_turn_angle", "gap_count", "lost_frames", "track_instability"]
    motion_summary = {k: motion[k] for k in motion_summary_keys if k in motion}

    return f"""You are reviewing surveillance evidence flagged by a statistical anomaly detector.

ANOMALY SCORE CONTEXT:
  Distribution score : {score_str}{ratio_str}
  Threshold          : {threshold_str}
  Trigger reasons    : {reasons}
  Motion summary     : {json.dumps(motion_summary, ensure_ascii=False)}

The images below show:
  - IMAGE 1: A horizontal strip of person crop frames in temporal order (left → right over time).
  - IMAGE 2+: Scene/context frames.

Your task:
Describe only what is VISIBLE. Focus on:
  - Gait: Is the person walking, running, stumbling, or stationary?
  - Posture: Upright, crouching, bent over, carrying something?
  - Interaction: With objects, other people, doors, equipment?
  - Motion quality: Smooth and continuous, or abrupt and erratic?
  - Scene context: Crowd, empty corridor, restricted area, etc.?

Also explicitly state whether the visible motion appears COMPLETELY NORMAL for the scene
(e.g., "person is walking at normal pace in an empty corridor").

Do NOT speculate about intent, identity, or events not visible in the images.
"""


def build_llm_prompt(narrative: str, metadata: dict[str, Any], active_rules: list[dict[str, Any]]) -> str:
    trigger_rules = format_rules(active_rules, "trigger")
    suppress_rules = format_rules(active_rules, "suppress")

    score = metadata.get('final_score')
    threshold = metadata.get('threshold_value')
    score_str = f"{score:.4f}" if isinstance(score, (int, float)) else str(score)
    threshold_str = f"{threshold:.4f}" if isinstance(threshold, (int, float)) else str(threshold)
    ratio_note = ""
    if isinstance(score, (int, float)) and isinstance(threshold, (int, float)) and threshold > 0:
        ratio = score / threshold
        ratio_note = f" — {ratio:.2f}× above threshold" if ratio > 1 else f" — {ratio:.2f}× of threshold"

    return f"""You are the final anomaly reasoning judge for a surveillance system.

VLM factual narrative:
{narrative}

Distribution and gate metadata:
  Final score      : {score_str}{ratio_note}
  Threshold        : {metadata.get('threshold_name')} = {threshold_str}
  Candidate reasons: {metadata.get('candidate_reasons')}
  Priority         : {metadata.get('priority')}
  Motion stats     : {json.dumps(metadata.get('motion_stats') or {}, ensure_ascii=False)}

Admin TRIGGER rules (visible behaviors that should produce ALERT: YES):
{trigger_rules}

Admin SUPPRESS rules (visible behaviors that should produce ALERT: NO even if score is high):
{suppress_rules}

Decision instructions:
1. Base your decision on the VLM narrative and the admin rules — NOT on the distribution score alone.
2. A high distribution score means the motion pattern is statistically unusual compared to the training
   data, but this system is currently being calibrated and generates false positives for normal walking.
3. If the VLM narrative describes only routine locomotion (walking, standing, sitting) and no trigger
   rule is matched, output ALERT: NO regardless of how high the score is.
4. If a suppress rule explicitly applies to the described behavior, output ALERT: NO.
5. Trigger rules can escalate a borderline case to ALERT: YES only if the behavior is clearly visible
   in the narrative.
6. Do not invent facts not present in the VLM narrative.
7. If you output ALERT: YES, the REASON must cite the specific visible behavior or matched trigger rule.

Respond EXACTLY in this format (no extra lines):
ALERT: YES or NO
SEVERITY: LOW / MEDIUM / HIGH
REASON: one sentence
"""


def mark_failed(conn: psycopg.Connection, job_id: int, error: str) -> None:
    conn.execute("BEGIN")
    conn.execute(
        "UPDATE reasoning_jobs SET status='failed', finished_at=now(), error=%s WHERE id=%s",
        (error, job_id),
    )
    conn.execute("COMMIT")


def main() -> None:
    log.info("DB_DSN=%s", DB_DSN)
    log.info("OLLAMA_HOST=%s VLM=%s LLM=%s", OLLAMA_HOST, VLM_MODEL, LLM_MODEL)
    client = _client()

    with psycopg.connect(DB_DSN) as conn:
        register_vector(conn)
        while True:
            conn.execute("BEGIN")
            job = conn.execute(
                """
                SELECT id, anomaly_candidate_id, model_name, job_type, prompt, request_json
                FROM reasoning_jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ).fetchone()
            if not job:
                conn.execute("COMMIT")
                time.sleep(0.75)
                continue

            job_id, candidate_id, model_name, job_type, prompt, request_json = job
            request_json = _as_dict(request_json)
            conn.execute("UPDATE reasoning_jobs SET status='running', started_at=now() WHERE id=%s", (job_id,))
            conn.execute("COMMIT")

            try:
                if job_type == "vlm_reasoning":
                    metadata = request_json.get("candidate_metadata") or {}
                    person_bytes, context_bytes = resolve_candidate_images(request_json)
                    images = compose_vlm_images(person_bytes, context_bytes)
                    if not images:
                        mark_failed(conn, job_id, "No images/frames could be fetched for VLM reasoning")
                        continue

                    log.info(
                        "VLM job %s: %d person frames → 1 strip + %d context frames = %d total images",
                        job_id, len(person_bytes), len(context_bytes), len(images),
                    )
                    vlm_prompt = build_vlm_prompt(metadata)
                    narrative = ollama_generate(
                        client,
                        model=model_name or VLM_MODEL,
                        prompt=vlm_prompt,
                        images=images,
                    )
                    active_rules = request_json.get("active_rules") or fetch_active_rules(conn)
                    next_request = {
                        "narrative": narrative,
                        "candidate_metadata": metadata,
                        "active_rules": active_rules,
                        "source_vlm_job_id": job_id,
                    }
                    response_json = {"narrative": narrative, "frames_used": len(images), "candidate_metadata": metadata}

                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        UPDATE reasoning_jobs
                        SET status='succeeded', finished_at=now(), response_text=%s, response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (narrative, _json(response_json), job_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO reasoning_jobs (
                            anomaly_candidate_id, provider, model_name, job_type, prompt, request_json, status
                        )
                        VALUES (%s, 'ollama', %s, 'llm_reasoning', %s, %s::jsonb, 'queued')
                        """,
                        (candidate_id, LLM_MODEL, "Final anomaly reasoning with active rules", _json(next_request)),
                    )
                    conn.execute("COMMIT")

                elif job_type == "llm_reasoning":
                    narrative = str(request_json.get("narrative") or "")
                    metadata = request_json.get("candidate_metadata") or {}
                    active_rules = request_json.get("active_rules") or fetch_active_rules(conn)
                    final_prompt = prompt if prompt and prompt != "Final anomaly reasoning with active rules" else build_llm_prompt(narrative, metadata, active_rules)
                    decision = ollama_chat(client, model=model_name or LLM_MODEL, prompt=final_prompt)
                    parsed = parse_final_decision(decision)
                    response_json = {
                        "narrative": narrative,
                        "decision": decision,
                        "parsed_decision": parsed,
                        "candidate_metadata": metadata,
                        "active_rules": active_rules,
                    }

                    conn.execute("BEGIN")
                    conn.execute(
                        """
                        UPDATE reasoning_jobs
                        SET status='succeeded', finished_at=now(), response_text=%s, response_json=%s::jsonb
                        WHERE id=%s
                        """,
                        (decision, _json(response_json), job_id),
                    )
                    # The first UPDATE works with the refined schema. The second is attempted only
                    # if the optional decision columns have been added by the supplemental patch.
                    conn.execute(
                        "UPDATE anomaly_candidates SET status='resolved' WHERE id=%s",
                        (candidate_id,),
                    )
                    conn.execute("SAVEPOINT decision_columns")
                    try:
                        conn.execute(
                            """
                            UPDATE anomaly_candidates
                            SET alert_decision=%s, severity=%s, decision_reason=%s, resolved_at=now()
                            WHERE id=%s
                            """,
                            (parsed.get("alert_decision"), parsed.get("severity"), parsed.get("decision_reason"), candidate_id),
                        )
                        conn.execute("RELEASE SAVEPOINT decision_columns")
                    except Exception:
                        # The refined SQL you sent drops these old decision columns.
                        # If the supplemental patch is not applied, the decision still remains in reasoning_jobs.response_json.
                        conn.execute("ROLLBACK TO SAVEPOINT decision_columns")
                    conn.execute("COMMIT")

                else:
                    mark_failed(conn, job_id, f"Unknown reasoning job_type: {job_type}")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                try:
                    mark_failed(conn, job_id, str(e))
                except Exception as inner:
                    log.error("Failed to mark job %s as failed: %s", job_id, inner)


if __name__ == "__main__":
    main()
