// src/components/AnalyticsCharts.tsx
import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AreaChart, Area, PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, LineChart, Line } from "recharts";
import { EntryLog } from "../services/analyticsService";

const STATUS_COLORS = { known: "hsl(142.1 76.2% 36.3%)", unknown: "hsl(38 92% 50%)" };
const tooltipStyle = { backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px", color: "hsl(var(--foreground))", fontSize: 12 };

export const VolumeChart = ({ logs, timeRange }: { logs: EntryLog[], timeRange: string }) => {
  const chartData = useMemo(() => {
    if (timeRange === "today") {
      const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);
      const counts: Record<string, { known: number; unknown: number }> = Object.fromEntries(hours.map(h => [h, { known: 0, unknown: 0 }]));
      
      logs.forEach(log => {
        const dateStr = log.created_at || log.timestamp;
        if (!dateStr) return;
        const h = new Date(dateStr).getHours();
        const key = `${String(h).padStart(2, "0")}:00`;
        if (log.detected_id) counts[key].known++;
        else counts[key].unknown++;
      });
      return hours.map(h => ({ time: h, ...counts[h] }));
    } else {
      // Logic for 7days or 30days (Group by Date)
      const counts: Record<string, { known: number; unknown: number }> = {};
      logs.forEach(log => {
         const dateStr = log.created_at || log.timestamp;
         if (!dateStr) return;
         // Format as YYYY-MM-DD
         const dateKey = new Date(dateStr).toISOString().split('T')[0]; 
         if (!counts[dateKey]) counts[dateKey] = { known: 0, unknown: 0 };

         if (log.detected_id) counts[dateKey].known++;
         else counts[dateKey].unknown++;
      });
      // Convert to array and sort by date
      return Object.entries(counts).map(([date, data]) => ({ time: date, ...data })).sort((a,b) => a.time.localeCompare(b.time));
    }
  }, [logs, timeRange]);

  return (
    <Card className="bg-card border-border shadow-sm lg:col-span-2">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Detection Volume ({timeRange === 'today' ? '24h' : timeRange})</CardTitle>
        <CardDescription className="text-muted-foreground">Known vs unknown subjects over time</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
               <defs>
                <linearGradient id="fillKnown" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={STATUS_COLORS.known} stopOpacity={0.3}/><stop offset="95%" stopColor={STATUS_COLORS.known} stopOpacity={0}/></linearGradient>
                <linearGradient id="fillUnknown" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={STATUS_COLORS.unknown} stopOpacity={0.3}/><stop offset="95%" stopColor={STATUS_COLORS.unknown} stopOpacity={0}/></linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} interval={timeRange === 'today' ? 3 : 'preserveStartEnd'} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: 'hsl(var(--foreground))' }} cursor={{ stroke: 'hsl(var(--muted))' }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
              <Area type="monotone" name="Known" dataKey="known" stroke={STATUS_COLORS.known} strokeWidth={2} fillOpacity={1} fill="url(#fillKnown)" />
              <Area type="monotone" name="Unknown" dataKey="unknown" stroke={STATUS_COLORS.unknown} strokeWidth={2} fillOpacity={1} fill="url(#fillUnknown)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const RatioDonut = ({ known, unknown }: { known: number, unknown: number }) => {
  const data = [{ name: "Known", value: known, color: STATUS_COLORS.known }, { name: "Unknown", value: unknown, color: STATUS_COLORS.unknown }];
  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Recognition Ratio</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={60} outerRadius={80} paddingAngle={2} dataKey="value" stroke="none">
                {data.map((entry, index) => <Cell key={`cell-${index}`} fill={entry.color} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} itemStyle={{ color: 'hsl(var(--foreground))' }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const CameraDistribution = ({ logs }: { logs: EntryLog[] }) => {
  const data = useMemo(() => {
    const cameras = Array.from(new Set(logs.map(r => r.camera_id))).sort((a, b) => a - b);
    return cameras.map(cam => ({
      camera: `Cam ${cam}`,
      known: logs.filter(r => r.camera_id === cam && r.detected_id !== null).length,
      unknown: logs.filter(r => r.camera_id === cam && r.detected_id === null).length,
    }));
  }, [logs]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Edge Device Dist.</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[200px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 10, left: -20, bottom: 0 }} barSize={40}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="camera" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'hsl(var(--muted))' }} />
              <Legend iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
              <Bar dataKey="known" name="Known" stackId="a" fill={STATUS_COLORS.known} radius={[0, 0, 4, 4]} />
              <Bar dataKey="unknown" name="Unknown" stackId="a" fill={STATUS_COLORS.unknown} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const QualityTrendChart = ({ logs, timeRange }: { logs: EntryLog[], timeRange: string }) => {
    const chartData = useMemo(() => {
        if (timeRange === "today") {
            const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);
            const counts: Record<string, { sum: number; count: number }> = Object.fromEntries(
                hours.map(h => [h, { sum: 0, count: 0 }])
            );
            
            logs.forEach(log => {
                const dateStr = log.created_at || log.timestamp;
                if (!dateStr || !log.quality_score) return;
                
                const h = new Date(dateStr).getHours();
                const key = `${String(h).padStart(2, "0")}:00`;
                
                counts[key].sum += log.quality_score;
                counts[key].count++;
            });
            
            return hours.map(h => ({ 
                time: h, 
                avgQuality: counts[h].count > 0 ? Number((counts[h].sum / counts[h].count).toFixed(2)) : null 
            }));
        } else {
            // Logic for 7days or 30days
            const counts: Record<string, { sum: number; count: number }> = {};
            logs.forEach(log => {
                 const dateStr = log.created_at || log.timestamp;
                 if (!dateStr || !log.quality_score) return;
                 const dateKey = new Date(dateStr).toISOString().split('T')[0]; 
                 if (!counts[dateKey]) counts[dateKey] = { sum: 0, count: 0 };
        
                 counts[dateKey].sum += log.quality_score;
                 counts[dateKey].count++;
            });
            return Object.entries(counts).map(([date, data]) => ({ 
                time: date, 
                avgQuality: data.count > 0 ? Number((data.sum / data.count).toFixed(2)) : null 
            })).sort((a,b) => a.time.localeCompare(b.time));
        }
      }, [logs, timeRange]);

  return (
    <Card className="bg-card border-border shadow-sm">
      <CardHeader>
        <CardTitle className="text-foreground text-lg">Capture Quality Over Time</CardTitle>
        <CardDescription className="text-muted-foreground">Track lighting drops or camera obstruction</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="h-[250px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} interval={timeRange === 'today' ? 3 : 'preserveStartEnd'} />
              <YAxis domain={[0, 1]} stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" name="Avg Quality" dataKey="avgQuality" stroke="#06b6d4" strokeWidth={3} dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
};

export const MarginRiskAnalysis = ({ logs }: { logs: EntryLog[] }) => {
    const data = useMemo(() => {
      const knownLogs = logs.filter(l => l.detected_id !== null);
      const safe = knownLogs.filter(l => l.margin >= 0.2).length;
      const warning = knownLogs.filter(l => l.margin >= 0.1 && l.margin < 0.2).length;
      const danger = knownLogs.filter(l => l.margin < 0.1).length;
  
      return [
        { name: "Safe (>0.2)", value: safe, color: "hsl(142.1 76.2% 36.3%)" }, // Green
        { name: "Warning (0.1 - 0.2)", value: warning, color: "hsl(38 92% 50%)" }, // Yellow
        { name: "Danger (<0.1)", value: danger, color: "hsl(0 84.2% 60.2%)" } // Red
      ];
    }, [logs]);
  
    return (
      <Card className="bg-card border-border shadow-sm">
        <CardHeader>
          <CardTitle className="text-foreground text-lg">Identity Conflict Risk</CardTitle>
          <CardDescription className="text-muted-foreground">Model certainty breakdown</CardDescription>
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