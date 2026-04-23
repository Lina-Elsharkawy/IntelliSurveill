from __future__ import annotations

import io
from typing import Optional, Any

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from transformers import VideoMAEImageProcessor, VideoMAEModel
from PIL import Image
from minio import Minio

from config import (
    TEACHER_MODEL,
    TEACHER_DEVICE,
    TEACHER_USE_AMP,
    TEACHER_NUM_FRAMES,
    TEACHER_EXTRACT_LAYERS,
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    S3_BUCKET,
    ALLOW_SERVICE_BOOT_WITHOUT_MODEL,
    MIN_REQUIRED_FRAME_RATIO,
    OLLAMA_HOST,
    VLM_MODEL,
    LLM_MODEL,
)
from db import DB

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Anomaly Service v3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = DB()

# ---------------------------------------------------------------------------
# Teacher model — loaded once at startup
# ---------------------------------------------------------------------------

_teacher_loaded          = False
_teacher_error: Optional[str]                    = None
_processor:     Optional[VideoMAEImageProcessor] = None
_teacher:       Optional[VideoMAEModel]          = None
_device:        Optional[torch.device]           = None


def try_load_teacher() -> None:
    global _teacher_loaded, _teacher_error, _processor, _teacher, _device
    if _teacher_loaded:
        return
    try:
        _device    = torch.device(
            TEACHER_DEVICE
            if (TEACHER_DEVICE != "cuda" or torch.cuda.is_available())
            else "cpu"
        )
        _processor = VideoMAEImageProcessor.from_pretrained(TEACHER_MODEL)
        _teacher   = VideoMAEModel.from_pretrained(
            TEACHER_MODEL,
            attn_implementation="sdpa" if _device.type == "cuda" else "eager",
        )
        _teacher.eval().to(_device)
        _teacher_loaded = True
        _teacher_error  = None
    except Exception as e:
        _teacher_error  = f"Failed to load teacher: {e}"
        _teacher_loaded = False


@app.on_event("startup")
async def startup() -> None:
    try_load_teacher()


# ---------------------------------------------------------------------------
# MinIO helpers
# ---------------------------------------------------------------------------

def _get_minio() -> Minio:
    ep = MINIO_ENDPOINT
    host = ep[len("http://"):] if ep.startswith("http://") else \
           ep[len("https://"):] if ep.startswith("https://") else ep
    return Minio(host, access_key=MINIO_ACCESS_KEY,
                 secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)


def fetch_frames_from_minio(s3_refs: list[str]) -> tuple[list[np.ndarray], int]:
    """Fetch RGB numpy frames from MinIO s3:// refs."""
    client = _get_minio()
    frames: list[np.ndarray] = []
    fetched = 0
    for ref in s3_refs:
        try:
            key = ref.split("/", 3)[-1]
            response = client.get_object(S3_BUCKET, key)
            data = response.read()
            response.close()
            frames.append(
                np.array(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.uint8)
            )
            fetched += 1
        except Exception as e:
            print(f"[fetch_frames] failed {ref}: {e}")
    return frames, fetched



def uniform_sample(frames: list, n: int) -> list:
    if len(frames) == n:
        return frames
    if len(frames) > n:
        idxs = np.round(np.linspace(0, len(frames) - 1, n)).astype(int)
        return [frames[i] for i in idxs]
    out = list(frames)
    while len(out) < n:
        out.append(frames[-1])
    return out


# ---------------------------------------------------------------------------
# Teacher inference
# ---------------------------------------------------------------------------

@torch.inference_mode()
def run_teacher(frames: list[np.ndarray]) -> np.ndarray:
    """
    Run VideoMAE teacher on frames.
    Extracts hidden states from TEACHER_EXTRACT_LAYERS (4, 8, 12),
    mean-pools each, concatenates → [2304-d].
    """
    sampled = uniform_sample(frames, TEACHER_NUM_FRAMES)
    inputs  = _processor(images=[sampled], return_tensors="pt")
    inputs  = {k: v.to(_device) for k, v in inputs.items()}

    with torch.autocast(
        device_type = _device.type,
        dtype       = torch.float16 if _device.type == "cuda" else None,
        enabled     = (TEACHER_USE_AMP and _device.type == "cuda"),
    ):
        outputs = _teacher(**inputs, output_hidden_states=True)

    scale_embs = []
    for layer_idx in TEACHER_EXTRACT_LAYERS:
        hs  = outputs.hidden_states[layer_idx]
        emb = hs.mean(dim=1).float().cpu()
        scale_embs.append(emb)

    return torch.cat(scale_embs, dim=1)[0].numpy()   # [2304]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_scores(s: np.ndarray, t: np.ndarray) -> dict[str, float]:
    diff = s - t
    l2   = float(np.sqrt(np.sum(diff ** 2)))
    mse  = float(np.mean(diff ** 2))
    sn   = s / max(float(np.linalg.norm(s)), 1e-12)
    tn   = t / max(float(np.linalg.norm(t)), 1e-12)
    cos  = float(1.0 - np.dot(sn, tn))
    return {"l2_score": l2, "mse_score": mse, "cosine_distance": cos}


def _parse_extract_layers(value: str | list[int]) -> list[int]:
    if isinstance(value, list):
        return [int(x) for x in value]
    return [int(x.strip()) for x in str(value).split(",") if str(x).strip()]


def validate_active_model(active_model: dict[str, Any], payload: "IngestPayload") -> None:
    expected_dim = int(active_model["embedding_dim"])
    actual_dim = len(payload.embedding)
    if payload.embedding_dim is not None and int(payload.embedding_dim) != actual_dim:
        raise HTTPException(
            status_code=400,
            detail=(
                f"embedding_dim={payload.embedding_dim} does not match "
                f"actual embedding length={actual_dim}"
            ),
        )
    if actual_dim != expected_dim:
        raise HTTPException(
            status_code=400,
            detail=(
                f"embedding length={actual_dim} does not match active model "
                f"embedding_dim={expected_dim}"
            ),
        )

    model_layers = _parse_extract_layers(active_model["extract_layers"])
    if str(active_model["teacher_model"]) != str(TEACHER_MODEL):
        raise HTTPException(
            status_code=500,
            detail=(
                "Active DB model teacher_model does not match runtime "
                f"teacher config ({active_model['teacher_model']} != {TEACHER_MODEL})"
            ),
        )
    if int(active_model["num_frames"]) != int(TEACHER_NUM_FRAMES):
        raise HTTPException(
            status_code=500,
            detail=(
                "Active DB model num_frames does not match runtime "
                f"teacher config ({active_model['num_frames']} != {TEACHER_NUM_FRAMES})"
            ),
        )
    if model_layers != [int(x) for x in TEACHER_EXTRACT_LAYERS]:
        raise HTTPException(
            status_code=500,
            detail=(
                "Active DB model extract_layers do not match runtime "
                f"teacher config ({model_layers} != {TEACHER_EXTRACT_LAYERS})"
            ),
        )


# ---------------------------------------------------------------------------
# Temporal consistency
# ---------------------------------------------------------------------------

def detect_run(
    recent:          list[dict],
    min_consecutive: int,
) -> tuple[bool, str | None]:
    """
    Check if the most recent window completes a run of
    >= min_consecutive consecutive anomalous windows.
    Returns (is_representative, run_id).
    The representative is the window with the highest L2 in the run.
    """
    if not recent:
        return False, None

    run_len = 0
    for w in reversed(recent):
        if w["is_anomalous"]:
            run_len += 1
        else:
            break

    if run_len < min_consecutive:
        return False, None

    run_windows = recent[-run_len:]
    max_window  = max(
        run_windows,
        key=lambda w: w["l2_score"] if w["l2_score"] is not None else 0.0,
    )
    current  = recent[-1]
    is_rep   = current["event_key"] == max_window["event_key"]
    run_id   = f"run_{run_windows[0]['id']}_{run_windows[-1]['id']}"
    return is_rep, run_id


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class IngestPayload(BaseModel):
    device_key:      str
    event_key:       str
    camera_id:       int
    track_id:        Optional[int]       = None
    window_start_ts: str
    window_end_ts:   Optional[str]       = None
    embedding_model: str                 = "student-v3-multiscale"
    embedding:       list[float]
    embedding_dim:   Optional[int]       = None
    frames:          Optional[list[str]] = None
    metadata:        Optional[dict]      = None


class ReviewPayload(BaseModel):
    """
    Admin review of an anomaly candidate.
    decision  : confirmed | dismissed | uncertain
    rule_text : optional natural language rule to add
    rule_type : anomalous (flag if seen) | normal (do not flag if seen)
    camera_id : optional scope — None means global rule
    lab_id    : optional scope
    """
    decision:  str           = Field(..., pattern=r"^(confirmed|dismissed|uncertain)$")
    rule_text: Optional[str] = None
    rule_type: str           = Field("anomalous", pattern=r"^(anomalous|normal)$")
    camera_id: Optional[int] = None
    lab_id:    Optional[int] = None
    reviewer:  Optional[str] = None
    notes:     Optional[str] = None


class CreateRulePayload(BaseModel):
    """Standalone rule creation not tied to a specific candidate."""
    rule_text: str
    rule_type: str           = Field("anomalous", pattern=r"^(anomalous|normal)$")
    camera_id: Optional[int] = None
    lab_id:    Optional[int] = None
    reviewer:  Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    try_load_teacher()
    return {
        "ok":             True,
        "teacher_loaded": _teacher_loaded,
        "teacher_model":  TEACHER_MODEL,
        "teacher_device": (_device.type if _device is not None else None),
        "extract_layers": TEACHER_EXTRACT_LAYERS,
        "ollama_host":    OLLAMA_HOST,
        "vlm_model":      VLM_MODEL,
        "llm_model":      LLM_MODEL,
        "error":          _teacher_error,
    }


@app.post("/ingest/scene_embedding")
def ingest_scene_embedding(p: IngestPayload) -> dict[str, Any]:
    try_load_teacher()
    if not _teacher_loaded:
        raise HTTPException(
            status_code=503 if ALLOW_SERVICE_BOOT_WITHOUT_MODEL else 500,
            detail=f"Teacher not ready: {_teacher_error}",
        )

    student_emb = np.array(p.embedding, dtype=np.float32)
    if student_emb.shape[0] == 0:
        raise HTTPException(status_code=400, detail="embedding must not be empty")

    teacher_emb = None
    scores = {"l2_score": None, "mse_score": None, "cosine_distance": None}
    frames_refs = p.frames or []
    fetched_count = 0
    teacher_status = "not_requested"

    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            active_model = db.get_active_model(conn)
            validate_active_model(active_model, p)

            model_id = int(active_model["id"])
            thresholds = db.get_thresholds(conn, model_id)
            device_id = db.upsert_edge_device(conn, p.device_key)

            if frames_refs:
                teacher_status = "requested"
                frames, fetched_count = fetch_frames_from_minio(frames_refs)
                minimum_needed = max(1, int(np.ceil(active_model["num_frames"] * MIN_REQUIRED_FRAME_RATIO)))
                if fetched_count >= minimum_needed:
                    teacher_emb = run_teacher(frames)
                    if teacher_emb.shape[0] != active_model["embedding_dim"]:
                        raise HTTPException(
                            status_code=500,
                            detail=(
                                f"teacher embedding length={teacher_emb.shape[0]} does not match "
                                f"active model embedding_dim={active_model['embedding_dim']}"
                            ),
                        )
                    scores = compute_scores(student_emb, teacher_emb)
                    teacher_status = "scored"
                else:
                    print(
                        f"[ingest] insufficient frames for event_key={p.event_key}: "
                        f"fetched={fetched_count}/{len(frames_refs)} minimum_needed={minimum_needed}"
                    )
                    teacher_status = "insufficient_frames"
            else:
                print(f"[ingest] no frames for event_key={p.event_key}")

            l2_flag = mse_flag = cos_flag = None
            metrics_agreed = is_anomalous = None

            if scores["l2_score"] is not None:
                l2_flag = bool(scores["l2_score"] > thresholds["l2_p95"])
                mse_flag = bool(scores["mse_score"] > thresholds["mse_p95"])
                cos_flag = bool(scores["cosine_distance"] > thresholds["cos_p95"])
                metrics_agreed = int(l2_flag) + int(mse_flag) + int(cos_flag)
                is_anomalous = metrics_agreed >= thresholds["min_metrics_agree"]

            scene_id = db.insert_scene_embedding(
                conn,
                model_id=model_id,
                device_id=device_id,
                camera_id=p.camera_id,
                track_id=p.track_id,
                window_start_ts=p.window_start_ts,
                window_end_ts=p.window_end_ts,
                event_key=p.event_key,
                student_embedding=student_emb.tolist(),
                teacher_embedding=teacher_emb.tolist() if teacher_emb is not None else None,
                frames=frames_refs or None,
                embedding_model=p.embedding_model,
                l2_score=scores["l2_score"],
                mse_score=scores["mse_score"],
                cosine_distance=scores["cosine_distance"],
                l2_flag=l2_flag,
                mse_flag=mse_flag,
                cos_flag=cos_flag,
                metrics_agreed=metrics_agreed,
                is_anomalous=is_anomalous,
            )

            ollama_job_id = None
            anomaly_candidate_id = None
            is_representative = False
            run_id = None

            if is_anomalous and p.track_id is not None:
                recent = db.get_recent_windows(
                    conn,
                    camera_id=p.camera_id,
                    track_id=p.track_id,
                    model_id=model_id,
                    lookback_n=20,
                )
                if not any(w["event_key"] == p.event_key for w in recent):
                    recent.append({
                        "id": scene_id,
                        "window_start_ts": p.window_start_ts,
                        "is_anomalous": is_anomalous,
                        "l2_score": scores["l2_score"],
                        "event_key": p.event_key,
                    })
                is_representative, run_id = detect_run(
                    recent, thresholds["min_consecutive"]
                )
            elif is_anomalous:
                is_representative = True
                run_id = f"run_notrack_{scene_id}"

            if is_representative:
                image_ref = frames_refs[0] if frames_refs else None
                active_rules = db.get_active_rules(conn, camera_id=p.camera_id)

                anomaly_candidate_id = db.create_anomaly_candidate(
                    conn,
                    scene_window_embedding_id=scene_id,
                    reason="multimetric_teacher_student_scoring",
                    image_ref=image_ref,
                    video_ref=None,
                    run_id=run_id,
                    l2_score=scores["l2_score"],
                )

                request_json = {
                    "job_type": "vlm_describe",
                    "scene_id": scene_id,
                    "candidate_id": anomaly_candidate_id,
                    "camera_id": p.camera_id,
                    "track_id": p.track_id,
                    "window_start_ts": p.window_start_ts,
                    "window_end_ts": p.window_end_ts,
                    "frames": frames_refs,
                    "image_ref": image_ref,
                    "run_id": run_id,
                    "rule_metadata": {
                        "l2_score": scores["l2_score"],
                        "mse_score": scores["mse_score"],
                        "cosine_distance": scores["cosine_distance"],
                        "metrics_agreed": metrics_agreed,
                        "l2_threshold": thresholds["l2_p95"],
                        "mse_threshold": thresholds["mse_p95"],
                        "cos_threshold": thresholds["cos_p95"],
                        "anomalous_rules": [
                            r["rule_text"] for r in active_rules
                            if r["rule_type"] == "anomalous"
                        ],
                        "normal_rules": [
                            r["rule_text"] for r in active_rules
                            if r["rule_type"] == "normal"
                        ],
                    },
                }

                ollama_job_id = db.enqueue_ollama_job(
                    conn,
                    anomaly_candidate_id=anomaly_candidate_id,
                    model_name=VLM_MODEL,
                    prompt=(
                        "Describe exactly what is happening in the provided frames. "
                        "Focus only on visible actions, people, objects, and movements. "
                        "Do not speculate about intent or emotions. Be factual and concise."
                    ),
                    request_json=request_json,
                )

            conn.execute("COMMIT")
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(500, detail=str(e))

    return {
        "scene_window_embedding_id": scene_id,
        "is_anomalous": is_anomalous,
        "metrics_agreed": metrics_agreed,
        "l2_score": scores["l2_score"],
        "mse_score": scores["mse_score"],
        "cosine_distance": scores["cosine_distance"],
        "is_representative": is_representative,
        "run_id": run_id,
        "anomaly_candidate_id": anomaly_candidate_id,
        "ollama_job_id": ollama_job_id,
        "status": "candidate_created" if anomaly_candidate_id else "normal",
        "teacher_status": teacher_status,
        "frames_requested": len(frames_refs),
        "frames_fetched": fetched_count,
    }


@app.post("/anomaly-candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: int,
    rv: ReviewPayload,
) -> dict[str, Any]:
    """Admin reviews a candidate. Optionally creates a new rule."""
    status_map = {
        "confirmed": "resolved",
        "dismissed": "discarded",
        "uncertain": "pending",
    }
    new_status = status_map[rv.decision]

    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            created_rule_id = None
            if rv.rule_text:
                created_rule_id = db.insert_anomaly_rule(
                    conn,
                    rule_text           = rv.rule_text,
                    rule_type           = rv.rule_type,
                    reviewer            = rv.reviewer,
                    source_candidate_id = candidate_id,
                    camera_id           = rv.camera_id,
                    lab_id              = rv.lab_id,
                )

            review_id = db.insert_candidate_review(
                conn,
                anomaly_candidate_id = candidate_id,
                decision             = rv.decision,
                reviewer             = rv.reviewer,
                notes                = rv.notes,
                rule_text            = rv.rule_text,
                created_rule_id      = created_rule_id,
            )

            updated = db.update_anomaly_candidate_status(
                conn,
                anomaly_candidate_id = candidate_id,
                status               = new_status,
            )
            if not updated:
                raise HTTPException(404, detail="Anomaly candidate not found")

            conn.execute("COMMIT")
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(500, detail=str(e))

    return {
        "review_id":            review_id,
        "anomaly_candidate_id": candidate_id,
        "decision":             rv.decision,
        "candidate_status":     new_status,
        "rule_created":         created_rule_id is not None,
        "rule_id":              created_rule_id,
    }


@app.post("/anomaly-rules")
def create_rule(p: CreateRulePayload) -> dict[str, Any]:
    """Create a standalone rule not tied to a specific candidate review."""
    with db.connect() as conn:
        conn.execute("BEGIN")
        rule_id = db.insert_anomaly_rule(
            conn,
            rule_text = p.rule_text,
            rule_type = p.rule_type,
            reviewer  = p.reviewer,
            camera_id = p.camera_id,
            lab_id    = p.lab_id,
        )
        conn.execute("COMMIT")
    return {"rule_id": rule_id, "rule_text": p.rule_text, "rule_type": p.rule_type}


# @app.get("/anomaly-rules")
# def list_rules(
#     camera_id:   Optional[int] = None,
#     active_only: bool          = True,
# ) -> list[dict[str, Any]]:
#     """List rules with full metadata for the admin UI."""
#     with db.connect() as conn:
#         return db.get_all_rules(conn, camera_id=camera_id, active_only=active_only)


# @app.delete("/anomaly-rules/{rule_id}")
# def deactivate_rule(rule_id: int) -> dict[str, Any]:
#     """Deactivate a rule so it is no longer injected into LLM prompts."""
#     with db.connect() as conn:
#         conn.execute("BEGIN")
#         ok = db.deactivate_rule(conn, rule_id)
#         conn.execute("COMMIT")
#     if not ok:
#         raise HTTPException(404, detail="Rule not found")
#     return {"rule_id": rule_id, "is_active": False}


@app.get("/anomaly-candidates")
def list_anomaly_candidates(
    limit:  int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ac.id,
                ac.status,
                ac.created_at,
                s.camera_id,
                s.track_id,
                ac.l2_score,
                ac.run_id,
                vlm.response_json->>'narrative'  AS narrative,
                llm.response_json->>'decision'   AS llm_decision,
                ac.image_ref,
                ac.alert_decision,
                ac.severity,
                ac.decision_reason
            FROM anomaly_candidates ac
            LEFT JOIN scene_window_embeddings s
                ON s.id = ac.scene_window_embedding_id
            -- VLM job for the scene narrative
            LEFT JOIN ollama_jobs vlm
                ON vlm.anomaly_candidate_id = ac.id
               AND vlm.status = 'succeeded'
               AND vlm.request_json->>'job_type' = 'vlm_describe'
            -- LLM job for the final alert decision
            LEFT JOIN ollama_jobs llm
                ON llm.anomaly_candidate_id = ac.id
               AND llm.status = 'succeeded'
               AND llm.request_json->>'job_type' = 'llm_reason'
            ORDER BY ac.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        ).fetchall()
    return [
        {
            "id":          r[0],
            "status":      r[1],
            "createdAt":   r[2],
            "cameraId":    r[3],
            "trackId":     r[4],
            "l2Score":     r[5],
            "runId":       r[6],
            "narrative":   r[7],
            "llmDecision": r[8],
            "imageRef":    r[9],
            "alertDecision": r[10],
            "severity": r[11],
            "decisionReason": r[12],
        }
        for r in rows
    ]