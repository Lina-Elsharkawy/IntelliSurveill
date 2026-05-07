import { apiGet, apiPost } from '@/lib/api';

const API_URL = import.meta.env.VITE_API_URL || '/api';

export type AnomalySeverity = "high" | "medium" | "low";

export interface GateDecision {
  gateName: string;
  fired: boolean;
  scoreValue?: number;
  thresholdValue?: number;
  reason?: string;
  details?: Record<string, any>;
}

export interface ReasoningJob {
  jobType: string;
  status: string;
  modelName?: string;
  responseJson?: Record<string, any>;
  responseText?: string;
  createdAt?: string;
  completedAt?: string;
}

export interface ParsedDecision {
  alert_decision?: string;
  severity?: string;
  decision_reason?: string;
}

export interface AnomalyCandidate {
  id: number;
  status: "pending" | "sent_to_reasoning" | "sent_to_llm" | "resolved" | "discarded" | "acknowledged";
  createdAt: string;
  cameraId?: number;
  trackId?: number;
  priority?: string;
  severity: AnomalySeverity;
  // Scores
  finalScore?: number;
  thresholdValue?: number;
  thresholdName?: string;
  personScore?: number;
  contextScore?: number;
  personScoreNorm?: number;
  contextScoreNorm?: number;
  // Evidence
  candidateReasons: string[];
  imageRef?: string;
  representativeFrameRef?: string;
  personClipRef?: string;
  contextClipRef?: string;
  personFrameRefs?: string[];
  contextFrameRefs?: string[];
  evidencePayload?: Record<string, any>;
  // Reasoning
  narrative?: string;
  llmDecision?: string;
  parsedDecision?: ParsedDecision;
  reasoningJobs?: ReasoningJob[];
  // Motion & gates
  motionStats?: Record<string, any>;
  gateDecisions?: GateDecision[];
  distributionGate?: boolean;
  highSpeedGate?: boolean;
  abruptDirectionGate?: boolean;
  trackInstabilityGate?: boolean;
  maxSpeedNorm?: number;
  maxTurnAngle?: number;
  trackInstabilityReason?: string;
}

export const evidenceUrl = (ref?: string | null): string | undefined => {
  if (!ref) return undefined;
  if (ref.startsWith('s3://')) {
    return `${API_URL}/evidence/object?ref=${encodeURIComponent(ref)}`;
  }
  return ref;
};

const mapBackendToFrontend = (data: any): AnomalyCandidate => {
  const priority = data.priority || 'low';
  const finalScore = data.final_score ?? data.finalScore ?? undefined;
  const thresholdValue = data.threshold_value ?? data.thresholdValue ?? undefined;
  const thresholdName = data.threshold_name ?? data.thresholdName ?? undefined;
  const personScore = data.person_score ?? data.personScore ?? undefined;
  const contextScore = data.context_score ?? data.contextScore ?? undefined;
  const personScoreNorm = data.person_score_norm ?? data.personScoreNorm ?? undefined;
  const contextScoreNorm = data.context_score_norm ?? data.contextScoreNorm ?? undefined;

  // Severity from priority
  let severity: AnomalySeverity = 'low';
  if (priority === 'very_high' || priority === 'high') {
    severity = 'high';
  } else if (priority === 'medium') {
    severity = 'medium';
  } else if (
    finalScore != null &&
    thresholdValue != null &&
    finalScore >= thresholdValue * 1.5
  ) {
    severity = 'high';
  }

  // Flat fields from list endpoint (llmDecision, parsedDecision come pre-extracted)
  let narrative: string | undefined = data.narrative;
  let llmDecision: string | undefined = data.llm_decision ?? data.llmDecision;
  let parsedDecision: ParsedDecision | undefined = data.parsed_decision ?? data.parsedDecision;

  // Reasoning jobs (detail endpoint provides full job array)
  const rawJobs = data.reasoning_jobs ?? data.reasoningJobs;
  const reasoningJobs: ReasoningJob[] | undefined = rawJobs && Array.isArray(rawJobs)
    ? rawJobs.map((j: any): ReasoningJob => ({
        jobType: j.job_type ?? j.jobType ?? '',
        status: j.status ?? '',
        modelName: j.model_name ?? j.modelName,
        responseJson: j.response_json ?? j.responseJson,
        responseText: j.response_text ?? j.responseText,
        createdAt: j.created_at ?? j.createdAt,
        completedAt: j.completed_at ?? j.completedAt,
      }))
    : undefined;

  // Extract narrative/decision from reasoning jobs if not already in flat fields
  if (reasoningJobs) {
    const vlmJob = reasoningJobs.find(j =>
      j.jobType === 'vlm_reasoning' || (j as any).model_type === 'vlm'
    );
    if (vlmJob && !narrative) {
      const rj = vlmJob.responseJson;
      narrative = rj?.narrative ?? rj?.description ?? vlmJob.responseText ?? undefined;
    }

    const llmJob = reasoningJobs.find(j =>
      j.jobType === 'llm_reasoning' || (j as any).model_type === 'llm'
    );
    if (llmJob) {
      const rj = llmJob.responseJson;
      if (!llmDecision) {
        llmDecision = rj?.decision ?? llmJob.responseText ?? undefined;
      }
      if (!parsedDecision) {
        parsedDecision = rj?.parsed_decision ?? rj?.parsedDecision ?? undefined;
      }
    }
  }

  // Evidence refs with fallback chain
  const evidencePayload = data.evidence_payload ?? data.evidencePayload;
  const repFrameRef =
    data.representative_frame_ref ??
    data.representativeFrameRef ??
    evidencePayload?.representative_frame_ref ??
    undefined;

  const personFrameRefs: string[] =
    data.person_frame_refs ??
    data.personFrameRefs ??
    evidencePayload?.person_frames ??
    [];

  const contextFrameRefs: string[] =
    data.context_frame_refs ??
    data.contextFrameRefs ??
    evidencePayload?.context_frames ??
    [];

  // Gate decisions
  const rawGates = data.gate_decisions ?? data.gateDecisions;
  const gateDecisions: GateDecision[] | undefined = rawGates
    ? rawGates.map((gd: any): GateDecision => ({
        gateName: gd.gate_name ?? gd.gateName ?? '',
        fired: gd.gate_fired ?? gd.fired ?? false,
        scoreValue: gd.score_value ?? gd.scoreValue,
        thresholdValue: gd.threshold_value ?? gd.thresholdValue,
        reason: gd.reason,
        details: gd.details,
      }))
    : undefined;

  // Status normalization
  let status = data.status || 'pending';
  if (status === 'sent_to_reasoning') status = 'sent_to_llm';

  return {
    id: data.id,
    status: status as AnomalyCandidate['status'],
    createdAt: data.created_at ?? data.createdAt,
    cameraId: data.camera_id ?? data.cameraId,
    trackId: data.track_id ?? data.trackId,
    priority: data.priority,
    severity,
    finalScore,
    thresholdValue,
    thresholdName,
    personScore,
    contextScore,
    personScoreNorm,
    contextScoreNorm,
    candidateReasons: data.candidate_reasons ?? data.candidateReasons ?? [],
    representativeFrameRef: repFrameRef,
    imageRef: repFrameRef ? evidenceUrl(repFrameRef) : undefined,
    personClipRef: data.person_clip_ref ?? data.personClipRef,
    contextClipRef: data.context_clip_ref ?? data.contextClipRef,
    personFrameRefs,
    contextFrameRefs,
    evidencePayload,
    reasoningJobs,
    narrative,
    llmDecision,
    parsedDecision,
    motionStats: data.motion_stats ?? data.motionStats,
    gateDecisions,
    distributionGate: data.distribution_gate ?? data.distributionGate,
    highSpeedGate: data.high_speed_gate ?? data.highSpeedGate,
    abruptDirectionGate: data.abrupt_direction_gate ?? data.abruptDirectionGate,
    trackInstabilityGate: data.track_instability_gate ?? data.trackInstabilityGate,
    maxSpeedNorm: data.max_speed_norm ?? data.maxSpeedNorm,
    maxTurnAngle: data.max_turn_angle ?? data.maxTurnAngle,
    trackInstabilityReason: data.track_instability_reason ?? data.trackInstabilityReason,
  };
};

export const getAnomalyCandidates = async (): Promise<AnomalyCandidate[]> => {
  const data = await apiGet<any[]>(`${API_URL}/anomalies`);
  if (Array.isArray(data)) return data.map(mapBackendToFrontend);
  return [];
};

export const getAnomalyCandidate = async (id: number): Promise<AnomalyCandidate> => {
  const data = await apiGet<any>(`${API_URL}/anomalies/${id}`);
  return mapBackendToFrontend(data);
};

export const reviewAnomalyCandidate = async (id: number, payload: {
  decision: 'confirmed' | 'dismissed' | 'uncertain' | 'normal_calibration';
  notes?: string;
}): Promise<any> => {
  return await apiPost<any, any>(`${API_URL}/anomalies/${id}/review`, payload);
};
