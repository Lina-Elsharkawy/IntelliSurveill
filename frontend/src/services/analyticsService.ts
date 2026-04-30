// src/services/analyticsService.ts
import { apiGet } from "@/lib/api";

export interface EntryLog {
  id: number;
  timestamp?: string;
  created_at?: string;
  camera_id: number;
  location: string | null;
  detected_id: number | null;
  status: "known" | "unknown" | "pending_review";
  quality_score: number;
  best_similarity: number | null;
  margin: number;
  processing_time?: string; // <--- CHANGED THIS KEY
}

export interface AnalyticsMetrics {
  total: number;
  knownCount: number;
  unknownCount: number;
  knownRatio: number;
  avgMargin: string;
  avgTime: string;
  avgQuality: string;
  avgSimilarity: string;
}

function parsePostgresInterval(val: any): number {
  if (val === null || val === undefined) return 0;
  
  // If the backend already sends a flat number
  if (typeof val === "number") return val;
  
  const str = String(val).trim().toUpperCase();
  
  // Handle FastAPI/Pydantic standard format: "PT0.382S"
  if (str.startsWith("PT") && str.includes("S")) {
    const seconds = parseFloat(str.replace("PT", "").replace("S", ""));
    return (seconds * 1000) || 0;
  }
  
  // Handle Postgres standard database format: "00:00:00.382"
  if (str.includes(":")) {
    const parts = str.split(":");
    if (parts.length >= 3) {
      return (parseInt(parts[0], 10) * 3600000) + 
             (parseInt(parts[1], 10) * 60000) + 
             (parseFloat(parts[2]) * 1000);
    }
  }
  
  // Final fallback
  return parseFloat(str) || 0;
}

export const CAMERA_LOCATIONS: Record<number, string> = {
  1: "Entrance",
  2: "Back Corner"
};

export const analyticsService = {
  async getRecentLogs(limit: number = 2000): Promise<EntryLog[]> {
    const data = await apiGet(`/api/admin/recent-entry-logs?limit=${limit}`);
    return Array.isArray(data) ? data : [];
  },

  calculateMetrics(logs: EntryLog[]): AnalyticsMetrics {
    const total = logs.length;
    const knownCount = logs.filter(l => l.detected_id !== null).length;
    const unknownCount = total - knownCount;
    
    const knownRatio = total ? Math.round((knownCount / total) * 100) : 0;
    const avgMargin = total ? (logs.reduce((acc, l) => acc + (l.margin || 0), 0) / total).toFixed(3) : "0.000";
    
    // --- 2. THE BULLETPROOF KEY CHECKER ---
    const totalTimeMs = logs.reduce((acc, l) => {
      // We force TypeScript to check every possible key name your backend might output
      const rawVal = (l as any).processing_time || (l as any).processing_time_interval || (l as any).processing_time_ms;
      return acc + parsePostgresInterval(rawVal);
    }, 0);
    
    const avgTime = total ? (totalTimeMs / total).toFixed(1) : "0.0";

    const avgQuality = total ? (logs.reduce((acc, l) => acc + (l.quality_score || 0), 0) / total).toFixed(2) : "0.00";
    
    const knownLogs = logs.filter(l => l.best_similarity !== null);
    const avgSimilarity = knownLogs.length 
      ? (knownLogs.reduce((acc, l) => acc + (l.best_similarity || 0), 0) / knownLogs.length).toFixed(3) 
      : "0.000";

    return { total, knownCount, unknownCount, knownRatio, avgMargin, avgTime, avgQuality, avgSimilarity };
  }
};