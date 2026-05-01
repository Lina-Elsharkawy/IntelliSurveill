import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
// Assuming you have a Select component in your ui folder
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Activity, Users, Clock, ScanFace, Camera } from "lucide-react";
import { VolumeChart, RatioDonut, CameraDistribution, MarginRiskAnalysis, QualityTrendChart } from "../components/AnalyticsCharts";
import { analyticsService, EntryLog, AnalyticsMetrics } from "../services/analyticsService";

type TimeRange = "today" | "7days" | "30days";

export default function AnalyticsPage() {
  const [logs, setLogs] = useState<EntryLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [cameraFilter, setCameraFilter] = useState<number | "all">("all");
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
      
      const passesTime = logDate >= cutoff;
      const passesCamera = cameraFilter === "all" || log.camera_id === cameraFilter;
      
      return passesTime && passesCamera;
    });
  }, [logs, cameraFilter, timeRange]);

  const metrics: AnalyticsMetrics = useMemo(() => 
    analyticsService.calculateMetrics(filteredLogs), 
  [filteredLogs]);

  const availableCameras = useMemo(() => 
    Array.from(new Set(logs.map(l => l.camera_id))).sort(), 
  [logs]);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header & Controls */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-1">Recognition Analytics</h1>
            <p className="text-muted-foreground text-sm">Real-time inference telemetry</p>
          </div>
          
          <div className="flex gap-4 items-center">
             {/* New Time Filter Dropdown */}
             <Select value={timeRange} onValueChange={(val) => setTimeRange(val as TimeRange)}>
                <SelectTrigger className="w-[150px] bg-card border-border">
                  <SelectValue placeholder="Select Time" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="today">Today</SelectItem>
                  <SelectItem value="7days">Last 7 Days</SelectItem>
                  <SelectItem value="30days">Last 30 Days</SelectItem>
                </SelectContent>
              </Select>

            <div className="flex gap-2 bg-secondary p-1 border border-border rounded-lg">
              <Button variant={cameraFilter === "all" ? "default" : "ghost"} size="sm" onClick={() => setCameraFilter("all")}>
                All Cameras
              </Button>
              {availableCameras.map(cam => (
                <Button key={cam} variant={cameraFilter === cam ? "default" : "ghost"} size="sm" onClick={() => setCameraFilter(cam)}>
                  Cam {cam}
                </Button>
              ))}
            </div>
          </div>
        </div>

        {loading ? (
           <div className="h-64 flex items-center justify-center text-muted-foreground">Processing telemetry...</div>
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

// Updated StatCard to use 'bg-card' for a slightly lighter dark theme
const StatCard = ({ title, value, icon }: { title: string, value: string | number, icon: React.ReactNode }) => (
  <Card className="bg-card border-border shadow-sm">
    <CardContent className="p-4">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-xs font-medium text-muted-foreground">{title}</p>
          <h3 className="text-xl font-bold text-foreground mt-1">{value}</h3>
        </div>
        <div className="p-2 bg-secondary rounded-lg">{icon}</div>
      </div>
    </CardContent>
  </Card>
);