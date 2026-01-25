import { apiGet, apiPost } from "@/lib/api";
import type { AnomalyCandidate, SuccessMessage } from "@/types/types";

/* -------------------- Unknown Identities -------------------- */
// export async function getUnknownIdentities(): Promise<UnknownIdentity[]> {
//     return apiGet<UnknownIdentity[]>("/api/admin/unknown_identities");
// }

/* -------------------- Anomalies -------------------- */
export async function getAnomalyCandidates(): Promise<AnomalyCandidate[]> {
    return apiGet<AnomalyCandidate[]>("/api/admin/anomalies");
}

/* -------------------- Submit feedback -------------------- */
export async function submitAnomalyFeedback(id: number, feedback: "true_anomaly" | "false_positive" | "uncertain"): Promise<SuccessMessage> {
    return apiPost<SuccessMessage, { feedback: string }>(`/api/admin/anomalies/${id}/feedback`, { feedback });
}
