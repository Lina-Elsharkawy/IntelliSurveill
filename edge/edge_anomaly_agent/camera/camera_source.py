import cv2
import time


def gstreamer_csi_pipeline(
    sensor_id:   int,
    width:       int,
    height:      int,
    fps:         int,
    flip_method: int = 0,
) -> str:
    """
    Build a GStreamer pipeline string for Jetson CSI cameras via nvarguscamerasrc.

    Compatible with:
        - Arducam 8MP V2.3  (IMX219) — recommended for anomaly detection (wide FOV)
        - Arducam 12.3MP    (IMX477) — recommended for face recognition (high detail)

    Requires JetPack with Argus camera drivers installed.

    Args:
        sensor_id   : CSI sensor index (0 or 1 for dual-camera setups)
        width       : capture width in pixels
        height      : capture height in pixels
        fps         : frames per second
        flip_method : nvvidconv flip (0=none, 2=180deg, etc.)

    Returns:
        GStreamer pipeline string for cv2.VideoCapture
    """
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
    Unified camera source supporting USB, CSI (Jetson), and RTSP streams.

    Configuration is read from the 'camera' section of config.yaml:

        camera:
          type: csi          # usb / csi / rtsp
          width: 640
          height: 480
          fps: 10
          sensor_id: 0       # CSI only
          flip_method: 0     # CSI only
          device_index: 0    # USB only
          rtsp_url: "..."    # RTSP only
    """

    def __init__(self, cfg: dict) -> None:
        cam_cfg     = cfg["camera"]
        self.type   = cam_cfg["type"].lower()
        self.width  = int(cam_cfg["width"])
        self.height = int(cam_cfg["height"])
        self.fps    = int(cam_cfg["fps"])

        if self.type == "usb":
            idx      = int(cam_cfg.get("device_index", 0))
            self.cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS,          self.fps)

        elif self.type == "rtsp":
            url      = cam_cfg["rtsp_url"]
            self.cap = cv2.VideoCapture(url)

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
                f"Valid options: usb / csi / rtsp"
            )

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Failed to open camera (type={self.type}). "
                f"Check sensor connection and JetPack drivers."
            )

    def frames(self):
        """
        Yield (frame_bgr, timestamp_ms) indefinitely.

        frame_bgr    : numpy array [H, W, 3] in BGR format
        timestamp_ms : Unix timestamp in milliseconds at time of capture
        """
        while True:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            yield frame, int(time.time() * 1000)

    def release(self) -> None:
        """Release the camera resource."""
        try:
            self.cap.release()
        except Exception:
            pass