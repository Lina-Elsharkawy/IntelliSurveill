import platform
import time
import cv2


def gstreamer_csi_pipeline(sensor_id: int, width: int, height: int, fps: int, flip_method: int = 0) -> str:
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM), width={width}, height={height}, framerate={fps}/1 ! "
        f"nvvidconv flip-method={flip_method} ! "
        f"video/x-raw, format=BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! "
        f"appsink drop=true sync=false max-buffers=1"
    )


class CameraSource:
    def __init__(self, cfg: dict):
        cam_cfg = cfg["camera"]
        self.type = str(cam_cfg["type"]).lower().strip()
        self.width = int(cam_cfg["width"])
        self.height = int(cam_cfg["height"])
        self.fps = int(cam_cfg["fps"])
        self.cap = None

        if self.type == "usb":
            idx = int(cam_cfg.get("device_index", 0))
            self.cap = self._open_usb(idx)

        elif self.type == "rtsp":
            url = cam_cfg["rtsp_url"]
            self.cap = cv2.VideoCapture(url)

        elif self.type == "csi":
            sensor_id = int(cam_cfg.get("sensor_id", 0))
            flip_method = int(cam_cfg.get("flip_method", 0))
            pipeline = gstreamer_csi_pipeline(sensor_id, self.width, self.height, self.fps, flip_method)
            self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        else:
            raise ValueError(f"Unknown camera.type={self.type}. Use usb/csi/rtsp")

        if self.cap is None or not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera source (type={self.type}).")

    def _open_usb(self, idx: int):
        if platform.system().lower().startswith("win"):
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

        return cap

    def frames(self):
        while True:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            ts_ms = int(time.time() * 1000)
            yield frame, ts_ms

    def release(self):
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass