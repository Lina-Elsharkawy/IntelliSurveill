from typing import Optional

from fastapi import FastAPI, HTTPException

from .config import (
    SEARCH_AUTHORITATIVE_FIRST,
    MAX_EMB_PER_PERSON,
    EMBEDDING_DIM,
    TOPK,
    DEDUP_SIM,
    AUTOLEARN_COOLDOWN_SEC,
)
from .models import (
    EdgeEvent,
    MatchResponse,
    AssignUnknownRequest,
    CreateIdentityFromUnknownRequest,
    PendingUnknownItem,
    EntryLogItem,
    IdentityItem,
)
from .utils import l2_normalize, to_pgvector_literal, interval_from_ms
from . import db
from .logic import decide_identity, should_identify, should_autolearn


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
            # 0) schema safety: ensure referenced camera row exists (FK in entry_logs)
            # If a camera_id is provided but not present in cameras, we auto-create it.
            if event.camera_id is not None:
                db.ensure_camera_exists(conn, camera_id=event.camera_id)

            # 1) search (authoritative-first optional)
            used_authoritative_only = False
            if SEARCH_AUTHORITATIVE_FIRST:
                topk = db.search_topk(conn, qvec_literal=qvec, only_authoritative=True, k=TOPK)
                if topk:
                    used_authoritative_only = True
                else:
                    topk = db.search_topk(conn, qvec_literal=qvec, only_authoritative=False, k=TOPK)
            else:
                topk = db.search_topk(conn, qvec_literal=qvec, only_authoritative=False, k=TOPK)

            best_id, best_sim, second_sim, margin = decide_identity(topk)

            # Identity-level margin safety:
            # If we have >=2 identities in the search space, require a valid second-best identity
            # so margin cannot be bypassed just because topK returned only one identity.
            identities_in_space = db.count_distinct_identities(conn, only_authoritative=used_authoritative_only)
            require_second = identities_in_space >= 2

            # 2) classify
            status = "unknown"
            detected_id: Optional[int] = None

            if best_id is not None and best_sim is not None:
                if require_second and second_sim is None:
                    status = "unknown"
                elif should_identify(best_sim, margin, event.quality_score):
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
                if (not require_second or second_sim is not None) and should_autolearn(best_sim, margin, event.quality_score):
                    # Safety 1: cooldown
                    since = db.seconds_since_last_autolearn(conn, detected_id=detected_id)
                    if since is None or since >= AUTOLEARN_COOLDOWN_SEC:
                        # Safety 2: deduplicate near-identical embeddings (avoid storing redundant vectors)
                        max_sim_same_id = db.max_similarity_for_identity(conn, detected_id=detected_id, qvec_literal=qvec)
                        if max_sim_same_id is None or max_sim_same_id < DEDUP_SIM:
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


@app.post("/admin/create-identity-from-unknown")
def admin_create_identity(req: CreateIdentityFromUnknownRequest):
    """Admin creates a *new* identity from an unknown event.

    This implements the missing design path: unknown -> new identity.

    Typical use:
    - an operator reviews unknown_face_events
    - decides this is a new person
    - creates an identity and (optionally) promotes the unknown embedding as an authoritative anchor
    """
    with db.get_conn() as conn:
        with conn.transaction():
            try:
                new_id = db.admin_create_identity_from_unknown(
                    conn,
                    unknown_face_event_id=req.unknown_face_event_id,
                    name=req.name,
                    additional_info=req.additional_info,
                    promote_to_authoritative=req.promote_to_authoritative,
                    notes=req.notes,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="unknown_face_event_id not found")

    return {"ok": True, "detected_id": new_id}


@app.get("/admin/pending-unknowns", response_model=list[PendingUnknownItem])
def admin_list_pending_unknowns(limit: int = 50, offset: int = 0):
    """List pending unknown events for review UI."""
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with db.get_conn() as conn:
        rows = db.list_pending_unknowns(conn, limit=limit, offset=offset)
        return [PendingUnknownItem(**r) for r in rows]


@app.get("/admin/recent-entry-logs", response_model=list[EntryLogItem])
def admin_list_recent_entry_logs(limit: int = 100, offset: int = 0):
    """List recent entry logs (for debugging / dashboards)."""
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    with db.get_conn() as conn:
        rows = db.list_recent_entry_logs(conn, limit=limit, offset=offset)
        return [EntryLogItem(**r) for r in rows]


@app.get("/admin/identities", response_model=list[IdentityItem])
def admin_list_identities(limit: int = 100, offset: int = 0):
    """List known identities and embedding counts."""
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    with db.get_conn() as conn:
        rows = db.list_identities(conn, limit=limit, offset=offset)
        return [IdentityItem(**r) for r in rows]


