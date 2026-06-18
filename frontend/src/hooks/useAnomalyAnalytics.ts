/**
 * useAnomalyAnalytics.ts
 *
 * Aggregates VAD event and reasoning job data on the frontend for the
 * Anomaly Detection Analytics tab.
 *
 * TODO (backend): Replace this hook's dual-fetch with a single dedicated
 *   backend endpoint (e.g. GET /vad/rtsp/analytics/summary?from=...&to=...)
 *   that returns all KPI values and chart series pre-aggregated.
 */

import { useState, useEffect, useMemo } from "react";
import { vadApi, VadEvent, VadReasoningListItem, VadReasoningSummary } from "@/services/vad_api";
import {
  getFinalDecision,
  getSeverity,
  getEvidenceKeys,
  getScoreRatio,
  getGateName,
} from "@/components/vad/reasoning/reasoningUtils";

// ─── Time-range helpers ──────────────────────────────────────────────────────

export type AnomalyTimeRange = "today" | "24h" | "7d" | "all";

export function getTimeRangeCutoff(range: AnomalyTimeRange): Date {
  const now = new Date();
  if (range === "today") {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  if (range === "24h") return new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (range === "7d") return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  if (range === "all") return new Date(0);
  return new Date(0);
}

// ─── Gate normalisation ──────────────────────────────────────────────────────

export type GateKey = "pose" | "deep" | "homography";

export const GATE_LABELS: Record<GateKey, string> = {
  pose: "Pose Micro-Motion",
  deep: "Deep Visual Similarity",
  homography: "Homography Motion",
};

// Muted, calm colours matching IntelliSurveil theme
export const GATE_COLORS: Record<GateKey, string> = {
  pose: "#d97706",       // muted amber-600
  deep: "#6366f1",       // indigo-500
  homography: "#0891b2", // cyan-600
};

// Subtle CSS accent classes used on cards
export const GATE_CSS: Record<GateKey, { border: string; text: string; bg: string; dot: string }> = {
  pose: {
    border: "border-amber-800/40",
    text: "text-amber-400",
    bg: "bg-amber-900/10",
    dot: "bg-amber-500",
  },
  deep: {
    border: "border-indigo-800/40",
    text: "text-indigo-400",
    bg: "bg-indigo-900/10",
    dot: "bg-indigo-500",
  },
  homography: {
    border: "border-cyan-800/40",
    text: "text-cyan-400",
    bg: "bg-cyan-900/10",
    dot: "bg-cyan-500",
  },
};

/**
 * Normalises any backend gate_name string to a canonical GateKey.
 * Priority:  homography > pose > deep (to avoid false deep matches)
 */
export function normalizeGateKey(raw: string | undefined | null): GateKey {
  const g = (raw ?? "").toLowerCase().trim();
  // homography — check before generic "contains" checks
  if (
    g === "homography" ||
    g === "homo" ||
    g === "macro" ||
    g === "homography_macro" ||
    g.includes("homography") ||
    g.includes("macro")
  ) return "homography";
  // pose
  if (g === "pose" || g.includes("pose")) return "pose";
  // deep — default / legacy
  return "deep";
}

// ─── Decision / Severity normalisation ──────────────────────────────────────

export type DecisionKey = "YES" | "NO" | "UNCERTAIN" | "FAILED";
export type SeverityKey = "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

const KNOWN_DECISIONS: DecisionKey[] = ["YES", "NO", "UNCERTAIN", "FAILED"];
const KNOWN_SEVERITIES: SeverityKey[] = ["NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"];

export function normalizeDecision(raw: string | undefined | null): DecisionKey {
  const d = (raw ?? "").toUpperCase();
  if ((KNOWN_DECISIONS as string[]).includes(d)) return d as DecisionKey;
  return "UNCERTAIN";
}

export function normalizeSeverity(raw: string | undefined | null): SeverityKey {
  const s = (raw ?? "").toUpperCase();
  if ((KNOWN_SEVERITIES as string[]).includes(s)) return s as SeverityKey;
  return "NONE";
}

// ─── Derived types ───────────────────────────────────────────────────────────

export interface AnomalyKpis {
  totalEvents: number;
  persistentEvents: number;
  alertDecisionRate: number; // percentage 0-100
  dominantGate: GateKey | null;
  avgScoreRatio: number;
  evidenceCoverage: number; // percentage 0-100
}

export interface GateHealthStats {
  gate: GateKey;
  eventCount: number;
  avgRatio: number;
  maxRatio: number;
  lastEventTime: string | null;
  hasReasoning: boolean; // true if any reasoning jobs exist for this gate
}

export interface AnomalyVolumePoint {
  time: string;
  pose: number;
  deep: number;
  homography: number;
}

export interface GateDistributionItem {
  name: string;
  value: number;
  color: string;
}

export interface DecisionCount {
  name: DecisionKey | string;
  value: number;
  color: string;
}

export interface SeverityCount {
  name: SeverityKey | string;
  value: number;
  color: string;
}

export interface ScoreRatioPoint {
  time: string;
  pose: number | null;
  deep: number | null;
  homography: number | null;
}

export interface EvidenceHealthDetail {
  totalJobs: number;
  jobsWithEvidence: number;
  jobsAnnotatedFrame: number;  // jobs that have an annotated frame key
  jobsTubeletMontage: number;  // jobs that have a tubelet montage key
  jobsWithFrames: number;      // jobs that have any frame keys
  totalFrameCount: number;     // raw sum of individual frame object keys
  missingEvidence: number;
}

export interface PrioritizedEvent {
  time: string;
  gate: GateKey;
  peakRatio: number;
  decision: DecisionKey;
  severity: SeverityKey;
  trackId: string;
  eventId: string;
  caseId: string;
  hasEvidence: boolean;
}

export interface AnomalyAnalyticsData {
  kpis: AnomalyKpis;
  gateHealth: GateHealthStats[];
  volumeOverTime: AnomalyVolumePoint[];
  gateDistribution: GateDistributionItem[];
  decisionCounts: DecisionCount[];
  severityCounts: SeverityCount[];
  scoreRatioTimeline: ScoreRatioPoint[];
  evidenceHealth: EvidenceHealthDetail;
  pipelineHealth: VadReasoningSummary | null;
  prioritizedEvents: PrioritizedEvent[];
  summaryStrip: string;
}

// ─── Filter state ────────────────────────────────────────────────────────────

export interface AnomalyFilterState {
  timeRange: AnomalyTimeRange;
  /**
   * TODO: camera filter — requires a camera_key field on VadEvent.
   * Currently not available on the backend; wired in UI with graceful fallback.
   */
  camera: string;
  gate: GateKey | "all";
  decision: DecisionKey | "all";
  severity: SeverityKey | "all";
}

// ─── Aggregation helpers (pure, testable) ────────────────────────────────────

function buildVolumeOverTime(
  events: VadEvent[],
  range: AnomalyTimeRange,
): AnomalyVolumePoint[] {
  const isToday = range === "today" || range === "24h";

  if (isToday) {
    const buckets: Record<string, { pose: number; deep: number; homography: number }> = {};
    for (let h = 0; h < 24; h++) {
      const key = `${String(h).padStart(2, "0")}:00`;
      buckets[key] = { pose: 0, deep: 0, homography: 0 };
    }
    events.forEach((ev) => {
      const h = new Date(ev.peak_ts || ev.start_ts).getHours();
      const key = `${String(h).padStart(2, "0")}:00`;
      const gate = normalizeGateKey(ev.gate_name);
      if (buckets[key]) buckets[key][gate]++;
    });
    return Object.entries(buckets).map(([time, data]) => ({ time, ...data }));
  } else {
    // 7d — bucket by date
    const buckets: Record<string, { pose: number; deep: number; homography: number }> = {};
    events.forEach((ev) => {
      const dateKey = new Date(ev.peak_ts || ev.start_ts).toISOString().split("T")[0];
      if (!buckets[dateKey]) buckets[dateKey] = { pose: 0, deep: 0, homography: 0 };
      const gate = normalizeGateKey(ev.gate_name);
      buckets[dateKey][gate]++;
    });
    return Object.entries(buckets)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([time, data]) => ({ time, ...data }));
  }
}

function buildGateHealth(
  events: VadEvent[],
  jobs: VadReasoningListItem[],
): GateHealthStats[] {
  const gates: GateKey[] = ["pose", "deep", "homography"];
  return gates.map((gate) => {
    const gateEvents = events.filter((e) => normalizeGateKey(e.gate_name) === gate);
    const ratios = gateEvents
      .map((e) => (e.threshold_value > 0 ? e.peak_score / e.threshold_value : null))
      .filter((r): r is number => r !== null);
    const avgRatio = ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : 0;
    const maxRatio = ratios.length > 0 ? Math.max(...ratios) : 0;
    const timestamps = gateEvents
      .map((e) => e.peak_ts || e.start_ts)
      .filter(Boolean)
      .sort((a, b) => b.localeCompare(a));
    const lastEventTime = timestamps[0] ?? null;
    const hasReasoning = jobs.some((j) => normalizeGateKey(getGateName(j)) === gate);
    return { gate, eventCount: gateEvents.length, avgRatio, maxRatio, lastEventTime, hasReasoning };
  });
}

function buildScoreRatioTimeline(
  events: VadEvent[],
  jobs: VadReasoningListItem[],
): ScoreRatioPoint[] {
  const points: ScoreRatioPoint[] = [];

  // From raw VAD events (peak_score / threshold_value)
  events.forEach((ev) => {
    if (!ev.peak_score || !ev.threshold_value) return;
    const ratio = ev.threshold_value > 0 ? ev.peak_score / ev.threshold_value : 0;
    const gate = normalizeGateKey(ev.gate_name);
    const time = new Date(ev.peak_ts || ev.start_ts).toISOString();
    points.push({
      time,
      pose: gate === "pose" ? ratio : null,
      deep: gate === "deep" ? ratio : null,
      homography: gate === "homography" ? ratio : null,
    });
  });

  // From reasoning jobs (already have score_ratio in input bundle)
  jobs.forEach((item) => {
    const ratio = getScoreRatio(item);
    if (!ratio) return;
    const gate = normalizeGateKey(getGateName(item));
    const time = item.job.queued_at;
    if (!time) return;
    points.push({
      time,
      pose: gate === "pose" ? ratio : null,
      deep: gate === "deep" ? ratio : null,
      homography: gate === "homography" ? ratio : null,
    });
  });

  return points.sort((a, b) => a.time.localeCompare(b.time)).slice(-200);
}

function buildEvidenceHealth(events: VadEvent[], jobs: VadReasoningListItem[]): EvidenceHealthDetail {
  let jobsAnnotatedFrame = 0;
  let jobsTubeletMontage = 0;
  let jobsWithFrames = 0;
  let totalFrameCount = 0;
  let missingEvidence = 0;

  jobs.forEach((item) => {
    const keys = getEvidenceKeys(item);
    if (keys.length === 0) {
      missingEvidence++;
      return;
    }
    let hasAnnotated = false;
    let hasMontage = false;
    let hasFrame = false;

    keys.forEach((k) => {
      if (k.includes("annotated_frame")) hasAnnotated = true;
      if (k.includes("tubelet_montage")) hasMontage = true;
      if (k.includes("frames/") || k.includes("frame_") || k.includes("tubelet_frame")) {
        hasFrame = true;
        totalFrameCount++;
      }
    });

    if (hasAnnotated) jobsAnnotatedFrame++;
    if (hasMontage) jobsTubeletMontage++;
    if (hasFrame) jobsWithFrames++;
    if (!hasAnnotated && !hasMontage && !hasFrame) missingEvidence++;
  });

  // Conservative fallback if no reasoning jobs
  if (jobs.length === 0 && events.length > 0) {
    missingEvidence = events.length;
  }

  const jobsWithEvidence = jobs.length - missingEvidence;

  return {
    totalJobs: jobs.length,
    jobsWithEvidence,
    jobsAnnotatedFrame,
    jobsTubeletMontage,
    jobsWithFrames,
    totalFrameCount,
    missingEvidence,
  };
}

// ─── Decision colours ────────────────────────────────────────────────────────
const DECISION_COLORS: Record<string, string> = {
  YES: "#ef4444",
  NO: "#22c55e",
  UNCERTAIN: "#6366f1",
  FAILED: "#6b7280",
};

const SEVERITY_COLORS: Record<string, string> = {
  NONE: "#52525b",
  LOW: "#16a34a",
  MEDIUM: "#d97706",
  HIGH: "#ea580c",
  CRITICAL: "#dc2626",
};

// ─── Summary strip ───────────────────────────────────────────────────────────

function buildSummaryStrip(
  events: VadEvent[],
  dominantGate: GateKey | null,
  alertDecisionRate: number,
  evidenceCoverage: number,
): string {
  if (events.length === 0) return "No anomaly events detected for the selected period";
  const parts: string[] = [];
  parts.push(`${events.length} anomaly event${events.length !== 1 ? "s" : ""} detected`);
  if (dominantGate) parts.push(`${GATE_LABELS[dominantGate]} is dominant`);
  parts.push(`${alertDecisionRate}% alert decision rate`);
  if (evidenceCoverage > 0) parts.push(`${evidenceCoverage}% evidence coverage`);
  return parts.join("  ·  ");
}

// ─── Main aggregation ────────────────────────────────────────────────────────

function aggregate(
  events: VadEvent[],
  jobs: VadReasoningListItem[],
  summary: VadReasoningSummary | null,
  filters: AnomalyFilterState,
): AnomalyAnalyticsData {
  // --- Gate distribution (from VAD events) ---
  const gateCounts: Record<GateKey, number> = { pose: 0, deep: 0, homography: 0 };
  events.forEach((ev) => {
    gateCounts[normalizeGateKey(ev.gate_name)]++;
  });

  const gateDistribution: GateDistributionItem[] = (
    Object.entries(gateCounts) as [GateKey, number][]
  )
    .filter(([, v]) => v > 0)
    .map(([key, value]) => ({
      name: GATE_LABELS[key],
      value,
      color: GATE_COLORS[key],
    }));

  const dominantGateEntry = (Object.entries(gateCounts) as [GateKey, number][]).sort(
    ([, a], [, b]) => b - a,
  )[0];
  const dominantGate: GateKey | null =
    dominantGateEntry && dominantGateEntry[1] > 0 ? dominantGateEntry[0] : null;

  // --- KPIs ---
  // Use `persistent` boolean when available; fall back to persistence_hits > 0
  const persistentEvents = events.filter(
    (e) => typeof e.persistent === "boolean" ? e.persistent : (e.persistence_hits ?? 0) > 0,
  ).length;
  const totalWithDecision = jobs.filter((j) => j.result != null).length;
  const alertYes = jobs.filter((j) => j.result && getFinalDecision(j) === "YES").length;
  const alertDecisionRate =
    totalWithDecision > 0 ? Math.round((alertYes / totalWithDecision) * 100) : 0;

  // Avg score ratio — normalized across gates
  const ratios = events
    .map((e) => (e.threshold_value > 0 ? e.peak_score / e.threshold_value : null))
    .filter((r): r is number => r !== null);
  const avgScoreRatio =
    ratios.length > 0 ? ratios.reduce((a, b) => a + b, 0) / ratios.length : 0;

  // Evidence coverage
  const jobsWithEvidence = jobs.filter((j) => getEvidenceKeys(j).length > 0).length;
  const evidenceCoverage =
    jobs.length > 0 ? Math.round((jobsWithEvidence / jobs.length) * 100) : 0;

  const kpis: AnomalyKpis = {
    totalEvents: events.length,
    persistentEvents,
    alertDecisionRate,
    dominantGate,
    avgScoreRatio,
    evidenceCoverage,
  };

  // --- Decision counts (from reasoning jobs) ---
  const decisionMap: Record<string, number> = { YES: 0, NO: 0, UNCERTAIN: 0, FAILED: 0 };
  jobs.forEach((j) => {
    if (j.job.status === "failed" && !j.result) {
      decisionMap["FAILED"]++;
    } else if (j.result) {
      decisionMap[normalizeDecision(getFinalDecision(j))]++;
    }
  });
  const decisionCounts: DecisionCount[] = Object.entries(decisionMap).map(([name, value]) => ({
    name,
    value,
    color: DECISION_COLORS[name] ?? "#6b7280",
  }));

  // --- Severity counts ---
  const severityMap: Record<string, number> = {
    NONE: 0, LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0,
  };
  jobs.forEach((j) => {
    if (j.result) severityMap[normalizeSeverity(getSeverity(j))]++;
  });
  const severityCounts: SeverityCount[] = Object.entries(severityMap).map(([name, value]) => ({
    name,
    value,
    color: SEVERITY_COLORS[name] ?? "#6b7280",
  }));

  // --- Prioritized events ---
  const prioritizedEvents: PrioritizedEvent[] = jobs
    .filter((j) => j.result != null)
    .map((j) => {
      const decision = normalizeDecision(getFinalDecision(j));
      const severity = normalizeSeverity(getSeverity(j));
      const gate = normalizeGateKey(getGateName(j));
      const evBundle = j.job?.input_bundle_json?.event;
      const ratio = getScoreRatio(j) || (() => {
        const ev = events.find((e) => e.id === j.case?.event_id);
        return ev && ev.threshold_value > 0 ? ev.peak_score / ev.threshold_value : 0;
      })();
      // Prefer event sub-object tracker_track_id, then metadata_json, then case
      const trackId =
        evBundle?.tracker_track_id?.toString() ??
        j.job?.metadata_json?.tracker_track_id?.toString() ??
        j.case?.track_id?.toString() ??
        "";
      const eventId = String(j.case?.event_id ?? "");
      const caseId = String(j.case?.id ?? j.job?.case_id ?? "");
      return {
        time: j.case?.peak_ts || j.job.queued_at || "",
        gate,
        peakRatio: ratio,
        decision,
        severity,
        trackId,
        eventId,
        caseId,
        hasEvidence: getEvidenceKeys(j).length > 0,
      };
    })
    .sort((a, b) => {
      const decisionRank: Record<string, number> = { YES: 0, UNCERTAIN: 1, NO: 2, FAILED: 3 };
      const severityRank: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, NONE: 4 };
      const dr = (decisionRank[a.decision] ?? 99) - (decisionRank[b.decision] ?? 99);
      if (dr !== 0) return dr;
      const sr = (severityRank[a.severity] ?? 99) - (severityRank[b.severity] ?? 99);
      if (sr !== 0) return sr;
      const rr = b.peakRatio - a.peakRatio;
      if (rr !== 0) return rr;
      return b.time.localeCompare(a.time);
    })
    .slice(0, 25);

  const summaryStrip = buildSummaryStrip(events, dominantGate, alertDecisionRate, evidenceCoverage);

  return {
    kpis,
    gateHealth: buildGateHealth(events, jobs),
    volumeOverTime: buildVolumeOverTime(events, filters.timeRange),
    gateDistribution,
    decisionCounts,
    severityCounts,
    scoreRatioTimeline: buildScoreRatioTimeline(events, jobs),
    evidenceHealth: buildEvidenceHealth(events, jobs),
    pipelineHealth: summary,
    prioritizedEvents,
    summaryStrip,
  };
}

// ─── Hook ────────────────────────────────────────────────────────────────────

export function useAnomalyAnalytics(filters: AnomalyFilterState, refreshKey: number = 0) {
  const [rawEvents, setRawEvents] = useState<VadEvent[]>([]);
  const [rawJobs, setRawJobs] = useState<VadReasoningListItem[]>([]);
  const [summary, setSummary] = useState<VadReasoningSummary | null>(null);
  const [serverData, setServerData] = useState<AnomalyAnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const cutoffTs = getTimeRangeCutoff(filters.timeRange).toISOString();

    // Preferred path: backend-side full DB aggregation. This avoids the old
    // `/events?limit=500` frontend cap that made "All Data" silently wrong.
    vadApi.getAnomalyAnalytics({
      timeRange: filters.timeRange,
      cutoffTs,
      gate: filters.gate,
      decision: filters.decision,
      severity: filters.severity,
    })
      .then((analytics) => {
        if (cancelled) return;
        setServerData(analytics as AnomalyAnalyticsData);
        setRawEvents([]);
        setRawJobs([]);
        setSummary((analytics as AnomalyAnalyticsData).pipelineHealth ?? null);
      })
      .catch(async (serverErr) => {
        // Graceful fallback for older vad_service containers that do not yet have
        // /analytics/summary. The fallback now asks the list endpoints for
        // all rows instead of silently clipping the browser-side dataset.
        try {
          const [eventsRes, reasoningRes] = await Promise.all([
            vadApi.getEvents(undefined, "all"),
            vadApi.getReasoningJobs({ limit: "all" }),
          ]);
          if (cancelled) return;
          setServerData(null);
          setRawEvents(eventsRes.events ?? []);
          setRawJobs(reasoningRes.items ?? []);
          setSummary(reasoningRes.summary ?? null);
        } catch (fallbackErr: any) {
          if (cancelled) return;
          setServerData(null);
          setError(fallbackErr?.message ?? serverErr?.message ?? "Failed to load anomaly analytics data.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey, filters.timeRange, filters.gate, filters.decision, filters.severity]);

  // ── Time filter ──────────────────────────────────────────────────────────
  const cutoff = useMemo(() => getTimeRangeCutoff(filters.timeRange), [filters.timeRange]);

  const filteredEvents = useMemo(() => {
    let evs = rawEvents.filter((e) => {
      const ts = e.peak_ts || e.start_ts;
      if (!ts) return false;
      return new Date(ts) >= cutoff;
    });

    if (filters.gate !== "all") {
      evs = evs.filter((e) => normalizeGateKey(e.gate_name) === filters.gate);
    }

    // TODO: camera filter — VadEvent does not currently carry a camera_key field.

    return evs;
  }, [rawEvents, cutoff, filters.gate]);

  const filteredJobs = useMemo(() => {
    let jobs = rawJobs.filter((j) => {
      const ts = j.case?.peak_ts || j.job.queued_at;
      if (!ts) return true;
      return new Date(ts) >= cutoff;
    });

    if (filters.gate !== "all") {
      jobs = jobs.filter((j) => normalizeGateKey(getGateName(j)) === filters.gate);
    }

    if (filters.decision !== "all") {
      jobs = jobs.filter(
        (j) => j.result && normalizeDecision(getFinalDecision(j)) === filters.decision,
      );
    }

    if (filters.severity !== "all") {
      jobs = jobs.filter(
        (j) => j.result && normalizeSeverity(getSeverity(j)) === filters.severity,
      );
    }

    return jobs;
  }, [rawJobs, cutoff, filters.gate, filters.decision, filters.severity]);

  const data = useMemo(
    () => serverData ?? aggregate(filteredEvents, filteredJobs, summary, filters),
    [serverData, filteredEvents, filteredJobs, summary, filters],
  );

  return { data, loading, error };
}
