// src/components/AnomalyAnalyticsTab.tsx
import { useState, useEffect, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AlertTriangle, CheckCircle, XCircle, Clock, ShieldAlert, Target, Info } from "lucide-react";
import { getAnomalyCandidates, AnomalyCandidate } from "../services/anomalyCandidatesService";
import { ScoreDistributionChart, CandidateReasonsChart, ReasoningDecisionsChart, CameraAnomalyDistribution, AnomalyTimelineChart } from "./AnomalyAnalyticsCharts";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

type TimeRange = "today" | "7days" | "30days";

export function AnomalyAnalyticsTab() {
  const [candidates, setCandidates] = useState<AnomalyCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>("today");

  useEffect(() => {
    getAnomalyCandidates()
      .then(setCandidates)
      .catch(err => console.error("Failed to fetch anomaly candidates:", err))
      .finally(() => setLoading(false));
  }, []);

  const filteredCandidates = useMemo(() => {
    const now = new Date();
    const cutoff = new Date();

    if (timeRange === "today") cutoff.setHours(0, 0, 0, 0);
    else if (timeRange === "7days") cutoff.setDate(now.getDate() - 7);
    else if (timeRange === "30days") cutoff.setDate(now.getDate() - 30);

    return candidates.filter(c => {
      if (!c.createdAt) return false;
      const cDate = new Date(c.createdAt);
      
      return cDate >= cutoff;
    });
  }, [candidates, timeRange]);

  const metrics = useMemo(() => {
    let confirmed = 0;
    let rejected = 0;
    let pending = 0;
    let falsePositives = 0;
    let normalCalibration = 0;
    let sumScore = 0;
    let maxScore = 0;

    filteredCandidates.forEach(c => {
      const decision = c.parsedDecision?.alert_decision?.toLowerCase();
      if (decision === 'yes') confirmed++;
      else if (decision === 'no') rejected++;
      else pending++;

      if (c.status === 'discarded') falsePositives++;
      // We assume discarded might also mean normal calibration if we had that specific status, 
      // but without it, let's look for calibration in the narrative or status.
      if (c.status === 'resolved' && decision === 'no') normalCalibration++; 

      const score = c.finalScore || 0;
      sumScore += score;
      if (score > maxScore) maxScore = score;
    });

    return {
      total: filteredCandidates.length,
      confirmed,
      rejected,
      pending,
      falsePositives,
      normalCalibration,
      avgScore: filteredCandidates.length > 0 ? (sumScore / filteredCandidates.length).toFixed(2) : "0.00",
      maxScore: maxScore.toFixed(2),
      alertRate: filteredCandidates.length > 0 ? ((confirmed / filteredCandidates.length) * 100).toFixed(1) : "0.0"
    };
  }, [filteredCandidates]);

  const highRiskEvents = useMemo(() => {
    return [...filteredCandidates]
      .filter(c => (c.finalScore || 0) > 0.6 || c.severity === 'high')
      .sort((a, b) => (b.finalScore || 0) - (a.finalScore || 0))
      .slice(0, 5);
  }, [filteredCandidates]);

  if (loading) {
    return <div className="h-64 flex items-center justify-center text-muted-foreground">Processing anomaly telemetry...</div>;
  }

  return (
    <div className="space-y-6 mt-4">
      <div className="flex flex-col md:flex-row justify-between items-center gap-4">
        <h2 className="text-xl font-bold text-foreground">Anomaly Telemetry</h2>
        
        <div className="flex gap-4 items-center">
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
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
        <StatCard title="Total Candidates" value={metrics.total} icon={<Target className="w-5 h-5 text-blue-500" />} />
        <StatCard title="Alerts Confirmed" value={metrics.confirmed} icon={<AlertTriangle className="w-5 h-5 text-red-500" />} />
        <StatCard title="Reasoning Rejected" value={metrics.rejected} icon={<ShieldAlert className="w-5 h-5 text-emerald-500" />} />
        <StatCard title="Pending Review" value={metrics.pending} icon={<Clock className="w-5 h-5 text-yellow-500" />} />
        <StatCard title="Alert Rate" value={`${metrics.alertRate}%`} icon={<Activity className="w-5 h-5 text-purple-500" />} />
        <StatCard title="False Positives" value={metrics.falsePositives} icon={<XCircle className="w-5 h-5 text-muted-foreground" />} />
        <StatCard title="Avg Score" value={metrics.avgScore} icon={<Info className="w-5 h-5 text-cyan-500" />} />
        <StatCard title="Highest Score" value={metrics.maxScore} icon={<AlertTriangle className="w-5 h-5 text-orange-500" />} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <AnomalyTimelineChart candidates={filteredCandidates} timeRange={timeRange} />
        <ScoreDistributionChart candidates={filteredCandidates} />
        <ReasoningDecisionsChart candidates={filteredCandidates} />
        <CandidateReasonsChart candidates={filteredCandidates} />
        <CameraAnomalyDistribution candidates={filteredCandidates} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="bg-card border-border shadow-sm lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-foreground text-lg">Recent High-Risk Events</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Camera</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead>Reasons</TableHead>
                  <TableHead>Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {highRiskEvents.length > 0 ? highRiskEvents.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="font-medium">{new Date(event.createdAt).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</TableCell>
                    <TableCell>Cam {event.cameraId}</TableCell>
                    <TableCell>
                      <span className={event.finalScore && event.finalScore > 0.6 ? 'text-red-500 font-bold' : ''}>
                        {event.finalScore?.toFixed(2) || 'N/A'}
                      </span>
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate" title={event.candidateReasons.join(', ')}>
                      {event.candidateReasons.join(', ') || 'Unknown'}
                    </TableCell>
                    <TableCell>
                       {event.parsedDecision?.alert_decision?.toLowerCase() === 'yes' ? (
                          <Badge variant="destructive">Alert YES</Badge>
                        ) : event.parsedDecision?.alert_decision?.toLowerCase() === 'no' ? (
                          <Badge variant="secondary" className="bg-emerald-500/20 text-emerald-500">Alert NO</Badge>
                        ) : (
                          <Badge variant="outline">Pending</Badge>
                        )}
                    </TableCell>
                  </TableRow>
                )) : (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-6">No high risk events found</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card className="bg-card border-border shadow-sm">
          <CardHeader>
            <CardTitle className="text-foreground text-lg flex items-center gap-2">
               <CheckCircle className="w-5 h-5 text-emerald-500" />
               Calibration Readiness
            </CardTitle>
          </CardHeader>
          <CardContent>
             <div className="flex flex-col gap-4">
                <div className="flex justify-between items-center border-b border-border pb-2">
                   <span className="text-sm text-muted-foreground">Normal Samples</span>
                   <span className="font-bold text-foreground">{metrics.normalCalibration} / 20+</span>
                </div>
                <div className="flex justify-between items-center border-b border-border pb-2">
                   <span className="text-sm text-muted-foreground">Status</span>
                   {metrics.normalCalibration >= 20 ? (
                      <Badge className="bg-emerald-500">Ready</Badge>
                   ) : metrics.normalCalibration > 0 ? (
                      <Badge variant="outline" className="text-yellow-500 border-yellow-500">Gathering</Badge>
                   ) : (
                      <Badge variant="outline" className="text-muted-foreground">Not Enough</Badge>
                   )}
                </div>
                <p className="text-xs text-muted-foreground mt-2 leading-relaxed">
                   The distribution model automatically updates when enough normal samples are captured and marked as safe.
                </p>
             </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// Minimal StatCard for Anomaly Tab to match Analytics
const StatCard = ({ title, value, icon }: { title: string, value: string | number, icon: React.ReactNode }) => (
  <Card className="bg-card border-border shadow-sm">
    <CardContent className="p-4">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{title}</p>
          <h3 className="text-lg font-bold text-foreground mt-1">{value}</h3>
        </div>
        <div className="p-1.5 bg-secondary rounded-md">{icon}</div>
      </div>
    </CardContent>
  </Card>
);

// We need an Activity icon for the Alert Rate
function Activity(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
    </svg>
  );
}
