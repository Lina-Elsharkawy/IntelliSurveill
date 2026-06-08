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

export interface VadReasoningJob {
  id: number;
  case_id: number;
  status: string;
  reasoner_type: string;
  prompt_version: string;
  attempts: number;
  max_attempts: number;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_json: any;
  input_bundle_json: any;
  metadata_json: any;
}

export interface VadReasoningCase {
  id: number;
  case_key: string;
  primary_gate_name: string;
  case_type: string;
  status: string;
  severity: string;
  start_ts: string;
  peak_ts: string;
  peak_score: number;
  score_summary_json: any;
  evidence_bundle_json: any;
}

export interface VadReasoningResult {
  id: number;
  alert_decision: string;
  severity: string;
  confidence: number;
  policy_version: string;
  rules_version: string;
  structured_output_json: any;
  vlm_visual_review_json: any;
  llm_policy_review_json: any;
  python_final_result_json: any;
  uncertainty_json: any;
}

export interface VadReasoningListItem {
  job: VadReasoningJob;
  case: VadReasoningCase | null;
  result: VadReasoningResult | null;
}

export interface VadReasoningSummary {
  total: number;
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  final_yes: number;
  final_no: number;
  final_uncertain: number;
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
  },

  async getEvidenceUrls(keys: string[]): Promise<Record<string, string>> {
    if (!keys || keys.length === 0) return {};
    const res = await fetch(`${VAD_BASE_URL}/evidence/urls`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ object_keys: keys })
    });
    if (!res.ok) throw new Error("Failed to fetch evidence urls");
    const data = await res.json();
    return data.urls || {};
  },

  async getReasoningJobs(
    params?: { status?: string; decision?: string; case_id?: number; limit?: number }
  ): Promise<{ items: VadReasoningListItem[], summary: VadReasoningSummary }> {
    const url = new URL(`${VAD_BASE_URL}/reasoning/jobs`);
    if (params) {
      if (params.status && params.status !== 'all') url.searchParams.append('status', params.status);
      if (params.decision && params.decision !== 'all') url.searchParams.append('decision', params.decision);
      if (params.case_id) url.searchParams.append('case_id', params.case_id.toString());
      if (params.limit) url.searchParams.append('limit', params.limit.toString());
    }
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error(`Failed to fetch VAD reasoning jobs: ${res.status} ${res.statusText}`);
    
    const data = await res.json();
    console.log("Reasoning API raw response:", data);
    
    const items = normalizeReasoningResponse(data);
    console.log("Reasoning items after normalization:", items);
    
    return {
      items,
      summary: data.summary || {
        total: items.length,
        queued: items.filter(i => i.job.status === 'queued').length,
        running: items.filter(i => i.job.status === 'running').length,
        succeeded: items.filter(i => i.job.status === 'succeeded').length,
        failed: items.filter(i => i.job.status === 'failed').length,
        final_yes: items.filter(i => (i.result?.python_final_result_json?.final_alert_decision || i.result?.alert_decision) === 'YES').length,
        final_no: items.filter(i => (i.result?.python_final_result_json?.final_alert_decision || i.result?.alert_decision) === 'NO').length,
        final_uncertain: items.filter(i => (i.result?.python_final_result_json?.final_alert_decision || i.result?.alert_decision) === 'UNCERTAIN').length,
      }
    };
  }
};

export function normalizeReasoningResponse(data: unknown): VadReasoningListItem[] {
  const rawItems = Array.isArray(data)
    ? data
    : Array.isArray((data as any)?.items)
      ? (data as any).items
      : [];

  return rawItems.map((row: any) => {
    // If it's already nested, just return it.
    if (row.job || row.case || row.result) {
      return row;
    }

    // Otherwise, normalize flat row into nested structure.
    return {
      job: {
        id: row.job_id ?? row.id,
        case_id: row.case_id,
        status: row.job_status ?? row.status,
        reasoner_type: row.reasoner_type,
        vlm_model: row.vlm_model,
        llm_model: row.llm_model,
        priority: row.priority,
        input_bundle_json: row.input_bundle_json,
        prompt_version: row.prompt_version,
        attempts: row.attempts,
        max_attempts: row.max_attempts,
        queued_at: row.queued_at,
        started_at: row.started_at,
        finished_at: row.finished_at,
        error_json: row.error_json,
        metadata_json: row.metadata_json,
      },
      case: (row.case_table_id ?? row.case_id) ? {
        id: row.case_table_id ?? row.case_id,
        case_key: row.case_key,
        primary_gate_name: row.primary_gate_name,
        case_type: row.case_type,
        severity: row.case_severity,
        status: row.case_status,
        start_ts: row.start_ts,
        peak_ts: row.peak_ts,
        evidence_bundle_json: row.evidence_bundle_json,
        score_summary_json: row.score_summary_json,
      } : null,
      result: row.result_id ? {
        id: row.result_id,
        reasoning_job_id: row.reasoning_job_id,
        case_id: row.case_id,
        alert_decision: row.alert_decision,
        severity: row.result_severity ?? row.severity,
        event_type: row.event_type,
        confidence: row.confidence,
        structured_output_json: row.structured_output_json,
        matched_rules_json: row.matched_rules_json,
        uncertainty_json: row.uncertainty_json,
        raw_vlm_output: row.raw_vlm_output,
        raw_llm_output: row.raw_llm_output,
        vlm_visual_review_json: row.vlm_visual_review_json,
        llm_policy_review_json: row.llm_policy_review_json,
        python_final_result_json: row.python_final_result_json,
        policy_version: row.policy_version,
        rules_version: row.rules_version,
        created_at: row.result_created_at,
      } : null,
    };
  });
}
