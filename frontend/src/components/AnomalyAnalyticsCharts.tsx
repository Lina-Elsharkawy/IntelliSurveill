// src/components/AnomalyAnalyticsCharts.tsx
import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AreaChart, Area, PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, LineChart, Line } from "recharts";
import { AnomalyCandidate } from "../services/anomalyCandidatesService";

const STATUS_COLORS = { 
  alertYes: "hsl(0 84.2% 60.2%)", // Red
  alertNo: "hsl(142.1 76.2% 36.3%)", // Green
  pending: "hsl(38 92% 50%)", // Yellow
  unknown: "hsl(var(--muted-foreground))"
};
const tooltipStyle = { backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px", color: "hsl(var(--foreground))", fontSize: 12 };

export const ScoreDistributionChart = ({ candidates }: { candidates: AnomalyCandidate[] }) => {
  const data = useMemo(() => {
    const bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0];
    const counts = [0, 0, 0, 0, 0];
    candidates.forEach(c => {
      const score = c.finalScore || 0;
      if (score < 0.2) counts[0]++;
      else if (score < 0.4) counts[1]++;
      else if (score < 0.6) counts[2]++;
      else if (score < 0.8) counts[3]++;
      else counts[4]++;
    });
    return [
      { range: "0.0 - 0.2", count: counts[0] },
      { range: "0.2 - 0.4", count: counts[1] },
      { range: "0.4 - 0.6", count: counts[2] },
      { range: "0.6 - 0.8", count: counts[3] },
      { range: "0.8 - 1.0", count: counts[4] },
    ];
  }, [candidates]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Final Score Distribution</CardTitle>
        <CardDescription className="text-muted-foreground">Distribution of anomaly scores</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[250px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="range" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'hsl(var(--muted))' }} />
              <Bar dataKey="count" name="Candidates" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const CandidateReasonsChart = ({ candidates }: { candidates: AnomalyCandidate[] }) => {
  const data = useMemo(() => {
    const reasonCounts: Record<string, number> = {};
    candidates.forEach(c => {
      if (!c.candidateReasons || c.candidateReasons.length === 0) {
        reasonCounts["unknown"] = (reasonCounts["unknown"] || 0) + 1;
      } else {
        c.candidateReasons.forEach(r => {
          reasonCounts[r] = (reasonCounts[r] || 0) + 1;
        });
      }
    });

    const colors = ["#0ea5e9", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#64748b"];
    return Object.entries(reasonCounts).map(([name, value], i) => ({
      name: name.replace(/_/g, ' '),
      value,
      color: colors[i % colors.length]
    }));
  }, [candidates]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Candidate Reasons</CardTitle>
        <CardDescription className="text-muted-foreground">Why candidates were flagged</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[250px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={60} outerRadius={90} paddingAngle={2} dataKey="value" stroke="none">
                {data.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const ReasoningDecisionsChart = ({ candidates }: { candidates: AnomalyCandidate[] }) => {
  const data = useMemo(() => {
    let yes = 0, no = 0, pending = 0;
    candidates.forEach(c => {
      const decision = c.parsedDecision?.alert_decision?.toLowerCase();
      if (decision === 'yes') yes++;
      else if (decision === 'no') no++;
      else pending++;
    });
    return [
      { name: "Alert YES", value: yes, color: STATUS_COLORS.alertYes },
      { name: "Alert NO", value: no, color: STATUS_COLORS.alertNo },
      { name: "Pending", value: pending, color: STATUS_COLORS.pending }
    ];
  }, [candidates]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Reasoning Decisions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={60} outerRadius={80} paddingAngle={2} dataKey="value" stroke="none">
                {data.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const CameraAnomalyDistribution = ({ candidates }: { candidates: AnomalyCandidate[] }) => {
  const data = useMemo(() => {
    const counts: Record<number, { alerts: number, dismissed: number, pending: number }> = {};
    candidates.forEach(c => {
      const cam = c.cameraId || 0;
      if (!counts[cam]) counts[cam] = { alerts: 0, dismissed: 0, pending: 0 };
      
      const decision = c.parsedDecision?.alert_decision?.toLowerCase();
      if (decision === 'yes') counts[cam].alerts++;
      else if (decision === 'no') counts[cam].dismissed++;
      else counts[cam].pending++;
    });

    return Object.entries(counts).map(([cam, data]) => ({
      camera: `Cam ${cam}`,
      ...data
    })).sort((a, b) => a.camera.localeCompare(b.camera));
  }, [candidates]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Anomalies by Camera</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }} barSize={30}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="camera" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'hsl(var(--muted))' }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
              <Bar dataKey="alerts" name="Alerts" stackId="a" fill={STATUS_COLORS.alertYes} />
              <Bar dataKey="dismissed" name="Dismissed" stackId="a" fill={STATUS_COLORS.alertNo} />
              <Bar dataKey="pending" name="Pending" stackId="a" fill={STATUS_COLORS.pending} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const AnomalyTimelineChart = ({ candidates, timeRange }: { candidates: AnomalyCandidate[], timeRange: string }) => {
  const chartData = useMemo(() => {
    if (timeRange === "today") {
      const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);
      const counts: Record<string, { count: number }> = Object.fromEntries(hours.map(h => [h, { count: 0 }]));
      
      candidates.forEach(c => {
        const dateStr = c.createdAt;
        if (!dateStr) return;
        const h = new Date(dateStr).getHours();
        const key = `${String(h).padStart(2, "0")}:00`;
        counts[key].count++;
      });
      return hours.map(h => ({ time: h, ...counts[h] }));
    } else {
      const counts: Record<string, { count: number }> = {};
      candidates.forEach(c => {
        const dateStr = c.createdAt;
        if (!dateStr) return;
        const dateKey = new Date(dateStr).toISOString().split('T')[0]; 
        if (!counts[dateKey]) counts[dateKey] = { count: 0 };
        counts[dateKey].count++;
      });
      return Object.entries(counts).map(([date, data]) => ({ time: date, ...data })).sort((a,b) => a.time.localeCompare(b.time));
    }
  }, [candidates, timeRange]);

  return (
    <Card className="bg-card border-border shadow-sm lg:col-span-2">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Candidate Volume ({timeRange === 'today' ? '24h' : timeRange})</CardTitle>
        <CardDescription className="text-muted-foreground">Anomaly candidates over time</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="fillCount" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={STATUS_COLORS.alertYes} stopOpacity={0.3}/>
                  <stop offset="95%" stopColor={STATUS_COLORS.alertYes} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} interval={timeRange === 'today' ? 3 : 'preserveStartEnd'} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: 'hsl(var(--foreground))' }} cursor={{ stroke: 'hsl(var(--muted))' }} />
              <Area type="monotone" name="Candidates" dataKey="count" stroke={STATUS_COLORS.alertYes} strokeWidth={2} fillOpacity={1} fill="url(#fillCount)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};
