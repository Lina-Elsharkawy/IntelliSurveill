from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

import cv2
import numpy as np
import psycopg

from .config import VadConfig
from .db import VadDB
from .frame_types import SampledPerson
from .minio_client import VadMinioClient, UploadedObject

log = logging.getLogger("vad.evidence_writer")


@dataclass(frozen=True)
class EvidenceWriteResult:
    media_object_ids: list[int]
    evidence_item_ids: list[int]
    object_keys: list[str]


class EvidenceWriter:
    """Writes event-only visual/JSON evidence to MinIO and records DB refs.

    It intentionally does not upload raw stream frames. It only runs after a
    gate event is emitted.
    """

    def __init__(self, cfg: VadConfig, db: VadDB, minio_client: VadMinioClient) -> None:
        self.cfg = cfg
        self.db = db
        self.minio = minio_client

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, (np.floating, np.integer)):
            return value.item()
        return str(value)

    def _encode_jpeg(self, frame_bgr: np.ndarray) -> bytes:
        ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.cfg.jpeg_quality)])
        if not ok:
            raise RuntimeError("cv2.imencode(.jpg) failed")
        return encoded.tobytes()

    @staticmethod
    def _draw_box(frame: np.ndarray, sample: SampledPerson, lines: Sequence[str]) -> np.ndarray:
        out = frame.copy()
        x1, y1, x2, y2 = [int(round(float(v))) for v in sample.bbox_xyxy]
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)
        y = max(18, y1 - 8)
        for line in lines:
            cv2.putText(out, str(line), (max(0, x1), y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
            y += 22
        return out

    @staticmethod
    def _make_montage(samples: Sequence[SampledPerson], width: int = 320, cols: int = 4) -> np.ndarray | None:
        if not samples:
            return None
        imgs: list[np.ndarray] = []
        for s in samples:
            img = EvidenceWriter._draw_box(s.frame_bgr, s, [f"track={s.tracker_track_id}", f"sample={s.sample_index}"])
            h, w = img.shape[:2]
            scale = width / max(1, w)
            imgs.append(cv2.resize(img, (width, max(1, int(round(h * scale))))))
        if not imgs:
            return None
        max_h = max(i.shape[0] for i in imgs)
        padded = []
        for img in imgs:
            if img.shape[0] < max_h:
                img = np.vstack([img, np.zeros((max_h - img.shape[0], img.shape[1], 3), dtype=img.dtype)])
            padded.append(img)
        rows = []
        for i in range(0, len(padded), cols):
            row = padded[i:i+cols]
            while len(row) < cols:
                row.append(np.zeros_like(padded[0]))
            rows.append(np.hstack(row))
        return np.vstack(rows)

    def _key_prefix(self, *, gate_name: str, session_id: int, track_id: int | None, event_id: int) -> str:
        prefix = self.cfg.evidence_prefix or "vad"
        return (
            f"{prefix}/{self.cfg.stream_key}/session_{session_id}/"
            f"{gate_name}/track_{track_id or 'none'}/event_{event_id:06d}"
        )

    def _record_upload(
        self,
        conn: psycopg.Connection,
        *,
        upload: UploadedObject,
        media_role: str,
        media_type: str,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        gate_event_id: int,
        case_id: int,
        tubelet_id: int | None,
        frame_id: int | None,
        captured_at: datetime | None,
        width: int | None = None,
        height: int | None = None,
        evidence_rank: int = 0,
        description: str = "",
        metadata_json: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        media_id = self.db.insert_media_object(
            conn,
            session_id=session_id,
            stream_id=stream_id,
            camera_id=camera_id,
            case_id=case_id,
            gate_event_id=gate_event_id,
            tubelet_id=tubelet_id,
            frame_id=frame_id,
            media_role=media_role,
            media_type=media_type,
            storage_backend="minio",
            bucket=upload.bucket,
            object_key=upload.object_key,
            uri=upload.uri,
            content_type=upload.content_type,
            size_bytes=upload.size_bytes,
            width=width,
            height=height,
            sha256=upload.sha256,
            captured_at=captured_at,
            metadata_json=metadata_json or {},
        )
        evidence_id = self.db.insert_evidence_item(
            conn,
            case_id=case_id,
            gate_event_id=gate_event_id,
            media_object_id=media_id,
            evidence_role=media_role,
            evidence_rank=evidence_rank,
            description=description,
            included_in_reasoning=True,
            metadata_json=metadata_json or {},
        )
        return media_id, evidence_id

    def write_gate_event_evidence(
        self,
        conn: psycopg.Connection,
        *,
        session_id: int,
        stream_id: int,
        camera_id: int | None,
        gate_name: str,
        gate_event_id: int,
        case_id: int,
        tubelet_id: int,
        score_id: int,
        db_track_id: int | None,
        tracker_track_id: int,
        tubelet_samples: Sequence[SampledPerson],
        gate_summary: dict[str, Any],
    ) -> EvidenceWriteResult:
        if not self.cfg.evidence_enabled or not self.cfg.save_evidence_on_gate_event:
            return EvidenceWriteResult([], [], [])
        if not tubelet_samples:
            return EvidenceWriteResult([], [], [])

        latest = tubelet_samples[-1]
        base_key = self._key_prefix(gate_name=gate_name, session_id=session_id, track_id=db_track_id, event_id=gate_event_id)
        lines = [
            f"{gate_name.upper()} EVENT",
            f"track={tracker_track_id} score={gate_summary.get('raw_score'):.3f}",
            f"smooth={gate_summary.get('smoothed_score'):.3f} thr={gate_summary.get('threshold_value'):.3f}",
        ]

        media_ids: list[int] = []
        evidence_ids: list[int] = []
        object_keys: list[str] = []

        annotated = self._draw_box(latest.frame_bgr, latest, lines)
        h, w = annotated.shape[:2]
        jpg = self._encode_jpeg(annotated)
        up = self.minio.upload_bytes(
            object_key=f"{base_key}/annotated_frame.jpg",
            data=jpg,
            content_type="image/jpeg",
            metadata={"gate": gate_name, "role": "annotated_frame"},
        )
        mid, eid = self._record_upload(
            conn,
            upload=up,
            media_role="annotated_frame",
            media_type="image",
            session_id=session_id,
            stream_id=stream_id,
            camera_id=camera_id,
            gate_event_id=gate_event_id,
            case_id=case_id,
            tubelet_id=tubelet_id,
            frame_id=latest.frame_id,
            captured_at=latest.captured_at,
            width=w,
            height=h,
            evidence_rank=0,
            description=f"Latest annotated frame for {gate_name} gate event",
            metadata_json={"score_id": score_id, "tracker_track_id": tracker_track_id},
        )
        media_ids.append(mid); evidence_ids.append(eid); object_keys.append(up.object_key)

        montage = self._make_montage(tubelet_samples)
        if montage is not None:
            mh, mw = montage.shape[:2]
            up = self.minio.upload_bytes(
                object_key=f"{base_key}/tubelet_montage.jpg",
                data=self._encode_jpeg(montage),
                content_type="image/jpeg",
                metadata={"gate": gate_name, "role": "tubelet_montage"},
            )
            mid, eid = self._record_upload(
                conn,
                upload=up,
                media_role="tubelet_montage",
                media_type="image",
                session_id=session_id,
                stream_id=stream_id,
                camera_id=camera_id,
                gate_event_id=gate_event_id,
                case_id=case_id,
                tubelet_id=tubelet_id,
                frame_id=latest.frame_id,
                captured_at=latest.captured_at,
                width=mw,
                height=mh,
                evidence_rank=1,
                description=f"Tubelet montage for {gate_name} gate event",
                metadata_json={"score_id": score_id, "sample_count": len(tubelet_samples), "tracker_track_id": tracker_track_id},
            )
            media_ids.append(mid); evidence_ids.append(eid); object_keys.append(up.object_key)

        for i, s in enumerate(tubelet_samples):
            f_jpg = self._encode_jpeg(s.frame_bgr)
            fh, fw = s.frame_bgr.shape[:2]
            up = self.minio.upload_bytes(
                object_key=f"{base_key}/frames/frame_{i:03d}.jpg",
                data=f_jpg,
                content_type="image/jpeg",
                metadata={"gate": gate_name, "role": "tubelet_frame", "index": i},
            )
            mid, eid = self._record_upload(
                conn,
                upload=up,
                media_role="tubelet_frame",
                media_type="image",
                session_id=session_id,
                stream_id=stream_id,
                camera_id=camera_id,
                gate_event_id=gate_event_id,
                case_id=case_id,
                tubelet_id=tubelet_id,
                frame_id=s.frame_id,
                captured_at=s.captured_at,
                width=fw,
                height=fh,
                evidence_rank=3,
                description=f"Tubelet frame {i} for {gate_name} gate event",
                metadata_json={
                    "frame_index": i,
                    "sample_index": s.sample_index,
                    "tracker_track_id": tracker_track_id,
                    "gate_name": gate_name,
                    "score_id": score_id,
                    "event_id": gate_event_id
                },
            )
            media_ids.append(mid); evidence_ids.append(eid); object_keys.append(up.object_key)

        metadata_payload = {
            "gate_summary": gate_summary,
            "session_id": session_id,
            "stream_id": stream_id,
            "camera_id": camera_id,
            "gate_event_id": gate_event_id,
            "case_id": case_id,
            "tubelet_id": tubelet_id,
            "score_id": score_id,
            "db_track_id": db_track_id,
            "tracker_track_id": tracker_track_id,
            "samples": [
                {
                    "sample_index": int(s.sample_index),
                    "frame_id": int(s.frame_id) if s.frame_id is not None else None,
                    "detection_id": int(s.detection_id) if s.detection_id is not None else None,
                    "captured_at": s.captured_at.isoformat(),
                    "bbox_xyxy": [float(v) for v in s.bbox_xyxy],
                    "confidence": float(s.confidence) if s.confidence is not None else None,
                }
                for s in tubelet_samples
            ],
        }
        meta_bytes = json.dumps(metadata_payload, ensure_ascii=False, indent=2, default=self._json_default).encode("utf-8")
        up = self.minio.upload_bytes(
            object_key=f"{base_key}/event_metadata.json",
            data=meta_bytes,
            content_type="application/json",
            metadata={"gate": gate_name, "role": "event_metadata"},
        )
        mid, eid = self._record_upload(
            conn,
            upload=up,
            media_role="event_metadata",
            media_type="json",
            session_id=session_id,
            stream_id=stream_id,
            camera_id=camera_id,
            gate_event_id=gate_event_id,
            case_id=case_id,
            tubelet_id=tubelet_id,
            frame_id=latest.frame_id,
            captured_at=latest.captured_at,
            evidence_rank=2,
            description=f"Structured metadata for {gate_name} gate event",
            metadata_json={"score_id": score_id, "tracker_track_id": tracker_track_id},
        )
        media_ids.append(mid); evidence_ids.append(eid); object_keys.append(up.object_key)

        return EvidenceWriteResult(media_ids, evidence_ids, object_keys)
