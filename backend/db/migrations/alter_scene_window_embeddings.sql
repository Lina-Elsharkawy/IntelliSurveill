-- ============================================================
-- Migration: Persist edge anomaly frame evidence refs
-- Purpose:
--   The edge now sends 16 person frame refs + 16 context frame refs.
--   Previously, scene_window_embeddings only stored clip refs and
--   representative_frame_ref, so the full evidence arrays were lost.
-- ============================================================

BEGIN;

ALTER TABLE public.scene_window_embeddings
    ADD COLUMN IF NOT EXISTS person_frame_refs jsonb,
    ADD COLUMN IF NOT EXISTS context_frame_refs jsonb,
    ADD COLUMN IF NOT EXISTS evidence_payload jsonb;

COMMENT ON COLUMN public.scene_window_embeddings.person_frame_refs IS
    'JSONB array of s3/http refs for person crop frames sent by the edge anomaly pipeline. Usually 16 refs.';

COMMENT ON COLUMN public.scene_window_embeddings.context_frame_refs IS
    'JSONB array of s3/http refs for wider context frames sent by the edge anomaly pipeline. Usually 16 refs.';

COMMENT ON COLUMN public.scene_window_embeddings.evidence_payload IS
    'Full evidence payload received from the edge/consumer, including person_frames, context_frames, representative_frame_ref, person_clip_ref, and context_clip_ref.';

-- Optional indexes for debugging/querying rows that have persisted frame refs.
CREATE INDEX IF NOT EXISTS idx_scene_window_embeddings_person_frame_refs_gin
    ON public.scene_window_embeddings
    USING gin (person_frame_refs);

CREATE INDEX IF NOT EXISTS idx_scene_window_embeddings_context_frame_refs_gin
    ON public.scene_window_embeddings
    USING gin (context_frame_refs);

CREATE INDEX IF NOT EXISTS idx_scene_window_embeddings_evidence_payload_gin
    ON public.scene_window_embeddings
    USING gin (evidence_payload);

COMMIT;