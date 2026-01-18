import os
import shutil
from collections import defaultdict

from sklearn.datasets import fetch_lfw_people

# ==========================
# Settings (edit if you want)
# ==========================
OUT_DIR = r"D:\UNIVERSITY\Graduation Project\gp\Graduation-Project\edge\test\lfw_subset"
MIN_FACES_PER_PERSON = 10
NUM_IDENTITIES = 5
ENROLL_PER_ID = 2
TEST_PER_ID = 1

lfw = fetch_lfw_people(
    min_faces_per_person=MIN_FACES_PER_PERSON,
    resize=2.0,
    color=True,
    data_home=r"D:\UNIVERSITY\Graduation Project\gp\Graduation-Project\datasets\sklearn_data"
)


images = lfw.images          # shape: (N, H, W, 3) because color=True
targets = lfw.target         # person index per image
names = lfw.target_names     # person names

# Group indexes by identity
by_id = defaultdict(list)
for i, t in enumerate(targets):
    by_id[int(t)].append(i)

# Pick identities with enough images
eligible = [pid for pid, idxs in by_id.items() if len(idxs) >= (ENROLL_PER_ID + TEST_PER_ID)]
eligible = eligible[:NUM_IDENTITIES]

if not eligible:
    raise SystemExit("No eligible identities found. Try lowering MIN_FACES_PER_PERSON or counts.")

# Prepare output folders
if os.path.exists(OUT_DIR):
    shutil.rmtree(OUT_DIR)
os.makedirs(OUT_DIR, exist_ok=True)

enroll_dir = os.path.join(OUT_DIR, "enroll")
test_dir = os.path.join(OUT_DIR, "test")
os.makedirs(enroll_dir, exist_ok=True)
os.makedirs(test_dir, exist_ok=True)

# Save images as JPG (OpenCV expects BGR)
import cv2
import numpy as np

def save_img(path, img_rgb):
    img_bgr = cv2.cvtColor(img_rgb.astype(np.uint8), cv2.COLOR_RGB2BGR)
    cv2.imwrite(path, img_bgr)

# Export
for pid in eligible:
    person = names[pid].replace(" ", "_")
    idxs = by_id[pid]

    # deterministic split: first ENROLL are enroll, next TEST are test
    enroll_idxs = idxs[:ENROLL_PER_ID]
    test_idxs = idxs[ENROLL_PER_ID:ENROLL_PER_ID + TEST_PER_ID]

    p_enroll = os.path.join(enroll_dir, person)
    p_test = os.path.join(test_dir, person)
    os.makedirs(p_enroll, exist_ok=True)
    os.makedirs(p_test, exist_ok=True)

    for k, i in enumerate(enroll_idxs, 1):
        save_img(os.path.join(p_enroll, f"{person}_enroll_{k}.jpg"), images[i])

    for k, i in enumerate(test_idxs, 1):
        save_img(os.path.join(p_test, f"{person}_test_{k}.jpg"), images[i])

print("Done.")
print("Exported to:", OUT_DIR)
print("Identities:", [names[pid] for pid in eligible])
