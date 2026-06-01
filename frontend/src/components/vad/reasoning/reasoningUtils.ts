import { VadReasoningListItem } from "@/services/vad_api";

export function getPythonFinalResult(item: VadReasoningListItem): any {
  return item.result?.python_final_result_json ?? item.result?.structured_output_json?.python_final_result ?? null;
}

export function getVlmReview(item: VadReasoningListItem): any {
  return item.result?.vlm_visual_review_json ?? item.result?.structured_output_json?.vlm_visual_review ?? null;
}

export function getLlmReview(item: VadReasoningListItem): any {
  return item.result?.llm_policy_review_json ?? item.result?.structured_output_json?.llm_policy_review ?? null;
}

export function getFinalDecision(item: VadReasoningListItem): string {
  const pfr = getPythonFinalResult(item);
  if (pfr?.final_alert_decision) return pfr.final_alert_decision;
  return item.result?.alert_decision || "UNCERTAIN";
}

export function getFinalSeverity(item: VadReasoningListItem): string {
  const pfr = getPythonFinalResult(item);
  if (pfr?.final_severity) return pfr.final_severity;
  return item.result?.severity || "LOW";
}

export function getFinalConfidence(item: VadReasoningListItem): number {
  const pfr = getPythonFinalResult(item);
  if (pfr?.final_confidence !== undefined) return pfr.final_confidence;
  return item.result?.confidence || 0.0;
}

export function getFinalRecommendedAction(item: VadReasoningListItem): string {
  const pfr = getPythonFinalResult(item);
  if (pfr?.final_recommended_action) return pfr.final_recommended_action;
  const llm = getLlmReview(item);
  if (llm?.recommended_action) return llm.recommended_action;
  return "review_only";
}

export function getDeepScore(item: VadReasoningListItem): number {
  return item.job?.input_bundle_json?.deep_score ?? item.case?.score_summary_json?.deep_score ?? 0;
}

export function getThresholdValue(item: VadReasoningListItem): number {
  return item.job?.input_bundle_json?.threshold_value ?? item.case?.score_summary_json?.threshold_value ?? 0;
}

export function getScoreRatio(item: VadReasoningListItem): number {
  return item.job?.input_bundle_json?.score_ratio ?? item.case?.score_summary_json?.score_ratio ?? 0;
}

export function getRatioBand(ratio: number): string {
  if (!ratio) return "weak";
  if (ratio < 1.15) return "weak";
  if (ratio < 1.50) return "moderate";
  return "strong";
}

export function getEvidenceItems(item: VadReasoningListItem): any[] {
  let evidence = [];
  if (item.case?.evidence_bundle_json) {
    if (Array.isArray(item.case.evidence_bundle_json)) {
      evidence = item.case.evidence_bundle_json;
    } else if (item.case.evidence_bundle_json.evidence) {
      evidence = item.case.evidence_bundle_json.evidence;
    } else if (item.case.evidence_bundle_json.evidence_objects) {
      evidence = item.case.evidence_bundle_json.evidence_objects;
    } else if (item.case.evidence_bundle_json.object_keys) {
      evidence = item.case.evidence_bundle_json.object_keys.map((k: string) => ({ object_key: k }));
    }
  } 
  
  if (evidence.length === 0 && item.job?.input_bundle_json?.visual_evidence?.object_keys) {
    evidence = item.job.input_bundle_json.visual_evidence.object_keys.map((k: string) => ({ object_key: k }));
  }
  return evidence;
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
