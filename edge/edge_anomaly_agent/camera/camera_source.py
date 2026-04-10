import cv2
import time


def gstreamer_csi_pipeline(
    sensor_id:   int,
    width:       int,
    height:      int,
    fps:         int,
    flip_method: int = 0,
) -> str:
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM), width={width}, height={height}, "
        f"framerate={fps}/1 ! "
        f"nvvidconv flip-method={flip_method} ! "
        f"video/x-raw, format=BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! "
        f"appsink drop=true sync=false"
    )


class CameraSource:
    """
    Unified camera source supporting:
        - usb
        - csi
        - rtsp
        - url        (HTTP/MJPEG stream from laptop)
        - video_file

    Example config:

        camera:
          type: url
          stream_url: "http://192.168.137.1:5000/video_feed"
          width: 640
          height: 480
          fps: 10
    """

    def __init__(self, cfg: dict) -> None:
        cam_cfg     = cfg["camera"]
        self.type   = cam_cfg["type"].lower()
        self.width  = int(cam_cfg.get("width", 640))
        self.height = int(cam_cfg.get("height", 480))
        self.fps    = int(cam_cfg.get("fps", 10))

        if self.type == "usb":
            idx      = int(cam_cfg.get("device_index", 0))
            self.cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS,          self.fps)

        elif self.type == "rtsp":
            url      = cam_cfg["rtsp_url"]
            self.cap = cv2.VideoCapture(url)

        elif self.type == "url":
            url      = cam_cfg["stream_url"]
            self.cap = cv2.VideoCapture(url)

        elif self.type == "video_file":
            path     = cam_cfg["video_path"]
            self.cap = cv2.VideoCapture(path)

        elif self.type == "csi":
            sensor_id   = int(cam_cfg.get("sensor_id",   0))
            flip_method = int(cam_cfg.get("flip_method", 0))
            pipeline    = gstreamer_csi_pipeline(
                sensor_id, self.width, self.height, self.fps, flip_method
            )
            self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        else:
            raise ValueError(
                f"Unknown camera.type={self.type!r}. "
                f"Valid options: usb / csi / rtsp / url / video_file"
            )

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Failed to open camera (type={self.type}). "
                f"Check source path/URL/device and network connectivity."
            )

        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def frames(self):
        while True:
            ok = False
            frame = None

            # For live sources, try to drop stale buffered frames first
            if self.type in ("usb", "csi", "rtsp", "url"):
                try:
                    for _ in range(2):
                        self.cap.grab()
                    ok, frame = self.cap.retrieve()
                except Exception:
                    ok, frame = self.cap.read()
            else:
                ok, frame = self.cap.read()

            if not ok or frame is None:
                if self.type == "video_file":
                    # loop the file for convenience
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    time.sleep(0.05)
                    continue
                time.sleep(0.05)
                continue

            yield frame, int(time.time() * 1000)

    def release(self) -> None:
        try:
            self.cap.release()
        except Exception:
            pass