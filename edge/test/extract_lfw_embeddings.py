import os
import json
import time
import uuid
import traceback
import warnings
from datetime import datetime, timezone

import cv2
import numpy as np
from insightface.app import FaceAnalysis

# Silence the harmless FutureWarning from insightface alignment
warnings.filterwarnings("ignore", category=FutureWarning, module=r"insightface\.utils\.transform")

# =========================
# PATHS (NO ABSOLUTE PATHS)
# =========================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LFW_SUBSET_DIR = os.path.join(SCRIPT_DIR, "lfw_subset")
ENROLL_DIR = os.path.join(LFW_SUBSET_DIR, "enroll")

OUT_JSONL_DB = os.path.join(LFW_SUBSET_DIR, "lfw_embeddings_db.jsonl")

# =========================
# SETTINGS (CPU FRIENDLY)
# =========================
MODEL_NAME = "buffalo_l"
EMBEDDING_MODEL = f"insightface-{MODEL_NAME}"

CTX_ID = -1  # CPU
DET_SIZE = 640

# permissive but not crazy
DET_THRESH = 0.05

# Multi-scale, but CPU-friendly
# IMPORTANT: we early-exit on first success, so order matters.
SCALES = [1.0, 2.0, 3.0]

# cap image max side before scaling to avoid massive images on CPU
MAX_SIDE = 800

# Optional filter; keep 0.0 for max recall
MIN_ACCEPT_SCORE = 0.0

# Print progress every N images
PROGRESS_EVERY = 10


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:12]}"


def iter_images(root_dir: str):
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in exts:
                yield os.path.join(dirpath, fn)


def ensure_bgr3(img: np.ndarray) -> np.ndarray:
    if img is None:
        raise ValueError("img is None")
    if not isinstance(img, np.ndarray):
        raise TypeError(f"img is not ndarray: {type(img)}")
    if img.size == 0:
        raise ValueError(f"img is empty: shape={getattr(img, 'shape', None)}")

    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3 and img.shape[2] == 3:
        return img
    if img.ndim == 3 and img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    raise ValueError(f"Unexpected image shape: {img.shape}")


def cap_max_side(img: np.ndarray, max_side: int = 800) -> np.ndarray:
    h, w = img.shape[:2]
    m = max(h, w)
    if m <= max_side:
        return img
    s = max_side / float(m)
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).reshape(-1)
    n = float(np.linalg.norm(v)) + 1e-12
    return (v / n).astype(np.float32)


def pgvector_literal(vec512: np.ndarray) -> str:
    """
    Returns a pgvector literal without quotes: [0.1,0.2,...]
    Use in SQL as:  '[...]'::vector
    """
    vec512 = vec512.reshape(-1).astype(np.float32)
    s = ",".join(f"{float(x):.8f}" for x in vec512.tolist())
    return f"[{s}]"


def pick_face_fast(app: FaceAnalysis, img_bgr: np.ndarray):
    """
    CPU-friendly:
    - Cap size once
    - Try scales in order
    - EARLY EXIT on first successful face (best face in that scale)
    Returns (face, used_scale, det_score).
    """
    base = cap_max_side(img_bgr, MAX_SIDE)

    for sc in SCALES:
        if sc == 1.0:
            img_sc = base
        else:
            img_sc = cv2.resize(base, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC)

        # app.get runs det + embedding. Early exit is what makes this fast.
        faces = app.get(img_sc)
        if not faces:
            continue

        face = max(faces, key=lambda fc: float(getattr(fc, "det_score", 0.0)))
        score = float(getattr(face, "det_score", 0.0))

        if getattr(face, "embedding", None) is None:
            continue

        return face, sc, score

    return None, None, -1.0


def main():
    print("RUNNING FILE:", os.path.abspath(__file__))

    if not os.path.isdir(ENROLL_DIR):
        raise RuntimeError(f"Enroll folder not found: {ENROLL_DIR}")

    os.makedirs(LFW_SUBSET_DIR, exist_ok=True)

    # Init InsightFace
    app = FaceAnalysis(name=MODEL_NAME)
    try:
        app.prepare(ctx_id=CTX_ID, det_size=(DET_SIZE, DET_SIZE), det_thresh=DET_THRESH)
    except TypeError:
        app.prepare(ctx_id=CTX_ID, det_size=(DET_SIZE, DET_SIZE))

    total = 0
    ok = 0
    no_face = 0
    failed = 0

    with open(OUT_JSONL_DB, "w", encoding="utf-8") as jf:
        for img_path in sorted(iter_images(ENROLL_DIR)):
            total += 1
            if total % PROGRESS_EVERY == 0:
                print(f"[{total}] ok={ok} no_face={no_face} failed={failed}")

            rel_to_enroll = os.path.relpath(img_path, ENROLL_DIR)
            identity = rel_to_enroll.split(os.sep)[0]
            image_ref = os.path.relpath(img_path, LFW_SUBSET_DIR)

            img = cv2.imread(img_path)
            if img is None:
                failed += 1
                jf.write(json.dumps({
                    "identity": identity,
                    "image_video_ref": image_ref,
                    "error": "cv2.imread_failed",
                    "running_file": os.path.abspath(__file__),
                }) + "\n")
                continue

            try:
                img = ensure_bgr3(img)
            except Exception as e:
                failed += 1
                jf.write(json.dumps({
                    "identity": identity,
                    "image_video_ref": image_ref,
                    "error": "invalid_image_array",
                    "details": str(e),
                    "trace": traceback.format_exc(),
                    "running_file": os.path.abspath(__file__),
                }) + "\n")
                continue

            img_mean = float(img.mean())
            img_min = int(img.min())
            img_max = int(img.max())

            t0 = time.time()
            try:
                face, used_scale, score = pick_face_fast(app, img)
                proc_ms = int((time.time() - t0) * 1000)
            except Exception as e:
                failed += 1
                jf.write(json.dumps({
                    "identity": identity,
                    "image_video_ref": image_ref,
                    "error": "detect_failed",
                    "details": str(e),
                    "trace": traceback.format_exc(),
                    "running_file": os.path.abspath(__file__),
                }) + "\n")
                continue

            if face is None or score < MIN_ACCEPT_SCORE:
                no_face += 1
                jf.write(json.dumps({
                    "identity": identity,
                    "image_video_ref": image_ref,
                    "error": "no_face_detected",
                    "attempted_scales": SCALES,
                    "det_size": DET_SIZE,
                    "det_thresh": DET_THRESH,
                    "best_score_seen": score,
                    "img_shape": list(img.shape),
                    "img_mean": round(img_mean, 3),
                    "img_min": img_min,
                    "img_max": img_max,
                    "processing_time_ms": proc_ms,
                    "running_file": os.path.abspath(__file__),
                }) + "\n")
                continue

            emb = l2_normalize(face.embedding)

            jf.write(json.dumps({
                "event_id": make_event_id(),
                "ts": iso_utc_now(),
                "identity": identity,
                "image_video_ref": image_ref,
                "embedding_model": EMBEDDING_MODEL,
                "quality_score": float(score),
                "processing_time_ms": proc_ms,
                "det_scale_used": float(used_scale),
                "embedding_pgvector": pgvector_literal(emb),
                "embedding_list": emb.tolist(),
            }) + "\n")
            ok += 1

    print("Done.")
    print("Output JSONL (DB-ready):", OUT_JSONL_DB)
    print(f"Total images: {total}")
    print(f"Embeddings extracted: {ok}")
    print(f"No-face: {no_face}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
