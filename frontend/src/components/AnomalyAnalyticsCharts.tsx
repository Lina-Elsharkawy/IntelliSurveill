/**
 * AnomalyAnalyticsCharts.tsx
 *
 * All chart components for the Anomaly Detection Analytics tab.
 * Design: calm, dark, professional — native to the IntelliSurveil theme.
 */

import { useMemo } from "react";
import {
  AreaChart, Area, PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
  LineChart, Line, ReferenceLine,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import {
  AnomalyVolumePoint, GateDistributionItem, DecisionCount,
  SeverityCount, ScoreRatioPoint, EvidenceHealthDetail,
  GATE_COLORS,
} from "@/hooks/useAnomalyAnalytics";

// ─── Shared tooltip style (matches existing AnalyticsCharts.tsx exactly) ─────
const tooltipStyle = {
  backgroundColor: "hsl(var(--card))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "8px",
  color: "hsl(var(--foreground))",
  fontSize: 12,
};

// ─── Skeleton shimmer ─────────────────────────────────────────────────────────
export function ChartSkeleton({ height = 260 }: { height?: number }) {
  return (
    <div
      className="w-full rounded-lg aa-shimmer"
      style={{ height }}
      aria-busy="true"
    />
  );
}

// ─── Empty state (inline, no external container needed) ──────────────────────
export function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-2 text-zinc-600 select-none">
      <span className="text-2xl opacity-30">–</span>
      <p className="text-xs text-zinc-500">{message}</p>
    </div>
  );
}

// ─── 1. Anomaly Volume Over Time ─────────────────────────────────────────────

export const AnomalyVolumeChart = ({
  data,
  timeRange,
  totalEvents,
  dominantGate,
}: {
  data: AnomalyVolumePoint[];
  timeRange: string;
  totalEvents?: number;
  dominantGate?: string;
}) => {
  // Compute peak hour
  const peakEntry = useMemo(() => {
    if (!data.length) return null;
    return [...data].sort(
      (a, b) => (b.pose + b.deep + b.homography) - (a.pose + a.deep + a.homography),
    )[0];
  }, [data]);

  const hasData = data.some((d) => d.pose + d.deep + d.homography > 0);

  return (
    <Card className="bg-card border-border shadow-sm lg:col-span-2 self-start h-fit">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">
          Anomaly Volume Over Time
        </CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          Gate-triggered anomaly events across the selected period
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[240px] w-full">
          {!hasData ? (
            <EmptyChart message="No anomaly events found for this period" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="fillPose" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={GATE_COLORS.pose} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={GATE_COLORS.pose} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="fillDeep" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={GATE_COLORS.deep} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={GATE_COLORS.deep} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="fillHomography" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={GATE_COLORS.homography} stopOpacity={0.25} />
                    <stop offset="95%" stopColor={GATE_COLORS.homography} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis
                  dataKey="time"
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  interval={timeRange === "today" || timeRange === "24h" ? 3 : "preserveStartEnd"}
                />
                <YAxis
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ color: "hsl(var(--foreground))" }}
                  cursor={{ stroke: "hsl(var(--muted))" }}
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                <Area
                  type="monotone"
                  name="Pose Micro-Motion"
                  dataKey="pose"
                  stroke={GATE_COLORS.pose}
                  strokeWidth={1.5}
                  fillOpacity={1}
                  fill="url(#fillPose)"
                  isAnimationActive
                  animationDuration={800}
                  animationEasing="ease-out"
                  animationBegin={0}
                />
                <Area
                  type="monotone"
                  name="Deep Visual Similarity"
                  dataKey="deep"
                  stroke={GATE_COLORS.deep}
                  strokeWidth={1.5}
                  fillOpacity={1}
                  fill="url(#fillDeep)"
                  isAnimationActive
                  animationDuration={900}
                  animationEasing="ease-out"
                  animationBegin={80}
                />
                <Area
                  type="monotone"
                  name="Homography Motion"
                  dataKey="homography"
                  stroke={GATE_COLORS.homography}
                  strokeWidth={1.5}
                  fillOpacity={1}
                  fill="url(#fillHomography)"
                  isAnimationActive
                  animationDuration={1000}
                  animationEasing="ease-out"
                  animationBegin={160}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Compact insight footer */}
        {hasData && (peakEntry || totalEvents) && (
          <div className="mt-3 pt-3 border-t border-zinc-800/60 flex flex-wrap gap-x-5 gap-y-1">
            {totalEvents !== undefined && (
              <span className="text-[11px] text-zinc-500">
                <span className="text-zinc-300 font-medium">{totalEvents}</span> total events
              </span>
            )}
            {dominantGate && (
              <span className="text-[11px] text-zinc-500">
                Most active: <span className="text-zinc-300 font-medium">{dominantGate}</span>
              </span>
            )}
            {peakEntry && (
              <span className="text-[11px] text-zinc-500">
                Peak window:{" "}
                <span className="text-zinc-300 font-medium">{peakEntry.time}</span>
              </span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

// ─── 2. Gate Trigger Distribution ────────────────────────────────────────────

export const GateTriggerDonut = ({ data }: { data: GateDistributionItem[] }) => {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <Card className="bg-card border-border shadow-sm h-fit self-start">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">
          Gate Trigger Distribution
        </CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          Proportion of events per gate
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[200px] w-full">
          {total === 0 ? (
            <EmptyChart message="No events to distribute" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  innerRadius={52}
                  outerRadius={76}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                  isAnimationActive
                  animationDuration={700}
                  animationEasing="ease-out"
                  animationBegin={100}
                >
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} opacity={0.85} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ color: "hsl(var(--foreground))" }}
                  formatter={(value: number) =>
                    [`${value} (${total > 0 ? Math.round((value / total) * 100) : 0}%)`, ""]
                  }
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: "11px" }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

// ─── 3. VAD Reasoning Outcomes ────────────────────────────────────────────────

export const ReasoningOutcomesChart = ({ data }: { data: DecisionCount[] }) => {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <Card className="bg-card border-border shadow-sm h-fit self-start">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">
          VAD Reasoning Outcomes
        </CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          VLM/LLM final decision distribution (Deep &amp; Pose gates)
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[200px] w-full">
          {total === 0 ? (
            <EmptyChart message="No reasoning results available" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  innerRadius={52}
                  outerRadius={76}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                  isAnimationActive
                  animationDuration={700}
                  animationEasing="ease-out"
                  animationBegin={100}
                >
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} opacity={0.85} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ color: "hsl(var(--foreground))" }}
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: "11px" }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

// ─── 4. Severity Distribution ─────────────────────────────────────────────────

export const SeverityBarChart = ({ data }: { data: SeverityCount[] }) => {
  const hasData = data.some((d) => d.value > 0);
  return (
    <Card className="bg-card border-border shadow-sm h-fit self-start">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">
          Severity Distribution
        </CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          Final severity level of reasoning decisions
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[220px] w-full">
          {!hasData ? (
            <EmptyChart message="No severity data available" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }} barSize={32}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis
                  dataKey="name"
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <YAxis
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  allowDecimals={false}
                />
                <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "hsl(var(--muted)/0.3)" }} />
                <Bar dataKey="value" name="Count" radius={[3, 3, 0, 0]} isAnimationActive animationDuration={700} animationEasing="ease-out" animationBegin={50}>
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} opacity={0.85} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

// ─── 5. Peak Score vs Threshold Timeline ──────────────────────────────────────

export const ScoreRatioTimeline = ({ data }: { data: ScoreRatioPoint[] }) => {
  const chartData = useMemo(() => {
    return data.map((p) => ({
      ...p,
      time: p.time
        ? (() => {
            try {
              return new Date(p.time).toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              });
            } catch {
              return p.time;
            }
          })()
        : p.time,
    }));
  }, [data]);

  return (
    <Card className="bg-card border-border shadow-sm lg:col-span-2 self-start h-fit">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">
          Peak Score vs Threshold
        </CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          Normalized ratio (peak_score / threshold_value) per gate — reference line at 1.0×
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="h-[240px] w-full">
          {data.length === 0 ? (
            <EmptyChart message="No score data available for this period" />
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                <XAxis
                  dataKey="time"
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v) => `${v.toFixed(1)}×`}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ color: "hsl(var(--foreground))" }}
                  formatter={(value: number | null, name: string) =>
                    value != null ? [`${value.toFixed(2)}×`, name] : [null, name]
                  }
                />
                <Legend iconType="circle" wrapperStyle={{ fontSize: "11px", paddingTop: "6px" }} />
                <ReferenceLine
                  y={1}
                  stroke="#6b7280"
                  strokeDasharray="4 4"
                  label={{
                    value: "Threshold 1.0×",
                    position: "insideTopRight",
                    fontSize: 10,
                    fill: "#6b7280",
                  }}
                />
                <Line
                  type="monotone"
                  name="Pose Micro-Motion"
                  dataKey="pose"
                  stroke={GATE_COLORS.pose}
                  strokeWidth={1.5}
                  dot={{ r: 3, fill: GATE_COLORS.pose, strokeWidth: 0 }}
                  activeDot={{ r: 5, fill: GATE_COLORS.pose, strokeWidth: 0 }}
                  connectNulls={false}
                  isAnimationActive
                  animationDuration={900}
                  animationEasing="ease-out"
                  animationBegin={0}
                />
                <Line
                  type="monotone"
                  name="Deep Visual Similarity"
                  dataKey="deep"
                  stroke={GATE_COLORS.deep}
                  strokeWidth={1.5}
                  dot={{ r: 3, fill: GATE_COLORS.deep, strokeWidth: 0 }}
                  activeDot={{ r: 5, fill: GATE_COLORS.deep, strokeWidth: 0 }}
                  connectNulls={false}
                  isAnimationActive
                  animationDuration={1000}
                  animationEasing="ease-out"
                  animationBegin={80}
                />
                <Line
                  type="monotone"
                  name="Homography Motion"
                  dataKey="homography"
                  stroke={GATE_COLORS.homography}
                  strokeWidth={1.5}
                  dot={{ r: 3, fill: GATE_COLORS.homography, strokeWidth: 0 }}
                  activeDot={{ r: 5, fill: GATE_COLORS.homography, strokeWidth: 0 }}
                  connectNulls={false}
                  isAnimationActive
                  animationDuration={1100}
                  animationEasing="ease-out"
                  animationBegin={160}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

// ─── 6. Evidence Health Panel ─────────────────────────────────────────────────

export const EvidenceHealthPanel = ({ health }: { health: EvidenceHealthDetail }) => {
  const { totalJobs, jobsWithEvidence, jobsAnnotatedFrame, jobsTubeletMontage,
    jobsWithFrames, totalFrameCount, missingEvidence } = health;

  const pct = (n: number) =>
    totalJobs > 0 ? Math.round((n / totalJobs) * 100) : 0;

  const rows = [
    { label: "Annotated Frame", count: jobsAnnotatedFrame, color: "#22c55e" },
    { label: "Tubelet Montage", count: jobsTubeletMontage, color: "#6366f1" },
    { label: "Frame Sets", count: jobsWithFrames, color: "#0891b2" },
    { label: "Missing Evidence", count: missingEvidence, color: "#6b7280" },
  ];

  return (
    <Card className="bg-card border-border shadow-sm h-fit self-start">
      <CardHeader className="pb-2">
        <CardTitle className="text-foreground text-base font-semibold">Evidence Health</CardTitle>
        <CardDescription className="text-muted-foreground text-xs">
          Evidence object availability across reasoning jobs
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {totalJobs === 0 ? (
          <div className="flex items-center justify-center h-24 text-zinc-600 text-xs">
            No reasoning jobs found
          </div>
        ) : (
          <div className="space-y-1">
            {/* Summary line */}
            <div className="flex items-center justify-between py-2 border-b border-zinc-800/50 mb-3">
              <span className="text-xs text-zinc-400">Jobs with evidence</span>
              <span className="text-sm font-semibold font-mono text-zinc-200">
                {jobsWithEvidence} / {totalJobs}
                <span className="text-zinc-500 ml-1.5 text-xs font-normal">
                  ({pct(jobsWithEvidence)}%)
                </span>
              </span>
            </div>

            {rows.map((row) => (
              <div key={row.label} className="flex items-center gap-3 py-1">
                <span className="text-[11px] text-zinc-500 w-28 flex-shrink-0">{row.label}</span>
                <div className="flex-1 h-1 rounded-full bg-zinc-800 overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${pct(row.count)}%`,
                      backgroundColor: row.color,
                      opacity: 0.75,
                    }}
                  />
                </div>
                <span className="text-[11px] font-mono text-zinc-400 w-16 text-right flex-shrink-0">
                  {row.count}
                  <span className="text-zinc-600 ml-1">({pct(row.count)}%)</span>
                </span>
              </div>
            ))}

            {totalFrameCount > 0 && (
              <div className="flex items-center justify-between pt-2 mt-1 border-t border-zinc-800/40">
                <span className="text-[11px] text-zinc-600">Total individual frames</span>
                <span className="text-[11px] font-mono text-zinc-500">{totalFrameCount}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
