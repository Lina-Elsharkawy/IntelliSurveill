from __future__ import annotations

import base64
import json
import logging
from typing import Any

from .config import VadConfig
from .evidence_keys import (
    frame_index_from_key as _frame_index_from_key,
    infer_evidence_role as _infer_evidence_role,
)
from .json_utils import sanitize_json
from .minio_client import VadMinioClient

log = logging.getLogger("vad.reasoning_evidence")


def _json_default(value: Any) -> Any:
    return sanitize_json(value)


# ─────────────────────────────────────────────────────────────────────────────
# Gate-aware reasoning frame selector
# This is reasoning-worker-only. It does not affect live VAD gate scoring.
# ─────────────────────────────────────────────────────────────────────────────

def _get_gate_name_from_bundle(bundle: dict[str, Any]) -> str:
    event = bundle.get("event") or {}
    if isinstance(event, dict):
        return str(event.get("gate_name") or event.get("source_gate_name") or "deep").strip().lower()
    return "deep"


# _frame_index_from_key and _infer_image_role_from_key are imported from evidence_keys.
# NOTE: evidence_keys.infer_evidence_role returns "other" for unrecognised keys
# (the previous local _infer_image_role_from_key returned "image").  Both callers
# in this file only act on "tubelet_frame" and "event_metadata" outcomes, so the
# difference between "other" and "image" has no effect on behaviour.


def _even_sample(keys: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return []
    if len(keys) <= limit:
        return list(keys)
    last = len(keys) - 1
    indexes = sorted({round(i * last / (limit - 1)) for i in range(limit)})
    return [keys[i] for i in indexes[:limit]]


# ─────────────────────────────────────────────────────────────────────────────
# Evidence key collection + gate-aware frame selection
# ─────────────────────────────────────────────────────────────────────────────

def _collect_frame_keys(bundle: dict[str, Any]) -> list[str]:
    """Collect all tubelet_frame keys from the reasoning bundle in chronological order."""
    visual = bundle.get("visual_evidence") or {}
    seen: set[str] = set()
    frames: list[str] = []

    def _add(key: Any, role: str | None = None) -> None:
        if not isinstance(key, str):
            return
        clean = key.strip().lstrip("/")
        if not clean or clean in seen:
            return
        if not clean.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return
        inferred = role or _infer_evidence_role(clean)
        if inferred == "tubelet_frame":
            seen.add(clean)
            frames.append(clean)

    for key in visual.get("object_keys") or []:
        _add(key)
    for obj in (visual.get("objects") or []) + (visual.get("evidence_objects") or []):
        if isinstance(obj, dict):
            _add(
                obj.get("object_key"),
                role=(obj.get("role") or obj.get("media_role") or "").strip() or None,
            )

    frames.sort(key=_frame_index_from_key)
    return frames


def _collect_event_metadata_keys(bundle: dict[str, Any]) -> list[str]:
    """Collect event_metadata.json keys from the reasoning bundle."""
    visual = bundle.get("visual_evidence") or {}
    seen: set[str] = set()
    keys: list[str] = []

    def _add(key: Any, role: str | None = None) -> None:
        if not isinstance(key, str):
            return
        clean = key.strip().lstrip("/")
        if not clean or clean in seen:
            return
        lower = clean.lower()
        inferred = role or _infer_evidence_role(clean)
        if inferred == "event_metadata" or lower.endswith("/event_metadata.json") or lower.endswith("event_metadata.json"):
            seen.add(clean)
            keys.append(clean)

    for key in visual.get("object_keys") or []:
        _add(key)
    for obj in (visual.get("objects") or []) + (visual.get("evidence_objects") or []):
        if isinstance(obj, dict):
            _add(
                obj.get("object_key"),
                role=(obj.get("role") or obj.get("media_role") or "").strip() or None,
            )
    return keys


def _download_event_metadata(bundle: dict[str, Any], minio: VadMinioClient) -> dict[str, Any]:
    for key in _collect_event_metadata_keys(bundle):
        try:
            raw = minio.download_bytes(key)
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            log.warning("Could not download/parse event metadata %s: %s", key, e)
    return {}


def select_evidence_object_keys(
    bundle: dict[str, Any],
    cfg: VadConfig,
    minio: VadMinioClient,
) -> tuple[list[str], dict[str, bytes], dict[str, Any]]:
    """
    Download all tubelet frames, then apply gate-aware reasoning frame selection.

    Returns
    -------
    selected_keys : list[str]
        Up to VAD_REASONING_MAX_IMAGES frame keys in chronological order.
    image_bytes_map : dict[str, bytes]
        Raw image bytes for every selected key (needed by _load_images_b64).
    """
    max_images = max(1, int(cfg.reasoning_max_images or 8))
    gate_name = _get_gate_name_from_bundle(bundle)
    frame_keys = _collect_frame_keys(bundle)
    event_metadata = _download_event_metadata(bundle, minio)

    if not frame_keys:
        # No tubelet frames — fall back to montage/annotated.
        visual = bundle.get("visual_evidence") or {}
        fallback: list[str] = []
        for key in visual.get("object_keys") or []:
            if isinstance(key, str) and key.strip().lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                fallback.append(key.strip().lstrip("/"))
        fallback = fallback[:max_images]
        bytes_map = {}
        for k in fallback:
            try:
                bytes_map[k] = minio.download_bytes(k)
            except Exception as e:
                log.warning("Could not download fallback frame %s: %s", k, e)
        log.info(
            "Frame selection: gate=%s selector=even_spacing_fallback total_frames=%d selected=%d max_images=%d selected_indices=%s reason=no_tubelet_frames",
            gate_name, len(fallback), len(fallback), max_images, list(range(len(fallback))),
        )
        return fallback, bytes_map, {
            "gate": gate_name,
            "selector": "even_spacing_fallback",
            "reason": "no_tubelet_frames",
            "total_frames": len(fallback),
            "selected": len(fallback),
            "max_images": max_images,
            "selected_indices": list(range(len(fallback))),
            "selected_object_keys": fallback,
        }

    # Download all candidate frames first. Selectors need bytes for image diff,
    # VideoMAE, or optional YOLO-pose reinference.
    all_bytes: dict[str, bytes] = {}
    for key in frame_keys:
        try:
            all_bytes[key] = minio.download_bytes(key)
        except Exception as e:
            log.warning("Could not download frame %s: %s", key, e)

    # Drop missing frames before selection.
    available_frame_keys = [k for k in frame_keys if k in all_bytes]

    try:
        from .keyframe_selector import select_reasoning_frames
        selection = select_reasoning_frames(
            gate_name=gate_name,
            frame_keys=available_frame_keys,
            image_bytes_map=all_bytes,
            metadata=event_metadata,
            max_images=max_images,
            cfg=cfg,
        )
        selected = selection.frame_keys
        selected_indices = selection.selected_indices
        selector_name = selection.selector
        selector_reason = selection.reason
        selector_debug = dict(getattr(selection, "debug", {}) or {})
    except Exception as e:
        log.warning("Gate-aware selector import/call failed: %s", e)
        selected = _even_sample(available_frame_keys, max_images)
        selected_indices = [_frame_index_from_key(k) for k in selected]
        selector_name = "even_spacing_fallback"
        selector_reason = "selector_import_or_call_failed"
        selector_debug = {"error": str(e)}

    selected_bytes = {k: all_bytes[k] for k in selected if k in all_bytes}

    frame_selection_audit = {
        "gate": gate_name,
        "selector": selector_name,
        "reason": selector_reason,
        "total_frames": len(available_frame_keys),
        "selected": len(selected),
        "max_images": max_images,
        "selected_indices": selected_indices,
        "selected_object_keys": selected,
        "debug": selector_debug,
    }

    log.info(
        "Frame selection: gate=%s selector=%s total=%d selected=%d max=%d "
        "indices=%s frame_numbers=%s reason=%s",
        gate_name,
        selector_name,
        len(available_frame_keys),
        len(selected),
        max_images,
        selected_indices,
        selector_debug.get("selected_frame_numbers", []),
        selector_reason,
    )
    log.info("Frame selection audit: %s", json.dumps(sanitize_json(frame_selection_audit), ensure_ascii=False, default=_json_default))
    return selected, selected_bytes, frame_selection_audit


# ─────────────────────────────────────────────────────────────────────────────
# Load images as base64 from already-downloaded bytes
# ─────────────────────────────────────────────────────────────────────────────

def images_b64_from_map(object_keys: list[str], image_bytes_map: dict[str, bytes]) -> list[str]:
    result = []
    for key in object_keys:
        data = image_bytes_map.get(key)
        if data:
            result.append(base64.b64encode(data).decode("ascii"))
    return result


