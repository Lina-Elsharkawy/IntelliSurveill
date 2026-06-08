from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from .config import VadConfig
from .db import VadDB
from .deep_gate import DeepGate
from .evidence_writer import EvidenceWriter
from .frame_types import PerTrackRouteBuffers, SampledPerson, TrackedPerson
from .homography_features import MacroSample
from .homography_gate import HomographyMacroGate
from .minio_client import VadMinioClient
from .pose_gate import PoseGate
from .reasoning_jobs import queue_deep_reasoning_job, queue_pose_reasoning_job, queue_cofire_reasoning_job
from .tubelet_buffer import TrackTubeletBuffer
from .yolo_tracker import YoloPoseTracker

log = logging.getLogger("vad.rtsp_sampler")


@dataclass
class BufferedFrame:
    frame_id: int | None
    sample_index: int
    source_frame_index: int
    captured_at: datetime
    frame_bgr: np.ndarray
    used_by_pose: bool
    used_by_deep: bool
    used_by_homography_macro: bool
    tracked_person_count: int


class VadRtspSampler:
    """Backend-direct RTSP sampler with shared YOLO tracking backbone.

    Current slice:
    - open RTSP directly;
    - run YOLO.track() on every decoded camera frame;
    - sample the tracked outputs into one canonical 5 fps VAD timeline;
    - write sampled frames, vad_tracks, and vad_detections;
    - maintain per-track route buffers in RAM for later gates.

    No gate scoring, tubelet creation, evidence saving, or reasoning yet.
    """

    def __init__(self, cfg: VadConfig, db: VadDB) -> None:
        self.cfg = cfg
        self.db = db
        self.tracker = YoloPoseTracker(cfg) if cfg.tracking_enabled else None
        self.pose_gate = PoseGate(cfg) if cfg.pose_gate_enabled else None
        self.deep_gate = DeepGate(cfg) if cfg.deep_gate_enabled else None
        self.homography_macro_gate = HomographyMacroGate(cfg) if cfg.homography_macro_gate_enabled else None
        self.minio_client = VadMinioClient(cfg) if cfg.evidence_enabled else None
        self.evidence_writer = EvidenceWriter(cfg, db, self.minio_client) if self.minio_client else None

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self.stream_id: int | None = None
        self.session_id: int | None = None

        self.sample_index = 0
        self.source_frame_index = 0
        self.dropped_frame_count = 0
        self.reconnect_count = 0
        self.processed_frame_count = 0
        self.tracker_frame_count = 0
        self.detection_count = 0
        self.tracked_detection_count = 0
        self.untracked_detection_count = 0
        self.pose_tubelet_count = 0
        self.pose_score_count = 0
        self.pose_persistent_count = 0
        self.deep_tubelet_count = 0
        self.deep_score_count = 0
        self.deep_persistent_count = 0
        self.homography_macro_tubelet_count = 0
        self.homography_macro_score_count = 0
        self.homography_macro_persistent_count = 0
        self.gate_event_count = 0
        self.evidence_object_count = 0
        self.evidence_item_count = 0
        self.deep_reasoning_job_count = 0
        self._gate_active_persistent: dict[tuple[str, int], bool] = {}
        self._gate_last_event_monotonic: dict[tuple[str, int], float] = {}
        self.started_monotonic: float | None = None
        self.last_error: str | None = None
        self.last_debug_path: str | None = None

        self.buffer: deque[BufferedFrame] = deque(maxlen=self.cfg.rolling_buffer_max_frames)
        self.track_buffers: dict[int, PerTrackRouteBuffers] = {}
        self.pose_tubelet_buffers: dict[int, TrackTubeletBuffer[SampledPerson]] = {}
        self.deep_tubelet_buffers: dict[int, TrackTubeletBuffer[SampledPerson]] = {}
        self.homography_macro_tubelet_buffers: dict[int, TrackTubeletBuffer[MacroSample]] = {}
        self.pose_gate_model_version_id: int | None = None
        self.pose_threshold_id: int | None = None
        self.pose_threshold_percentile: float | None = None
        self.deep_gate_model_version_id: int | None = None
        self.deep_threshold_id: int | None = None
        self.deep_threshold_percentile: float | None = None
        self.homography_macro_gate_model_version_id: int | None = None
        self.homography_macro_threshold_id: int | None = None
        self.homography_macro_threshold_percentile: float | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self.is_running:
                return self.status()

            if not self.cfg.backend_direct_enabled:
                raise RuntimeError("VAD_BACKEND_DIRECT_ENABLED is disabled")
            if not self.cfg.rtsp_url:
                raise RuntimeError(f"RTSP URL missing. Set {self.cfg.rtsp_url_env_var} in backend/.env")

            self._stop_event.clear()
            self.last_error = None
            self.sample_index = 0
            self.source_frame_index = 0
            self.dropped_frame_count = 0
            self.reconnect_count = 0
            self.processed_frame_count = 0
            self.tracker_frame_count = 0
            self.detection_count = 0
            self.tracked_detection_count = 0
            self.untracked_detection_count = 0
            self.pose_tubelet_count = 0
            self.pose_score_count = 0
            self.pose_persistent_count = 0
            self.deep_tubelet_count = 0
            self.deep_score_count = 0
            self.deep_persistent_count = 0
            self.homography_macro_tubelet_count = 0
            self.homography_macro_score_count = 0
            self.homography_macro_persistent_count = 0
            self.gate_event_count = 0
            self.evidence_object_count = 0
            self.evidence_item_count = 0
            self.deep_reasoning_job_count = 0
            self._gate_active_persistent.clear()
            self._gate_last_event_monotonic.clear()
            self.started_monotonic = time.monotonic()
            self.buffer.clear()
            self.track_buffers.clear()
            self.pose_tubelet_buffers.clear()
            self.deep_tubelet_buffers.clear()
            self.homography_macro_tubelet_buffers.clear()

            with self.db.connect() as conn:
                with conn.transaction():
                    self.stream_id = self.db.upsert_stream(conn, self.cfg)
                    self.session_id = self.db.start_stream_session(conn, stream_id=self.stream_id, cfg=self.cfg)
                    pose_model = self.db.get_active_gate_model_version(conn, gate_name="pose") if self.cfg.pose_gate_enabled else None
                    self.pose_gate_model_version_id = int(pose_model["id"]) if pose_model else None
                    pose_threshold = self.db.get_primary_gate_threshold(conn, gate_model_version_id=self.pose_gate_model_version_id) if self.pose_gate_model_version_id else None
                    self.pose_threshold_id = int(pose_threshold["id"]) if pose_threshold else None
                    self.pose_threshold_percentile = float(pose_threshold["threshold_percentile"]) if pose_threshold and pose_threshold.get("threshold_percentile") is not None else 99.5

                    deep_model = self.db.get_active_gate_model_version(conn, gate_name="deep") if self.cfg.deep_gate_enabled else None
                    self.deep_gate_model_version_id = int(deep_model["id"]) if deep_model else None
                    deep_threshold = self.db.get_primary_gate_threshold(conn, gate_model_version_id=self.deep_gate_model_version_id) if self.deep_gate_model_version_id else None
                    self.deep_threshold_id = int(deep_threshold["id"]) if deep_threshold else None
                    self.deep_threshold_percentile = float(deep_threshold["threshold_percentile"]) if deep_threshold and deep_threshold.get("threshold_percentile") is not None else 99.5

                    macro_model = self.db.get_active_gate_model_version(conn, gate_name="homography_macro") if self.cfg.homography_macro_gate_enabled else None
                    self.homography_macro_gate_model_version_id = int(macro_model["id"]) if macro_model else None
                    macro_threshold = self.db.get_primary_gate_threshold(conn, gate_model_version_id=self.homography_macro_gate_model_version_id) if self.homography_macro_gate_model_version_id else None
                    self.homography_macro_threshold_id = int(macro_threshold["id"]) if macro_threshold else None
                    self.homography_macro_threshold_percentile = float(macro_threshold["threshold_percentile"]) if macro_threshold and macro_threshold.get("threshold_percentile") is not None else 99.5

            self._thread = threading.Thread(target=self._run_loop, name="vad-rtsp-sampler", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._thread:
                return self.status()
            self._stop_event.set()
            thread = self._thread

        thread.join(timeout=10.0)

        with self._lock:
            if self.session_id is not None:
                try:
                    with self.db.connect() as conn:
                        with conn.transaction():
                            self.db.stop_session(conn, session_id=self.session_id, status="stopped")
                except Exception as e:
                    log.warning("Could not mark VAD session stopped: %s", e)
            self._thread = None

        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = max(0.001, time.monotonic() - self.started_monotonic) if self.started_monotonic else 0.0
            actual_fps = (self.sample_index / elapsed) if elapsed else 0.0
            latest = self.buffer[-1] if self.buffer else None
            active_buffers = [b.public_status() for b in self.track_buffers.values()]
            return {
                "running": self.is_running,
                "stream_id": self.stream_id,
                "session_id": self.session_id,
                "stream_key": self.cfg.stream_key,
                "camera_key": self.cfg.camera_key,
                "camera_id": self.cfg.camera_id,
                "target_sample_fps": self.cfg.target_sample_fps,
                "actual_sample_fps": round(actual_fps, 3),
                "sampled_frame_count": self.sample_index,
                "source_frame_count": self.source_frame_index,
                "processed_frame_count": self.processed_frame_count,
                "tracker_frame_count": self.tracker_frame_count,
                "detection_count": self.detection_count,
                "tracked_detection_count": self.tracked_detection_count,
                "untracked_detection_count": self.untracked_detection_count,
                "active_track_buffer_count": len(self.track_buffers),
                "track_buffers_preview": active_buffers[:10],
                "dropped_frame_count": self.dropped_frame_count,
                "reconnect_count": self.reconnect_count,
                "rolling_buffer_sec": self.cfg.rolling_buffer_sec,
                "rolling_buffer_max_frames": self.cfg.rolling_buffer_max_frames,
                "buffer_frame_count": len(self.buffer),
                "latest_sample_index": latest.sample_index if latest else None,
                "latest_frame_id": latest.frame_id if latest else None,
                "latest_source_frame_index": latest.source_frame_index if latest else None,
                "latest_captured_at": latest.captured_at.isoformat() if latest else None,
                "last_error": self.last_error,
                "last_debug_path": self.last_debug_path,
                "tracking_enabled": self.cfg.tracking_enabled,
                "tracker_loaded": bool(self.tracker and self.tracker.loaded),
                "tracker_load_error": self.tracker.load_error if self.tracker else None,
                "pose_gate_enabled": self.cfg.pose_gate_enabled,
                "pose_gate_loaded": bool(self.pose_gate and self.pose_gate.loaded),
                "pose_gate_load_error": self.pose_gate.load_error if self.pose_gate else None,
                "pose_tubelet_count": self.pose_tubelet_count,
                "pose_score_count": self.pose_score_count,
                "pose_persistent_count": self.pose_persistent_count,
                "deep_gate_enabled": self.cfg.deep_gate_enabled,
                "deep_gate_loaded": bool(self.deep_gate and self.deep_gate.loaded),
                "deep_gate_load_error": self.deep_gate.load_error if self.deep_gate else None,
                "deep_tubelet_count": self.deep_tubelet_count,
                "deep_score_count": self.deep_score_count,
                "deep_persistent_count": self.deep_persistent_count,
                "homography_macro_gate_enabled": self.cfg.homography_macro_gate_enabled,
                "homography_macro_gate_loaded": bool(self.homography_macro_gate and self.homography_macro_gate.loaded),
                "homography_macro_gate_load_error": self.homography_macro_gate.load_error if self.homography_macro_gate else None,
                "homography_macro_tubelet_count": self.homography_macro_tubelet_count,
                "homography_macro_score_count": self.homography_macro_score_count,
                "homography_macro_persistent_count": self.homography_macro_persistent_count,
                "evidence_enabled": self.cfg.evidence_enabled,
                "minio_bucket": self.cfg.minio_bucket,
                "gate_event_count": self.gate_event_count,
                "evidence_object_count": self.evidence_object_count,
                "evidence_item_count": self.evidence_item_count,
                "deep_reasoning_enabled": self.cfg.deep_reasoning_enabled,
                "deep_reasoning_job_count": self.deep_reasoning_job_count,
            }

    def save_latest_debug_frame(self) -> dict[str, Any]:
        with self._lock:
            if not self.buffer:
                raise RuntimeError("No buffered frames available yet")
            item = self.buffer[-1]
            frame = item.frame_bgr.copy()

        ts = item.captured_at.strftime("%Y%m%d_%H%M%S_%f")
        out_path = self.cfg.debug_save_dir / f"vad_latest_{self.cfg.stream_key}_{item.sample_index}_{ts}.jpg"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.cfg.jpeg_quality])
        if not ok:
            raise RuntimeError(f"cv2.imwrite failed for {out_path}")

        with self._lock:
            self.last_debug_path = str(out_path)

        return {
            "saved": True,
            "path": str(out_path),
            "sample_index": item.sample_index,
            "frame_id": item.frame_id,
            "tracked_person_count": item.tracked_person_count,
            "captured_at": item.captured_at.isoformat(),
        }

    def _open_capture(self) -> cv2.VideoCapture:
        cap = cv2.VideoCapture(self.cfg.rtsp_url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _route_step_samples(self, route_fps: float) -> int:
        # Convert a route fps to canonical sample ticks. Example: target 5 fps, route 2.5 fps => every 2 ticks.
        try:
            return max(1, int(round(float(self.cfg.target_sample_fps) / max(float(route_fps), 1e-6))))
        except Exception:
            return 1

    def _route_flags(self, sample_index: int) -> tuple[bool, bool, bool]:
        # Unified canonical timeline. Each gate consumes only the ticks matching its calibrated route fps.
        pose_step = self._route_step_samples(self.cfg.pose_route_fps)
        deep_step = self._route_step_samples(self.cfg.deep_route_fps)
        macro_step = self._route_step_samples(self.cfg.homography_macro_route_fps)
        used_by_pose = (sample_index % pose_step == 0)
        used_by_deep = (sample_index % deep_step == 0)
        used_by_homography_macro = (sample_index % macro_step == 0)
        return used_by_pose, used_by_deep, used_by_homography_macro

    def _run_tracker(self, frame: np.ndarray, source_frame_index: int) -> list[TrackedPerson]:
        if not self.tracker:
            return []
        people = self.tracker.track_frame(frame, source_frame_index=source_frame_index)
        with self._lock:
            self.tracker_frame_count += 1
        return people

    def _append_route_buffers(
        self,
        *,
        frame_id: int,
        sample_index: int,
        captured_at: datetime,
        frame_bgr: np.ndarray,
        used_by_pose: bool,
        used_by_deep: bool,
        used_by_homography_macro: bool,
        sampled_people: list[tuple[TrackedPerson, int | None, int | None]],
    ) -> None:
        with self._lock:
            for person, db_track_id, detection_id in sampled_people:
                buf = self.track_buffers.get(person.tracker_track_id)
                if buf is None:
                    buf = PerTrackRouteBuffers(tracker_track_id=person.tracker_track_id, db_track_id=db_track_id)
                    self.track_buffers[person.tracker_track_id] = buf
                sampled_person = SampledPerson(
                    frame_id=frame_id,
                    detection_id=detection_id,
                    db_track_id=db_track_id,
                    tracker_track_id=person.tracker_track_id,
                    sample_index=sample_index,
                    captured_at=captured_at,
                    frame_bgr=frame_bgr.copy(),
                    bbox_xyxy=person.bbox_xyxy,
                    confidence=person.confidence,
                    keypoints_xy=person.keypoints_xy,
                    keypoints_conf=person.keypoints_conf,
                )
                buf.add(
                    sampled_person,
                    used_by_pose=used_by_pose,
                    used_by_deep=used_by_deep,
                    used_by_homography_macro=used_by_homography_macro,
                )
                if used_by_pose and self.cfg.pose_gate_enabled:
                    self._maybe_score_pose_tubelet(sampled_person)
                if used_by_deep and self.cfg.deep_gate_enabled:
                    self._maybe_score_deep_tubelet(sampled_person)
                if used_by_homography_macro and self.cfg.homography_macro_gate_enabled:
                    self._maybe_score_homography_macro_tubelet(sampled_person)

            # Prune very stale in-memory buffers.
            stale = [
                tid for tid, buf in self.track_buffers.items()
                if sample_index - buf.last_seen_sample_index > self.cfg.track_buffer_max_age_samples
            ]
            for tid in stale:
                self.track_buffers.pop(tid, None)


    def _min_event_gap_for_gate(self, gate_name: str) -> float:
        if gate_name == "pose":
            return float(self.cfg.pose_min_event_gap_sec)
        if gate_name == "deep":
            return float(self.cfg.deep_min_event_gap_sec)
        if gate_name == "homography_macro":
            return float(self.cfg.homography_macro_min_event_gap_sec)
        return 5.0

    @staticmethod
    def _severity_for_gate(gate_name: str) -> str:
        if gate_name == "deep":
            return "medium"
        return "low"

    @staticmethod
    def _event_type_for_gate(gate_name: str) -> str:
        return {
            "pose": "rare_pose_articulation",
            "deep": "deep_semantic_spatiotemporal_anomaly",
            "homography_macro": "rare_macro_floor_motion",
        }.get(gate_name, "other")

    def _should_emit_gate_event(self, *, gate_name: str, tracker_track_id: int, persistent: bool) -> tuple[bool, dict[str, Any]]:
        key = (gate_name, int(tracker_track_id))
        was_active = bool(self._gate_active_persistent.get(key, False))
        rising_edge = bool(persistent and not was_active)
        now_mono = time.monotonic()
        min_gap = self._min_event_gap_for_gate(gate_name)
        last_event = self._gate_last_event_monotonic.get(key, -1e18)
        seconds_since_last = float(now_mono - last_event)
        cooldown_ok = bool(seconds_since_last >= min_gap)
        emit = bool(rising_edge and cooldown_ok)
        self._gate_active_persistent[key] = bool(persistent)
        if emit:
            self._gate_last_event_monotonic[key] = now_mono
        return emit, {
            "event_policy": "persistent_rising_edge_with_per_track_cooldown",
            "persistent_rising_edge": rising_edge,
            "cooldown_ok": cooldown_ok,
            "seconds_since_last_event": seconds_since_last,
            "min_event_gap_sec": min_gap,
            "previous_persistent": was_active,
        }

    def _create_gate_event_case_and_evidence(
        self,
        conn,
        *,
        gate_name: str,
        tubelet_id: int,
        score_id: int,
        sample: SampledPerson,
        tubelet_samples: list[SampledPerson],
        gate_out: Any,
        gate_model_version_id: int | None,
        persistence_window: int,
        event_policy: dict[str, Any],
        reason_when_fired: str,
    ) -> tuple[int, int, int, int]:
        assert self.session_id is not None and self.stream_id is not None
        event_type = self._event_type_for_gate(gate_name)
        severity = self._severity_for_gate(gate_name)
        event_key = (
            f"session:{self.session_id}:{gate_name}:track:{sample.db_track_id}:"
            f"{tubelet_samples[0].sample_index}-{tubelet_samples[-1].sample_index}"
        )
        case_key = f"case:{event_key}"
        gate_summary = {
            "gate_name": gate_name,
            "raw_score": float(gate_out.raw_score),
            "smoothed_score": float(gate_out.smoothed_score),
            "threshold_value": float(gate_out.threshold_value),
            "above_threshold": bool(gate_out.above_threshold),
            "persistent": bool(gate_out.persistent),
            "persistence_hits": int(gate_out.persistence_hits),
            "persistence_window": int(persistence_window),
            "reason_when_fired": reason_when_fired,
            "event_type": event_type,
            "severity": severity,
        }
        score_summary = {
            "score_id": int(score_id),
            "tubelet_id": int(tubelet_id),
            "raw_score": float(gate_out.raw_score),
            "smoothed_score": float(gate_out.smoothed_score),
            "threshold_value": float(gate_out.threshold_value),
        }
        # Keep evaluation timestamps semantically clean:
        # - start_ts is the beginning of the scored tubelet/window.
        # - peak_ts is the latest/alarm timestamp for this emitted event.
        tubelet_start_ts = tubelet_samples[0].captured_at
        tubelet_peak_ts = tubelet_samples[-1].captured_at
        gate_event_id = self.db.insert_gate_event(
            conn,
            session_id=self.session_id,
            stream_id=self.stream_id,
            camera_id=self.cfg.camera_id,
            track_id=sample.db_track_id,
            gate_name=gate_name,
            gate_model_version_id=gate_model_version_id,
            tubelet_id=tubelet_id,
            score_id=score_id,
            event_key=event_key,
            severity=severity,
            event_type=event_type,
            start_ts=tubelet_start_ts,
            peak_ts=tubelet_peak_ts,
            peak_score=float(gate_out.smoothed_score),
            threshold_value=float(gate_out.threshold_value),
            persistence_hits=int(gate_out.persistence_hits),
            persistence_window=int(persistence_window),
            reason_when_fired=reason_when_fired,
            trigger_policy_json=event_policy,
            feature_values_json=gate_out.feature_values,
            dominant_features_json={"reason_when_fired": reason_when_fired},
            quality_json={"backend_slice": "gate_events_minio_evidence"},
            metadata_json={"tracker_track_id": sample.tracker_track_id, "gate_metadata": gate_out.metadata},
        )
        case_id = self.db.insert_anomaly_case_for_gate_event(
            conn,
            case_key=case_key,
            session_id=self.session_id,
            stream_id=self.stream_id,
            camera_id=self.cfg.camera_id,
            primary_track_id=sample.db_track_id,
            severity=severity,
            case_type=event_type,
            start_ts=tubelet_start_ts,
            peak_ts=tubelet_peak_ts,
            peak_score=float(gate_out.smoothed_score),
            primary_gate_name=gate_name,
            gate_summary_json={gate_name: gate_summary},
            score_summary_json={gate_name: score_summary},
            evidence_bundle_json={"status": "pending_upload"},
            metadata_json={"source": "vad-service", "gate_event_id": gate_event_id},
        )
        self.db.link_case_gate_event(conn, case_id=case_id, gate_event_id=gate_event_id, relation="primary")

        evidence_objects = 0
        evidence_items = 0
        reasoning_jobs = 0
        evidence_result = None
        if self.evidence_writer and self.cfg.evidence_enabled and self.cfg.save_evidence_on_gate_event:
            try:
                evidence_result = self.evidence_writer.write_gate_event_evidence(
                    conn,
                    session_id=self.session_id,
                    stream_id=self.stream_id,
                    camera_id=self.cfg.camera_id,
                    gate_name=gate_name,
                    gate_event_id=gate_event_id,
                    case_id=case_id,
                    tubelet_id=tubelet_id,
                    score_id=score_id,
                    db_track_id=sample.db_track_id,
                    tracker_track_id=sample.tracker_track_id,
                    tubelet_samples=tubelet_samples,
                    gate_summary=gate_summary | {"event_policy": event_policy},
                )
                evidence_objects = len(evidence_result.media_object_ids)
                evidence_items = len(evidence_result.evidence_item_ids)
                self.db.update_anomaly_case_evidence_bundle(
                    conn,
                    case_id=case_id,
                    evidence_bundle_json={
                        "status": "uploaded",
                        "object_keys": list(evidence_result.object_keys),
                        "media_object_ids": [int(x) for x in evidence_result.media_object_ids],
                        "evidence_item_ids": [int(x) for x in evidence_result.evidence_item_ids],
                        "gate_event_id": int(gate_event_id),
                        "tubelet_id": int(tubelet_id),
                        "score_id": int(score_id),
                    },
                )
            except Exception as e:
                self.last_error = f"Evidence upload failed for {gate_name} event {gate_event_id}: {e}"
                log.exception(self.last_error)

        if gate_name in {"deep", "pose"}:
            try:
                tubelet_start_ts = tubelet_samples[0].captured_at
                tubelet_peak_ts = tubelet_samples[-1].captured_at

                overlap = self.db.get_overlapping_gate_event_with_evidence(
                    conn,
                    session_id=self.session_id,
                    db_track_id=sample.db_track_id,
                    my_gate_event_id=gate_event_id,
                    my_start_ts=tubelet_start_ts,
                    my_peak_ts=tubelet_peak_ts,
                )

                if overlap:
                    # Co-fire: deep and pose both fired on same track + time
                    # Queue exactly one VLM job using deep frames
                    job_id = queue_cofire_reasoning_job(
                        conn,
                        cfg=self.cfg,
                        db=self.db,
                        my_gate_name=gate_name,
                        my_case_id=case_id,
                        my_gate_event_id=gate_event_id,
                        my_gate_out=gate_out,
                        my_gate_summary=gate_summary,
                        my_event_policy=event_policy,
                        my_evidence_result=evidence_result,
                        overlap=overlap,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        db_track_id=sample.db_track_id,
                        tracker_track_id=sample.tracker_track_id,
                        tubelet_id=tubelet_id,
                        score_id=score_id,
                        tubelet_start_ts=tubelet_start_ts,
                        tubelet_peak_ts=tubelet_peak_ts,
                    )
                    reasoning_jobs = 1 if job_id is not None else 0
                    log.info(
                        "Co-fire detected gate=%s track=%s overlap_gate=%s",
                        gate_name, sample.tracker_track_id, overlap["gate_name"],
                    )
                elif gate_name == "deep":
                    job_id = queue_deep_reasoning_job(
                        conn,
                        cfg=self.cfg,
                        db=self.db,
                        case_id=case_id,
                        gate_event_id=gate_event_id,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        db_track_id=sample.db_track_id,
                        tracker_track_id=sample.tracker_track_id,
                        tubelet_id=tubelet_id,
                        score_id=score_id,
                        gate_out=gate_out,
                        gate_summary=gate_summary,
                        event_policy=event_policy,
                        evidence_result=evidence_result,
                    )
                    reasoning_jobs = 1 if job_id is not None else 0
                else:
                    job_id = queue_pose_reasoning_job(
                        conn,
                        cfg=self.cfg,
                        db=self.db,
                        case_id=case_id,
                        gate_event_id=gate_event_id,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        db_track_id=sample.db_track_id,
                        tracker_track_id=sample.tracker_track_id,
                        tubelet_id=tubelet_id,
                        score_id=score_id,
                        gate_out=gate_out,
                        gate_summary=gate_summary,
                        event_policy=event_policy,
                        evidence_result=evidence_result,
                    )
                    reasoning_jobs = 1 if job_id is not None else 0

            except Exception as e:
                self.last_error = f"{gate_name} reasoning job queue failed for event {gate_event_id}: {e}"
                log.exception(self.last_error)

        return gate_event_id, evidence_objects, evidence_items, reasoning_jobs

    def _maybe_score_pose_tubelet(self, sample: SampledPerson) -> None:
        if not self.pose_gate or self.session_id is None or self.stream_id is None:
            return
        if sample.db_track_id is None:
            return
        tb = self.pose_tubelet_buffers.get(sample.tracker_track_id)
        if tb is None:
            tb = TrackTubeletBuffer[SampledPerson](
                tubelet_frames=self.cfg.pose_tubelet_frames,
                stride=self.cfg.pose_stride * self._route_step_samples(self.cfg.pose_route_fps),
                max_samples=max(256, self.cfg.pose_tubelet_frames * 6),
            )
            self.pose_tubelet_buffers[sample.tracker_track_id] = tb
        tubelet = tb.add(sample, sample_index=sample.sample_index)
        if tubelet is None:
            return
        try:
            gate_out = self.pose_gate.score_tubelet(sample.tracker_track_id, tubelet)
            frame_ids = [int(s.frame_id) for s in tubelet if s.frame_id is not None]
            detection_ids = [int(s.detection_id) for s in tubelet if s.detection_id is not None]
            bbox_sequence = [
                {
                    "sample_index": int(s.sample_index),
                    "frame_id": int(s.frame_id) if s.frame_id is not None else None,
                    "detection_id": int(s.detection_id) if s.detection_id is not None else None,
                    "bbox_xyxy": [float(v) for v in s.bbox_xyxy],
                    "confidence": float(s.confidence) if s.confidence is not None else None,
                }
                for s in tubelet
            ]
            tubelet_key = (
                f"session:{self.session_id}:pose:track:{sample.db_track_id}:"
                f"{tubelet[0].sample_index}-{tubelet[-1].sample_index}"
            )
            duration_sec = max(0.0, float((tubelet[-1].captured_at - tubelet[0].captured_at).total_seconds()))
            trigger_recommendation = "reasoning_candidate" if gate_out.persistent else "none"
            with self.db.connect() as conn:
                with conn.transaction():
                    tubelet_id = self.db.insert_tubelet(
                        conn,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        track_id=sample.db_track_id,
                        route_name="pose",
                        tubelet_key=tubelet_key,
                        start_frame_id=frame_ids[0] if frame_ids else None,
                        end_frame_id=frame_ids[-1] if frame_ids else None,
                        frame_sample_ids=frame_ids,
                        detection_ids=detection_ids,
                        window_start_ts=tubelet[0].captured_at,
                        window_end_ts=tubelet[-1].captured_at,
                        sample_fps=self.cfg.pose_route_fps,
                        tubelet_frames=self.cfg.pose_tubelet_frames,
                        stride=self.cfg.pose_stride,
                        duration_sec=duration_sec,
                        bbox_sequence_json=bbox_sequence,
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={
                            "reason_when_fired": "rare_pose_articulation",
                            "top_features_note": "dominant feature ranking will be added after calibration parity review",
                        },
                        quality_json={
                            "tubelet_sample_count": len(tubelet),
                            "has_keypoints": any(bool(s.keypoints_xy) for s in tubelet),
                        },
                        metadata_json=gate_out.metadata,
                    )
                    score_id = self.db.insert_gate_score(
                        conn,
                        tubelet_id=tubelet_id,
                        gate_name="pose",
                        gate_model_version_id=self.pose_gate_model_version_id,
                        threshold_id=self.pose_threshold_id,
                        raw_score=gate_out.raw_score,
                        smoothed_score=gate_out.smoothed_score,
                        threshold_key=self.cfg.pose_threshold_key,
                        threshold_value=gate_out.threshold_value,
                        threshold_percentile=self.pose_threshold_percentile,
                        above_threshold=gate_out.above_threshold,
                        persistence_window=self.cfg.pose_persistence_window,
                        persistence_required_hits=self.cfg.pose_persistence_required_hits,
                        persistence_hits=gate_out.persistence_hits,
                        persistent=gate_out.persistent,
                        trigger_recommendation=trigger_recommendation,
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={"reason_when_fired": "rare_pose_articulation"},
                        score_metadata_json=gate_out.metadata | {"gate_update": gate_out.gate_update.as_metadata()},
                        quality_json={"score_source": "backend_pose_gate_slice"},
                    )
                    emit_event, event_policy = self._should_emit_gate_event(
                        gate_name="pose",
                        tracker_track_id=sample.tracker_track_id,
                        persistent=gate_out.persistent,
                    )
                    new_events = new_evidence_objects = new_evidence_items = new_reasoning_jobs = 0
                    if emit_event:
                        _, new_evidence_objects, new_evidence_items, new_reasoning_jobs = self._create_gate_event_case_and_evidence(
                            conn,
                            gate_name="pose",
                            tubelet_id=tubelet_id,
                            score_id=score_id,
                            sample=sample,
                            tubelet_samples=list(tubelet),
                            gate_out=gate_out,
                            gate_model_version_id=self.pose_gate_model_version_id,
                            persistence_window=self.cfg.pose_persistence_window,
                            event_policy=event_policy,
                            reason_when_fired="rare_pose_articulation",
                        )
                        new_events = 1
            with self._lock:
                self.pose_tubelet_count += 1
                self.pose_score_count += 1
                if gate_out.persistent:
                    self.pose_persistent_count += 1
                self.gate_event_count += new_events
                self.evidence_object_count += new_evidence_objects
                self.evidence_item_count += new_evidence_items
                self.deep_reasoning_job_count += new_reasoning_jobs
            if gate_out.persistent:
                log.warning(
                    "POSE persistent hit track=%s score=%.4f smooth=%.4f threshold=%.4f hits=%s/%s",
                    sample.tracker_track_id,
                    gate_out.raw_score,
                    gate_out.smoothed_score,
                    gate_out.threshold_value,
                    gate_out.persistence_hits,
                    self.cfg.pose_persistence_window,
                )
        except Exception as e:
            self.last_error = f"Pose gate scoring failed: {e}"
            log.exception(self.last_error)


    def _bbox_sequence_for_tubelet(self, tubelet: list[SampledPerson]) -> list[dict[str, Any]]:
        return [
            {
                "sample_index": int(s.sample_index),
                "frame_id": int(s.frame_id) if s.frame_id is not None else None,
                "detection_id": int(s.detection_id) if s.detection_id is not None else None,
                "bbox_xyxy": [float(v) for v in s.bbox_xyxy],
                "confidence": float(s.confidence) if s.confidence is not None else None,
            }
            for s in tubelet
        ]

    def _maybe_score_deep_tubelet(self, sample: SampledPerson) -> None:
        if not self.deep_gate or self.session_id is None or self.stream_id is None:
            return
        if sample.db_track_id is None:
            return
        tb = self.deep_tubelet_buffers.get(sample.tracker_track_id)
        if tb is None:
            tb = TrackTubeletBuffer[SampledPerson](
                tubelet_frames=self.cfg.deep_tubelet_frames,
                stride=self.cfg.deep_stride * self._route_step_samples(self.cfg.deep_route_fps),
                max_samples=max(128, self.cfg.deep_tubelet_frames * 6),
            )
            self.deep_tubelet_buffers[sample.tracker_track_id] = tb
        tubelet = tb.add(sample, sample_index=sample.sample_index)
        if tubelet is None:
            return
        try:
            gate_out = self.deep_gate.score_tubelet(sample.tracker_track_id, tubelet)
            frame_ids = [int(s.frame_id) for s in tubelet if s.frame_id is not None]
            detection_ids = [int(s.detection_id) for s in tubelet if s.detection_id is not None]
            tubelet_key = f"session:{self.session_id}:deep:track:{sample.db_track_id}:{tubelet[0].sample_index}-{tubelet[-1].sample_index}"
            duration_sec = max(0.0, float((tubelet[-1].captured_at - tubelet[0].captured_at).total_seconds()))
            trigger_recommendation = "reasoning_required" if gate_out.persistent else "none"
            with self.db.connect() as conn:
                with conn.transaction():
                    tubelet_id = self.db.insert_tubelet(
                        conn,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        track_id=sample.db_track_id,
                        route_name="deep",
                        tubelet_key=tubelet_key,
                        start_frame_id=frame_ids[0] if frame_ids else None,
                        end_frame_id=frame_ids[-1] if frame_ids else None,
                        frame_sample_ids=frame_ids,
                        detection_ids=detection_ids,
                        window_start_ts=tubelet[0].captured_at,
                        window_end_ts=tubelet[-1].captured_at,
                        sample_fps=self.cfg.deep_route_fps,
                        tubelet_frames=self.cfg.deep_tubelet_frames,
                        stride=self.cfg.deep_stride,
                        duration_sec=duration_sec,
                        bbox_sequence_json=self._bbox_sequence_for_tubelet(tubelet),
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={"reason_when_fired": "deep_semantic_spatiotemporal_anomaly"},
                        quality_json={"tubelet_sample_count": len(tubelet), "crop_mode": "union"},
                        metadata_json=gate_out.metadata,
                    )
                    score_id = self.db.insert_gate_score(
                        conn,
                        tubelet_id=tubelet_id,
                        gate_name="deep",
                        gate_model_version_id=self.deep_gate_model_version_id,
                        threshold_id=self.deep_threshold_id,
                        raw_score=gate_out.raw_score,
                        smoothed_score=gate_out.smoothed_score,
                        threshold_key=self.cfg.deep_threshold_key,
                        threshold_value=gate_out.threshold_value,
                        threshold_percentile=self.deep_threshold_percentile,
                        above_threshold=gate_out.above_threshold,
                        persistence_window=self.cfg.deep_persistence_window,
                        persistence_required_hits=self.cfg.deep_persistence_required_hits,
                        persistence_hits=gate_out.persistence_hits,
                        persistent=gate_out.persistent,
                        trigger_recommendation=trigger_recommendation,
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={"reason_when_fired": "deep_semantic_spatiotemporal_anomaly"},
                        score_metadata_json=gate_out.metadata | {"gate_update": gate_out.gate_update.as_metadata()},
                        quality_json={"score_source": "backend_deep_gate_union_slice"},
                    )
                    emit_event, event_policy = self._should_emit_gate_event(
                        gate_name="deep",
                        tracker_track_id=sample.tracker_track_id,
                        persistent=gate_out.persistent,
                    )
                    new_events = new_evidence_objects = new_evidence_items = new_reasoning_jobs = 0
                    if emit_event:
                        _, new_evidence_objects, new_evidence_items, new_reasoning_jobs = self._create_gate_event_case_and_evidence(
                            conn,
                            gate_name="deep",
                            tubelet_id=tubelet_id,
                            score_id=score_id,
                            sample=sample,
                            tubelet_samples=list(tubelet),
                            gate_out=gate_out,
                            gate_model_version_id=self.deep_gate_model_version_id,
                            persistence_window=self.cfg.deep_persistence_window,
                            event_policy=event_policy,
                            reason_when_fired="deep_semantic_spatiotemporal_anomaly",
                        )
                        new_events = 1
            with self._lock:
                self.deep_tubelet_count += 1
                self.deep_score_count += 1
                if gate_out.persistent:
                    self.deep_persistent_count += 1
                self.gate_event_count += new_events
                self.evidence_object_count += new_evidence_objects
                self.evidence_item_count += new_evidence_items
                self.deep_reasoning_job_count += new_reasoning_jobs
            if gate_out.persistent:
                log.warning("DEEP persistent hit track=%s score=%.4f smooth=%.4f threshold=%.4f hits=%s/%s", sample.tracker_track_id, gate_out.raw_score, gate_out.smoothed_score, gate_out.threshold_value, gate_out.persistence_hits, self.cfg.deep_persistence_window)
        except Exception as e:
            self.last_error = f"Deep gate scoring failed: {e}"
            log.exception(self.last_error)

    def _maybe_score_homography_macro_tubelet(self, sample: SampledPerson) -> None:
        if not self.homography_macro_gate or self.session_id is None or self.stream_id is None:
            return
        if sample.db_track_id is None:
            return
        try:
            macro_sample = self.homography_macro_gate.make_macro_sample(sample)
        except Exception as e:
            self.last_error = f"Macro groundpoint failed: {e}"
            log.exception(self.last_error)
            return
        tb = self.homography_macro_tubelet_buffers.get(sample.tracker_track_id)
        if tb is None:
            tb = TrackTubeletBuffer[MacroSample](
                tubelet_frames=self.cfg.homography_macro_tubelet_frames,
                stride=self.cfg.homography_macro_stride * self._route_step_samples(self.cfg.homography_macro_route_fps),
                max_samples=max(128, self.cfg.homography_macro_tubelet_frames * 6),
            )
            self.homography_macro_tubelet_buffers[sample.tracker_track_id] = tb
        tubelet = tb.add(macro_sample, sample_index=sample.sample_index)
        if tubelet is None:
            return
        try:
            gate_out = self.homography_macro_gate.score_tubelet(sample.tracker_track_id, tubelet)
            samples = [m.sample for m in tubelet]
            frame_ids = [int(s.frame_id) for s in samples if s.frame_id is not None]
            detection_ids = [int(s.detection_id) for s in samples if s.detection_id is not None]
            tubelet_key = f"session:{self.session_id}:homography_macro:track:{sample.db_track_id}:{samples[0].sample_index}-{samples[-1].sample_index}"
            duration_sec = max(0.0, float((samples[-1].captured_at - samples[0].captured_at).total_seconds()))
            # Macro gate should not always force reasoning; mark as candidate only when persistent.
            trigger_recommendation = "reasoning_candidate" if gate_out.persistent else "none"
            bbox_sequence = self._bbox_sequence_for_tubelet(samples)
            trajectory_json = {
                "ground_points_image": [m.ground_xy for m in tubelet],
                "ground_sources": [m.ground_source for m in tubelet],
                "ground_confs": [m.ground_conf for m in tubelet],
                "ground_frozen": [m.ground_frozen for m in tubelet],
            }
            with self.db.connect() as conn:
                with conn.transaction():
                    tubelet_id = self.db.insert_tubelet(
                        conn,
                        session_id=self.session_id,
                        stream_id=self.stream_id,
                        camera_id=self.cfg.camera_id,
                        track_id=sample.db_track_id,
                        route_name="homography_macro",
                        tubelet_key=tubelet_key,
                        start_frame_id=frame_ids[0] if frame_ids else None,
                        end_frame_id=frame_ids[-1] if frame_ids else None,
                        frame_sample_ids=frame_ids,
                        detection_ids=detection_ids,
                        window_start_ts=samples[0].captured_at,
                        window_end_ts=samples[-1].captured_at,
                        sample_fps=self.cfg.homography_macro_route_fps,
                        tubelet_frames=self.cfg.homography_macro_tubelet_frames,
                        stride=self.cfg.homography_macro_stride,
                        duration_sec=duration_sec,
                        bbox_sequence_json=bbox_sequence,
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={"reason_when_fired": "rare_macro_floor_motion"},
                        quality_json={"tubelet_sample_count": len(tubelet), "trajectory_json": trajectory_json},
                        metadata_json=gate_out.metadata,
                    )
                    score_id = self.db.insert_gate_score(
                        conn,
                        tubelet_id=tubelet_id,
                        gate_name="homography_macro",
                        gate_model_version_id=self.homography_macro_gate_model_version_id,
                        threshold_id=self.homography_macro_threshold_id,
                        raw_score=gate_out.raw_score,
                        smoothed_score=gate_out.smoothed_score,
                        threshold_key=self.cfg.homography_macro_threshold_key,
                        threshold_value=gate_out.threshold_value,
                        threshold_percentile=self.homography_macro_threshold_percentile,
                        above_threshold=gate_out.above_threshold,
                        persistence_window=self.cfg.homography_macro_persistence_window,
                        persistence_required_hits=self.cfg.homography_macro_persistence_required_hits,
                        persistence_hits=gate_out.persistence_hits,
                        persistent=gate_out.persistent,
                        trigger_recommendation=trigger_recommendation,
                        feature_values_json=gate_out.feature_values,
                        dominant_features_json={"reason_when_fired": "rare_macro_floor_motion"},
                        score_metadata_json=gate_out.metadata | {"gate_update": gate_out.gate_update.as_metadata()},
                        quality_json={"score_source": "backend_homography_macro_stage3_slice"},
                    )
                    emit_event, event_policy = self._should_emit_gate_event(
                        gate_name="homography_macro",
                        tracker_track_id=sample.tracker_track_id,
                        persistent=gate_out.persistent,
                    )
                    new_events = new_evidence_objects = new_evidence_items = new_reasoning_jobs = 0
                    if emit_event:
                        _, new_evidence_objects, new_evidence_items, new_reasoning_jobs = self._create_gate_event_case_and_evidence(
                            conn,
                            gate_name="homography_macro",
                            tubelet_id=tubelet_id,
                            score_id=score_id,
                            sample=sample,
                            tubelet_samples=list(samples),
                            gate_out=gate_out,
                            gate_model_version_id=self.homography_macro_gate_model_version_id,
                            persistence_window=self.cfg.homography_macro_persistence_window,
                            event_policy=event_policy,
                            reason_when_fired="rare_macro_floor_motion",
                        )
                        new_events = 1
            with self._lock:
                self.homography_macro_tubelet_count += 1
                self.homography_macro_score_count += 1
                if gate_out.persistent:
                    self.homography_macro_persistent_count += 1
                self.gate_event_count += new_events
                self.evidence_object_count += new_evidence_objects
                self.evidence_item_count += new_evidence_items
                self.deep_reasoning_job_count += new_reasoning_jobs
            if gate_out.persistent:
                log.warning("MACRO persistent hit track=%s score=%.4f smooth=%.4f threshold=%.4f hits=%s/%s", sample.tracker_track_id, gate_out.raw_score, gate_out.smoothed_score, gate_out.threshold_value, gate_out.persistence_hits, self.cfg.homography_macro_persistence_window)
        except Exception as e:
            self.last_error = f"Homography/macro gate scoring failed: {e}"
            log.exception(self.last_error)

    def _run_loop(self) -> None:
        assert self.stream_id is not None and self.session_id is not None

        next_sample_time = time.monotonic()
        sample_period = 1.0 / self.cfg.target_sample_fps
        read_failures = 0
        cap: cv2.VideoCapture | None = None

        try:
            while not self._stop_event.is_set():
                if cap is None or not cap.isOpened():
                    cap = self._open_capture()
                    if not cap.isOpened():
                        self.reconnect_count += 1
                        self.last_error = "Could not open RTSP stream"
                        log.warning("%s; retrying in %.1fs", self.last_error, self.cfg.reconnect_sleep_sec)
                        time.sleep(self.cfg.reconnect_sleep_sec)
                        continue

                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or None
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or None
                    fps_reported = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
                    with self.db.connect() as conn:
                        with conn.transaction():
                            self.db.mark_session_running(
                                conn,
                                session_id=self.session_id,
                                width=width,
                                height=height,
                                fps_reported=fps_reported,
                            )
                    log.info("Opened RTSP stream for %s (%sx%s @ reported fps=%s)", self.cfg.stream_key, width, height, fps_reported)

                ok, frame = cap.read()
                if not ok or frame is None:
                    read_failures += 1
                    self.dropped_frame_count += 1
                    if read_failures >= self.cfg.read_fail_reconnect_after:
                        self.reconnect_count += 1
                        self.last_error = f"RTSP read failed {read_failures} times; reconnecting"
                        log.warning(self.last_error)
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = None
                        read_failures = 0
                        time.sleep(self.cfg.reconnect_sleep_sec)
                    continue

                read_failures = 0
                with self._lock:
                    self.source_frame_index += 1
                    source_frame_index = self.source_frame_index

                # Critical parity with live scripts: track every decoded camera frame.
                tracked_people: list[TrackedPerson] = []
                if self.cfg.tracking_enabled:
                    try:
                        tracked_people = self._run_tracker(frame, source_frame_index)
                    except Exception as e:
                        self.last_error = f"YOLO tracking failed: {e}"
                        log.exception(self.last_error)
                        tracked_people = []

                now = time.monotonic()
                if now < next_sample_time:
                    continue

                captured_at = datetime.now(timezone.utc)
                h, w = frame.shape[:2]
                with self._lock:
                    self.sample_index += 1
                    sample_index = self.sample_index
                    self.processed_frame_count += 1

                used_by_pose, used_by_deep, used_by_homography_macro = self._route_flags(sample_index)

                frame_id: int | None = None
                sampled_people_for_buffers: list[tuple[TrackedPerson, int | None, int | None]] = []

                try:
                    with self.db.connect() as conn:
                        with conn.transaction():
                            frame_id = self.db.insert_sampled_frame(
                                conn,
                                session_id=self.session_id,
                                stream_id=self.stream_id,
                                camera_id=self.cfg.camera_id,
                                sample_index=sample_index,
                                source_frame_index=source_frame_index,
                                captured_at=captured_at,
                                monotonic_ts_sec=now,
                                frame_width=w,
                                frame_height=h,
                                used_by_pose=used_by_pose,
                                used_by_deep=used_by_deep,
                                used_by_homography_macro=used_by_homography_macro,
                                used_by_raft=False,
                                metadata_json={
                                    "source": "backend_direct_rtsp",
                                    "buffer_max_frames": self.cfg.rolling_buffer_max_frames,
                                    "tracking_enabled": self.cfg.tracking_enabled,
                                    "tracked_person_count": len(tracked_people),
                                },
                            )

                            for person in tracked_people:
                                db_track_id = self.db.upsert_track(
                                    conn,
                                    session_id=self.session_id,
                                    stream_id=self.stream_id,
                                    camera_id=self.cfg.camera_id,
                                    tracker_name=self.cfg.tracker_config,
                                    tracker_track_id=person.tracker_track_id,
                                    frame_id=frame_id,
                                    seen_at=captured_at,
                                    bbox_xyxy=person.bbox_xyxy,
                                    confidence=person.confidence,
                                    metadata_json={"detector_model": str(self.cfg.detector_model)},
                                )
                                detection_id = self.db.insert_detection(
                                    conn,
                                    frame_id=frame_id,
                                    session_id=self.session_id,
                                    stream_id=self.stream_id,
                                    camera_id=self.cfg.camera_id,
                                    db_track_id=db_track_id,
                                    person=person,
                                    frame_width=w,
                                    frame_height=h,
                                    detector_name="ultralytics_yolo_pose",
                                    detector_model_version=str(self.cfg.detector_model),
                                )
                                sampled_people_for_buffers.append((person, db_track_id, detection_id))

                    with self._lock:
                        self.detection_count += len(tracked_people)
                        self.tracked_detection_count += len(tracked_people)

                except Exception as e:
                    self.last_error = f"DB frame/tracking insert failed: {e}"
                    log.warning(self.last_error)

                if frame_id is not None:
                    self._append_route_buffers(
                        frame_id=frame_id,
                        sample_index=sample_index,
                        captured_at=captured_at,
                        frame_bgr=frame,
                        used_by_pose=used_by_pose,
                        used_by_deep=used_by_deep,
                        used_by_homography_macro=used_by_homography_macro,
                        sampled_people=sampled_people_for_buffers,
                    )

                item = BufferedFrame(
                    frame_id=frame_id,
                    sample_index=sample_index,
                    source_frame_index=source_frame_index,
                    captured_at=captured_at,
                    frame_bgr=frame,
                    used_by_pose=used_by_pose,
                    used_by_deep=used_by_deep,
                    used_by_homography_macro=used_by_homography_macro,
                    tracked_person_count=len(tracked_people),
                )
                with self._lock:
                    self.buffer.append(item)

                if self.cfg.debug_save_every_n_frames > 0 and sample_index % self.cfg.debug_save_every_n_frames == 0:
                    try:
                        self.save_latest_debug_frame()
                    except Exception as e:
                        log.warning("Auto debug save failed: %s", e)

                if sample_index == 1 or sample_index % max(1, int(self.cfg.target_sample_fps * 5)) == 0:
                    self._heartbeat()

                # Stable sampling: schedule based on target time, but do not let a long stall cause burst catch-up.
                next_sample_time += sample_period
                if time.monotonic() - next_sample_time > sample_period * 3:
                    next_sample_time = time.monotonic() + sample_period

        except Exception as e:
            self.last_error = str(e)
            log.exception("VAD RTSP sampler crashed")
            try:
                with self.db.connect() as conn:
                    with conn.transaction():
                        self.db.fail_session(
                            conn,
                            session_id=self.session_id,
                            error=str(e),
                            sampled_frame_count=self.sample_index,
                            dropped_frame_count=self.dropped_frame_count,
                            reconnect_count=self.reconnect_count,
                        )
            except Exception:
                log.exception("Could not mark VAD session failed")
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            try:
                self._heartbeat()
            except Exception:
                pass

    def _heartbeat(self) -> None:
        if self.session_id is None:
            return
        elapsed = max(0.001, time.monotonic() - self.started_monotonic) if self.started_monotonic else 0.0
        actual_fps = self.sample_index / elapsed if elapsed else 0.0
        route_counters = {
            "pose_frames": self.sample_index,
            "deep_frames": self.sample_index // 2,
            "homography_macro_frames": self.sample_index // 2,
            "tracked_detections": self.tracked_detection_count,
            "active_track_buffers": len(self.track_buffers),
            "pose_tubelets": self.pose_tubelet_count,
            "pose_scores": self.pose_score_count,
            "pose_persistent_hits": self.pose_persistent_count,
            "deep_tubelets": self.deep_tubelet_count,
            "deep_scores": self.deep_score_count,
            "deep_persistent_hits": self.deep_persistent_count,
            "homography_macro_tubelets": self.homography_macro_tubelet_count,
            "homography_macro_scores": self.homography_macro_score_count,
            "homography_macro_persistent_hits": self.homography_macro_persistent_count,
            "deep_reasoning_jobs": self.deep_reasoning_job_count,
        }
        runtime_stats = {
            "source_frame_count": self.source_frame_index,
            "processed_frame_count": self.processed_frame_count,
            "tracker_frame_count": self.tracker_frame_count,
            "detection_count": self.detection_count,
            "tracked_detection_count": self.tracked_detection_count,
            "untracked_detection_count": self.untracked_detection_count,
            "buffer_frame_count": len(self.buffer),
            "buffer_max_frames": self.cfg.rolling_buffer_max_frames,
            "active_track_buffer_count": len(self.track_buffers),
            "pose_tubelet_count": self.pose_tubelet_count,
            "pose_score_count": self.pose_score_count,
            "pose_persistent_count": self.pose_persistent_count,
            "deep_tubelet_count": self.deep_tubelet_count,
            "deep_score_count": self.deep_score_count,
            "deep_persistent_count": self.deep_persistent_count,
            "homography_macro_tubelet_count": self.homography_macro_tubelet_count,
            "homography_macro_score_count": self.homography_macro_score_count,
            "homography_macro_persistent_count": self.homography_macro_persistent_count,
            "deep_reasoning_job_count": self.deep_reasoning_job_count,
            "last_error": self.last_error,
        }
        with self.db.connect() as conn:
            with conn.transaction():
                self.db.heartbeat_session(
                    conn,
                    session_id=self.session_id,
                    sampled_frame_count=self.sample_index,
                    dropped_frame_count=self.dropped_frame_count,
                    reconnect_count=self.reconnect_count,
                    actual_sample_fps=actual_fps,
                    route_counters=route_counters,
                    runtime_stats=runtime_stats,
                )
