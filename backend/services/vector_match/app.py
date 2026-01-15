from typing import Optional

from fastapi import FastAPI, HTTPException

from .config import (
    SEARCH_AUTHORITATIVE_FIRST,
    MAX_EMB_PER_PERSON,
    EMBEDDING_DIM,
)
from .models import EdgeEvent, MatchResponse, AssignUnknownRequest
from .utils import l2_normalize, to_pgvector_literal, interval_from_ms
from . import db
from .logic import decide, should_identify, should_autolearn


app = FastAPI(title="Face Vector Match Service (Flink -> FastAPI -> pgvector)")


@app.post("/match", response_model=MatchResponse)
def match(event: EdgeEvent):
    # Normalize
    try:
        emb = l2_normalize(event.embedding)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad embedding: {e}")

    if len(emb) != EMBEDDING_DIM:
        raise HTTPException(status_code=400, detail=f"Expected {EMBEDDING_DIM} floats, got {len(emb)}")

    qvec = to_pgvector_literal(emb)
    embedding_model = event.model_version or "unknown"

    with db.get_conn() as conn:
        with conn.transaction():
            # 1) search (authoritative-first optional)
            if SEARCH_AUTHORITATIVE_FIRST:
                top2 = db.search_top2(conn, qvec_literal=qvec, only_authoritative=True)
                if not top2:
                    top2 = db.search_top2(conn, qvec_literal=qvec, only_authoritative=False)
            else:
                top2 = db.search_top2(conn, qvec_literal=qvec, only_authoritative=False)

            best_id, best_sim, second_sim, margin = decide(top2)

            # 2) classify
            status = "unknown"
            detected_id: Optional[int] = None

            if best_id is not None and best_sim is not None:
                if should_identify(best_sim, margin, event.quality_score):
                    status = "known"
                    detected_id = best_id
                else:
                    status = "unknown"

            # 3) write entry log (authorized left NULL; can be updated by access-control later)
            entry_log_id = db.insert_entry_log(
                conn,
                detected_id=detected_id,
                camera_id=event.camera_id,
                authorized=None,
                event_type=event.event_type,
                location=event.location,
                device_status=event.device_status,
                image_video_ref=event.image_video_ref,
                processing_time_interval=interval_from_ms(event.processing_time_ms),
                model_version=event.model_version,
            )

            auto_learned = False
            unknown_id = None

            # 4) drift handling: auto-learn only when very confident
            if status == "known" and detected_id is not None and best_sim is not None:
                if should_autolearn(best_sim, margin, event.quality_score):
                    db.insert_face_embedding(
                        conn,
                        detected_id=detected_id,
                        entry_log_id=entry_log_id,
                        qvec_literal=qvec,
                        embedding_model=embedding_model,
                        is_authoritative=False,
                        quality_score=event.quality_score,
                        match_confidence=best_sim,
                        notes="auto_learned",
                    )
                    db.prune_embeddings_if_needed(conn, detected_id=detected_id, keep_max=MAX_EMB_PER_PERSON)
                    auto_learned = True

            # 5) unknown handling: store pending event for admin review
            if status != "known":
                unknown_id = db.insert_unknown_face_event(
                    conn,
                    entry_log_id=entry_log_id,
                    qvec_literal=qvec,
                    embedding_model=embedding_model,
                    notes="pending_review",
                )

            return MatchResponse(
                event_id=event.event_id,
                status=status,
                entry_log_id=entry_log_id,
                detected_id=detected_id,
                best_similarity=best_sim,
                second_similarity=second_sim,
                margin=margin,
                auto_learned=auto_learned,
                unknown_face_event_id=unknown_id,
            )


@app.post("/admin/assign-unknown")
def admin_assign(req: AssignUnknownRequest):
    """
    Admin says: this unknown belongs to detected_id.
    Optionally promote to authoritative embedding.
    """
    with db.get_conn() as conn:
        with conn.transaction():
            try:
                db.admin_assign_unknown(
                    conn,
                    unknown_face_event_id=req.unknown_face_event_id,
                    detected_id=req.detected_id,
                    promote_to_authoritative=req.promote_to_authoritative,
                    notes=req.notes,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="unknown_face_event_id not found")

    return {"ok": True}
