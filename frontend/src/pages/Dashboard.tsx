import { Camera, AlertTriangle, Activity, Shield } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { StatsCard } from "@/components/StatsCard";
import { CameraCard } from "@/components/CameraFeed";
import { AlertItem } from "@/components/AlertItem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Link } from "react-router-dom";

const Dashboard = () => {
  const cameras = [
    { id: "CAM-01", db_id: 1, name: "Main Entrance", location: "Building A", lab_id: 1, status: "active" as const, thumbnail: "https://images.unsplash.com/photo-1557597774-9d273605dfa9?auto=format&fit=crop&q=80&w=800" },
    { id: "CAM-02", db_id: 2, name: "Parking Lot", location: "West Wing", lab_id: 2, status: "active" as const, thumbnail: "https://images.unsplash.com/photo-1541888946425-d81bb19480c5?auto=format&fit=crop&q=80&w=800" },
    { id: "CAM-03", db_id: 3, name: "Central Lab", location: "Central Lab", lab_id: 1, status: "alert" as const, thumbnail: "https://images.unsplash.com/photo-1590073242678-70ee3fc28e8e?auto=format&fit=crop&q=80&w=800" },
    { id: "CAM-04", db_id: 4, name: "Corridor 2B", location: "Building B", lab_id: 4, status: "active" as const, thumbnail: "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&q=80&w=800" },
  ];

  const alerts = [
    { title: "Unusual Activity Detected", location: "Lab - Zone 3", timestamp: "2 min ago", severity: "high" as const, status: "new" as const },
    { title: "Camera Offline", location: "Parking Lot B", timestamp: "15 min ago", severity: "medium" as const, status: "acknowledged" as const },
    { title: "Motion After Hours", location: "Building C - Floor 2", timestamp: "1 hour ago", severity: "high" as const, status: "new" as const },
    { title: "Low Battery Alert", location: "Camera CAM-015", timestamp: "3 hours ago", severity: "low" as const, status: "resolved" as const },
  ];

  return (
    <DashboardLayout>
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">Dashboard Overview</h1>
          <p className="text-muted-foreground">Real-time monitoring security systems</p>
        </div>
        <div className="flex gap-4">
          <Link to="/departments" className="text-xs text-green-500/60 uppercase tracking-widest hover:text-green-500 transition-colors">Departments</Link>
          <Link to="/labs" className="text-xs text-green-500/60 uppercase tracking-widest hover:text-green-500 transition-colors">Labs</Link>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Active Cameras"
          value="142"
          icon={Camera}
          variant="success"
          trend={{ value: "+5% from yesterday", isPositive: true }}
        />
        <StatsCard
          title="Active Anomalies"
          value="8"
          icon={AlertTriangle}
          variant="destructive"
          trend={{ value: "+2 new", isPositive: false }}
        />
        <StatsCard
          title="System Status"
          value="98.5%"
          icon={Activity}
          variant="success"
          trend={{ value: "Excellent", isPositive: true }}
        />
        <StatsCard
          title="Coverage Zones"
          value="24"
          icon={Shield}
          variant="default"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="flex items-center justify-between">
                <span className="text-foreground">Live Camera Feeds</span>
                <Link to="/cameras" className="text-xs text-green-500/60 uppercase tracking-widest hover:text-green-500 transition-colors">View All Feeds</Link>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start justify-items-center">
                {cameras.map((camera) => (
                  <CameraCard key={camera.id} cam={camera} width="100%" height={240} />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div>
          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">Recent Anomalies</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {alerts.map((alert, index) => (
                <AlertItem key={index} {...alert} />
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
    </DashboardLayout>
  );
};

export default Dashboard;
