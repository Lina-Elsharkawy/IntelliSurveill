import base64
import logging
from typing import Optional, Tuple

import cv2
import numpy as np

try:
    import tensorrt as trt
except ImportError:
    trt = None

try:
    import pycuda.driver as cuda
    import pycuda.autoinit  # noqa: F401
except ImportError:
    cuda = None

from face.trt_face_detector import SCRFDTensorRTDetector


LOG = logging.getLogger("tensorrt_face_pipeline")


class ArcFaceTensorRTRecognizer:
    TRT_LOGGER = None

    def __init__(self, engine_path: str, input_size: int = 112):
        if trt is None:
            raise RuntimeError("tensorrt Python package is not installed.")
        if cuda is None:
            raise RuntimeError("pycuda is required for TensorRT inference.")

        self.input_size = int(input_size)

        if ArcFaceTensorRTRecognizer.TRT_LOGGER is None:
            ArcFaceTensorRTRecognizer.TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

        with open(engine_path, "rb") as f, trt.Runtime(ArcFaceTensorRTRecognizer.TRT_LOGGER) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        if self.engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Failed to create TensorRT execution context for ArcFace.")

        self.input_binding_idx = None
        self.output_binding_indices = []

        for i in range(self.engine.num_bindings):
            if self.engine.binding_is_input(i):
                self.input_binding_idx = i
            else:
                self.output_binding_indices.append(i)

        if self.input_binding_idx is None:
            raise RuntimeError("Could not find ArcFace input binding.")
        if len(self.output_binding_indices) != 1:
            raise RuntimeError(
                f"ArcFace engine should have exactly 1 output binding, got {len(self.output_binding_indices)}"
            )

        input_shape = tuple(self.engine.get_binding_shape(self.input_binding_idx))
        if input_shape[0] == -1 or input_shape[2] <= 1 or input_shape[3] <= 1:
            self.context.set_binding_shape(
                self.input_binding_idx, (1, 3, self.input_size, self.input_size)
            )

        self.input_shape = tuple(self.context.get_binding_shape(self.input_binding_idx))
        self.input_dtype = trt.nptype(self.engine.get_binding_dtype(self.input_binding_idx))

        self.output_binding_idx = self.output_binding_indices[0]
        self.output_shape = tuple(self.context.get_binding_shape(self.output_binding_idx))
        self.output_dtype = trt.nptype(self.engine.get_binding_dtype(self.output_binding_idx))

        self.host_input = cuda.pagelocked_empty(
            int(trt.volume(self.input_shape)), dtype=self.input_dtype
        )
        self.device_input = cuda.mem_alloc(self.host_input.nbytes)

        self.host_output = cuda.pagelocked_empty(
            int(trt.volume(self.output_shape)), dtype=self.output_dtype
        )
        self.device_output = cuda.mem_alloc(self.host_output.nbytes)

        self.bindings = [0] * self.engine.num_bindings
        self.bindings[self.input_binding_idx] = int(self.device_input)
        self.bindings[self.output_binding_idx] = int(self.device_output)

        self.stream = cuda.Stream()

        LOG.info(
            "ArcFace TensorRT recognizer ready. input_shape=%s output_shape=%s",
            self.input_shape,
            self.output_shape,
        )

    def _preprocess(self, face_bgr: np.ndarray) -> np.ndarray:
        face = cv2.resize(
            face_bgr,
            (self.input_size, self.input_size),
            interpolation=cv2.INTER_LINEAR,
        )
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32)

        # ArcFace normalization
        face = (face - 127.5) / 127.5

        x = np.transpose(face, (2, 0, 1))
        x = np.expand_dims(x, axis=0)
        x = np.ascontiguousarray(x, dtype=self.input_dtype)
        return x

    def get_embedding(self, face_bgr: np.ndarray) -> Optional[np.ndarray]:
        if face_bgr is None or face_bgr.size == 0:
            return None

        x = self._preprocess(face_bgr)
        np.copyto(self.host_input, x.ravel())

        cuda.memcpy_htod_async(self.device_input, self.host_input, self.stream)
        self.context.execute_async_v2(bindings=self.bindings, stream_handle=self.stream.handle)
        cuda.memcpy_dtoh_async(self.host_output, self.device_output, self.stream)
        self.stream.synchronize()

        emb = self.host_output.reshape(self.output_shape).astype(np.float32).reshape(-1)
        if emb.size == 0:
            return None

        norm = float(np.linalg.norm(emb))
        if norm > 0.0:
            emb = emb / norm

        return emb.astype(np.float32)


class TensorRTFacePipeline:
    """
    Jetson deployment replacement for the laptop InsightFace pipeline.

    Expected config.yaml face section:
      face:
        det_size: [640, 640]
        face_img_size: 160
        jpeg_quality: 80
        min_face_size: 40
        min_det_score: 0.35
        nms_thres: 0.4
        use_kps_alignment: true
        det_engine_path: /opt/face_app/models/scrfd_10g_bnkps.engine
        rec_engine_path: /opt/face_app/models/w600k_r50_fp16.engine
        rec_input_size: 112
        det_score_mode: auto
    """

    ARC_TEMPLATE = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float32,
    )

    def __init__(self, cfg: dict):
        fcfg = cfg["face"]

        self.det_size = tuple(fcfg.get("det_size", [640, 640]))
        self.face_img_size = int(fcfg.get("face_img_size", 160))
        self.jpeg_quality = int(fcfg.get("jpeg_quality", 80))
        self.min_face_size = int(fcfg.get("min_face_size", 40))
        self.min_det_score = float(fcfg.get("min_det_score", 0.45))
        self.nms_thres = float(fcfg.get("nms_thres", 0.4))
        self.use_kps_alignment = bool(fcfg.get("use_kps_alignment", True))

        self.det_engine_path = str(fcfg["det_engine_path"])
        self.rec_engine_path = str(fcfg["rec_engine_path"])
        self.rec_input_size = int(fcfg.get("rec_input_size", 112))
        self.det_score_mode = str(fcfg.get("det_score_mode", "auto")).lower().strip()

        self.detector = SCRFDTensorRTDetector(
            engine_path=self.det_engine_path,
            input_size=self.det_size,
            conf_thres=self.min_det_score,
            nms_thres=self.nms_thres,
            score_mode=self.det_score_mode,
        )

        self.recognizer = ArcFaceTensorRTRecognizer(
            engine_path=self.rec_engine_path,
            input_size=self.rec_input_size,
        )

        LOG.info(
            "TensorRTFacePipeline initialized. det_engine=%s rec_engine=%s det_size=%s rec_input=%s",
            self.det_engine_path,
            self.rec_engine_path,
            self.det_size,
            self.rec_input_size,
        )

    def infer(self, frame_bgr: np.ndarray):
        detections = self.detector.detect(frame_bgr)
        out = []

        for det in detections:
            bbox = det["bbox_xyxy"].astype(np.float32)
            score = float(det["score"])
            kps = det.get("kps", None)

            x1, y1, x2, y2 = self._sanitize_bbox(frame_bgr, bbox)
            box_w = max(0, x2 - x1)
            box_h = max(0, y2 - y1)
            face_size = min(box_w, box_h)

            if face_size < self.min_face_size:
                continue
            if score < self.min_det_score:
                continue

            face_for_rec = self._extract_face_for_recognition(frame_bgr, (x1, y1, x2, y2), kps)
            if face_for_rec is None or face_for_rec.size == 0:
                continue

            emb = self.recognizer.get_embedding(face_for_rec)
            if emb is None:
                continue

            face_b64 = self._crop_face_b64(frame_bgr, (x1, y1, x2, y2))
            if not face_b64:
                continue

            out.append(
                {
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "embedding": emb.astype(np.float32).tolist(),
                    "face_jpeg_b64": face_b64,
                    "quality_score": score,
                    "face_size": int(face_size),
                }
            )

        return out

    def _sanitize_bbox(self, frame_bgr: np.ndarray, bbox_xyxy) -> Tuple[int, int, int, int]:
        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = [int(round(v)) for v in bbox_xyxy]

        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        return x1, y1, x2, y2

    def _extract_face_for_recognition(
        self,
        frame_bgr: np.ndarray,
        bbox_xyxy: Tuple[int, int, int, int],
        kps: Optional[np.ndarray],
    ) -> Optional[np.ndarray]:
        if self.use_kps_alignment and kps is not None:
            aligned = self._align_face(frame_bgr, kps)
            if aligned is not None and aligned.size > 0:
                return aligned

        x1, y1, x2, y2 = bbox_xyxy
        if x2 <= x1 or y2 <= y1:
            return None

        face = frame_bgr[y1:y2, x1:x2]
        if face.size == 0:
            return None

        face = cv2.resize(
            face,
            (self.rec_input_size, self.rec_input_size),
            interpolation=cv2.INTER_LINEAR,
        )
        return face

    def _align_face(self, frame_bgr: np.ndarray, kps: np.ndarray) -> Optional[np.ndarray]:
        try:
            src = np.asarray(kps, dtype=np.float32).reshape(5, 2)
        except Exception:
            return None

        if src.shape != (5, 2):
            return None

        dst = self.ARC_TEMPLATE.copy()
        if self.rec_input_size != 112:
            scale = self.rec_input_size / 112.0
            dst *= scale

        M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
        if M is None:
            return None

        aligned = cv2.warpAffine(
            frame_bgr,
            M,
            (self.rec_input_size, self.rec_input_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        return aligned

    def _crop_face_b64(self, frame_bgr: np.ndarray, bbox_xyxy: Tuple[int, int, int, int]) -> str:
        x1, y1, x2, y2 = bbox_xyxy
        h, w = frame_bgr.shape[:2]

        x1 = max(0, min(x1, w - 1))
        x2 = max(0, min(x2, w - 1))
        y1 = max(0, min(y1, h - 1))
        y2 = max(0, min(y2, h - 1))

        if x2 <= x1 or y2 <= y1:
            return ""

        face = frame_bgr[y1:y2, x1:x2]
        if face.size == 0:
            return ""

        face = cv2.resize(
            face,
            (self.face_img_size, self.face_img_size),
            interpolation=cv2.INTER_AREA,
        )

        ok, buf = cv2.imencode(
            ".jpg",
            face,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            return ""

        return base64.b64encode(buf.tobytes()).decode("ascii")