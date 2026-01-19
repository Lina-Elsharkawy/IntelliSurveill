import os
import shutil
from collections import defaultdict

import cv2
import numpy as np
from sklearn.datasets import fetch_lfw_people

# ==========================
# Paths (NO ABSOLUTE PATHS)
# ==========================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OUT_DIR = os.path.join(SCRIPT_DIR, "lfw_subset")
SKLEARN_DATA_DIR = os.path.join(SCRIPT_DIR, "sklearn_data")

# ==========================
# Dataset Settings
# ==========================
NUM_IDENTITIES = 20
ENROLL_PER_ID = 5
MIN_FACES_PER_PERSON = max(10, ENROLL_PER_ID)  # LFW requires enough images/person

# ==========================
# Load LFW (IMPORTANT: keep resize=1.0)
# ==========================
lfw = fetch_lfw_people(
    min_faces_per_person=MIN_FACES_PER_PERSON,
    resize=1.0,  # DO NOT upscale here
    color=True,
    data_home=SKLEARN_DATA_DIR
)

images = lfw.images          # float32 RGB in [0,1]
targets = lfw.target
names = lfw.target_names

# ==========================
# Group indexes by identity
# ==========================
by_id = defaultdict(list)
for i, t in enumerate(targets):
    by_id[int(t)].append(i)

eligible_ids = [pid for pid, idxs in by_id.items() if len(idxs) >= ENROLL_PER_ID]
eligible_ids = eligible_ids[:NUM_IDENTITIES]

if not eligible_ids:
    raise SystemExit("No eligible identities found. Try lowering MIN_FACES_PER_PERSON or ENROLL_PER_ID.")

# ==========================
# Prepare output folders
# ==========================
if os.path.exists(OUT_DIR):
    shutil.rmtree(OUT_DIR)

enroll_dir = os.path.join(OUT_DIR, "enroll")
os.makedirs(enroll_dir, exist_ok=True)

def save_img(path, img_float_rgb):
    """
    img_float_rgb: float32 RGB image in [0,1]
    Must multiply by 255 before converting to uint8.
    """
    img_uint8 = np.clip(img_float_rgb * 255.0, 0, 255).astype(np.uint8)
    img_bgr = cv2.cvtColor(img_uint8, cv2.COLOR_RGB2BGR)
    ok = cv2.imwrite(path, img_bgr)
    if not ok:
        raise RuntimeError(f"Failed to write image: {path}")

# ==========================
# Export enroll-only dataset
# ==========================
for pid in eligible_ids:
    person = names[pid].replace(" ", "_")
    idxs = by_id[pid][:ENROLL_PER_ID]

    p_enroll = os.path.join(enroll_dir, person)
    os.makedirs(p_enroll, exist_ok=True)

    for k, i in enumerate(idxs, 1):
        save_img(os.path.join(p_enroll, f"{person}_enroll_{k}.jpg"), images[i])

print("Done.")
print("Exported to:", OUT_DIR)
print("Identities:", len(eligible_ids))
print("Enroll per ID:", ENROLL_PER_ID)
print("Total images:", len(eligible_ids) * ENROLL_PER_ID)
