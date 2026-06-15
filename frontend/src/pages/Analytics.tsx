import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Activity, Users, Clock, ScanFace, Camera } from "lucide-react";
import { VolumeChart, RatioDonut, CameraDistribution, MarginRiskAnalysis, QualityTrendChart } from "../components/AnalyticsCharts";
import { analyticsService, EntryLog, AnalyticsMetrics } from "../services/analyticsService";

type TimeRange = "today" | "7days" | "30days";

export default function AnalyticsPage() {
  const [logs, setLogs] = useState<EntryLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>("today");

  useEffect(() => {
    // We fetch a larger limit to ensure we have enough data for 7/30 days
    analyticsService.getRecentLogs(5000)
      .then(setLogs)
      .catch(err => console.error("Failed to fetch analytics:", err))
      .finally(() => setLoading(false));
  }, []);

  const filteredLogs = useMemo(() => {
    const now = new Date();
    const cutoff = new Date();

    if (timeRange === "today") cutoff.setHours(0, 0, 0, 0);
    else if (timeRange === "7days") cutoff.setDate(now.getDate() - 7);
    else if (timeRange === "30days") cutoff.setDate(now.getDate() - 30);

    return logs.filter(log => {
      const logDateStr = log.created_at || log.timestamp;
      if (!logDateStr) return false;
      const logDate = new Date(logDateStr);
      
      return logDate >= cutoff;
    });
  }, [logs, timeRange]);

  const metrics: AnalyticsMetrics = useMemo(() => 
    analyticsService.calculateMetrics(filteredLogs), 
  [filteredLogs]);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="mb-2">
          <h1 className="text-3xl font-bold text-foreground mb-1">Analytics Dashboard</h1>
          <p className="text-muted-foreground text-sm">Operational overview of face recognition activity</p>
        </div>

        {/* Time range filter */}
        <div className="flex justify-end gap-4 items-center">
          <Select value={timeRange} onValueChange={(val) => setTimeRange(val as TimeRange)}>
            <SelectTrigger className="w-[150px] bg-zinc-950/60 border-zinc-800 hover:border-emerald-500/40 focus:border-emerald-500/50 transition-colors text-sm">
              <SelectValue placeholder="Select Time" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-950 border-zinc-800">
              <SelectItem value="today">Today</SelectItem>
              <SelectItem value="7days">Last 7 Days</SelectItem>
              <SelectItem value="30days">Last 30 Days</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {loading ? (
           <div className="flex flex-col items-center justify-center gap-3 py-20 text-zinc-500">
             <div className="flex gap-1.5">
               {[0,1,2].map(i => (
                 <span key={i} className="w-2 h-2 rounded-full bg-emerald-500/50 animate-bounce" style={{ animationDelay: `${i * 120}ms` }} />
               ))}
             </div>
             <p className="text-sm tracking-wide">Processing telemetry…</p>
           </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              <StatCard title="Total Detections" value={metrics.total} icon={<ScanFace className="w-5 h-5 text-blue-500" />} />
              <StatCard title="Known Ratio" value={`${metrics.knownRatio}%`} icon={<Users className="w-5 h-5 text-emerald-500" />} />
              <StatCard title="Avg Quality" value={metrics.avgQuality} icon={<Camera className="w-5 h-5 text-cyan-500" />} />
              <StatCard title="Match Confidence" value={metrics.avgSimilarity} icon={<Activity className="w-5 h-5 text-emerald-400" />} />
              <StatCard title="Model Margin" value={metrics.avgMargin} icon={<Activity className="w-5 h-5 text-amber-500" />} />
              <StatCard title="Pipeline Time" value={`${metrics.avgTime}ms`} icon={<Clock className="w-5 h-5 text-purple-500" />} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Pass the timeRange to the VolumeChart */}
              <VolumeChart logs={filteredLogs} timeRange={timeRange} />
              
              <div className="flex flex-col gap-6">
                  <RatioDonut known={metrics.knownCount} unknown={metrics.unknownCount} />
                  <CameraDistribution logs={filteredLogs} /> 
              </div>

              <div className="lg:col-span-2">
                 <QualityTrendChart logs={filteredLogs} timeRange={timeRange} />
              </div>
              <MarginRiskAnalysis logs={filteredLogs} />
            </div>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}

// StatCard matching the Admin page KPI card style
const StatCard = ({ title, value, icon }: { title: string; value: string | number; icon: React.ReactNode }) => (
  <Card className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border-zinc-800">
    <CardContent className="p-4">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs font-medium text-zinc-400 uppercase tracking-wider">{title}</p>
          <h3 className="text-xl font-bold text-foreground mt-1 drop-shadow-[0_0_6px_rgba(16,185,129,0.2)]">{value}</h3>
        </div>
        <div className="p-2 bg-zinc-800/60 rounded-lg border border-zinc-700/50">{icon}</div>
      </div>
    </CardContent>
  </Card>
);