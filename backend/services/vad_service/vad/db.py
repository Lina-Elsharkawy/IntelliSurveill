from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import VadConfig
from .frame_types import TrackedPerson
from .json_utils import sanitize_json


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    """Serialize JSONB payloads after removing NaN/Infinity/NumPy values."""
    return json.dumps(sanitize_json(value if value is not None else {}), ensure_ascii=False, allow_nan=False)


class VadDB:
    """DB layer for the new backend-direct VAD schema.

    This file intentionally touches only vad_* tables. It does not use the old
    scene_window_embeddings / anomaly_candidates flow.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def upsert_stream(self, conn: psycopg.Connection, cfg: VadConfig) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_streams (
                stream_key,
                camera_id,
                camera_key,
                display_name,
                source_type,
                rtsp_url_env_var,
                target_sample_fps,
                rolling_buffer_sec,
                route_fps_json,
                config_json,
                metadata_json,
                is_active,
                updated_at
            )
            VALUES (
                %(stream_key)s,
                %(camera_id)s,
                %(camera_key)s,
                %(display_name)s,
                'rtsp',
                %(rtsp_url_env_var)s,
                %(target_sample_fps)s,
                %(rolling_buffer_sec)s,
                %(route_fps_json)s::jsonb,
                %(config_json)s::jsonb,
                %(metadata_json)s::jsonb,
                TRUE,
                NOW()
            )
            ON CONFLICT (stream_key) DO UPDATE SET
                camera_id = EXCLUDED.camera_id,
                camera_key = EXCLUDED.camera_key,
                rtsp_url_env_var = EXCLUDED.rtsp_url_env_var,
                target_sample_fps = EXCLUDED.target_sample_fps,
                rolling_buffer_sec = EXCLUDED.rolling_buffer_sec,
                route_fps_json = EXCLUDED.route_fps_json,
                config_json = EXCLUDED.config_json,
                is_active = TRUE,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "stream_key": cfg.stream_key,
                "camera_id": cfg.camera_id,
                "camera_key": cfg.camera_key,
                "display_name": cfg.camera_key or cfg.stream_key,
                "rtsp_url_env_var": cfg.rtsp_url_env_var,
                "target_sample_fps": cfg.target_sample_fps,
                "rolling_buffer_sec": cfg.rolling_buffer_sec,
                "route_fps_json": _json(cfg.route_fps_json),
                "config_json": _json(cfg.public_dict()),
                "metadata_json": _json({"created_by": "vad-service"}),
            },
        ).fetchone()
        return int(row["id"])

    def start_stream_session(self, conn: psycopg.Connection, *, stream_id: int, cfg: VadConfig) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_stream_sessions (
                stream_id,
                status,
                started_at,
                last_heartbeat_at,
                target_sample_fps,
                actual_sample_fps,
                sampled_frame_count,
                dropped_frame_count,
                reconnect_count,
                route_counters_json,
                runtime_stats_json,
                metadata_json
            )
            VALUES (
                %(stream_id)s,
                'starting',
                NOW(),
                NOW(),
                %(target_sample_fps)s,
                0,
                0,
                0,
                0,
                '{}'::jsonb,
                '{}'::jsonb,
                %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "stream_id": stream_id,
                "target_sample_fps": cfg.target_sample_fps,
                "metadata_json": _json({"service": "vad-service", "mode": "backend_direct_rtsp"}),
            },
        ).fetchone()
        return int(row["id"])

    def mark_session_running(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        width: int | None,
        height: int | None,
        fps_reported: float | None,
    ) -> None:
        conn.execute(
            """
            UPDATE vad_stream_sessions
            SET
                status = 'running',
                first_frame_at = COALESCE(first_frame_at, NOW()),
                last_frame_at = NOW(),
                last_heartbeat_at = NOW(),
                runtime_stats_json = COALESCE(runtime_stats_json, '{}'::jsonb)
                    || %(stats)s::jsonb
            WHERE id = %(session_id)s
            """,
            {
                "session_id": session_id,
                "stats": _json({"capture_width": width, "capture_height": height, "capture_fps_reported": fps_reported}),
            },
        )

    def heartbeat_session(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        sampled_frame_count: int,
        dropped_frame_count: int,
        reconnect_count: int,
        actual_sample_fps: float,
        route_counters: dict[str, int],
        runtime_stats: dict[str, Any],
    ) -> None:
        conn.execute(
            """
            UPDATE vad_stream_sessions
            SET
                last_heartbeat_at = NOW(),
                last_frame_at = NOW(),
                sampled_frame_count = %(sampled_frame_count)s,
                dropped_frame_count = %(dropped_frame_count)s,
                reconnect_count = %(reconnect_count)s,
                actual_sample_fps = %(actual_sample_fps)s,
                route_counters_json = %(route_counters_json)s::jsonb,
                runtime_stats_json = COALESCE(runtime_stats_json, '{}'::jsonb)
                    || %(runtime_stats_json)s::jsonb
            WHERE id = %(session_id)s
            """,
            {
                "session_id": session_id,
                "sampled_frame_count": sampled_frame_count,
                "dropped_frame_count": dropped_frame_count,
                "reconnect_count": reconnect_count,
                "actual_sample_fps": actual_sample_fps,
                "route_counters_json": _json(route_counters),
                "runtime_stats_json": _json(runtime_stats),
            },
        )

    def stop_session(self, conn: psycopg.Connection, *, session_id: int, status: str = "stopped") -> None:
        conn.execute(
            """
            UPDATE vad_stream_sessions
            SET
                status = %(status)s,
                stopped_at = NOW(),
                last_heartbeat_at = NOW()
            WHERE id = %(session_id)s
            """,
            {"session_id": session_id, "status": status},
        )

    def fail_session(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        error: str,
        sampled_frame_count: int = 0,
        dropped_frame_count: int = 0,
        reconnect_count: int = 0,
    ) -> None:
        conn.execute(
            """
            UPDATE vad_stream_sessions
            SET
                status = 'failed',
                stopped_at = NOW(),
                last_heartbeat_at = NOW(),
                sampled_frame_count = %(sampled_frame_count)s,
                dropped_frame_count = %(dropped_frame_count)s,
                reconnect_count = %(reconnect_count)s,
                error_json = %(error_json)s::jsonb
            WHERE id = %(session_id)s
            """,
            {
                "session_id": session_id,
                "sampled_frame_count": sampled_frame_count,
                "dropped_frame_count": dropped_frame_count,
                "reconnect_count": reconnect_count,
                "error_json": _json({"error": error}),
            },
        )

    def insert_sampled_frame(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        stream_id: int,
        sample_index: int,
        captured_at: datetime,
        frame_width: int,
        frame_height: int,
        used_by_pose: bool,
        used_by_deep: bool,
        used_by_homography_macro: bool,
        used_by_raft: bool = False,
        source_frame_index: int | None = None,
        stream_pts_sec: float | None = None,
        monotonic_ts_sec: float | None = None,
        camera_id: int | None = None,
        quality_json: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_sampled_frames (
                session_id,
                stream_id,
                camera_id,
                sample_index,
                source_frame_index,
                captured_at,
                stream_pts_sec,
                monotonic_ts_sec,
                frame_width,
                frame_height,
                used_by_pose,
                used_by_deep,
                used_by_homography_macro,
                used_by_raft,
                quality_json,
                metadata_json
            )
            VALUES (
                %(session_id)s,
                %(stream_id)s,
                %(camera_id)s,
                %(sample_index)s,
                %(source_frame_index)s,
                %(captured_at)s,
                %(stream_pts_sec)s,
                %(monotonic_ts_sec)s,
                %(frame_width)s,
                %(frame_height)s,
                %(used_by_pose)s,
                %(used_by_deep)s,
                %(used_by_homography_macro)s,
                %(used_by_raft)s,
                %(quality_json)s::jsonb,
                %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "sample_index": sample_index,
                "source_frame_index": source_frame_index,
                "captured_at": captured_at,
                "stream_pts_sec": stream_pts_sec,
                "monotonic_ts_sec": monotonic_ts_sec,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "used_by_pose": used_by_pose,
                "used_by_deep": used_by_deep,
                "used_by_homography_macro": used_by_homography_macro,
                "used_by_raft": used_by_raft,
                "quality_json": _json(quality_json or {}),
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def upsert_track(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        tracker_name: str,
        tracker_track_id: int,
        frame_id: int,
        seen_at: datetime,
        bbox_xyxy: list[float],
        confidence: float | None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        global_track_key = f"session:{session_id}:{tracker_name}:{tracker_track_id}"
        row = conn.execute(
            """
            INSERT INTO vad_tracks (
                session_id,
                stream_id,
                camera_id,
                tracker_name,
                tracker_track_id,
                global_track_key,
                status,
                first_seen_frame_id,
                last_seen_frame_id,
                first_seen_at,
                last_seen_at,
                detection_count,
                gap_count,
                best_confidence,
                last_bbox_xyxy_json,
                metadata_json
            )
            VALUES (
                %(session_id)s,
                %(stream_id)s,
                %(camera_id)s,
                %(tracker_name)s,
                %(tracker_track_id)s,
                %(global_track_key)s,
                'active',
                %(frame_id)s,
                %(frame_id)s,
                %(seen_at)s,
                %(seen_at)s,
                0,
                0,
                %(confidence)s,
                %(bbox_xyxy_json)s::jsonb,
                %(metadata_json)s::jsonb
            )
            ON CONFLICT (session_id, tracker_name, tracker_track_id) DO UPDATE SET
                status = 'active',
                last_seen_frame_id = EXCLUDED.last_seen_frame_id,
                last_seen_at = EXCLUDED.last_seen_at,
                best_confidence = GREATEST(COALESCE(vad_tracks.best_confidence, 0), COALESCE(EXCLUDED.best_confidence, 0)),
                last_bbox_xyxy_json = EXCLUDED.last_bbox_xyxy_json,
                metadata_json = COALESCE(vad_tracks.metadata_json, '{}'::jsonb) || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "tracker_name": tracker_name,
                "tracker_track_id": tracker_track_id,
                "global_track_key": global_track_key,
                "frame_id": frame_id,
                "seen_at": seen_at,
                "confidence": confidence,
                "bbox_xyxy_json": _json(bbox_xyxy),
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def insert_detection(
        self,
        conn: psycopg.Connection,
        *,
        frame_id: int,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        db_track_id: int | None,
        person: TrackedPerson,
        frame_width: int,
        frame_height: int,
        detector_name: str,
        detector_model_version: str,
    ) -> int:
        x1, y1, x2, y2 = [float(v) for v in person.bbox_xyxy]
        bbox_norm = {
            "x1": x1 / max(1, frame_width),
            "y1": y1 / max(1, frame_height),
            "x2": x2 / max(1, frame_width),
            "y2": y2 / max(1, frame_height),
        }
        keypoints_json = {
            "format": "coco17_xy_conf",
            "xy": person.keypoints_xy,
            "conf": person.keypoints_conf,
        } if person.keypoints_xy else {}
        row = conn.execute(
            """
            INSERT INTO vad_detections (
                frame_id,
                session_id,
                stream_id,
                camera_id,
                track_id,
                detector_name,
                detector_model_version,
                class_name,
                class_id,
                confidence,
                bbox_xyxy_json,
                bbox_norm_json,
                keypoints_json,
                detection_features_json,
                quality_json,
                metadata_json
            )
            VALUES (
                %(frame_id)s,
                %(session_id)s,
                %(stream_id)s,
                %(camera_id)s,
                %(track_id)s,
                %(detector_name)s,
                %(detector_model_version)s,
                %(class_name)s,
                %(class_id)s,
                %(confidence)s,
                %(bbox_xyxy_json)s::jsonb,
                %(bbox_norm_json)s::jsonb,
                %(keypoints_json)s::jsonb,
                %(detection_features_json)s::jsonb,
                %(quality_json)s::jsonb,
                %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "frame_id": frame_id,
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "track_id": db_track_id,
                "detector_name": detector_name,
                "detector_model_version": detector_model_version,
                "class_name": person.class_name,
                "class_id": person.class_id,
                "confidence": person.confidence,
                "bbox_xyxy_json": _json(person.bbox_xyxy),
                "bbox_norm_json": _json(bbox_norm),
                "keypoints_json": _json(keypoints_json),
                "detection_features_json": _json({}),
                "quality_json": _json({"has_keypoints": bool(person.keypoints_xy), "tracker_track_id": person.tracker_track_id}),
                "metadata_json": _json(person.detector_metadata),
            },
        ).fetchone()
        conn.execute("UPDATE vad_tracks SET detection_count = detection_count + 1, updated_at = NOW() WHERE id = %(id)s", {"id": db_track_id}) if db_track_id else None
        return int(row["id"])

    def mark_missing_tracks_lost(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        tracker_name: str,
        active_tracker_ids: list[int],
        max_age_samples: int,
        current_sample_index: int,
    ) -> int:
        # Lightweight DB-side stale marker. The exact last_seen sample index is
        # also tracked in memory, so this is mainly for readable DB status.
        del active_tracker_ids, max_age_samples, current_sample_index
        row = conn.execute(
            """
            UPDATE vad_tracks
            SET status = 'lost', updated_at = NOW()
            WHERE session_id = %(session_id)s
              AND tracker_name = %(tracker_name)s
              AND status = 'active'
              AND last_seen_at < NOW() - interval '10 seconds'
            RETURNING id
            """,
            {"session_id": session_id, "tracker_name": tracker_name},
        ).fetchall()
        return len(row)

    def get_active_gate_model_version(self, conn: psycopg.Connection, *, gate_name: str) -> dict[str, Any] | None:
        return conn.execute(
            """
            SELECT id, gate_name, version, model_name, model_type, feature_dim,
                   sample_fps, tubelet_frames, stride, artifact_refs_json,
                   inference_config_json
            FROM vad_gate_model_versions
            WHERE gate_name = %(gate_name)s AND is_active = TRUE
            ORDER BY activated_at DESC NULLS LAST, id DESC
            LIMIT 1
            """,
            {"gate_name": gate_name},
        ).fetchone()

    def get_primary_gate_threshold(self, conn: psycopg.Connection, *, gate_model_version_id: int) -> dict[str, Any] | None:
        return conn.execute(
            """
            SELECT id, threshold_key, threshold_percentile, threshold_value,
                   smoothing_sigma, persistence_window, persistence_required_hits,
                   min_event_gap_sec, trigger_policy_json
            FROM vad_gate_thresholds
            WHERE gate_model_version_id = %(gate_model_version_id)s AND is_primary = TRUE
            ORDER BY id DESC
            LIMIT 1
            """,
            {"gate_model_version_id": gate_model_version_id},
        ).fetchone()

    def insert_tubelet(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        track_id: int | None,
        route_name: str,
        tubelet_key: str,
        start_frame_id: int | None,
        end_frame_id: int | None,
        frame_sample_ids: list[int],
        detection_ids: list[int],
        window_start_ts: datetime,
        window_end_ts: datetime,
        sample_fps: float,
        tubelet_frames: int,
        stride: int,
        duration_sec: float | None,
        bbox_sequence_json: list[Any],
        feature_values_json: dict[str, Any],
        dominant_features_json: dict[str, Any] | None = None,
        quality_json: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_tubelets (
                session_id, stream_id, camera_id, track_id, route_name, tubelet_key,
                start_frame_id, end_frame_id, frame_sample_ids, detection_ids,
                window_start_ts, window_end_ts, sample_fps, tubelet_frames, stride,
                duration_sec, bbox_sequence_json, feature_values_json,
                dominant_features_json, quality_json, metadata_json
            )
            VALUES (
                %(session_id)s, %(stream_id)s, %(camera_id)s, %(track_id)s, %(route_name)s, %(tubelet_key)s,
                %(start_frame_id)s, %(end_frame_id)s, %(frame_sample_ids)s, %(detection_ids)s,
                %(window_start_ts)s, %(window_end_ts)s, %(sample_fps)s, %(tubelet_frames)s, %(stride)s,
                %(duration_sec)s, %(bbox_sequence_json)s::jsonb, %(feature_values_json)s::jsonb,
                %(dominant_features_json)s::jsonb, %(quality_json)s::jsonb, %(metadata_json)s::jsonb
            )
            ON CONFLICT (tubelet_key) DO UPDATE SET
                feature_values_json = EXCLUDED.feature_values_json,
                dominant_features_json = EXCLUDED.dominant_features_json,
                quality_json = EXCLUDED.quality_json,
                metadata_json = EXCLUDED.metadata_json
            RETURNING id
            """,
            {
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "track_id": track_id,
                "route_name": route_name,
                "tubelet_key": tubelet_key,
                "start_frame_id": start_frame_id,
                "end_frame_id": end_frame_id,
                "frame_sample_ids": frame_sample_ids,
                "detection_ids": detection_ids,
                "window_start_ts": window_start_ts,
                "window_end_ts": window_end_ts,
                "sample_fps": sample_fps,
                "tubelet_frames": tubelet_frames,
                "stride": stride,
                "duration_sec": duration_sec,
                "bbox_sequence_json": _json(bbox_sequence_json),
                "feature_values_json": _json(feature_values_json),
                "dominant_features_json": _json(dominant_features_json or {}),
                "quality_json": _json(quality_json or {}),
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def insert_gate_score(
        self,
        conn: psycopg.Connection,
        *,
        tubelet_id: int,
        gate_name: str,
        gate_model_version_id: int | None,
        threshold_id: int | None,
        raw_score: float,
        smoothed_score: float,
        threshold_key: str,
        threshold_value: float,
        threshold_percentile: float | None,
        above_threshold: bool,
        persistence_window: int,
        persistence_required_hits: int,
        persistence_hits: int,
        persistent: bool,
        trigger_recommendation: str,
        feature_values_json: dict[str, Any],
        dominant_features_json: dict[str, Any] | None = None,
        score_metadata_json: dict[str, Any] | None = None,
        quality_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_gate_scores (
                tubelet_id, gate_name, gate_model_version_id, threshold_id,
                raw_score, smoothed_score, threshold_key, threshold_value,
                threshold_percentile, score_direction, above_threshold,
                persistence_window, persistence_required_hits, persistence_hits,
                persistent, trigger_recommendation, feature_values_json,
                dominant_features_json, score_metadata_json, quality_json
            )
            VALUES (
                %(tubelet_id)s, %(gate_name)s, %(gate_model_version_id)s, %(threshold_id)s,
                %(raw_score)s, %(smoothed_score)s, %(threshold_key)s, %(threshold_value)s,
                %(threshold_percentile)s, 'higher_is_more_anomalous', %(above_threshold)s,
                %(persistence_window)s, %(persistence_required_hits)s, %(persistence_hits)s,
                %(persistent)s, %(trigger_recommendation)s, %(feature_values_json)s::jsonb,
                %(dominant_features_json)s::jsonb, %(score_metadata_json)s::jsonb, %(quality_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "tubelet_id": tubelet_id,
                "gate_name": gate_name,
                "gate_model_version_id": gate_model_version_id,
                "threshold_id": threshold_id,
                "raw_score": raw_score,
                "smoothed_score": smoothed_score,
                "threshold_key": threshold_key,
                "threshold_value": threshold_value,
                "threshold_percentile": threshold_percentile,
                "above_threshold": above_threshold,
                "persistence_window": persistence_window,
                "persistence_required_hits": persistence_required_hits,
                "persistence_hits": persistence_hits,
                "persistent": persistent,
                "trigger_recommendation": trigger_recommendation,
                "feature_values_json": _json(feature_values_json),
                "dominant_features_json": _json(dominant_features_json or {}),
                "score_metadata_json": _json(score_metadata_json or {}),
                "quality_json": _json(quality_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def insert_gate_event(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        track_id: int | None,
        gate_name: str,
        gate_model_version_id: int | None,
        tubelet_id: int,
        score_id: int,
        event_key: str,
        severity: str,
        event_type: str,
        start_ts: datetime,
        peak_ts: datetime | None = None,
        peak_score: float,
        threshold_value: float,
        persistence_hits: int,
        persistence_window: int,
        reason_when_fired: str,
        trigger_policy_json: dict[str, Any] | None = None,
        feature_values_json: dict[str, Any] | None = None,
        dominant_features_json: dict[str, Any] | None = None,
        quality_json: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_gate_events (
                session_id, stream_id, camera_id, track_id, gate_name, gate_model_version_id,
                start_tubelet_id, peak_tubelet_id, start_score_id, peak_score_id,
                event_key, status, severity, event_type, start_ts, peak_ts,
                peak_score, threshold_value, persistence_hits, persistence_window,
                reason_when_fired, trigger_policy_json, feature_values_json,
                dominant_features_json, quality_json, metadata_json
            )
            VALUES (
                %(session_id)s, %(stream_id)s, %(camera_id)s, %(track_id)s, %(gate_name)s, %(gate_model_version_id)s,
                %(tubelet_id)s, %(tubelet_id)s, %(score_id)s, %(score_id)s,
                %(event_key)s, 'open', %(severity)s, %(event_type)s, %(start_ts)s, COALESCE(%(peak_ts)s, %(start_ts)s),
                %(peak_score)s, %(threshold_value)s, %(persistence_hits)s, %(persistence_window)s,
                %(reason_when_fired)s, %(trigger_policy_json)s::jsonb, %(feature_values_json)s::jsonb,
                %(dominant_features_json)s::jsonb, %(quality_json)s::jsonb, %(metadata_json)s::jsonb
            )
            ON CONFLICT (event_key) DO UPDATE SET
                peak_tubelet_id = EXCLUDED.peak_tubelet_id,
                peak_score_id = EXCLUDED.peak_score_id,
                peak_ts = EXCLUDED.peak_ts,
                peak_score = EXCLUDED.peak_score,
                metadata_json = COALESCE(vad_gate_events.metadata_json, '{}'::jsonb) || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "track_id": track_id,
                "gate_name": gate_name,
                "gate_model_version_id": gate_model_version_id,
                "tubelet_id": tubelet_id,
                "score_id": score_id,
                "event_key": event_key,
                "severity": severity,
                "event_type": event_type,
                "start_ts": start_ts,
                "peak_ts": peak_ts,
                "peak_score": peak_score,
                "threshold_value": threshold_value,
                "persistence_hits": persistence_hits,
                "persistence_window": persistence_window,
                "reason_when_fired": reason_when_fired,
                "trigger_policy_json": _json(trigger_policy_json or {}),
                "feature_values_json": _json(feature_values_json or {}),
                "dominant_features_json": _json(dominant_features_json or {}),
                "quality_json": _json(quality_json or {}),
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def insert_anomaly_case_for_gate_event(
        self,
        conn: psycopg.Connection,
        *,
        case_key: str,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        primary_track_id: int | None,
        severity: str,
        case_type: str,
        start_ts: datetime,
        peak_ts: datetime | None = None,
        peak_score: float,
        primary_gate_name: str,
        gate_summary_json: dict[str, Any] | None = None,
        score_summary_json: dict[str, Any] | None = None,
        evidence_bundle_json: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_anomaly_cases (
                case_key, session_id, stream_id, camera_id, primary_track_id,
                status, severity, case_type, start_ts, peak_ts, primary_gate_name,
                gate_summary_json, score_summary_json, evidence_bundle_json, metadata_json
            )
            VALUES (
                %(case_key)s, %(session_id)s, %(stream_id)s, %(camera_id)s, %(primary_track_id)s,
                'open', %(severity)s, %(case_type)s, %(start_ts)s, %(peak_ts)s, %(primary_gate_name)s,
                %(gate_summary_json)s::jsonb, %(score_summary_json)s::jsonb, %(evidence_bundle_json)s::jsonb, %(metadata_json)s::jsonb
            )
            ON CONFLICT (case_key) DO UPDATE SET
                peak_ts = EXCLUDED.peak_ts,
                metadata_json = COALESCE(vad_anomaly_cases.metadata_json, '{}'::jsonb) || EXCLUDED.metadata_json,
                updated_at = NOW()
            RETURNING id
            """,
            {
                "case_key": case_key,
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "primary_track_id": primary_track_id,
                "severity": severity,
                "case_type": case_type,
                "start_ts": start_ts,
                "peak_ts": peak_ts or start_ts,
                "primary_gate_name": primary_gate_name,
                "gate_summary_json": _json(gate_summary_json or {}),
                "score_summary_json": _json(score_summary_json or {}),
                "evidence_bundle_json": _json(evidence_bundle_json or {}),
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    
    def update_anomaly_case_evidence_bundle(
        self,
        conn: psycopg.Connection,
        *,
        case_id: int,
        evidence_bundle_json: dict[str, Any],
    ) -> None:
        """Persist final evidence references on the anomaly case after MinIO upload.

        The case is created before visual evidence is written, so it starts with a
        pending bundle. Updating it here keeps the case table/UI consistent with
        vad_media_objects and vad_evidence_items.
        """
        conn.execute(
            """
            UPDATE vad_anomaly_cases
            SET evidence_bundle_json = %(evidence_bundle_json)s::jsonb,
                updated_at = NOW()
            WHERE id = %(case_id)s
            """,
            {
                "case_id": int(case_id),
                "evidence_bundle_json": _json(evidence_bundle_json or {}),
            },
        )

    def get_recent_gate_events(self, conn: psycopg.Connection, *, limit: int = 50, gate_name: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT e.id, e.event_key, e.gate_name, e.severity, e.start_ts, e.peak_ts, e.peak_score,
                   e.threshold_value, e.persistence_hits, e.persistence_window, e.track_id,
                   t.tracker_track_id, t.global_track_key,
                   e.reason_when_fired
            FROM vad_gate_events e
            LEFT JOIN vad_tracks t ON e.track_id = t.id
            WHERE 1=1
        """
        params: dict[str, Any] = {}
        if gate_name:
            query += " AND e.gate_name = %(gate_name)s"
            params["gate_name"] = gate_name
        query += " ORDER BY e.start_ts DESC LIMIT %(limit)s"
        params["limit"] = limit
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_event_evidence(self, conn: psycopg.Connection, *, event_id: int) -> list[dict[str, Any]]:
        query = """
            SELECT m.id, m.media_role, m.media_type, m.object_key, m.uri, m.content_type, m.metadata_json
            FROM vad_media_objects m
            JOIN vad_evidence_items i ON i.media_object_id = m.id
            WHERE i.gate_event_id = %(event_id)s
            ORDER BY i.evidence_rank ASC
        """
        rows = conn.execute(query, {"event_id": event_id}).fetchall()
        return [dict(r) for r in rows]

    def link_case_gate_event(self, conn: psycopg.Connection, *, case_id: int, gate_event_id: int, relation: str = "primary") -> None:
        conn.execute(
            """
            INSERT INTO vad_case_gate_events (case_id, gate_event_id, relation)
            VALUES (%(case_id)s, %(gate_event_id)s, %(relation)s)
            ON CONFLICT (case_id, gate_event_id) DO UPDATE SET relation = EXCLUDED.relation
            """,
            {"case_id": case_id, "gate_event_id": gate_event_id, "relation": relation},
        )

    def get_overlapping_gate_event_with_evidence(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        db_track_id: int,
        my_gate_event_id: int,
        my_start_ts: datetime,
        my_peak_ts: datetime,
        my_gate_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Return overlapping opposite Deep/Pose event with uploaded evidence.

        This is correlation metadata only.  It deliberately excludes same-gate
        overlaps and Homography, so a Deep/Deep, Pose/Pose, or Homography event
        cannot be mislabeled as a Deep+Pose co-fire.
        """
        my_gate = str(my_gate_name or "").strip().lower()
        if my_gate == "deep":
            other_gate = "pose"
        elif my_gate == "pose":
            other_gate = "deep"
        else:
            other_gate = None

        row = conn.execute(
            """
            SELECT
                e.id,
                e.gate_name,
                e.start_ts,
                e.peak_ts,
                e.track_id,
                c.id AS case_id,
                c.evidence_bundle_json
            FROM vad_gate_events e
            JOIN vad_case_gate_events cge ON cge.gate_event_id = e.id
            JOIN vad_anomaly_cases c ON c.id = cge.case_id
            WHERE e.session_id = %(session_id)s
              AND e.track_id = %(track_id)s
              AND e.id != %(my_gate_event_id)s
              AND e.gate_name IN ('deep', 'pose')
              AND (%(other_gate)s IS NULL OR e.gate_name = %(other_gate)s)
              AND e.start_ts < %(my_peak_ts)s
              AND e.peak_ts > %(my_start_ts)s
              AND c.evidence_bundle_json->>'status' = 'uploaded'
            ORDER BY e.id DESC
            LIMIT 1
            """,
            {
                "session_id": int(session_id),
                "track_id": int(db_track_id),
                "my_gate_event_id": int(my_gate_event_id),
                "my_start_ts": my_start_ts,
                "my_peak_ts": my_peak_ts,
                "other_gate": other_gate,
            },
        ).fetchone()
        return dict(row) if row else None



    def get_existing_reasoning_job_for_gate_event(
        self,
        conn: psycopg.Connection,
        *,
        case_id: int,
        gate_event_id: int,
        gate_name: str = "deep",
    ) -> dict[str, Any] | None:
        """Return an existing reasoning job for the same gate event, if one exists.

        The current schema stores the source gate event in metadata_json instead
        of a dedicated foreign-key column, so the duplicate check is JSONB-based.
        """
        row = conn.execute(
            """
            SELECT id, case_id, status, reasoner_type, priority, prompt_version,
                   attempts, max_attempts, queued_at, started_at, finished_at,
                   error_json, metadata_json
            FROM vad_reasoning_jobs
            WHERE case_id = %(case_id)s
              AND metadata_json @> %(source_metadata)s::jsonb
            ORDER BY queued_at DESC, id DESC
            LIMIT 1
            """,
            {
                "case_id": case_id,
                "source_metadata": _json({
                    "source_gate_event_id": int(gate_event_id),
                    "source_gate_name": str(gate_name),
                }),
            },
        ).fetchone()
        return dict(row) if row else None

    def insert_reasoning_job(
        self,
        conn: psycopg.Connection,
        *,
        case_id: int,
        reasoner_type: str = "vlm_llm",
        priority: str = "normal",
        input_bundle_json: dict[str, Any] | None = None,
        prompt_version: str | None = None,
        max_attempts: int = 3,
        metadata_json: dict[str, Any] | None = None,
        vlm_model: str | None = None,
        llm_model: str | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_reasoning_jobs (
                case_id, status, reasoner_type, vlm_model, llm_model, priority,
                input_bundle_json, prompt_version, max_attempts, metadata_json
            )
            VALUES (
                %(case_id)s, 'queued', %(reasoner_type)s, %(vlm_model)s, %(llm_model)s, %(priority)s,
                %(input_bundle_json)s::jsonb, %(prompt_version)s, %(max_attempts)s, %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "case_id": case_id,
                "reasoner_type": reasoner_type,
                "vlm_model": vlm_model,
                "llm_model": llm_model,
                "priority": priority,
                "input_bundle_json": _json(input_bundle_json or {}),
                "prompt_version": prompt_version,
                "max_attempts": max_attempts,
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def get_reasoning_jobs_for_gate_event(
        self,
        conn: psycopg.Connection,
        *,
        gate_event_id: int,
        gate_name: str | None = None,
    ) -> list[dict[str, Any]]:
        source = {"source_gate_event_id": int(gate_event_id)}
        if gate_name:
            source["source_gate_name"] = str(gate_name)
        rows = conn.execute(
            """
            SELECT id, case_id, status, reasoner_type, priority, prompt_version,
                   attempts, max_attempts, queued_at, started_at, finished_at,
                   error_json, metadata_json
            FROM vad_reasoning_jobs
            WHERE metadata_json @> %(source_metadata)s::jsonb
            ORDER BY queued_at DESC, id DESC
            """,
            {"source_metadata": _json(source)},
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_reasoning_jobs(
        self,
        conn: psycopg.Connection,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT id, case_id, status, reasoner_type, priority, prompt_version,
                   attempts, max_attempts, queued_at, started_at, finished_at,
                   error_json, metadata_json
            FROM vad_reasoning_jobs
            WHERE 1=1
        """
        params: dict[str, Any] = {"limit": limit}
        if status:
            query += " AND status = %(status)s"
            params["status"] = status
        query += " ORDER BY queued_at DESC, id DESC LIMIT %(limit)s"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_joined_reasoning_jobs(
        self,
        conn: psycopg.Connection,
        *,
        status: str | None = None,
        decision: str | None = None,
        case_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT 
                j.id AS job_id, j.case_id AS j_case_id, j.status AS job_status, j.reasoner_type, 
                j.vlm_model, j.llm_model, j.priority,
                j.prompt_version, j.attempts, j.max_attempts, j.queued_at, j.started_at, j.finished_at,
                j.error_json, j.input_bundle_json, j.metadata_json AS job_metadata_json,
                
                c.id AS case_table_id, c.case_key, c.primary_gate_name, c.case_type,
                c.status AS case_status, c.severity AS case_severity, c.start_ts, c.peak_ts,
                c.score_summary_json, c.evidence_bundle_json, c.created_at AS case_created_at,
                
                r.id AS result_id, r.reasoning_job_id, r.alert_decision, r.severity AS result_severity, 
                r.event_type, r.confidence, r.policy_version, r.rules_version,
                r.structured_output_json, r.matched_rules_json, r.uncertainty_json,
                r.raw_vlm_output, r.raw_llm_output,
                r.vlm_visual_review_json, r.llm_policy_review_json,
                r.python_final_result_json, r.created_at AS result_created_at
            FROM vad_reasoning_jobs j
            LEFT JOIN vad_anomaly_cases c ON j.case_id = c.id
            LEFT JOIN LATERAL (
                SELECT * FROM vad_reasoning_results rr
                WHERE rr.reasoning_job_id = j.id
                ORDER BY rr.id DESC LIMIT 1
            ) r ON true
            WHERE 1=1
        """
        params: dict[str, Any] = {"limit": limit}
        
        if status:
            query += " AND j.status = %(status)s"
            params["status"] = status
            
        if case_id:
            query += " AND j.case_id = %(case_id)s"
            params["case_id"] = case_id
            
        if decision:
            query += " AND r.alert_decision = %(decision)s"
            params["decision"] = decision
            
        query += " ORDER BY j.queued_at DESC, j.id DESC LIMIT %(limit)s"
        
        rows = conn.execute(query, params).fetchall()
        
        # Format the output to separate job, case, and result fields
        result_list = []
        for r in rows:
            row_dict = dict(r)
            item = {
                "job": {
                    "id": row_dict["job_id"],
                    "case_id": row_dict["j_case_id"],
                    "status": row_dict["job_status"],
                    "reasoner_type": row_dict.get("reasoner_type"),
                    "vlm_model": row_dict.get("vlm_model"),
                    "llm_model": row_dict.get("llm_model"),
                    "priority": row_dict.get("priority"),
                    "prompt_version": row_dict.get("prompt_version"),
                    "attempts": row_dict.get("attempts"),
                    "max_attempts": row_dict.get("max_attempts"),
                    "queued_at": row_dict.get("queued_at"),
                    "started_at": row_dict.get("started_at"),
                    "finished_at": row_dict.get("finished_at"),
                    "error_json": row_dict.get("error_json"),
                    "input_bundle_json": row_dict.get("input_bundle_json"),
                    "metadata_json": row_dict.get("job_metadata_json")
                },
                "case": None,
                "result": None
            }
            
            if row_dict.get("case_table_id") is not None:
                item["case"] = {
                    "id": row_dict["case_table_id"],
                    "case_key": row_dict.get("case_key"),
                    "primary_gate_name": row_dict.get("primary_gate_name"),
                    "case_type": row_dict.get("case_type"),
                    "status": row_dict.get("case_status"),
                    "severity": row_dict.get("case_severity"),
                    "start_ts": row_dict.get("start_ts"),
                    "peak_ts": row_dict.get("peak_ts"),
                    "score_summary_json": row_dict.get("score_summary_json"),
                    "evidence_bundle_json": row_dict.get("evidence_bundle_json"),
                    "created_at": row_dict.get("case_created_at")
                }
                
            if row_dict.get("result_id") is not None:
                item["result"] = {
                    "id": row_dict["result_id"],
                    "reasoning_job_id": row_dict.get("reasoning_job_id"),
                    "case_id": row_dict.get("j_case_id"),
                    "alert_decision": row_dict.get("alert_decision"),
                    "severity": row_dict.get("result_severity"),
                    "event_type": row_dict.get("event_type"),
                    "confidence": row_dict.get("confidence"),
                    "policy_version": row_dict.get("policy_version"),
                    "rules_version": row_dict.get("rules_version"),
                    "structured_output_json": row_dict.get("structured_output_json"),
                    "matched_rules_json": row_dict.get("matched_rules_json"),
                    "uncertainty_json": row_dict.get("uncertainty_json"),
                    "raw_vlm_output": row_dict.get("raw_vlm_output"),
                    "raw_llm_output": row_dict.get("raw_llm_output"),
                    "vlm_visual_review_json": row_dict.get("vlm_visual_review_json"),
                    "llm_policy_review_json": row_dict.get("llm_policy_review_json"),
                    "python_final_result_json": row_dict.get("python_final_result_json"),
                    "created_at": row_dict.get("result_created_at")
                }
                
            result_list.append(item)
            
        return result_list



    # NOTE: The old claim_next_deep_reasoning_job() method was removed.
    # Current architecture is gate-generic: the worker calls
    # claim_next_reasoning_job(gate_name="deep") and
    # claim_next_reasoning_job(gate_name="pose").

    def claim_next_reasoning_job(
        self,
        conn: psycopg.Connection,
        *,
        gate_name: str,
        vlm_model: str | None = None,
        llm_model: str | None = None,
        max_age_sec: float | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim one queued reasoning job for the given gate_name.

        Generic queue claiming for Deep and Pose reasoning jobs.

        The worker calls this method with gate_name="deep" or gate_name="pose".
        Homography jobs are intentionally not queued for VLM/LLM reasoning.
        """
        if max_age_sec is not None:
            conn.execute(
                """
                UPDATE vad_reasoning_jobs
                SET status = 'failed', finished_at = NOW(),
                    error_json = '{"reason": "job_too_old_skipped"}'::jsonb
                WHERE status = 'queued'
                  AND attempts < max_attempts
                  AND (
                        metadata_json @> %(source_metadata)s::jsonb
                        OR metadata_json ->> 'source_gate_name' = %(gate_name)s
                        OR input_bundle_json -> 'event' ->> 'gate_name' = %(gate_name)s
                        OR input_bundle_json ->> 'reasoning_scope' = %(reasoning_scope)s
                  )
                  AND queued_at < NOW() - (%(max_age_sec)s || ' seconds')::interval
                """,
                {
                    "source_metadata": _json({"source_gate_name": str(gate_name)}),
                    "gate_name": str(gate_name),
                    "reasoning_scope": f"{str(gate_name)}_gate_only",
                    "max_age_sec": float(max_age_sec),
                },
            )

        row = conn.execute(
            """
            WITH next_job AS (
                SELECT id
                FROM vad_reasoning_jobs
                WHERE status = 'queued'
                  AND attempts < max_attempts
                  AND (
                        metadata_json @> %(source_metadata)s::jsonb
                        OR metadata_json ->> 'source_gate_name' = %(gate_name)s
                        OR input_bundle_json -> 'event' ->> 'gate_name' = %(gate_name)s
                        OR input_bundle_json ->> 'reasoning_scope' = %(reasoning_scope)s
                  )
                ORDER BY
                    CASE priority
                        WHEN 'urgent' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'normal' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    queued_at ASC,
                    id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE vad_reasoning_jobs j
            SET status = 'running',
                attempts = attempts + 1,
                started_at = NOW(),
                finished_at = NULL,
                vlm_model = COALESCE(%(vlm_model)s, vlm_model),
                llm_model = COALESCE(%(llm_model)s, llm_model),
                error_json = '{}'::jsonb
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.*
            """,
            {
                "source_metadata": _json({"source_gate_name": str(gate_name)}),
                "gate_name": str(gate_name),
                "reasoning_scope": f"{str(gate_name)}_gate_only",
                "vlm_model": vlm_model,
                "llm_model": llm_model,
            },
        ).fetchone()
        return dict(row) if row else None
    def mark_reasoning_job_succeeded(
        self,
        conn: psycopg.Connection,
        *,
        job_id: int,
    ) -> None:
        conn.execute(
            """
            UPDATE vad_reasoning_jobs
            SET status = 'succeeded', finished_at = NOW(), error_json = '{}'::jsonb
            WHERE id = %(job_id)s
            """,
            {"job_id": int(job_id)},
        )

    def mark_reasoning_job_failed(
        self,
        conn: psycopg.Connection,
        *,
        job_id: int,
        error_json: dict[str, Any] | None = None,
        retry: bool = False,
    ) -> None:
        conn.execute(
            """
            UPDATE vad_reasoning_jobs
            SET status = CASE WHEN %(retry)s THEN 'queued' ELSE 'failed' END,
                finished_at = CASE WHEN %(retry)s THEN NULL ELSE NOW() END,
                error_json = %(error_json)s::jsonb
            WHERE id = %(job_id)s
            """,
            {"job_id": int(job_id), "retry": bool(retry), "error_json": _json(error_json or {})},
        )

    def insert_reasoning_result(
        self,
        conn: psycopg.Connection,
        *,
        reasoning_job_id: int,
        case_id: int,
        alert_decision: str | None = None,
        severity: str | None = None,
        event_type: str | None = None,
        confidence: float | None = None,
        visual_evidence: str | None = None,
        reasoning_summary: str | None = None,
        decision_reason: str | None = None,
        raw_vlm_output: str | None = None,
        raw_llm_output: str | None = None,
        structured_output_json: dict[str, Any] | None = None,
        matched_rules_json: dict[str, Any] | None = None,
        uncertainty_json: dict[str, Any] | None = None,
        vlm_visual_review_json: dict[str, Any] | None = None,
        llm_policy_review_json: dict[str, Any] | None = None,
        python_final_result_json: dict[str, Any] | None = None,
        policy_version: str | None = None,
        rules_version: str | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_reasoning_results (
                reasoning_job_id, case_id, alert_decision, severity, event_type,
                confidence, visual_evidence, reasoning_summary, decision_reason,
                raw_vlm_output, raw_llm_output, structured_output_json,
                matched_rules_json, uncertainty_json, vlm_visual_review_json,
                llm_policy_review_json, python_final_result_json, policy_version, rules_version
            )
            VALUES (
                %(reasoning_job_id)s, %(case_id)s, %(alert_decision)s, %(severity)s, %(event_type)s,
                %(confidence)s, %(visual_evidence)s, %(reasoning_summary)s, %(decision_reason)s,
                %(raw_vlm_output)s, %(raw_llm_output)s, %(structured_output_json)s::jsonb,
                %(matched_rules_json)s::jsonb, %(uncertainty_json)s::jsonb, %(vlm_visual_review_json)s::jsonb,
                %(llm_policy_review_json)s::jsonb, %(python_final_result_json)s::jsonb, %(policy_version)s, %(rules_version)s
            )
            RETURNING id
            """,
            {
                "reasoning_job_id": int(reasoning_job_id),
                "case_id": int(case_id),
                "alert_decision": alert_decision,
                "severity": severity,
                "event_type": event_type,
                "confidence": confidence,
                "visual_evidence": visual_evidence,
                "reasoning_summary": reasoning_summary,
                "decision_reason": decision_reason,
                "raw_vlm_output": raw_vlm_output,
                "raw_llm_output": raw_llm_output,
                "structured_output_json": _json(structured_output_json or {}),
                "matched_rules_json": _json(matched_rules_json or {}),
                "uncertainty_json": _json(uncertainty_json or {}),
                "vlm_visual_review_json": _json(vlm_visual_review_json or {}),
                "llm_policy_review_json": _json(llm_policy_review_json or {}),
                "python_final_result_json": _json(python_final_result_json or {}),
                "policy_version": policy_version,
                "rules_version": rules_version,
            },
        ).fetchone()
        return int(row["id"])

    def get_reasoning_results_for_gate_event(
        self,
        conn: psycopg.Connection,
        *,
        gate_event_id: int,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT r.*
            FROM vad_reasoning_results r
            JOIN vad_reasoning_jobs j ON j.id = r.reasoning_job_id
            WHERE j.metadata_json @> %(source_metadata)s::jsonb
            ORDER BY r.created_at DESC, r.id DESC
            """,
            {"source_metadata": _json({"source_gate_event_id": int(gate_event_id)})},
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_media_object(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int | None,
        stream_id: int | None,
        camera_id: int | None,
        case_id: int | None,
        gate_event_id: int | None,
        tubelet_id: int | None,
        frame_id: int | None,
        media_role: str,
        media_type: str,
        storage_backend: str,
        bucket: str | None,
        object_key: str | None,
        uri: str | None,
        content_type: str | None,
        size_bytes: int | None,
        width: int | None = None,
        height: int | None = None,
        duration_sec: float | None = None,
        sha256: str | None = None,
        captured_at: datetime | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_media_objects (
                session_id, stream_id, camera_id, case_id, gate_event_id, tubelet_id, frame_id,
                media_role, media_type, storage_backend, bucket, object_key, uri,
                content_type, size_bytes, width, height, duration_sec, sha256, captured_at, metadata_json
            )
            VALUES (
                %(session_id)s, %(stream_id)s, %(camera_id)s, %(case_id)s, %(gate_event_id)s, %(tubelet_id)s, %(frame_id)s,
                %(media_role)s, %(media_type)s, %(storage_backend)s, %(bucket)s, %(object_key)s, %(uri)s,
                %(content_type)s, %(size_bytes)s, %(width)s, %(height)s, %(duration_sec)s, %(sha256)s, %(captured_at)s, %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "session_id": session_id,
                "stream_id": stream_id,
                "camera_id": camera_id,
                "case_id": case_id,
                "gate_event_id": gate_event_id,
                "tubelet_id": tubelet_id,
                "frame_id": frame_id,
                "media_role": media_role,
                "media_type": media_type,
                "storage_backend": storage_backend,
                "bucket": bucket,
                "object_key": object_key,
                "uri": uri,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "width": width,
                "height": height,
                "duration_sec": duration_sec,
                "sha256": sha256,
                "captured_at": captured_at,
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    def insert_evidence_item(
        self,
        conn: psycopg.Connection,
        *,
        case_id: int,
        gate_event_id: int | None,
        media_object_id: int | None,
        evidence_role: str,
        evidence_rank: int,
        description: str | None,
        included_in_reasoning: bool,
        metadata_json: dict[str, Any] | None = None,
    ) -> int:
        row = conn.execute(
            """
            INSERT INTO vad_evidence_items (
                case_id, gate_event_id, media_object_id, evidence_role, evidence_rank,
                description, included_in_reasoning, metadata_json
            )
            VALUES (
                %(case_id)s, %(gate_event_id)s, %(media_object_id)s, %(evidence_role)s, %(evidence_rank)s,
                %(description)s, %(included_in_reasoning)s, %(metadata_json)s::jsonb
            )
            RETURNING id
            """,
            {
                "case_id": case_id,
                "gate_event_id": gate_event_id,
                "media_object_id": media_object_id,
                "evidence_role": evidence_role,
                "evidence_rank": evidence_rank,
                "description": description,
                "included_in_reasoning": included_in_reasoning,
                "metadata_json": _json(metadata_json or {}),
            },
        ).fetchone()
        return int(row["id"])

    # ------------------------------------------------------------------
    # VAD Reasoning Rules (vad_reasoning_rules table)
    # ------------------------------------------------------------------

    def get_active_vad_reasoning_rules(self, conn: psycopg.Connection) -> list[dict[str, Any]]:
        """Return all active rows from vad_reasoning_rules ordered by priority then id.

        Returns an empty list (rather than raising) if the table does not yet
        exist so the reasoning pipeline keeps working before the migration runs.
        """
        try:
            rows = conn.execute(
                """
                SELECT id, rule_name, rule_type, event_types, conditions, effect,
                       source, active, description
                FROM vad_reasoning_rules
                WHERE active = TRUE
                ORDER BY priority ASC NULLS LAST, id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            # Table likely doesn't exist yet — caller will use built-in fallback.
            return []

    def insert_vad_reasoning_rule(
        self,
        conn: psycopg.Connection,
        *,
        rule_name: str,
        rule_type: str,
        event_types: list[str],
        conditions: dict[str, Any] | None = None,
        effect: dict[str, Any] | None = None,
        source: str = "admin",
        description: str = "",
        priority: int = 50,
    ) -> int:
        """Insert a new rule into vad_reasoning_rules and return its id."""
        row = conn.execute(
            """
            INSERT INTO vad_reasoning_rules (
                rule_name, rule_type, event_types, conditions, effect,
                source, active, description, priority
            )
            VALUES (
                %(rule_name)s, %(rule_type)s, %(event_types)s::jsonb, %(conditions)s::jsonb,
                %(effect)s::jsonb, %(source)s, TRUE, %(description)s, %(priority)s
            )
            RETURNING id
            """,
            {
                "rule_name": rule_name,
                "rule_type": rule_type,
                "event_types": _json(event_types),
                "conditions": _json(conditions or {}),
                "effect": _json(effect or {}),
                "source": source,
                "description": description,
                "priority": priority,
            },
        ).fetchone()
        return int(row["id"])

    def deactivate_vad_reasoning_rule(self, conn: psycopg.Connection, *, rule_id: int) -> bool:
        """Soft-delete a rule by setting active=FALSE.  Returns True if updated."""
        row = conn.execute(
            """
            UPDATE vad_reasoning_rules
            SET active = FALSE, updated_at = NOW()
            WHERE id = %(rule_id)s
            RETURNING id
            """,
            {"rule_id": int(rule_id)},
        ).fetchone()
        return bool(row)

    def delete_vad_reasoning_rule(self, conn: psycopg.Connection, *, rule_id: int) -> bool:
        """Hard-delete a rule row.  Returns True if a row was deleted."""
        row = conn.execute(
            "DELETE FROM vad_reasoning_rules WHERE id = %(rule_id)s RETURNING id",
            {"rule_id": int(rule_id)},
        ).fetchone()
        return bool(row)

    def get_all_vad_reasoning_rules(self, conn: psycopg.Connection) -> list[dict[str, Any]]:
        """Return all rules (active and inactive) for admin/UI listing."""
        try:
            rows = conn.execute(
                """
                SELECT id, rule_name, rule_type, event_types, conditions, effect,
                       source, active, description, priority, created_at, updated_at
                FROM vad_reasoning_rules
                ORDER BY priority ASC NULLS LAST, id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


