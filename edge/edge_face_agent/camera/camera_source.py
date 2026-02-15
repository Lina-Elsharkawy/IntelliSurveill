import cv2
import time

def gstreamer_csi_pipeline(sensor_id: int, width: int, height: int, fps: int, flip_method: int = 0) -> str:
    """
    Jetson CSI camera pipeline using nvarguscamerasrc (Argus).
    Works with IMX477/IMX219 CSI cameras when drivers are available via JetPack.
    """
    return (
        f"nvarguscamerasrc sensor-id={sensor_id} ! "
        f"video/x-raw(memory:NVMM), width={width}, height={height}, framerate={fps}/1 ! "
        f"nvvidconv flip-method={flip_method} ! "
        f"video/x-raw, format=BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=BGR ! "
        f"appsink drop=true sync=false"
    )

class CameraSource:
    def __init__(self, cfg: dict):
        cam_cfg = cfg["camera"]
        self.type = cam_cfg["type"].lower()
        self.width = int(cam_cfg["width"])
        self.height = int(cam_cfg["height"])
        self.fps = int(cam_cfg["fps"])

        if self.type == "usb":
            idx = int(cam_cfg.get("device_index", 0))
            self.cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

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

        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera source (type={self.type}).")

    def frames(self):
        while True:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            ts_ms = int(time.time() * 1000)
            yield frame, ts_ms

    def release(self):
        try:
            self.cap.release()
        except Exception:
            pass
