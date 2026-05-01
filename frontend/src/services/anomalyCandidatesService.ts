import { apiGet } from "@/lib/api";

export interface AnomalyCandidate {
  id: number;
  status: string;
  narrative?: string;
  imageRef?: string;
  createdAt: string;
  cameraId?: string;
  severity?: "high" | "medium" | "low";
}

export const getAnomalyCandidates = async (): Promise<AnomalyCandidate[]> => {
  const data = await apiGet<any[]>("/api/anomaly-candidates");
  
  return data.map((a) => {
    // Map backend fields to frontend interface if needed, or just pass them through
    const candidate: AnomalyCandidate = {
      id: a.id,
      status: a.status,
      narrative: a.narrative,
      imageRef: a.imageRef || a.image_video_ref, // handle potential snake_case from DB
      createdAt: a.createdAt || a.created_at,
      cameraId: a.cameraId || a.camera_id,
      severity: determineSeverity(a.status),
    };
    return candidate;
  });
};

export const determineSeverity = (status: string): "high" | "medium" | "low" => {
  if (status === "pending" || status === "sent_to_llm") {
    return "high";
  } else if (status === "resolved") {
    return "low";
  }
  return "medium";
};
