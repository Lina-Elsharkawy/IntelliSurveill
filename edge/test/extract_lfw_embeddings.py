import os
import json
import time
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np
from insightface.app import FaceAnalysis
from insightface.model_zoo import get_model


# =========================
# EDIT THESE TWO PATHS
# =========================
LFW_SUBSET_DIR = r"D:\UNIVERSITY\Graduation Project\gp\Graduation-Project\edge\test\lfw_subset"
OUT_JSONL = os.path.join(LFW_SUBSET_DIR, "lfw_embeddings.jsonl")


# =========================
# SETTINGS
# =========================
MODEL_NAME = "buffalo_l"
DET_SIZE = 1024
CTX_ID = -1  # CPU
CAMERA_ID = 1
MIN_DET_SCORE = 0.0

# Recognition model file (already downloaded on your machine)
# Your logs showed: C:\Users\linae/.insightface\models\buffalo_l\w600k_r50.onnx
RECOG_MODEL_PATH = os.path.expanduser(r"~\.insightface\models\buffalo_l\w600k_r50.onnx")


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


def extract_embedding_fallback(rec_model, img_bgr: np.ndarray) -> np.ndarray:
    """
    Fallback embedding extractor when detection fails:
    Treat the entire image as the face crop (LFW often contains aligned faces).
    Resize to 112x112 and run recognition model directly.
    """
    # Ensure 3 channels
    if img_bgr.ndim == 2:
        img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)

    face_crop = cv2.resize(img_bgr, (112, 112), interpolation=cv2.INTER_CUBIC)
    emb = rec_model.get(face_crop)  # returns np.ndarray (usually 512,)
    return emb


def main():
    enroll_dir = os.path.join(LFW_SUBSET_DIR, "enroll")
    test_dir = os.path.join(LFW_SUBSET_DIR, "test")

    if not os.path.isdir(enroll_dir) or not os.path.isdir(test_dir):
        raise RuntimeError(f"Expected folders not found:\n- {enroll_dir}\n- {test_dir}")

    # Init detector+pipeline (may fail on tiny/aligned images)
    app = FaceAnalysis(name=MODEL_NAME)
    app.prepare(ctx_id=CTX_ID, det_size=(DET_SIZE, DET_SIZE))

    # Init recognition model for fallback (direct embedding, no detection)
    if not os.path.exists(RECOG_MODEL_PATH):
        raise RuntimeError(
            f"Recognition model not found at:\n{RECOG_MODEL_PATH}\n"
            f"Run your InsightFace once (it auto-downloads), then try again."
        )
    rec_model = get_model(RECOG_MODEL_PATH)
    rec_model.prepare(ctx_id=CTX_ID)

    total = 0
    ok = 0
    failed = 0

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for split_name, split_dir in [("enroll", enroll_dir), ("test", test_dir)]:
            for img_path in iter_images(split_dir):
                total += 1

                rel = os.path.relpath(img_path, split_dir)
                identity = rel.split(os.sep)[0]

                img = cv2.imread(img_path)
                if img is None:
                    failed += 1
                    f.write(json.dumps({
                        "split": split_name,
                        "identity": identity,
                        "img_path": img_path,
                        "error": "cv2.imread_failed",
                    }) + "\n")
                    continue

                t0 = time.time()

                # 1) Try normal detection
                faces = app.get(img)
                proc_ms = int((time.time() - t0) * 1000)

                emb = None
                det_score = None
                mode = None

                if faces:
                    best = max(faces, key=lambda fc: float(getattr(fc, "det_score", 0.0)))
                    det_score = float(getattr(best, "det_score", 0.0))
                    if det_score >= MIN_DET_SCORE and best.embedding is not None:
                        emb = best.embedding.astype(np.float32)
                        mode = "detected"
                # 2) Fallback: no face detected -> direct embedding
                if emb is None:
                    try:
                        t1 = time.time()
                        emb = extract_embedding_fallback(rec_model, img).astype(np.float32)
                        proc_ms = int((time.time() - t1) * 1000)
                        det_score = None
                        mode = "fallback_full_image"
                    except Exception as e:
                        failed += 1
                        f.write(json.dumps({
                            "split": split_name,
                            "identity": identity,
                            "img_path": img_path,
                            "error": "fallback_failed",
                            "details": str(e),
                            "img_shape": list(img.shape),
                        }) + "\n")
                        continue

                rec = {
                    "event_id": make_event_id(),
                    "camera_id": CAMERA_ID,
                    "ts": iso_utc_now(),
                    "embedding": emb.tolist(),
                    "event_type": "face_detected",
                    "location": None,
                    "device_status": None,
                    "image_video_ref": img_path,
                    "processing_time_ms": proc_ms,
                    "model_version": f"insightface-{MODEL_NAME}",
                    "quality_score": det_score,
                    "split": split_name,
                    "identity": identity,
                    "extraction_mode": mode,
                }

                f.write(json.dumps(rec) + "\n")
                ok += 1

    print("Done.")
    print("Output:", OUT_JSONL)
    print(f"Total images: {total}")
    print(f"Embeddings extracted: {ok}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
