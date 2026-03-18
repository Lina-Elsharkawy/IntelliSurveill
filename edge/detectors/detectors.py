"""
detectors.py
Local webcam demo (VS Code / Windows) for 4 use-case detectors using:
- Ultralytics YOLO26 (person detection + tracking IDs)
- MediaPipe Tasks PoseLandmarker (for fall detection)  ✅ works with mediapipe 0.10.30–0.10.32 (no mp.solutions)

Detectors:
1) Fall detection (pose bbox aspect ratio + immobility + lowish position)
2) Intrusion detection (person enters forbidden ROI polygon)
3) Fight detection (proximity + speed spike using tracked IDs)
4) Crowd detection (count in ROI >= threshold)

Install (same interpreter that runs the script):
  python -m pip install ultralytics mediapipe opencv-python numpy pillow requests

Run:
  python detectors.py
Press:
  q = quit
  r = reset counters/state
"""

import os
import time
import math
from collections import defaultdict, deque
from typing import Dict, Deque, Tuple, List

import cv2
import numpy as np
import requests
from ultralytics import YOLO

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


# =========================
# CONFIG
# =========================
CAMERA_ID = 0
FRAME_W, FRAME_H = 960, 540

YOLO_MODEL = "yolo26n.pt"   # use yolo26s.pt if you want higher accuracy (slower)

# Forbidden zone polygon in normalized coords (x,y in [0,1]).
# Adjust later to match your lab camera view.
FORBIDDEN_POLY_NORM = np.array([
    [0.55, 0.15],
    [0.95, 0.15],
    [0.95, 0.85],
    [0.55, 0.85],
], dtype=np.float32)


# --- Intrusion ---
INTRUSION_MIN_FRAMES = 3  # require persistence across frames

# --- Crowd ---
CROWD_THRESHOLD = 3       # number of persons inside ROI
CROWD_MIN_FRAMES = 5

# --- Fight ---
FIGHT_MAX_DIST_PX = 120   # proximity threshold
FIGHT_SPEED_PX_S = 350    # speed threshold
FIGHT_MIN_FRAMES = 4

# --- Fall (PoseLandmarker-based heuristic) ---
FALL_ASPECT_RATIO = 1.25     # bbox w/h threshold (horizontal-ish)
FALL_IMMOBILE_SECONDS = 1.0  # how long to check immobility
FALL_MOVE_EPS_PX = 10        # max movement in that window
FALL_LOWISH_Y = 0.55         # bbox center must be in lower part of image (reduce false positives)
FALL_MIN_FRAMES = 4          # require persistence across frames

# Display / performance
DRAW_TRACK_LINES = True
SHOW_DEBUG_TEXT = True


# =========================
# MediaPipe PoseLandmarker model
# =========================
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "pose_landmarker_lite.task")


def ensure_pose_model() -> str:
    """Download the PoseLandmarker model once (kept next to this script)."""
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        return MODEL_PATH

    print(f"[mediapipe] Downloading PoseLandmarker model to: {MODEL_PATH}")
    r = requests.get(MODEL_URL, stream=True, timeout=120)
    r.raise_for_status()
    with open(MODEL_PATH, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
    return MODEL_PATH


def create_pose_landmarker():
    model_path = ensure_pose_model()
    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.PoseLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,  # single-frame (good enough for heuristic)
        num_poses=1
    )
    return vision.PoseLandmarker.create_from_options(options)


# =========================
# Helpers
# =========================
def norm_poly_to_px(poly_norm: np.ndarray, w: int, h: int) -> np.ndarray:
    p = poly_norm.copy()
    p[:, 0] *= w
    p[:, 1] *= h
    return p.astype(np.int32)


def point_in_poly(cx: float, cy: float, poly_px: np.ndarray) -> bool:
    return cv2.pointPolygonTest(poly_px, (float(cx), float(cy)), False) >= 0


def compute_speed(track_deque: Deque[Tuple[float, float, float]]) -> float:
    """Speed (px/s) using last two points in track history."""
    if len(track_deque) < 2:
        return 0.0
    (t1, x1, y1), (t2, x2, y2) = track_deque[-2], track_deque[-1]
    dt = max(1e-3, t2 - t1)
    return math.hypot(x2 - x1, y2 - y1) / dt


def draw_poly(img: np.ndarray, poly_px: np.ndarray, label: str) -> None:
    cv2.polylines(img, [poly_px], isClosed=True, color=(0, 255, 255), thickness=2)
    x, y = poly_px[0]
    cv2.putText(img, label, (int(x), int(y) - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


# =========================
# Fall detection via MediaPipe Tasks
# =========================
def fall_heuristic_from_pose_landmarker(
    pose_landmarker,
    frame_bgr: np.ndarray,
    t_now: float,
    fall_centers: Deque[Tuple[float, float, float]],
) -> Tuple[bool, Dict]:
    """
    Heuristic:
      - Detect pose landmarks (1 pose).
      - Compute bbox from all landmarks.
      - "Possible fall" if bbox becomes horizontal-ish (w/h >= threshold)
      - Confirm if:
          - immobile for ~1 sec (center movement small)
          - bbox center is lowish in the image (reduce bending false positives)
    """
    h, w = frame_bgr.shape[:2]
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
    result = pose_landmarker.detect(mp_image)

    if not result.pose_landmarks:
        fall_centers.clear()
        return False, {"pose": "none"}

    lms = result.pose_landmarks[0]  # NormalizedLandmark list
    xs, ys = [], []
    for lm in lms:
        xs.append(lm.x * w)
        ys.append(lm.y * h)

    if len(xs) < 8:
        fall_centers.clear()
        return False, {"pose": "low_landmarks"}

    x1, x2 = float(min(xs)), float(max(xs))
    y1, y2 = float(min(ys)), float(max(ys))
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    aspect = bw / bh

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    fall_centers.append((t_now, cx, cy))

    # immobility over last FALL_IMMOBILE_SECONDS
    recent = [(t, x, y) for (t, x, y) in fall_centers if (t_now - t) <= FALL_IMMOBILE_SECONDS]
    immobile = False
    move = None
    if len(recent) >= 2:
        x0, y0 = recent[0][1], recent[0][2]
        xN, yN = recent[-1][1], recent[-1][2]
        move = math.hypot(xN - x0, yN - y0)
        immobile = move < FALL_MOVE_EPS_PX

    lowish = cy > (FALL_LOWISH_Y * h)
    is_fall = (aspect >= FALL_ASPECT_RATIO) and immobile and lowish

    dbg = {
        "pose": "ok",
        "aspect": aspect,
        "immobile": immobile,
        "move_px": move,
        "lowish": lowish,
        "bbox": (int(x1), int(y1), int(x2), int(y2)),
        "center": (cx, cy),
    }
    return is_fall, dbg


# =========================
# Main
# =========================
def main():
    print("[init] Loading YOLO model:", YOLO_MODEL)
    yolo = YOLO(YOLO_MODEL)

    print("[init] Creating PoseLandmarker...")
    pose_landmarker = create_pose_landmarker()
    print("[init] Ready. Press 'q' to quit, 'r' to reset counters/state.")

    cap = cv2.VideoCapture(CAMERA_ID)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open webcam CAMERA_ID={CAMERA_ID}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

    # Track history for fight speed estimation
    track_hist: Dict[int, Deque[Tuple[float, float, float]]] = defaultdict(lambda: deque(maxlen=10))

    # Counters for stability
    intrusion_counter = 0
    crowd_counter = 0
    fight_counter = 0
    fall_counter = 0

    # Fall immobility tracking (for the single pose)
    fall_centers: Deque[Tuple[float, float, float]] = deque(maxlen=30)

    # Optional: show past centers for each ID
    # (keep short lines)
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[warn] Frame read failed.")
            break

        t_now = time.time()
        h, w = frame.shape[:2]

        forbidden_poly = norm_poly_to_px(FORBIDDEN_POLY_NORM, w, h)
        draw_poly(frame, forbidden_poly, "FORBIDDEN ZONE")

        # ---------------------------
        # YOLO tracking for persons (class 0 = person)
        # ---------------------------
        persons = []  # list of dicts: id, bbox, center
        results = yolo.track(frame, classes=[0], persist=True, verbose=False)

        if results and len(results) > 0:
            r = results[0]
            boxes = r.boxes
            if boxes is not None and boxes.id is not None:
                for b in boxes:
                    tid = int(b.id.item())
                    x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    persons.append({"id": tid, "bbox": (x1, y1, x2, y2), "c": (cx, cy)})
                    track_hist[tid].append((t_now, cx, cy))

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"ID {tid}", (x1, max(0, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                    if DRAW_TRACK_LINES and len(track_hist[tid]) >= 2:
                        pts = [(int(x), int(y)) for (_, x, y) in track_hist[tid]]
                        for k in range(1, len(pts)):
                            cv2.line(frame, pts[k - 1], pts[k], (0, 200, 0), 1)

        # ---------------------------
        # Intrusion + Crowd (ROI based)
        # ---------------------------
        in_roi = [p for p in persons if point_in_poly(p["c"][0], p["c"][1], forbidden_poly)]
        count_in_roi = len(in_roi)

        if count_in_roi >= 1:
            intrusion_counter += 1
        else:
            intrusion_counter = max(0, intrusion_counter - 1)

        if count_in_roi >= CROWD_THRESHOLD:
            crowd_counter += 1
        else:
            crowd_counter = max(0, crowd_counter - 1)

        intrusion_trigger = intrusion_counter >= INTRUSION_MIN_FRAMES
        crowd_trigger = crowd_counter >= CROWD_MIN_FRAMES

        # ---------------------------
        # Fight detection (proximity + speed)
        # ---------------------------
        speeds = {p["id"]: compute_speed(track_hist[p["id"]]) for p in persons}

        fight_hit = False
        for i in range(len(persons)):
            for j in range(i + 1, len(persons)):
                pi, pj = persons[i], persons[j]
                xi, yi = pi["c"]
                xj, yj = pj["c"]
                dist = math.hypot(xi - xj, yi - yj)
                if dist < FIGHT_MAX_DIST_PX:
                    si = speeds.get(pi["id"], 0.0)
                    sj = speeds.get(pj["id"], 0.0)
                    if max(si, sj) > FIGHT_SPEED_PX_S:
                        fight_hit = True
                        cv2.line(frame, (int(xi), int(yi)), (int(xj), int(yj)), (0, 0, 255), 2)
                        cv2.putText(frame, "close+fast",
                                    (int((xi + xj) / 2), int((yi + yj) / 2) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if fight_hit:
            fight_counter += 1
        else:
            fight_counter = max(0, fight_counter - 1)

        fight_trigger = fight_counter >= FIGHT_MIN_FRAMES

        # ---------------------------
        # Fall detection (PoseLandmarker heuristic)
        # ---------------------------
        fall_hit, fall_dbg = fall_heuristic_from_pose_landmarker(
            pose_landmarker=pose_landmarker,
            frame_bgr=frame,
            t_now=t_now,
            fall_centers=fall_centers,
        )

        if fall_hit:
            fall_counter += 1
        else:
            fall_counter = max(0, fall_counter - 1)

        fall_trigger = fall_counter >= FALL_MIN_FRAMES

        # Draw fall bbox/debug
        if isinstance(fall_dbg, dict) and "bbox" in fall_dbg:
            x1, y1, x2, y2 = fall_dbg["bbox"]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
            if SHOW_DEBUG_TEXT:
                cv2.putText(frame, f"fall_aspect:{fall_dbg.get('aspect', 0):.2f}",
                            (x1, max(0, y1 - 22)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)
                cv2.putText(frame, f"immobile:{fall_dbg.get('immobile', False)} move:{(fall_dbg.get('move_px') or 0):.1f}",
                            (x1, max(0, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

        # ---------------------------
        # Overlay alerts + status
        # ---------------------------
        alerts = []
        if intrusion_trigger:
            alerts.append("INTRUSION")
        if crowd_trigger:
            alerts.append(f"CROWD({count_in_roi})")
        if fight_trigger:
            alerts.append("FIGHT")
        if fall_trigger:
            alerts.append("FALL")

        cv2.putText(frame, f"ROI count: {count_in_roi}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        if SHOW_DEBUG_TEXT:
            # show up to 5 track speeds
            y0 = 55
            for p in persons[:5]:
                tid = p["id"]
                sp = speeds.get(tid, 0.0)
                cv2.putText(frame, f"ID {tid} speed: {sp:.1f}px/s", (10, y0),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                y0 += 20

            cv2.putText(frame,
                        f"ctr I:{intrusion_counter} C:{crowd_counter} F:{fight_counter} FALL:{fall_counter}",
                        (10, h - 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        if alerts:
            cv2.putText(frame, "ALERT: " + ", ".join(alerts), (10, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 3)

        cv2.imshow("YOLO26 + 4 Detectors (Local Webcam)", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            # reset counters/state
            intrusion_counter = crowd_counter = fight_counter = fall_counter = 0
            track_hist.clear()
            fall_centers.clear()
            print("[reset] counters/state cleared")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
