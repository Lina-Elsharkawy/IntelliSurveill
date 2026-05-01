import { apiGet, apiPost, apiDelete, apiPatch } from "@/lib/api";

export interface AnomalyRule {
  rule_id: number;
  rule_text: string;
  rule_type: string;
  active: boolean;
  event_type?: string;
  location?: string;
  created_at?: string;
}

export interface ConflictRule {
  rule_id: number;
  rule_text: string;
  rule_type: string;
  event_type: string;
  location: string;
  has_type_conflict: boolean;
}

export interface PreviewResult {
  parsed: any;
  conflicts: ConflictRule[];
  has_conflicts: boolean;
  duplicate?: ConflictRule;
  has_duplicate?: boolean;
}

export const getAnomalyRules = async (): Promise<AnomalyRule[]> => {
  const data = await apiGet<any[]>("/api/anomaly-rules");
  return Array.isArray(data) ? data : [];
};

export const deactivateAnomalyRule = async (ruleId: number): Promise<void> => {
  await apiPatch(`/api/anomaly-rules/${ruleId}/deactivate`, {});
};

export const reactivateRulePreview = async (ruleId: number): Promise<PreviewResult> => {
  return await apiPost<PreviewResult>(`/api/anomaly-rules/reactivate-preview/${ruleId}`, {});
};

export const reactivateAnomalyRule = async (ruleId: number): Promise<void> => {
  await apiPatch(`/api/anomaly-rules/${ruleId}/reactivate`, {});
};

export const deleteAnomalyRule = async (ruleId: number): Promise<void> => {
  await apiDelete(`/api/anomaly-rules/${ruleId}`);
};

export const previewNewRule = async (ruleText: string, ruleType: string): Promise<PreviewResult> => {
  return await apiPost<PreviewResult>("/api/anomaly-rules/preview", {
    rule_text: ruleText,
    rule_type: ruleType,
  });
};

export const addAnomalyRule = async (ruleText: string, ruleType: string): Promise<void> => {
  await apiPost("/api/anomaly-rules", { rule_text: ruleText, rule_type: ruleType });
};

export const resolveAndReactivateRule = async (ruleId: number, deactivateRuleIds: number[]): Promise<void> => {
  await apiPost("/api/anomaly-rules/resolve-and-reactivate", {
    rule_id: ruleId,
    deactivate_rule_ids: deactivateRuleIds,
  });
};

export const resolveAndAddRule = async (ruleText: string, ruleType: string, deactivateRuleIds: number[]): Promise<void> => {
  await apiPost("/api/anomaly-rules/resolve-and-add", {
    rule_text: ruleText,
    rule_type: ruleType,
    deactivate_rule_ids: deactivateRuleIds,
  });
};
