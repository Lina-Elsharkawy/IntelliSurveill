# import cv2
# import json
# import uuid
# import time
# import numpy as np
# from datetime import datetime, timezone
# from insightface.app import FaceAnalysis

# # =========================
# # CONFIG
# # =========================
# CAMERA_ID = 1
# CAM_INDEX = 0                 # change to 1/2 if camera not found

# DET_SIZE = 320                # lowered for speed (320/480/640)
# MIN_FACE_PX = 60              # skip tiny faces
# MODEL_VERSION = "insightface-buffalo_l"

# # Performance / UX
# MAX_FPS = 10.0                # compute limiter
# FRAME_STRIDE = 2              # process every Nth frame (2 = every other frame)
# PRINT_COOLDOWN_S = 1.0        # prevent spam: print approx once per second per coarse bbox
# SHOW_WINDOW = True
# QUIT_KEY = "q"

# # Camera resolution (big speed win)
# CAM_W, CAM_H = 640, 360


# # =========================
# # HELPERS
# # =========================
# def iso_utc_now() -> str:
#     return datetime.now(timezone.utc).isoformat()


# def make_event_id() -> str:
#     ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
#     return f"{ts}-{uuid.uuid4().hex[:12]}"


# def build_edge_event(face, processing_ms: int) -> dict:
#     embedding = face.embedding.astype(np.float32).tolist()
#     quality = float(getattr(face, "det_score", 0.0))
#     return {
#         "event_id": make_event_id(),
#         "camera_id": CAMERA_ID,
#         "ts": iso_utc_now(),
#         "embedding": embedding,  # List[float]
#         "event_type": "face_detected",
#         "location": None,
#         "device_status": None,
#         "image_video_ref": None,
#         "processing_time_ms": processing_ms,
#         "model_version": MODEL_VERSION,
#         "quality_score": quality,
#     }


# def bbox_key(x1, y1, x2, y2, quant=40):
#     # Not a tracker: just coarse quantization so the same face bbox maps
#     # to a similar key across frames (good enough for cooldown)
#     return (
#         (x1 // quant) * quant,
#         (y1 // quant) * quant,
#         (x2 // quant) * quant,
#         (y2 // quant) * quant,
#     )


# def print_event_short(event: dict):
#     emb = event["embedding"]
#     # Short, readable output (backend-like summary)
#     print(
#         f'event_id={event["event_id"]} camera_id={event["camera_id"]} '
#         f'ts={event["ts"]} quality={event["quality_score"]:.3f} '
#         f'proc_ms={event["processing_time_ms"]} emb_dim={len(emb)} '
#         f'emb_head={emb[:8]}'
#     )


# # =========================
# # MAIN
# # =========================
# def main():
#     # Init InsightFace (CPU). Later on Jetson you can try GPU/TensorRT options.
#     app = FaceAnalysis(name="buffalo_l")
#     app.prepare(ctx_id=-1, det_size=(DET_SIZE, DET_SIZE))

#     # Open camera
#     cap = cv2.VideoCapture(CAM_INDEX)
#     if not cap.isOpened():
#         raise RuntimeError(f"Could not open camera index {CAM_INDEX}. Try CAM_INDEX=1 or 2.")

#     # Set camera resolution (big speed win)
#     cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_W)
#     cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_H)

#     # FPS limiter
#     min_frame_interval = 1.0 / max(MAX_FPS, 0.1)
#     last_frame_time = 0.0

#     # cooldown map: bbox_key -> last_print_time
#     last_print = {}

#     frame_idx = 0
#     print("[INFO] Running. Press 'q' to quit.")

#     try:
#         while True:
#             now = time.time()
#             if now - last_frame_time < min_frame_interval:
#                 time.sleep(0.001)
#                 continue
#             last_frame_time = now

#             ok, frame = cap.read()
#             if not ok or frame is None:
#                 continue

#             frame_idx += 1

#             # If skipping inference frames, still show window smoothly
#             if frame_idx % FRAME_STRIDE != 0:
#                 if SHOW_WINDOW:
#                     cv2.imshow("Edge Face Embedder (print-only)", frame)
#                     if cv2.waitKey(1) & 0xFF == ord(QUIT_KEY):
#                         break
#                 continue

#             # Inference
#             t0 = time.time()
#             faces = app.get(frame)
#             processing_ms = int((time.time() - t0) * 1000)

#             printed = 0

#             for face in faces:
#                 if face.embedding is None:
#                     continue

#                 x1, y1, x2, y2 = face.bbox.astype(int).tolist()
#                 w, h = x2 - x1, y2 - y1
#                 if w < MIN_FACE_PX or h < MIN_FACE_PX:
#                     continue

#                 key = bbox_key(x1, y1, x2, y2)
#                 last_t = last_print.get(key, 0.0)

#                 # Print event if cooldown passed
#                 if (now - last_t) >= PRINT_COOLDOWN_S:
#                     event = build_edge_event(face, processing_ms)
#                     print_event_short(event)
#                     last_print[key] = now
#                     printed += 1

#                 # Draw overlay
#                 if SHOW_WINDOW:
#                     score = float(getattr(face, "det_score", 0.0))
#                     cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
#                     cv2.putText(
#                         frame,
#                         f"{score:.2f} {processing_ms}ms",
#                         (x1, max(0, y1 - 6)),
#                         cv2.FONT_HERSHEY_SIMPLEX,
#                         0.7,
#                         (0, 255, 0),
#                         2,
#                     )

#             if SHOW_WINDOW:
#                 cv2.putText(
#                     frame,
#                     f"faces={len(faces)} printed={printed} | proc={processing_ms}ms | det={DET_SIZE}",
#                     (10, 30),
#                     cv2.FONT_HERSHEY_SIMPLEX,
#                     0.9,
#                     (255, 255, 255),
#                     2,
#                 )
#                 cv2.imshow("Edge Face Embedder (print-only)", frame)
#                 if cv2.waitKey(1) & 0xFF == ord(QUIT_KEY):
#                     break

#     finally:
#         cap.release()
#         if SHOW_WINDOW:
#             cv2.destroyAllWindows()
#         print("[INFO] Stopped.")


# if __name__ == "__main__":
#     main()