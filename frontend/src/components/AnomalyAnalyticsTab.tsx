/**
 * AnomalyAnalyticsTab.tsx
 * Anomaly Detection Analytics — polished, calm, premium IntelliSurveil style.
 */

import { useState, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ShieldAlert, Activity, Target, Zap, BarChart2, Layers,
  AlertCircle, RefreshCw, Clock, CheckCircle2, XCircle,
  CircleDashed, TrendingUp, Shield,
} from "lucide-react";

import {
  useAnomalyAnalytics,
  AnomalyFilterState, AnomalyTimeRange,
  GateKey, DecisionKey, SeverityKey,
  GATE_LABELS, GATE_COLORS, GATE_CSS,
  GateHealthStats,
} from "@/hooks/useAnomalyAnalytics";

import {
  AnomalyVolumeChart, GateTriggerDonut, ReasoningOutcomesChart,
  SeverityBarChart, ScoreRatioTimeline, EvidenceHealthPanel, ChartSkeleton,
} from "@/components/AnomalyAnalyticsCharts";

// ─── Shared badge helpers ────────────────────────────────────────────────────

function DecisionBadge({ decision }: { decision: string }) {
  const d = (decision ?? "").toUpperCase();
  if (d === "YES") return <Badge className="bg-red-900/30 text-red-400 border border-red-800/50 uppercase text-[10px] font-semibold">YES</Badge>;
  if (d === "NO") return <Badge className="bg-emerald-900/20 text-emerald-400 border border-emerald-800/40 uppercase text-[10px] font-semibold">NO</Badge>;
  if (d === "UNCERTAIN") return <Badge className="bg-indigo-900/20 text-indigo-400 border border-indigo-800/40 uppercase text-[10px] font-semibold">UNCERTAIN</Badge>;
  if (d === "FAILED") return <Badge className="bg-zinc-800/60 text-zinc-400 border border-zinc-700/50 uppercase text-[10px] font-semibold">FAILED</Badge>;
  return <Badge variant="outline" className="uppercase text-[10px]">{d || "—"}</Badge>;
}

function SeverityBadge({ severity }: { severity: string }) {
  const s = (severity ?? "").toUpperCase();
  const cls: Record<string, string> = {
    CRITICAL: "bg-red-900/30 text-red-400 border-red-800/50",
    HIGH:     "bg-orange-900/20 text-orange-400 border-orange-800/40",
    MEDIUM:   "bg-amber-900/20 text-amber-400 border-amber-800/40",
    LOW:      "bg-emerald-900/20 text-emerald-400 border-emerald-800/40",
    NONE:     "bg-zinc-800/60 text-zinc-500 border-zinc-700/50",
  };
  return <Badge className={`border uppercase text-[10px] font-semibold ${cls[s] ?? cls.NONE}`}>{s || "—"}</Badge>;
}

function GateBadge({ gate }: { gate: GateKey }) {
  const css = GATE_CSS[gate];
  return (
    <Badge className={`border text-[10px] font-semibold ${css.bg} ${css.text} ${css.border}`}>
      {GATE_LABELS[gate]}
    </Badge>
  );
}

// ─── KPI card ────────────────────────────────────────────────────────────────

const KpiCard = ({
  title, value, sub, icon, accentColor = "emerald",
}: {
  title: string; value: string | number; sub?: string;
  icon: React.ReactNode;
  accentColor?: "emerald" | "amber" | "red" | "indigo" | "cyan" | "blue";
}) => {
  const hover: Record<string, string> = {
    emerald: "hover:border-emerald-800/60",
    amber:   "hover:border-amber-800/60",
    red:     "hover:border-red-800/60",
    indigo:  "hover:border-indigo-800/60",
    cyan:    "hover:border-cyan-800/60",
    blue:    "hover:border-blue-800/60",
  };
  return (
    <Card className={`transition-all duration-200 hover:-translate-y-0.5 bg-zinc-950/50 border-zinc-800 ${hover[accentColor]}`}>
      <CardContent className="p-4">
        <div className="flex justify-between items-start gap-2">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider truncate">{title}</p>
            <h3 className="text-xl font-bold text-foreground mt-1 leading-none">{value}</h3>
            {sub && <p className="text-[11px] text-zinc-600 mt-1">{sub}</p>}
          </div>
          <div className="p-2 bg-zinc-900/60 rounded-lg border border-zinc-800/60 flex-shrink-0">{icon}</div>
        </div>
      </CardContent>
    </Card>
  );
};

// ─── Gate Health card ─────────────────────────────────────────────────────────

function GateHealthCard({ stats }: { stats: GateHealthStats }) {
  const { gate, eventCount, avgRatio, maxRatio, lastEventTime, hasReasoning } = stats;
  const css = GATE_CSS[gate];
  const label = GATE_LABELS[gate];
  const reasoningLabel = gate === "homography"
    ? "Gate-only · Motion path"
    : hasReasoning ? "Reasoned" : "Gate-only";
  const reasoningColor = gate === "homography"
    ? "text-zinc-500" : hasReasoning ? "text-emerald-400" : "text-zinc-500";

  let lastTimeStr = "—";
  if (lastEventTime) {
    try {
      lastTimeStr = new Date(lastEventTime).toLocaleString([], {
        month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      });
    } catch { /* ignore */ }
  }

  return (
    <Card className={`bg-zinc-950/50 border ${css.border} transition-all duration-200 hover:-translate-y-0.5`}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className={`w-2 h-2 rounded-full ${css.dot} opacity-70`} />
          <span className={`text-xs font-semibold ${css.text}`}>{label}</span>
          <span className={`ml-auto text-[10px] ${reasoningColor}`}>{reasoningLabel}</span>
        </div>
        <div className="grid grid-cols-2 gap-y-2 gap-x-3">
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Events</p>
            <p className="text-lg font-bold text-zinc-200 leading-tight">{eventCount}</p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Avg Ratio</p>
            <p className="text-lg font-bold text-zinc-200 leading-tight">
              {avgRatio > 0 ? `${avgRatio.toFixed(2)}×` : "—"}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Max Ratio</p>
            <p className="text-sm font-semibold text-zinc-300">
              {maxRatio > 0 ? `${maxRatio.toFixed(2)}×` : "—"}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-zinc-600 uppercase tracking-wide">Last Event</p>
            <p className="text-[11px] text-zinc-400 font-mono">{lastTimeStr}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Summary strip ────────────────────────────────────────────────────────────

function SummaryStrip({ text }: { text: string }) {
  const isEmpty = text.startsWith("No anomaly");
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg bg-zinc-900/60 border border-zinc-800/60">
      <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isEmpty ? "bg-zinc-600" : "bg-emerald-500"}`} />
      <p className="text-xs text-zinc-400 leading-relaxed">{text}</p>
    </div>
  );
}

// ─── Pipeline Health ──────────────────────────────────────────────────────────

function PipelineHealthSection({ summary }: { summary: ReturnType<typeof useAnomalyAnalytics>["data"]["pipelineHealth"] }) {
  if (!summary) {
    return (
      <div className="flex items-center justify-center p-6 rounded-lg bg-zinc-900/40 border border-zinc-800/50 text-zinc-600 text-xs">
        No pipeline health data available
      </div>
    );
  }
  const items = [
    { label: "Queued",    value: summary.queued,    icon: <CircleDashed size={13} />, color: "text-zinc-400" },
    { label: "Running",   value: summary.running,   icon: <Activity size={13} />,     color: "text-blue-400" },
    { label: "Succeeded", value: summary.succeeded, icon: <CheckCircle2 size={13} />, color: "text-emerald-400" },
    { label: "Failed",    value: summary.failed,    icon: <XCircle size={13} />,      color: "text-red-400" },
  ];
  return (
    <Card className="bg-zinc-950/50 border-zinc-800">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3 pb-3 border-b border-zinc-800/50">
          <Activity size={14} className="text-blue-400" />
          <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            Reasoning Pipeline Health
          </span>
          <span className="ml-auto text-[11px] text-zinc-600 font-mono">{summary.total} total jobs</span>
          <span className="text-[10px] text-zinc-700 bg-zinc-800/50 rounded px-1.5 py-0.5">Selected range</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {items.map((item) => (
            <div key={item.label} className={`rounded-lg bg-zinc-900/40 border border-zinc-800/50 p-3 flex flex-col gap-1 ${item.color}`}>
              <div className="flex items-center gap-1.5 opacity-80">
                {item.icon}
                <span className="text-[10px] font-semibold uppercase tracking-wide">{item.label}</span>
              </div>
              <span className="text-xl font-bold font-mono leading-none">{item.value}</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Prioritized Events Table ─────────────────────────────────────────────────

function PrioritizedEventsTable({ events }: { events: ReturnType<typeof useAnomalyAnalytics>["data"]["prioritizedEvents"] }) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-10 rounded-lg bg-zinc-900/40 border border-zinc-800/50 text-zinc-600">
        <Shield size={20} className="opacity-30" />
        <p className="text-xs">No events for this period</p>
      </div>
    );
  }

  // Row left-border color by decision
  const rowAccent: Record<string, string> = {
    YES: "border-l-red-700/60",
    UNCERTAIN: "border-l-indigo-700/60",
    NO: "border-l-emerald-800/50",
    FAILED: "border-l-zinc-700/50",
  };

  return (
    <Card className="bg-zinc-950/50 border-zinc-800 overflow-hidden">
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900/50">
                {["Time", "Gate", "Peak Ratio", "Decision", "Severity", "Track / Event", "Evidence"].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-[10px] font-semibold text-zinc-600 uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/40">
              {events.map((ev, idx) => {
                let timeStr = "—";
                if (ev.time) {
                  try {
                    timeStr = new Date(ev.time).toLocaleString([], {
                      month: "2-digit", day: "2-digit",
                      hour: "2-digit", minute: "2-digit",
                    });
                  } catch { /* ignore */ }
                }

                const displayId = ev.trackId
                  ? `T-${ev.trackId}`
                  : ev.eventId
                  ? `E-${ev.eventId}`
                  : ev.caseId
                  ? `C-${ev.caseId}`
                  : "—";

                const ratioColor =
                  ev.peakRatio >= 2 ? "text-red-400" :
                  ev.peakRatio >= 1.5 ? "text-amber-400" : "text-zinc-300";

                return (
                  <tr
                    key={idx}
                    className={`border-l-2 ${rowAccent[ev.decision] ?? "border-l-zinc-800"} hover:bg-zinc-900/40 transition-colors`}
                  >
                    <td className="px-3 py-2 font-mono text-[11px] text-zinc-500 whitespace-nowrap">{timeStr}</td>
                    <td className="px-3 py-2"><GateBadge gate={ev.gate} /></td>
                    <td className={`px-3 py-2 font-mono text-[11px] font-semibold ${ratioColor}`}>
                      {ev.peakRatio > 0 ? `${ev.peakRatio.toFixed(2)}×` : "—"}
                    </td>
                    <td className="px-3 py-2"><DecisionBadge decision={ev.decision} /></td>
                    <td className="px-3 py-2"><SeverityBadge severity={ev.severity} /></td>
                    <td className="px-3 py-2 font-mono text-[11px] text-zinc-500">{displayId}</td>
                    <td className="px-3 py-2">
                      {ev.hasEvidence ? (
                        <span className="flex items-center gap-1 text-emerald-500 text-[10px]">
                          <CheckCircle2 size={12} /> Available
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-zinc-600 text-[10px]">
                          <XCircle size={12} /> Missing
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Skeleton loader ──────────────────────────────────────────────────────────

function PageSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="h-8 w-64 rounded bg-zinc-800/60" />
      <div className="h-9 w-full rounded-lg bg-zinc-900/60" />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-20 rounded-lg bg-zinc-900/60" />
        ))}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <ChartSkeleton key={i} height={120} />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <ChartSkeleton height={280} />
        <div className="flex flex-col gap-6">
          <ChartSkeleton height={220} />
          <ChartSkeleton height={220} />
        </div>
      </div>
    </div>
  );
}

// ─── Main Tab Export ──────────────────────────────────────────────────────────

export default function AnomalyAnalyticsTab() {
  const [filters, setFilters] = useState<AnomalyFilterState>({
    timeRange: "today",
    camera: "all",
    gate: "all",
    decision: "all",
    severity: "all",
  });
  const [refreshKey, setRefreshKey] = useState(0);
  const { data, loading, error } = useAnomalyAnalytics(filters, refreshKey);
  const handleRefresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  const setFilter = <K extends keyof AnomalyFilterState>(key: K, value: AnomalyFilterState[K]) =>
    setFilters((f) => ({ ...f, [key]: value }));

  // ── Loading ──────────────────────────────────────────────────────────────
  if (loading) return <PageSkeleton />;

  // ── Error ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-zinc-500">
        <div className="p-3 rounded-full bg-zinc-900 border border-red-900/50">
          <AlertCircle size={20} className="text-red-400" />
        </div>
        <p className="text-sm font-medium text-red-400">Failed to load analytics</p>
        <p className="text-xs text-zinc-600">{error}</p>
        <Button variant="outline" size="sm" onClick={handleRefresh} className="mt-1 h-8">
          <RefreshCw size={13} className="mr-1.5" /> Retry
        </Button>
      </div>
    );
  }

  const { kpis, gateHealth, volumeOverTime, gateDistribution, decisionCounts,
    severityCounts, scoreRatioTimeline, evidenceHealth, pipelineHealth,
    prioritizedEvents, summaryStrip } = data;

  const dominantGateLabel = kpis.dominantGate ? GATE_LABELS[kpis.dominantGate] : "N/A";

  const filterTrigger = "w-auto min-w-[120px] bg-zinc-950/60 border-zinc-800 hover:border-zinc-700 text-sm h-8 transition-colors";
  const filterContent = "bg-zinc-950 border-zinc-800";

  return (
    <div className="space-y-5">

      {/* 1 · Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-foreground">Anomaly Detection Analytics</h2>
          <p className="text-muted-foreground text-xs mt-0.5">
            Operational overview of VAD gate activity, evidence generation, and reasoning decisions
          </p>
        </div>
        <Button
          variant="outline" size="sm" onClick={handleRefresh}
          className="h-8 bg-zinc-900 border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 self-start sm:self-auto"
        >
          <RefreshCw size={13} className="mr-1.5" /> Refresh
        </Button>
      </div>

      {/* 2 · Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <Select value={filters.timeRange} onValueChange={(v) => setFilter("timeRange", v as AnomalyTimeRange)}>
          <SelectTrigger className={filterTrigger}>
            <Clock size={12} className="mr-1.5 text-zinc-600 flex-shrink-0" />
            <SelectValue placeholder="Time" />
          </SelectTrigger>
          <SelectContent className={filterContent}>
            <SelectItem value="today">Today</SelectItem>
            <SelectItem value="24h">Last 24h</SelectItem>
            <SelectItem value="7d">Last 7 Days</SelectItem>
            <SelectItem value="all">All Data</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.camera} onValueChange={(v) => setFilter("camera", v)} disabled>
          <SelectTrigger className={`${filterTrigger} opacity-40 cursor-not-allowed`}>
            <SelectValue placeholder="Camera" />
          </SelectTrigger>
          <SelectContent className={filterContent}>
            <SelectItem value="all">All Cameras</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.gate} onValueChange={(v) => setFilter("gate", v as GateKey | "all")}>
          <SelectTrigger className={filterTrigger}>
            <Layers size={12} className="mr-1.5 text-zinc-600 flex-shrink-0" />
            <SelectValue placeholder="Gate" />
          </SelectTrigger>
          <SelectContent className={filterContent}>
            <SelectItem value="all">All Gates</SelectItem>
            <SelectItem value="pose">Pose Micro-Motion</SelectItem>
            <SelectItem value="deep">Deep Visual Similarity</SelectItem>
            <SelectItem value="homography">Homography Motion</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.decision} onValueChange={(v) => setFilter("decision", v as DecisionKey | "all")}>
          <SelectTrigger className={filterTrigger}>
            <Target size={12} className="mr-1.5 text-zinc-600 flex-shrink-0" />
            <SelectValue placeholder="Decision" />
          </SelectTrigger>
          <SelectContent className={filterContent}>
            <SelectItem value="all">All Decisions</SelectItem>
            <SelectItem value="YES">YES (Alert)</SelectItem>
            <SelectItem value="NO">NO</SelectItem>
            <SelectItem value="UNCERTAIN">UNCERTAIN</SelectItem>
            <SelectItem value="FAILED">FAILED</SelectItem>
          </SelectContent>
        </Select>

        <Select value={filters.severity} onValueChange={(v) => setFilter("severity", v as SeverityKey | "all")}>
          <SelectTrigger className={filterTrigger}>
            <Zap size={12} className="mr-1.5 text-zinc-600 flex-shrink-0" />
            <SelectValue placeholder="Severity" />
          </SelectTrigger>
          <SelectContent className={filterContent}>
            <SelectItem value="all">All Severities</SelectItem>
            <SelectItem value="CRITICAL">CRITICAL</SelectItem>
            <SelectItem value="HIGH">HIGH</SelectItem>
            <SelectItem value="MEDIUM">MEDIUM</SelectItem>
            <SelectItem value="LOW">LOW</SelectItem>
            <SelectItem value="NONE">NONE</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 3 · Summary strip */}
      <SummaryStrip text={summaryStrip} />

      {/* 4 · KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard title="Total Events"      value={kpis.totalEvents}
          icon={<ShieldAlert className="w-4 h-4 text-red-500" />} accentColor="red" />
        <KpiCard title="Persistent Events" value={kpis.persistentEvents} sub="hits > 0 or flag"
          icon={<Activity className="w-4 h-4 text-amber-500" />} accentColor="amber" />
        <KpiCard title="Alert Rate"        value={`${kpis.alertDecisionRate}%`} sub="YES decisions"
          icon={<TrendingUp className="w-4 h-4 text-red-400" />} accentColor="red" />
        <KpiCard title="Dominant Gate"     value={dominantGateLabel}
          icon={<Layers className="w-4 h-4 text-indigo-400" />} accentColor="indigo" />
        <KpiCard title="Avg Score Ratio"   value={kpis.avgScoreRatio > 0 ? `${kpis.avgScoreRatio.toFixed(2)}×` : "—"} sub="peak / threshold"
          icon={<BarChart2 className="w-4 h-4 text-cyan-500" />} accentColor="cyan" />
        <KpiCard title="Evidence Coverage" value={`${kpis.evidenceCoverage}%`} sub="jobs with evidence"
          icon={<CheckCircle2 className="w-4 h-4 text-emerald-500" />} accentColor="emerald" />
      </div>

      {/* 5 · Gate Health row */}
      <div>
        <p className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest mb-2">Gate Health</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {gateHealth.map((stats) => (
            <GateHealthCard key={stats.gate} stats={stats} />
          ))}
        </div>
      </div>

      {/* 6 · Analytics charts
          Keep all cards in one grid. This prevents the left cards from being
          forced to wait for a stacked right column, which created large
          vertical dead space under the volume chart. */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        <AnomalyVolumeChart
          data={volumeOverTime}
          timeRange={filters.timeRange}
          totalEvents={kpis.totalEvents}
          dominantGate={kpis.dominantGate ? GATE_LABELS[kpis.dominantGate] : undefined}
        />
        <GateTriggerDonut data={gateDistribution} />

        <ScoreRatioTimeline data={scoreRatioTimeline} />
        <ReasoningOutcomesChart data={decisionCounts} />

        <div className="lg:col-span-2">
          <EvidenceHealthPanel health={evidenceHealth} />
        </div>
        <SeverityBarChart data={severityCounts} />
      </div>

      {/* 7 · Pipeline Health */}
      <PipelineHealthSection summary={pipelineHealth} />

      {/* 8 · Prioritized Events table */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert size={14} className="text-zinc-500" />
          <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-widest">
            Prioritized Recent Events
          </h3>
          <span className="ml-auto text-[10px] text-zinc-600">
            Sorted by decision · severity · ratio · recency
          </span>
        </div>
        <PrioritizedEventsTable events={prioritizedEvents} />
      </div>

    </div>
  );
}
