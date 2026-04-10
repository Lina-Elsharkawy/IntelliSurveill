import argparse
import time
from flask import Flask, Response
import cv2

app = Flask(__name__)
cap = None
jpeg_quality = 80
target_width = 640
target_height = 480
target_fps = 10


def generate():
    global cap
    frame_interval = 1.0 / max(target_fps, 1)

    while True:
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue

        if target_width > 0 and target_height > 0:
            frame = cv2.resize(frame, (target_width, target_height))

        ok, buf = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
        )
        if not ok:
            continue

        jpg = buf.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
        )

        elapsed = time.time() - t0
        sleep_for = frame_interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


def main():
    global cap, jpeg_quality, target_width, target_height, target_fps

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--quality", type=int, default=80)
    args = parser.parse_args()

    target_width = args.width
    target_height = args.height
    target_fps = args.fps
    jpeg_quality = args.quality

    cap = cv2.VideoCapture(args.device, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, args.fps)

    if not cap.isOpened():
        raise RuntimeError("Failed to open laptop webcam.")

    print(f"Serving webcam at http://{args.host}:{args.port}/video_feed")
    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()