import cv2

for idx in range(4):
    cap = cv2.VideoCapture(idx)
    ok = cap.isOpened()
    print(f"Index {idx}: opened={ok}")

    if ok:
        ret, frame = cap.read()
        print(f"  read={ret}, shape={None if frame is None else frame.shape}")
        cap.release()