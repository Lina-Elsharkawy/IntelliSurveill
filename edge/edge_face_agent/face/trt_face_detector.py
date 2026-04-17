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


class SCRFDTensorRTDetector:
    TRT_LOGGER = None

    def __init__(
        self,
        engine_path: str,
        input_size=(640, 640),
        conf_thres=0.5,
        nms_thres=0.4,
        score_mode="auto",  # "auto", "raw", "sigmoid"
    ):
        if trt is None:
            raise RuntimeError("tensorrt Python package is not installed.")
        if cuda is None:
            raise RuntimeError("pycuda is required for TensorRT inference.")

        self.input_w = int(input_size[0])
        self.input_h = int(input_size[1])
        self.conf_thres = float(conf_thres)
        self.nms_thres = float(nms_thres)
        self.score_mode = str(score_mode).lower().strip()

        if self.score_mode not in ("auto", "raw", "sigmoid"):
            raise ValueError("score_mode must be one of: auto, raw, sigmoid")

        if SCRFDTensorRTDetector.TRT_LOGGER is None:
            SCRFDTensorRTDetector.TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

        with open(engine_path, "rb") as f, trt.Runtime(SCRFDTensorRTDetector.TRT_LOGGER) as runtime:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        if self.engine is None:
            raise RuntimeError(f"Failed to deserialize TensorRT engine: {engine_path}")

        self.context = self.engine.create_execution_context()
        if self.context is None:
            raise RuntimeError("Failed to create TensorRT execution context.")

        self.input_binding_idx = None
        self.output_binding_indices = []

        for i in range(self.engine.num_bindings):
            if self.engine.binding_is_input(i):
                self.input_binding_idx = i
            else:
                self.output_binding_indices.append(i)

        if self.input_binding_idx is None:
            raise RuntimeError("Could not find input binding.")
        if not self.output_binding_indices:
            raise RuntimeError("Could not find output bindings.")

        input_shape = tuple(self.engine.get_binding_shape(self.input_binding_idx))
        if input_shape[0] == -1 or input_shape[2] <= 1 or input_shape[3] <= 1:
            self.context.set_binding_shape(
                self.input_binding_idx, (1, 3, self.input_h, self.input_w)
            )

        self.input_shape = tuple(self.context.get_binding_shape(self.input_binding_idx))
        self.input_dtype = trt.nptype(self.engine.get_binding_dtype(self.input_binding_idx))

        self.output_shapes = []
        self.output_dtypes = []
        for out_idx in self.output_binding_indices:
            self.output_shapes.append(tuple(self.context.get_binding_shape(out_idx)))
            self.output_dtypes.append(trt.nptype(self.engine.get_binding_dtype(out_idx)))

        if len(self.output_shapes) != 9:
            raise RuntimeError(
                f"Expected 9 output bindings for SCRFD (3 levels x cls/bbox/kps), got {len(self.output_shapes)}"
            )

        self.host_input = cuda.pagelocked_empty(
            int(trt.volume(self.input_shape)), dtype=self.input_dtype
        )
        self.device_input = cuda.mem_alloc(self.host_input.nbytes)

        self.host_outputs = []
        self.device_outputs = []
        for shape, dtype in zip(self.output_shapes, self.output_dtypes):
            host = cuda.pagelocked_empty(int(trt.volume(shape)), dtype=dtype)
            dev = cuda.mem_alloc(host.nbytes)
            self.host_outputs.append(host)
            self.device_outputs.append(dev)

        self.bindings = [0] * self.engine.num_bindings
        self.bindings[self.input_binding_idx] = int(self.device_input)
        for out_idx, dev in zip(self.output_binding_indices, self.device_outputs):
            self.bindings[out_idx] = int(dev)

        self.stream = cuda.Stream()

        # SCRFD layout for your engine:
        # stride 8  -> 12800 anchors (80x80x2)
        # stride 16 -> 3200 anchors  (40x40x2)
        # stride 32 -> 800 anchors   (20x20x2)
        self.strides = [8, 16, 32]
        self.num_anchors = 2

    def _preprocess(self, frame_bgr: np.ndarray):
        orig_h, orig_w = frame_bgr.shape[:2]

        # Keep aspect ratio and paste at top-left into detector canvas
        im_ratio = float(orig_h) / float(orig_w)
        model_ratio = float(self.input_h) / float(self.input_w)

        if im_ratio > model_ratio:
            new_h = self.input_h
            new_w = int(new_h / im_ratio)
        else:
            new_w = self.input_w
            new_h = int(new_w * im_ratio)

        resized = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        det_img = np.zeros((self.input_h, self.input_w, 3), dtype=np.uint8)
        det_img[:new_h, :new_w, :] = resized

        rgb = cv2.cvtColor(det_img, cv2.COLOR_BGR2RGB).astype(np.float32)
        rgb = (rgb - 127.5) / 128.0

        x = np.transpose(rgb, (2, 0, 1))
        x = np.expand_dims(x, axis=0)
        x = np.ascontiguousarray(x, dtype=self.input_dtype)

        det_scale = float(new_h) / float(orig_h)
        return x, det_scale, orig_w, orig_h

    def _infer_raw(self, input_tensor: np.ndarray):
        np.copyto(self.host_input, input_tensor.ravel())

        cuda.memcpy_htod_async(self.device_input, self.host_input, self.stream)
        self.context.execute_async_v2(bindings=self.bindings, stream_handle=self.stream.handle)

        outputs = []
        for host, dev, shape in zip(self.host_outputs, self.device_outputs, self.output_shapes):
            cuda.memcpy_dtoh_async(host, dev, self.stream)
            outputs.append((host, shape))

        self.stream.synchronize()

        final_outputs = []
        for host, shape in outputs:
            final_outputs.append(host.reshape(shape))
        return final_outputs

    def _process_scores(self, scores: np.ndarray) -> np.ndarray:
        scores = scores.astype(np.float32).reshape(-1)

        if self.score_mode == "raw":
            return scores

        if self.score_mode == "sigmoid":
            return 1.0 / (1.0 + np.exp(-scores))

        # auto
        smin = float(scores.min()) if scores.size else 0.0
        smax = float(scores.max()) if scores.size else 0.0
        if smin < 0.0 or smax > 1.0:
            return 1.0 / (1.0 + np.exp(-scores))
        return scores

    def _make_anchor_centers(self, feat_h: int, feat_w: int, stride: int):
        centers = np.stack(np.mgrid[:feat_h, :feat_w][::-1], axis=-1).astype(np.float32)
        centers = (centers * stride).reshape((-1, 2))
        if self.num_anchors > 1:
            centers = np.repeat(centers, self.num_anchors, axis=0)
        return centers

    def _distance2bbox(self, centers, dists):
        x1 = centers[:, 0] - dists[:, 0]
        y1 = centers[:, 1] - dists[:, 1]
        x2 = centers[:, 0] + dists[:, 2]
        y2 = centers[:, 1] + dists[:, 3]
        return np.stack([x1, y1, x2, y2], axis=1)

    def _distance2kps(self, centers, kps_dists):
        kps = np.zeros((kps_dists.shape[0], 5, 2), dtype=np.float32)
        for i in range(5):
            kps[:, i, 0] = centers[:, 0] + kps_dists[:, 2 * i]
            kps[:, i, 1] = centers[:, 1] + kps_dists[:, 2 * i + 1]
        return kps

    def _nms(self, dets: np.ndarray, thresh: float):
        if dets.shape[0] == 0:
            return []

        x1 = dets[:, 0]
        y1 = dets[:, 1]
        x2 = dets[:, 2]
        y2 = dets[:, 3]
        scores = dets[:, 4]

        areas = np.maximum(0.0, x2 - x1 + 1) * np.maximum(0.0, y2 - y1 + 1)
        order = scores.argsort()[::-1]
        keep = []

        while order.size > 0:
            i = order[0]
            keep.append(i)

            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            union = areas[i] + areas[order[1:]] - inter
            iou = np.where(union > 0.0, inter / union, 0.0)

            inds = np.where(iou <= thresh)[0]
            order = order[inds + 1]

        return keep

    def detect(self, frame_bgr: np.ndarray, debug: bool = False):
        input_tensor, det_scale, orig_w, orig_h = self._preprocess(frame_bgr)
        outs = self._infer_raw(input_tensor)

        # Expected output layout:
        # [score8, bbox8, kps8, score16, bbox16, kps16, score32, bbox32, kps32]
        all_boxes = []
        all_scores = []
        all_kps = []

        feat_sizes = [
            (self.input_h // 8, self.input_w // 8),
            (self.input_h // 16, self.input_w // 16),
            (self.input_h // 32, self.input_w // 32),
        ]

        for level, stride in enumerate(self.strides):
            raw_scores = outs[level * 3 + 0].reshape(-1)
            scores = self._process_scores(raw_scores)

            bbox_preds = outs[level * 3 + 1].reshape(-1, 4).astype(np.float32) * stride
            kps_preds = outs[level * 3 + 2].reshape(-1, 10).astype(np.float32) * stride

            feat_h, feat_w = feat_sizes[level]
            centers = self._make_anchor_centers(feat_h, feat_w, stride)

            if debug:
                print(
                    "[stride={}] raw_score_min={:.6f} raw_score_max={:.6f} "
                    "score_min={:.6f} score_max={:.6f} score_mean={:.6f} "
                    "anchors={} bbox_shape={} kps_shape={}".format(
                        stride,
                        float(raw_scores.min()) if raw_scores.size else 0.0,
                        float(raw_scores.max()) if raw_scores.size else 0.0,
                        float(scores.min()) if scores.size else 0.0,
                        float(scores.max()) if scores.size else 0.0,
                        float(scores.mean()) if scores.size else 0.0,
                        len(centers),
                        bbox_preds.shape,
                        kps_preds.shape,
                    )
                )

            if len(centers) != len(scores):
                raise RuntimeError(
                    f"Anchor count mismatch at stride {stride}: "
                    f"{len(centers)} centers vs {len(scores)} scores"
                )

            keep = scores >= self.conf_thres
            if not np.any(keep):
                continue

            scores_kept = scores[keep]
            bbox_kept = bbox_preds[keep]
            kps_kept = kps_preds[keep]
            centers_kept = centers[keep]

            boxes = self._distance2bbox(centers_kept, bbox_kept)
            kps = self._distance2kps(centers_kept, kps_kept)

            boxes /= det_scale
            kps /= det_scale

            all_boxes.append(boxes)
            all_scores.append(scores_kept)
            all_kps.append(kps)

        if not all_boxes:
            return []

        boxes = np.concatenate(all_boxes, axis=0).astype(np.float32)
        scores = np.concatenate(all_scores, axis=0).astype(np.float32)
        kps = np.concatenate(all_kps, axis=0).astype(np.float32)

        boxes[:, 0] = np.clip(boxes[:, 0], 0, orig_w - 1)
        boxes[:, 1] = np.clip(boxes[:, 1], 0, orig_h - 1)
        boxes[:, 2] = np.clip(boxes[:, 2], 0, orig_w - 1)
        boxes[:, 3] = np.clip(boxes[:, 3], 0, orig_h - 1)

        kps[:, :, 0] = np.clip(kps[:, :, 0], 0, orig_w - 1)
        kps[:, :, 1] = np.clip(kps[:, :, 1], 0, orig_h - 1)

        dets = np.concatenate([boxes, scores[:, None]], axis=1)
        order = dets[:, 4].argsort()[::-1]
        dets = dets[order]
        kps = kps[order]

        keep = self._nms(dets, self.nms_thres)
        if len(keep) == 0:
            return []

        dets = dets[keep]
        kps = kps[keep]

        results = []
        for i in range(dets.shape[0]):
            results.append(
                {
                    "bbox_xyxy": dets[i, :4].astype(np.float32),
                    "score": float(dets[i, 4]),
                    "kps": kps[i].astype(np.float32),
                }
            )

        return results