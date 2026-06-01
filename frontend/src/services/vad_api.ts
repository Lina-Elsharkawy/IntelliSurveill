export const VAD_BASE_URL = "http://localhost:8015/vad/rtsp";

export interface VadStatus {
  running: boolean;
  session_id: number | null;
  stream_key: string | null;
  camera_key: string | null;
  actual_sample_fps: number | null;
  sampled_frame_count: number | null;
  source_frame_count: number | null;
  processed_frame_count: number | null;
  detection_count: number | null;
  tracked_detection_count: number | null;
  active_track_buffer_count: number | null;
  dropped_frame_count: number | null;
  reconnect_count: number | null;
  last_error: string | null;
  track_buffers_preview?: any[];
  [key: string]: any;
}

export interface VadConfig {
  backend_direct_enabled?: boolean;
  autostart?: boolean;
  stream_key?: string;
  [key: string]: any;
}

export interface VadEvent {
  id: number;
  event_key: string;
  gate_name: string;
  severity: string;
  start_ts: string;
  peak_ts: string;
  peak_score: number;
  threshold_value: number;
  persistence_hits: number;
  persistent: boolean;
  track_id: number | null;
  tracker_track_id: number | null;
  global_track_key: string | null;
  reason_when_fired: string | null;
}

export interface VadEventEvidence {
  id: number;
  media_role: string;
  media_type: string;
  object_key: string;
  uri: string;
  content_type: string;
  metadata_json: any;
  presigned_url?: string;
}

export interface VadEventDetails {
  annotated_frame_url?: string;
  tubelet_montage_url?: string;
  frame_urls: string[];
  metadata_url?: string;
  raw_evidence: VadEventEvidence[];
}

/**
 * Defensive helper: if the backend still returns a url containing 'minio:9000',
 * replace it with 'localhost:9000' so the browser can resolve it.
 */
export function normalizeEvidenceUrl(url?: string): string | undefined {
  if (!url) return url;
  return url.replace(/https?:\/\/minio:9000/i, 'http://localhost:9000');
}

export const vadApi = {
  async getConfig(): Promise<VadConfig> {
    const res = await fetch(`${VAD_BASE_URL}/config`);
    if (!res.ok) throw new Error("Failed to fetch VAD config");
    return res.json();
  },

  async getStatus(): Promise<VadStatus> {
    const res = await fetch(`${VAD_BASE_URL}/status`);
    if (!res.ok) throw new Error("Failed to fetch VAD status");
    return res.json();
  },

  async start(): Promise<any> {
    const res = await fetch(`${VAD_BASE_URL}/start`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to start VAD");
    return res.json();
  },

  async stop(): Promise<any> {
    const res = await fetch(`${VAD_BASE_URL}/stop`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to stop VAD");
    return res.json();
  },

  async saveDebugFrame(): Promise<any> {
    const res = await fetch(`${VAD_BASE_URL}/debug/save-latest`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to save debug frame");
    return res.json();
  },

  async getEvents(gate?: string, limit: number = 50): Promise<{ events: VadEvent[] }> {
    let url = `${VAD_BASE_URL}/events?limit=${limit}`;
    if (gate) {
      url += `&gate=${encodeURIComponent(gate)}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error("Failed to fetch VAD events");
    return res.json();
  },

  async getEventDetails(eventId: number): Promise<VadEventDetails> {
    const res = await fetch(`${VAD_BASE_URL}/events/${eventId}`);
    if (!res.ok) throw new Error(`Failed to fetch details for event ${eventId}`);
    const data = await res.json();
    
    const details: VadEventDetails = {
      frame_urls: [],
      raw_evidence: data.evidence || []
    };

    if (data.evidence) {
      const frameEvidence = data.evidence.filter((e: VadEventEvidence) => e.media_role === "tubelet_frame" || e.media_role === "frame");
      frameEvidence.sort((a: VadEventEvidence, b: VadEventEvidence) => {
        const idxA = a.metadata_json?.frame_index ?? a.metadata_json?.index ?? 0;
        const idxB = b.metadata_json?.frame_index ?? b.metadata_json?.index ?? 0;
        return idxA - idxB;
      });
      details.frame_urls = frameEvidence
        .map((e: VadEventEvidence) => normalizeEvidenceUrl(e.presigned_url))
        .filter(Boolean) as string[];

      for (const e of data.evidence) {
        const url = normalizeEvidenceUrl(e.presigned_url);
        if (!url) continue;

        if (e.media_role === "annotated_frame") {
          details.annotated_frame_url = url;
        } else if (e.media_role === "tubelet_montage") {
          details.tubelet_montage_url = url;
        } else if (e.media_role === "event_metadata") {
          details.metadata_url = url;
        }
      }
    }
    return details;
  }
};
