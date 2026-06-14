"""
vad.evidence_keys
=================
Pure helpers for parsing and classifying VAD evidence object keys stored in MinIO.

These functions contain **no I/O** and have **no side-effects**.
They may be imported freely by reasoning_worker, reasoning_jobs, and
keyframe_selector without creating circular dependencies.

Rules
-----
* Never change the MinIO key structure here.  These functions only *read* keys.
* The sentinel value 10**9 for non-frame keys in ``frame_index_from_key`` must
  remain stable — keyframe_selector relies on it for sort ordering.
* ``infer_evidence_role`` is the canonical role classifier; both reasoning_jobs
  (previously returning ``"other"`` for unknowns) and reasoning_worker
  (previously returning ``"image"``) now call this single function.  The two
  callers use the result differently, so the distinction between "other"/"image"
  is irrelevant for routing — only ``"tubelet_frame"`` and ``"event_metadata"``
  affect behaviour.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Image extension set — used for quick membership tests
# ---------------------------------------------------------------------------
_IMAGE_EXTS = frozenset((".jpg", ".jpeg", ".png", ".webp"))

# ---------------------------------------------------------------------------
# Compiled patterns for hot-path use
# ---------------------------------------------------------------------------
_TUBELET_FRAME_RE = re.compile(
    r"(?:^|/)frames/frame_(\d+)\.(?:jpg|jpeg|png|webp)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def frame_index_from_key(key: str) -> int:
    """Return the numeric frame index embedded in a tubelet-frame key.

    Returns ``10**9`` for keys that do not match the
    ``frames/frame_NNN.{jpg,jpeg,png,webp}`` pattern so that non-frame keys
    sort to the end when frame keys are sorted chronologically.

    Examples
    --------
    >>> frame_index_from_key("events/abc/frames/frame_007.jpg")
    7
    >>> frame_index_from_key("events/abc/tubelet_montage.jpg")
    1000000000
    """
    m = _TUBELET_FRAME_RE.search(key.lower())
    return int(m.group(1)) if m else 10**9


def is_image_key(key: str) -> bool:
    """Return True if *key* has a recognised image file extension."""
    return key.lower().rsplit(".", 1)[-1] in {"jpg", "jpeg", "png", "webp"}


def is_tubelet_frame_key(key: str) -> bool:
    """Return True if *key* matches the ``frames/frame_NNN.*`` pattern."""
    return bool(_TUBELET_FRAME_RE.search(key.lower()))


def is_event_metadata_key(key: str) -> bool:
    """Return True if *key* refers to an ``event_metadata.json`` object."""
    lower = key.lower().strip().lstrip("/")
    return lower.endswith("/event_metadata.json") or lower == "event_metadata.json"


def infer_evidence_role(key: str) -> str:
    """Classify a MinIO object key into a VAD evidence role string.

    Returns one of:
    - ``"tubelet_frame"``   — ``frames/frame_NNN.{jpg,jpeg,png,webp}``
    - ``"tubelet_montage"`` — ``tubelet_montage.jpg``
    - ``"annotated_frame"`` — ``annotated_frame.jpg``
    - ``"event_metadata"``  — ``event_metadata.json``
    - ``"other"``           — anything else
    """
    lower = key.lower().strip().lstrip("/")
    name = lower.rsplit("/", 1)[-1]

    if name == "annotated_frame.jpg":
        return "annotated_frame"
    if name == "tubelet_montage.jpg":
        return "tubelet_montage"
    if name == "event_metadata.json":
        return "event_metadata"
    if is_tubelet_frame_key(lower):
        return "tubelet_frame"
    return "other"


def sort_frame_keys(frame_keys: list[str]) -> list[str]:
    """Return *frame_keys* sorted chronologically by embedded frame index.

    Non-frame keys sort to the end (index sentinel ``10**9``).
    Input list is **not** mutated.
    """
    return sorted(
        [str(k).strip().lstrip("/") for k in frame_keys if k],
        key=frame_index_from_key,
    )
