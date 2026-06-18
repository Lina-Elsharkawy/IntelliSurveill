import { VadReasoningListItem } from "@/services/vad_api";

// ------------------------------------------------------------------
// Core Metadata Extraction
// ------------------------------------------------------------------

export function getGateName(item: VadReasoningListItem): string {
  // Try metadata first (most reliable for jobs), fallback to case primary_gate_name, then default to 'deep' for legacy
  return item.job?.metadata_json?.source_gate_name ?? item.case?.primary_gate_name ?? "deep";
}

export function getGateDisplayName(item: VadReasoningListItem): string {
  const gateName = getGateName(item).toLowerCase();
  if (gateName === "pose") return "Pose Micro-Motion Gate";
  return "Deep Visual Similarity Gate";
}

export function getGateBadgeVariant(item: VadReasoningListItem): { color: string, iconColor: string } {
  const gateName = getGateName(item).toLowerCase();
  if (gateName === "pose") {
    return { color: "bg-amber-500/10 border-amber-500/30 text-amber-400", iconColor: "text-amber-500" };
  }
  return { color: "bg-indigo-500/10 border-indigo-500/30 text-indigo-400", iconColor: "text-indigo-500" };
}

export function getTrackId(item: VadReasoningListItem): string {
  // event sub-object (backend stores per-event fields here)
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    evBundle?.tracker_track_id?.toString() ??
    evBundle?.track_id?.toString() ??
    item.job?.metadata_json?.tracker_track_id?.toString() ??
    item.job?.input_bundle_json?.track_id?.toString() ??
    item.case?.primary_track_id?.toString() ??
    item.case?.track_id?.toString() ??
    "Unknown"
  );
}

export function getSessionId(item: VadReasoningListItem): string {
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    evBundle?.session_id?.toString() ??
    item.job?.metadata_json?.session_id?.toString() ??
    item.case?.session_id?.toString() ??
    "N/A"
  );
}

export function getSourceGateEventId(item: VadReasoningListItem): string {
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    item.job?.metadata_json?.source_gate_event_id?.toString() ??
    evBundle?.case_id?.toString() ??
    evBundle?.id?.toString() ??
    item.case?.event_id?.toString() ??
    "N/A"
  );
}

// ------------------------------------------------------------------
// Stage Outputs
// ------------------------------------------------------------------

export function getVlmReview(item: VadReasoningListItem): any {
  return item.result?.vlm_visual_review_json ?? item.result?.structured_output_json?.vlm_visual_review ?? null;
}

export function getLlmReview(item: VadReasoningListItem): any {
  return item.result?.llm_policy_review_json ?? item.result?.structured_output_json?.llm_policy_review ?? null;
}

export function getPythonFinal(item: VadReasoningListItem): any {
  return (
    item.result?.python_final_result_json ??
    item.result?.structured_output_json?.python_final_guardrails ??
    item.result?.structured_output_json?.python_validation_result ??
    item.result?.structured_output_json?.python_final_result ??
    null
  );
}

export function getNeedsHumanReview(item: VadReasoningListItem): boolean {
  const pfr = getPythonFinal(item);
  return Boolean(
    pfr?.needs_human_review ??
    item.result?.uncertainty_json?.needs_human_review ??
    getFinalDecision(item) === "UNCERTAIN"
  );
}

export function getFinalEventType(item: VadReasoningListItem): string {
  const pfr = getPythonFinal(item);
  return (
    pfr?.final_event_type ??
    item.result?.event_type ??
    item.result?.structured_output_json?.event_type ??
    "unknown"
  );
}

export function getGateCandidateEventType(item: VadReasoningListItem): string {
  return (
    item.job?.input_bundle_json?.event?.event_type ??
    item.job?.input_bundle_json?.event_type ??
    item.case?.case_type ??
    "unknown"
  );
}

export function getMatchedRules(item: VadReasoningListItem): any {
  return item.result?.matched_rules_json ?? null;
}

// ------------------------------------------------------------------
// Final Decisions (Prioritize Python Final Guardrails)
// ------------------------------------------------------------------

export function getFinalDecision(item: VadReasoningListItem): string {
  const pfr = getPythonFinal(item);
  if (pfr?.final_alert_decision) return pfr.final_alert_decision;
  return item.result?.alert_decision || "UNCERTAIN";
}

export function getSeverity(item: VadReasoningListItem): string {
  const pfr = getPythonFinal(item);
  if (pfr?.final_severity) return pfr.final_severity;
  return item.result?.severity || "LOW";
}

export function getConfidence(item: VadReasoningListItem): number {
  const pfr = getPythonFinal(item);
  const value = pfr?.final_confidence ?? item.result?.confidence ?? 0.0;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : 0.0;
}

export function getShortReason(item: VadReasoningListItem): string {
  const pfr = getPythonFinal(item);
  if (pfr?.final_decision_reason) return pfr.final_decision_reason;

  const llm = getLlmReview(item);
  if (llm?.decision_reason) return llm.decision_reason;

  return item.result?.reasoning_summary || "Reasoning completed.";
}

export function getFinalRecommendedAction(item: VadReasoningListItem): string {
  const pfr = getPythonFinal(item);
  if (pfr?.final_recommended_action) return pfr.final_recommended_action;
  const llm = getLlmReview(item);
  if (llm?.recommended_action) return llm.recommended_action;
  return "review_only";
}

// ------------------------------------------------------------------
// Scores and Metrics
// ------------------------------------------------------------------

export function getScoreRatio(item: VadReasoningListItem): number {
  // Check event sub-object first (backend wraps per-event fields here)
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    evBundle?.ratio ??
    evBundle?.score_ratio ??
    item.job?.input_bundle_json?.score_ratio ??
    item.case?.score_summary_json?.score_ratio ??
    0
  );
}

export function getRatioBand(ratio: number): string {
  if (!ratio) return "weak";
  if (ratio < 1.15) return "weak";
  if (ratio < 1.50) return "moderate";
  return "strong";
}

export function getDeepScore(item: VadReasoningListItem): number {
  // Keeping this for backward compatibility or explicit deep score fetching
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    evBundle?.peak_score ??
    item.job?.input_bundle_json?.deep_score ??
    item.job?.input_bundle_json?.peak_score ??
    item.case?.score_summary_json?.deep_score ??
    0
  );
}

export function getThresholdValue(item: VadReasoningListItem): number {
  const evBundle = item.job?.input_bundle_json?.event;
  return (
    evBundle?.threshold_value ??
    item.job?.input_bundle_json?.threshold_value ??
    item.case?.score_summary_json?.threshold_value ??
    0
  );
}

// ------------------------------------------------------------------
// Evidence & Utils
// ------------------------------------------------------------------

export function getEvidenceKeys(item: VadReasoningListItem): string[] {
  let evidence: string[] = [];
  
  if (item.job?.input_bundle_json?.visual_evidence?.object_keys) {
    evidence = item.job.input_bundle_json.visual_evidence.object_keys;
  } else if (item.case?.evidence_bundle_json?.object_keys) {
    evidence = item.case.evidence_bundle_json.object_keys;
  } else if (Array.isArray(item.case?.evidence_bundle_json)) {
     evidence = item.case?.evidence_bundle_json.map((e: any) => e.object_key).filter(Boolean);
  }
  
  return evidence;
}

export function getEvidenceItems(item: VadReasoningListItem): any[] {
  // Legacy support for older components expecting objects instead of strings
  return getEvidenceKeys(item).map(k => ({ object_key: k }));
}

export function getShortError(item: VadReasoningListItem): string {
  if (!item.job.error_json) return "";
  if (typeof item.job.error_json === "string") return item.job.error_json;
  return item.job.error_json.error || item.job.error_json.message || JSON.stringify(item.job.error_json);
}

export function formatJson(value: any): string {
  if (!value) return "";
  return JSON.stringify(value, null, 2);
}

export function generateAnalysisSummary(item: VadReasoningListItem): string {
  const caseId = item.case?.id || "N/A";
  const eventId = item.case?.event_id || "N/A";
  const gate = getGateDisplayName(item);
  const decision = getFinalDecision(item);
  const vlm = getVlmReview(item);
  const llm = getLlmReview(item);
  const evidence = getEvidenceKeys(item).join(", ");
  
  const scoreValue = getDeepScore(item);
  const thresholdValue = getThresholdValue(item);
  const ratioValue = getScoreRatio(item);
  const score = scoreValue ? scoreValue.toFixed(2) : "N/A";
  const threshold = thresholdValue ? thresholdValue.toFixed(2) : "N/A";
  const ratio = ratioValue ? ratioValue.toFixed(2) : "N/A";

  return `VAD Analysis Summary
---------------------
Case ID: ${caseId} | Event ID: ${eventId}
Gate: ${gate}
Score/Threshold: ${score} / ${threshold} (Ratio: ${ratio})
Final Decision: ${decision}

VLM Perception:
${vlm?.visible_scene || "N/A"}
${vlm?.person_observation || "N/A"}

LLM Policy Reason:
${llm?.decision_reason || "N/A"}

Evidence Keys:
${evidence || "None"}`;
}
