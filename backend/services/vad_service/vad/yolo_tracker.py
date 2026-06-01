from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from .config import VadConfig
from .frame_types import TrackedPerson

log = logging.getLogger("vad.yolo_tracker")


class YoloPoseTracker:
    """Ultralytics YOLO pose/person tracker.

    Important parity rule from the live scripts:
    YOLO.track() is called on every decoded camera frame. Only the outputs that
    fall on the canonical 5 fps sample ticks are written into VAD route buffers.
    This avoids starving ByteTrack/BoT-SORT and reduces ID resets.
    """

    def __init__(self, cfg: VadConfig) -> None:
        self.cfg = cfg
        self.model = None
        self.loaded = False
        self.load_error: str | None = None

    def load(self) -> None:
        if self.loaded:
            return
        try:
            from ultralytics import YOLO

            model_path = str(self.cfg.detector_model)
            self.model = YOLO(model_path)
            self.loaded = True
            self.load_error = None
            log.info("Loaded YOLO tracker model: %s", model_path)
        except Exception as e:
            self.loaded = False
            self.load_error = str(e)
            raise

    @staticmethod
    def _to_numpy(value: Any) -> np.ndarray | None:
        if value is None:
            return None
        try:
            return value.detach().cpu().numpy()
        except Exception:
            try:
                return np.asarray(value)
            except Exception:
                return None

    def track_frame(self, frame_bgr: np.ndarray, *, source_frame_index: int) -> list[TrackedPerson]:
        self.load()
        assert self.model is not None

        results = self.model.track(
            source=frame_bgr,
            persist=True,
            tracker=self.cfg.tracker_config,
            conf=self.cfg.detector_conf,
            imgsz=self.cfg.detector_imgsz,
            device=self.cfg.detector_device,
            verbose=False,
        )
        if not results:
            return []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or getattr(boxes, "xyxy", None) is None:
            return []

        xyxy = self._to_numpy(boxes.xyxy)
        conf = self._to_numpy(getattr(boxes, "conf", None))
        cls = self._to_numpy(getattr(boxes, "cls", None))
        ids = self._to_numpy(getattr(boxes, "id", None))

        if xyxy is None or len(xyxy) == 0:
            return []

        kxy = None
        kconf = None
        keypoints = getattr(result, "keypoints", None)
        if keypoints is not None:
            kxy = self._to_numpy(getattr(keypoints, "xy", None))
            kconf = self._to_numpy(getattr(keypoints, "conf", None))

        people: list[TrackedPerson] = []
        h, w = frame_bgr.shape[:2]
        for i, box in enumerate(xyxy):
            # Keep person class only when class IDs are present. Pose models are usually class 0/person.
            class_id = int(cls[i]) if cls is not None and i < len(cls) else 0
            if class_id != 0:
                continue

            # For backend gate parity we require a stable tracker ID.
            if ids is None or i >= len(ids) or ids[i] is None or int(ids[i]) < 0:
                continue

            x1, y1, x2, y2 = [float(v) for v in box]
            x1 = max(0.0, min(float(w - 1), x1))
            y1 = max(0.0, min(float(h - 1), y1))
            x2 = max(0.0, min(float(w - 1), x2))
            y2 = max(0.0, min(float(h - 1), y2))
            if x2 <= x1 or y2 <= y1:
                continue

            kp_xy_list: list[list[float]] = []
            kp_conf_list: list[float] = []
            if kxy is not None and i < len(kxy):
                kp_xy_list = [[float(p[0]), float(p[1])] for p in kxy[i].tolist()]
            if kconf is not None and i < len(kconf):
                kp_conf_list = [float(c) for c in kconf[i].tolist()]

            people.append(
                TrackedPerson(
                    tracker_track_id=int(ids[i]),
                    bbox_xyxy=[x1, y1, x2, y2],
                    confidence=float(conf[i]) if conf is not None and i < len(conf) else None,
                    class_id=class_id,
                    class_name="person",
                    keypoints_xy=kp_xy_list,
                    keypoints_conf=kp_conf_list,
                    detector_metadata={
                        "source_frame_index": source_frame_index,
                        "detector_imgsz": self.cfg.detector_imgsz,
                        "tracker_config": self.cfg.tracker_config,
                    },
                )
            )

        return people
