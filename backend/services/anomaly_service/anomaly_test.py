import json
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta

SERVICE_URL = "http://127.0.0.1:8008"
DEVICE_KEY = "offline-fight-test"
CAMERA_ID = 1

# backend/services/anomaly_service/anomaly_test.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASETS_ROOT = PROJECT_ROOT / "datasets" / "anomaly_test"


def run_fight(fight_dir: Path):
    emb_file = fight_dir / "embeddings.json"
    frames_dir = fight_dir / "frames"

    if not emb_file.exists():
        print(f"[SKIP] {fight_dir.name} (no embeddings.json)")
        return 0, 0

    data = json.loads(emb_file.read_text(encoding="utf-8"))
    windows = data.get("windows", [])
    video_source = data.get("video_source")

    # Base time for this fight (UTC ISO timestamps)
    base_ts = datetime.now(timezone.utc)

    total_windows = 0
    anomaly_count = 0

    print(f"\n=== {fight_dir.name} | windows={len(windows)} ===")

    for w in windows:
        total_windows += 1

        window_idx = int(w["window_index"])
        motion_score = float(w.get("motion_score", 0.0))
        embedding = w["embedding"]

        # ---------- timestamps (VALID for Postgres timestamptz) ----------
        start_dt = base_ts + timedelta(seconds=window_idx)
        end_dt = start_dt + timedelta(seconds=1)

        window_start_ts = start_dt.isoformat()
        window_end_ts = end_dt.isoformat()

        # ---------- frames path (robust) ----------
        frames = []
        frame_path_raw = w.get("frame_path")
        if frame_path_raw:
            frame_name = Path(frame_path_raw).name  # win_XX.jpg
            frame_abs = (frames_dir / frame_name).resolve()
            if frame_abs.exists():
                frames = [str(frame_abs)]
            else:
                print(f"[WARN] Missing frame: {frame_abs}")

        payload = {
            "device_key": DEVICE_KEY,
            "event_key": f"{fight_dir.name}-win-{window_idx}",
            "camera_id": CAMERA_ID,
            "entry_log_id": None,
            "window_start_ts": window_start_ts,
            "window_end_ts": window_end_ts,
            "embedding_model": "scene_pca_128",
            "embedding_pca": embedding,
            "embedding_raw": None,
            "frames": frames,
            "image_ref": None,
            "video_ref": video_source,
        }

        r = requests.post(
            f"{SERVICE_URL}/ingest/scene_embedding",
            json=payload,
            timeout=30,
        )

        if r.status_code != 200:
            print(f"[ERR] win={window_idx} HTTP {r.status_code}: {r.text[:300]}")
            continue

        res = r.json()
        is_anom = (res.get("is_normal") is False)
        if is_anom:
            anomaly_count += 1
            tag = "ANOMALY"
        else:
            tag = "normal"

        print(
            f"[{tag}] win={window_idx} "
            f"motion={motion_score:.3f} "
            f"dist={res.get('cosine_distance')} "
            f"radius={res.get('radius_threshold')} "
            f"frames={len(frames)}"
        )

    print(f"--- {fight_dir.name} SUMMARY: anomalies={anomaly_count}/{total_windows}")
    return anomaly_count, total_windows


def main():
    if not DATASETS_ROOT.exists():
        raise SystemExit(f"Datasets folder not found: {DATASETS_ROOT}")

    fights = sorted(p for p in DATASETS_ROOT.iterdir() if p.is_dir())
    if not fights:
        raise SystemExit("No fight folders found under datasets/anomaly_test")

    total_anom = 0
    total = 0

    for fight_dir in fights:
        a, t = run_fight(fight_dir)
        total_anom += a
        total += t

    print("\n=== GLOBAL SUMMARY ===")
    print(f"Detected anomalies: {total_anom}/{total}")


if __name__ == "__main__":
    main()
