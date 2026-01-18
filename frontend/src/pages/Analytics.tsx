import { TrendingUp, Activity, Users, Clock, BarChart3 } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { StatsCard } from "@/components/StatsCard";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

const Analytics = () => {
  const alertsData = [
    { name: "Mon", alerts: 12 },
    { name: "Tue", alerts: 19 },
    { name: "Wed", alerts: 8 },
    { name: "Thu", alerts: 15 },
    { name: "Fri", alerts: 22 },
    { name: "Sat", alerts: 6 },
    { name: "Sun", alerts: 4 },
  ];

  const cameraActivityData = [
    { time: "00:00", activity: 20 },
    { time: "04:00", activity: 10 },
    { time: "08:00", activity: 45 },
    { time: "12:00", activity: 80 },
    { time: "16:00", activity: 75 },
    { time: "20:00", activity: 40 },
  ];

  const severityData = [
    { name: "High", value: 15, color: "hsl(var(--destructive))" },
    { name: "Medium", value: 35, color: "hsl(var(--warning))" },
    { name: "Low", value: 50, color: "hsl(var(--success))" },
  ];

  const zoneActivityData = [
    { zone: "Building A", incidents: 24 },
    { zone: "Building B", incidents: 18 },
    { zone: "Parking", incidents: 32 },
    { zone: "Lab", incidents: 12 },
    
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Analytics & Reports</h1>
            <p className="text-muted-foreground">Detailed insights and security metrics</p>
          </div>
          <Select defaultValue="7days">
            <SelectTrigger className="w-48 bg-secondary border-border">
              <SelectValue placeholder="Time range" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="today">Today</SelectItem>
              <SelectItem value="7days">Last 7 Days</SelectItem>
              <SelectItem value="30days">Last 30 Days</SelectItem>
              <SelectItem value="90days">Last 90 Days</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatsCard
            title="Total Incidents"
            value="247"
            icon={Activity}
            variant="default"
            trend={{ value: "-12% from last week", isPositive: true }}
          />
          <StatsCard
            title="Avg Response Time"
            value="3.2m"
            icon={Clock}
            variant="success"
            trend={{ value: "-30s improvement", isPositive: true }}
          />
          <StatsCard
            title="Peak Activity"
            value="2:30 PM"
            icon={TrendingUp}
            variant="warning"
          />
          <StatsCard
            title="Coverage Rate"
            value="98.5%"
            icon={BarChart3}
            variant="success"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">Weekly Alert Trends</CardTitle>
              <CardDescription className="text-muted-foreground">
                Number of alerts detected this week
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={alertsData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" />
                  <YAxis stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  <Bar dataKey="alerts" fill="hsl(var(--primary))" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">24-Hour Activity Pattern</CardTitle>
              <CardDescription className="text-muted-foreground">
                Camera activity throughout the day
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={cameraActivityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" />
                  <YAxis stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="activity"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    dot={{ fill: "hsl(var(--primary))" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">Alert Severity Distribution</CardTitle>
              <CardDescription className="text-muted-foreground">
                Breakdown by priority level
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={severityData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                    outerRadius={100}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {severityData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">Anomalies by Zone</CardTitle>
              <CardDescription className="text-muted-foreground">
                Most active surveillance areas
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={zoneActivityData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis type="number" stroke="hsl(var(--muted-foreground))" />
                  <YAxis dataKey="zone" type="category" stroke="hsl(var(--muted-foreground))" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: "var(--radius)",
                    }}
                  />
                  <Bar dataKey="incidents" fill="hsl(var(--primary))" radius={[0, 8, 8, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      </div>
    </DashboardLayout>
  );
};

export default Analytics;
