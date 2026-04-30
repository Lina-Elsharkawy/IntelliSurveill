'use client';

import {
  TrendingUp, Activity, Shield, BarChart3, Star, Clock, UserCheck, UserX
} from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { StatsCard } from "@/components/StatsCard";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, Legend
} from "recharts";
import { useMemo, useState } from "react";

// ── Shared Types & Helpers ───────────────────────────────────────────────────
type Range = "today" | "7days" | "30days" | "90days";

const tooltipStyle = {
  backgroundColor: "hsl(var(--popover))",
  border: "1px solid hsl(var(--border))",
  borderRadius: "var(--radius)",
  color: "hsl(var(--popover-foreground))",
  fontSize: 12,
};

function filterByRange<T extends { timestamp: string }>(records: T[], range: Range): T[] {
  const now = new Date();
  const cutoff = new Date(now);
  if (range === "today") cutoff.setHours(0, 0, 0, 0);
  if (range === "7days") cutoff.setDate(now.getDate() - 7);
  if (range === "30days") cutoff.setDate(now.getDate() - 30);
  if (range === "90days") cutoff.setDate(now.getDate() - 90);

  const filtered = records.filter(r => new Date(r.timestamp) >= cutoff);
  return filtered.length > 0 ? filtered : records;
}

// ── 1. Anomaly Data Model ────────────────────────────────────────────────────
interface AnomalyRecord {
  timestamp: string;
  qualityScore: number;
  zone: string;
  severity: "low" | "medium" | "high";
}

const RAW_ANOMALIES: AnomalyRecord[] = [
  { timestamp: "2025-04-21T00:15:00Z", qualityScore: 72, zone: "Lab 1", severity: "low" },
  { timestamp: "2025-04-21T01:45:00Z", qualityScore: 88, zone: "Lab 3", severity: "high" },
  { timestamp: "2025-04-21T04:10:00Z", qualityScore: 55, zone: "Lab 2", severity: "medium" },
  { timestamp: "2025-04-21T08:20:00Z", qualityScore: 91, zone: "Lab 4", severity: "high" },
  { timestamp: "2025-04-21T13:15:00Z", qualityScore: 95, zone: "Lab 1", severity: "high" },
  { timestamp: "2025-04-21T17:20:00Z", qualityScore: 78, zone: "Lab 3", severity: "medium" },
  { timestamp: "2025-04-22T08:00:00Z", qualityScore: 92, zone: "Lab 2", severity: "high" },
  { timestamp: "2025-04-23T09:00:00Z", qualityScore: 93, zone: "Lab 2", severity: "high" },
  { timestamp: "2025-04-23T16:45:00Z", qualityScore: 87, zone: "Lab 1", severity: "high" },
];

const SEVERITY_COLORS: Record<string, string> = {
  high: "hsl(var(--destructive))",
  medium: "hsl(var(--warning))",
  low: "hsl(var(--success))",
};

// ── 2. Face Recognition Data Model ───────────────────────────────────────────
interface RecognitionRecord {
  timestamp: string;
  zone: string;
  status: "identified" | "unidentified" | "flagged";
  confidence: number;
}

const RAW_RECOGNITION_DATA: RecognitionRecord[] = [
  { timestamp: "2025-04-21T00:15:00Z", zone: "Lab 1", status: "identified", confidence: 98 },
  { timestamp: "2025-04-21T01:45:00Z", zone: "Lab 3", status: "unidentified", confidence: 45 },
  { timestamp: "2025-04-21T04:10:00Z", zone: "Lab 2", status: "identified", confidence: 92 },
  { timestamp: "2025-04-21T08:20:00Z", zone: "Lab 4", status: "flagged", confidence: 88 },
  { timestamp: "2025-04-21T13:15:00Z", zone: "Lab 1", status: "flagged", confidence: 95 },
  { timestamp: "2025-04-22T08:00:00Z", zone: "Lab 2", status: "identified", confidence: 99 },
  { timestamp: "2025-04-22T10:45:00Z", zone: "Lab 4", status: "unidentified", confidence: 52 },
  { timestamp: "2025-04-22T15:30:00Z", zone: "Lab 2", status: "flagged", confidence: 91 },
  { timestamp: "2025-04-23T16:45:00Z", zone: "Lab 1", status: "identified", confidence: 97 },
];

const STATUS_COLORS: Record<string, string> = {
  identified: "hsl(var(--success))",
  unidentified: "hsl(var(--warning))",
  flagged: "hsl(var(--destructive))",
};

// ── Chart Builders ───────────────────────────────────────────────────────────
function buildHourlyIncidentVolume(records: AnomalyRecord[]) {
  const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);
  const counts: Record<string, number> = Object.fromEntries(hours.map(h => [h, 0]));
  records.forEach(r => {
    const h = new Date(r.timestamp).getHours();
    const key = `${String(h).padStart(2, "0")}:00`;
    counts[key]++;
  });
  return hours.map(h => ({ time: h, count: counts[h] }));
}

function buildDailyTrend(records: AnomalyRecord[]) {
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const counts: Record<string, number> = Object.fromEntries(days.map(d => [d, 0]));
  records.forEach(r => { counts[days[new Date(r.timestamp).getDay()]]++; });
  return days.map(d => ({ name: d, anomalies: counts[d] }));
}

// ── Main Component ───────────────────────────────────────────────────────────
const Analytics = () => {
  const [range, setRange] = useState<Range>("7days");

  // Filter Data
  const anomalyRecords = useMemo(() => filterByRange(RAW_ANOMALIES, range), [range]);
  const bioRecords = useMemo(() => filterByRange(RAW_RECOGNITION_DATA, range), [range]);

  // 1. Anomaly Logic
  const totalAnomalies = anomalyRecords.length;
  const avgQuality = totalAnomalies ? Math.round(anomalyRecords.reduce((s, r) => s + r.qualityScore, 0) / totalAnomalies) : 0;
  const highCount = anomalyRecords.filter(r => r.severity === "high").length;

  const peakHour = useMemo(() => {
    const counts: Record<number, number> = {};
    anomalyRecords.forEach(r => { const h = new Date(r.timestamp).getHours(); counts[h] = (counts[h] || 0) + 1; });
    const peak = Object.entries(counts).sort((a, b) => +b[1] - +a[1])[0];
    if (!peak) return "—";
    return `${String(peak[0]).padStart(2, "0")}:00`;
  }, [anomalyRecords]);

  const dailyTrend = useMemo(() => buildDailyTrend(anomalyRecords), [anomalyRecords]);
  const hourlyVolume = useMemo(() => buildHourlyIncidentVolume(anomalyRecords), [anomalyRecords]);

  // 2. Biometric Logic
  const bioStats = useMemo(() => {
    const total = bioRecords.length;
    const identified = bioRecords.filter(r => r.status === "identified").length;
    const unidentified = bioRecords.filter(r => r.status === "unidentified").length;
    const flagged = bioRecords.filter(r => r.status === "flagged").length;
    const avgConf = total ? Math.round(bioRecords.reduce((acc, r) => acc + r.confidence, 0) / total) : 0;
    return { total, identified, unidentified, flagged, avgConf };
  }, [bioRecords]);

  const recognitionDist = useMemo(() => [
    { name: "Identified", value: bioStats.identified, color: STATUS_COLORS.identified },
    { name: "Unidentified", value: bioStats.unidentified, color: STATUS_COLORS.unidentified },
    { name: "Flagged", value: bioStats.flagged, color: STATUS_COLORS.flagged },
  ], [bioStats]);

  // Create the Stacked Bar Chart mapping out the Zones
  const zoneRecognitionMap = useMemo(() => {
    const zones = Array.from(new Set(bioRecords.map(r => r.zone)));
    return zones.map(zone => ({
      zone,
      identified: bioRecords.filter(r => r.zone === zone && r.status === "identified").length,
      unidentified: bioRecords.filter(r => r.zone === zone && r.status === "unidentified").length,
      flagged: bioRecords.filter(r => r.zone === zone && r.status === "flagged").length,
    }));
  }, [bioRecords]);

  return (
    <DashboardLayout>
      <div className="space-y-10">

        {/* Global Header & Controls */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Security Analytics</h1>
            <p className="text-muted-foreground">Historical anomalies and biometric intelligence</p>
          </div>
          <Select value={range} onValueChange={(v) => setRange(v as Range)}>
            <SelectTrigger className="w-48 bg-secondary border-border">
              <SelectValue placeholder="Time range" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="today">Today</SelectItem>
              <SelectItem value="7days">Last 7 days</SelectItem>
              <SelectItem value="30days">Last 30 days</SelectItem>
              <SelectItem value="90days">Last 90 days</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* ── SECTION 1: SURVEILLANCE INTELLIGENCE ── */}
        <div className="space-y-6">

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatsCard title="Total Anomalies" value={String(totalAnomalies)} icon={Activity} variant="default" />
            <StatsCard title="Avg Capture Quality" value={`${avgQuality}%`} icon={Star} variant="success" />
            <StatsCard title="Critical Events" value={String(highCount)} icon={Shield} variant="destructive" />
            <StatsCard title="Peak Incident Time" value={peakHour} icon={Clock} variant="warning" />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle>Anomalies by Day</CardTitle>
                <CardDescription>Frequency of detections per weekday</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={dailyTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Bar dataKey="anomalies" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle>Incident Peak Analysis</CardTitle>
                <CardDescription>Anomaly detection frequency across 24-hour cycle</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={hourlyVolume}>
                    <defs>
                      <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="hsl(var(--primary))" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} interval={3} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Area type="monotone" dataKey="count" stroke="hsl(var(--primary))" fillOpacity={1} fill="url(#colorCount)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* ── SECTION 2: BIOMETRIC INTELLIGENCE ── */}
        <div className="space-y-6">


          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Chart 1: The Pie Chart (Left Side) */}
            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle>Recognition Status</CardTitle>
                <CardDescription>Ratio of identified vs. unknown subjects</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={recognitionDist}
                      innerRadius={60}
                      outerRadius={100}
                      paddingAngle={5}
                      dataKey="value"
                    >
                      {recognitionDist.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend verticalAlign="bottom" height={36} />
                  </PieChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            {/* Chart 2: Zone Activity Bar Chart (Right Side) */}
            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle>Detections by Zone</CardTitle>
                <CardDescription>Facial recognition distribution across locations</CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={zoneRecognitionMap}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="zone" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} allowDecimals={false} />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend verticalAlign="bottom" height={36} />
                    <Bar dataKey="identified" name="Known" stackId="a" fill={STATUS_COLORS.identified} />
                    <Bar dataKey="unidentified" name="Unidentified" stackId="a" fill={STATUS_COLORS.unidentified} />
                    <Bar dataKey="flagged" name="Flagged" stackId="a" fill={STATUS_COLORS.flagged} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

          </div>
        </div>

      </div>
    </DashboardLayout>
  );
};

export default Analytics;