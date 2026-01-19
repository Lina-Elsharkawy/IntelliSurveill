from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Any

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import (
    MODEL_TYPE,
    MODEL_PATH,
    MODEL_META_PATH,
    ALLOW_START_WITHOUT_MODEL,
    OLLAMA_HOST,
    VLM_MODEL,
    LLM_MODEL,
    RETRAIN_FALSE_POSITIVE_THRESHOLD,
)
from db import DB


def l2_normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = float(np.linalg.norm(x))
    if n < eps:
        return x
    return x / n


class IngestPayload(BaseModel):
    device_key: str
    event_key: str
    camera_id: int
    entry_log_id: Optional[int] = None

    window_start_ts: str
    window_end_ts: Optional[str] = None

    embedding_model: str = "unknown"
    embedding_pca: list[float]
    embedding_raw: Optional[list[float]] = None

    # Placeholder refs (your worker currently only uses `frames` paths)
    frames: Optional[list[str]] = None
    image_ref: Optional[str] = None
    video_ref: Optional[str] = None


class FeedbackPayload(BaseModel):
    label: str = Field(..., pattern=r"^(true_anomaly|false_positive|uncertain)$")
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    system_decision: Optional[dict[str, Any]] = None


app = FastAPI(title="Anomaly Service")
db = DB()

_MODEL_LOADED = False
_MODEL_ERROR: Optional[str] = None

# Model objects
clf = None
SCORE_THRESHOLD = None

clusters_centroids = None
clusters_radii = None


def try_load_model() -> None:
    """Load model artifacts if available. Safe to call repeatedly."""
    global _MODEL_LOADED, _MODEL_ERROR
    global clf, SCORE_THRESHOLD
    global clusters_centroids, clusters_radii

    if _MODEL_LOADED:
        return

    model_file = Path(MODEL_PATH)
    meta_file = Path(MODEL_META_PATH)

    if not model_file.exists() or not meta_file.exists():
        _MODEL_ERROR = f"Model files missing: {MODEL_PATH} / {MODEL_META_PATH}"
        return

    try:
        if MODEL_TYPE == "isoforest":
            clf = joblib.load(MODEL_PATH)
            with open(MODEL_META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            SCORE_THRESHOLD = float(meta.get("score_threshold_p5", meta.get("threshold_p5", 0.0)))

        elif MODEL_TYPE == "clusters":
            artifact = joblib.load(MODEL_PATH)
            clusters_centroids = np.asarray(artifact["centroids"], dtype=np.float32)  # (k,128)
            clusters_radii = np.asarray(artifact["radii"], dtype=np.float32)          # (k,)
            _ = json.loads(Path(MODEL_META_PATH).read_text(encoding="utf-8"))

        else:
            raise ValueError(f"Unknown MODEL_TYPE={MODEL_TYPE}")

    except Exception as e:
        _MODEL_ERROR = f"Failed to load model: {e}"
        return

    _MODEL_LOADED = True
    _MODEL_ERROR = None


@app.get("/health")
def health() -> dict[str, Any]:
    try_load_model()
    return {
        "ok": True,
        "model_loaded": _MODEL_LOADED,
        "model_type": MODEL_TYPE,
        "model_path": MODEL_PATH,
        "meta_path": MODEL_META_PATH,
        "ollama_host": OLLAMA_HOST,
        "vlm_model": VLM_MODEL,
        "llm_model": LLM_MODEL,
        "error": _MODEL_ERROR,
        "retrain_false_positive_threshold": RETRAIN_FALSE_POSITIVE_THRESHOLD,
    }


def score_isoforest(x128: np.ndarray) -> tuple[bool, float, float]:
    """Return (is_normal, score, threshold). Higher score = more normal."""
    score = float(clf.decision_function([x128])[0])
    threshold = float(SCORE_THRESHOLD)
    is_normal = bool(score >= threshold)
    return is_normal, score, threshold


def score_clusters(x128: np.ndarray) -> tuple[bool, float, float, int]:
    """Return (is_normal, cosine_distance, radius_threshold, nearest_cluster_index)."""
    sims = clusters_centroids @ x128
    best_idx = int(np.argmax(sims))
    best_sim = float(np.clip(float(sims[best_idx]), -1.0, 1.0))
    dist = 1.0 - best_sim
    radius = float(clusters_radii[best_idx])
    is_normal = bool(dist <= radius)
    return is_normal, float(dist), radius, best_idx


@app.post("/ingest/scene_embedding")
def ingest_scene_embedding(p: IngestPayload) -> dict[str, Any]:
    try_load_model()
    if not _MODEL_LOADED:
        if ALLOW_START_WITHOUT_MODEL:
            raise HTTPException(status_code=503, detail=f"Model not ready: {_MODEL_ERROR}")
        raise HTTPException(status_code=500, detail=f"Model load failed: {_MODEL_ERROR}")

    x = np.array(p.embedding_pca, dtype=np.float32)
    if x.shape[0] != 128:
        raise HTTPException(status_code=400, detail="embedding_pca must have length 128")
    x = l2_normalize(x)

    nearest_cluster_index = None
    cosine_distance = None
    radius_threshold = None
    score = None

    if MODEL_TYPE == "isoforest":
        is_normal, score, _ = score_isoforest(x)
    elif MODEL_TYPE == "clusters":
        is_normal, cosine_distance, radius_threshold, nearest_cluster_index = score_clusters(x)
        score = float(cosine_distance)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown MODEL_TYPE={MODEL_TYPE}")

    with db.connect() as conn:
        conn.execute("BEGIN")

        model_id = db.get_active_model_id(conn)
        device_id = db.upsert_edge_device(conn, p.device_key)

        scene_id = db.insert_scene_embedding(
            conn,
            model_id=model_id,
            device_id=device_id,
            camera_id=p.camera_id,
            entry_log_id=p.entry_log_id,
            window_start_ts=p.window_start_ts,
            window_end_ts=p.window_end_ts,
            event_key=p.event_key,
            embedding_pca=p.embedding_pca,
            embedding_raw=p.embedding_raw,
            embedding_model=p.embedding_model,
            cosine_distance=cosine_distance,
            radius_threshold=radius_threshold,
            is_normal=is_normal,
            score=score,
            nearest_cluster_id=None,
            nearest_cluster_index=nearest_cluster_index,
        )

        ollama_job_id = None
        anomaly_candidate_id = None

        if not is_normal:
            reason = "outside_cluster_radius" if MODEL_TYPE == "clusters" else "isolation_forest_score_below_threshold"

            anomaly_candidate_id = db.create_anomaly_candidate(
                conn,
                scene_window_embedding_id=scene_id,
                reason=reason,
                image_ref=p.image_ref,
                video_ref=p.video_ref,
            )

            request_json = {
                "job_type": "vlm_describe",
                "scene_window_embedding_id": scene_id,
                "anomaly_candidate_id": anomaly_candidate_id,
                "camera_id": p.camera_id,
                "window_start_ts": p.window_start_ts,
                "window_end_ts": p.window_end_ts,
                "image_ref": p.image_ref,
                "video_ref": p.video_ref,
                "frames": p.frames or [],
                "rule_metadata": {
                    "model_type": MODEL_TYPE,
                    "nearest_cluster_index": nearest_cluster_index,
                    "cosine_distance": cosine_distance,
                    "radius_threshold": radius_threshold,
                    "score": score,
                },
                "next_llm_model": LLM_MODEL,
            }

            prompt = (
                "Describe exactly what is happening in the provided frames. "
                "Focus only on visible actions, people, objects, and movements. "
                "Do not speculate about intent or emotions. Be factual and concise."
            )

            ollama_job_id = db.enqueue_ollama_job(
                conn,
                anomaly_candidate_id=anomaly_candidate_id,
                model_name=VLM_MODEL,
                prompt=prompt,
                request_json=request_json,
            )

        conn.execute("COMMIT")

    return {
        "scene_window_embedding_id": scene_id,
        "is_normal": is_normal,
        "model_type": MODEL_TYPE,
        "nearest_cluster_index": nearest_cluster_index,
        "cosine_distance": cosine_distance,
        "radius_threshold": radius_threshold,
        "score": score,
        "anomaly_candidate_id": anomaly_candidate_id,
        "ollama_job_id": ollama_job_id,
    }


@app.post("/anomaly-candidates/{candidate_id}/feedback")
def submit_feedback(candidate_id: int, fb: FeedbackPayload) -> dict[str, Any]:
    """Store admin feedback. Does NOT retrain automatically."""
    # Map admin labels to existing anomaly_candidates.status values
    status_map = {
        "false_positive": "discarded",
        "true_anomaly": "resolved",
        "uncertain": "pending",
    }
    new_status = status_map.get(fb.label)
    if not new_status:
        raise HTTPException(status_code=400, detail=f"Invalid label: {fb.label}")

    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            feedback_id = db.insert_anomaly_feedback(
                conn,
                anomaly_candidate_id=candidate_id,
                label=fb.label,
                reviewer=fb.reviewer,
                notes=fb.notes,
                system_decision=fb.system_decision,
            )

            # Update anomaly candidate status to reflect the admin decision
            updated = db.update_anomaly_candidate_status(
                conn,
                anomaly_candidate_id=candidate_id,
                status=new_status,
            )
            if not updated:
                raise HTTPException(status_code=404, detail="Anomaly candidate not found")

            pending_fp = db.count_pending_false_positives(conn)
            conn.execute("COMMIT")
        except HTTPException:
            conn.execute("ROLLBACK")
            raise
        except Exception as e:
            conn.execute("ROLLBACK")
            raise HTTPException(status_code=500, detail=str(e))

    return {
        "feedback_id": feedback_id,
        "anomaly_candidate_id": candidate_id,
        "label": fb.label,
        "candidate_status": new_status,
        "pending_false_positives": pending_fp,
        "threshold": RETRAIN_FALSE_POSITIVE_THRESHOLD,
        "retrain_recommended": bool(pending_fp >= RETRAIN_FALSE_POSITIVE_THRESHOLD),
    }


@app.get("/retrain/status")
def retrain_status() -> dict[str, Any]:
    """How many false positives are pending for the next retrain batch."""
    with db.connect() as conn:
        try:
            pending_fp = db.count_pending_false_positives(conn)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {
        "pending_false_positives": pending_fp,
        "threshold": RETRAIN_FALSE_POSITIVE_THRESHOLD,
        "retrain_recommended": bool(pending_fp >= RETRAIN_FALSE_POSITIVE_THRESHOLD),
    }
