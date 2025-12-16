import { Camera, AlertTriangle, Activity, Shield } from "lucide-react";
import { StatsCard } from "@/components/StatsCard";
import { CameraFeed } from "@/components/CameraFeed";
import { AlertItem } from "@/components/AlertItem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import cameraFeed1 from "@/assets/camera-feed-1.jpg";
import cameraFeed2 from "@/assets/camera-feed-2.jpg";
import cameraFeed3 from "@/assets/camera-feed-3.jpg";
import cameraFeed4 from "@/assets/camera-feed-4.jpg";

const Dashboard = () => {
  const cameras = [
    { id: "cam-001", name: "Main Entrance", location: "Building A", status: "active" as const, thumbnail: cameraFeed1 },
    { id: "cam-002", name: "Parking Lot", location: "West Wing", status: "active" as const, thumbnail: cameraFeed2 },
    { id: "cam-003", name: "Lab", location: "Central Lab", status: "alert" as const, thumbnail: cameraFeed3 },
    { id: "cam-004", name: "Corridor 2B", location: "Building B", status: "active" as const, thumbnail: cameraFeed4 },
    { id: "cam-005", name: "Cafeteria", location: "Student Center", status: "inactive" as const, thumbnail: cameraFeed1 },
    { id: "cam-006", name: "Sports Complex", location: "East Campus", status: "active" as const, thumbnail: cameraFeed2 },
  ];

  const alerts = [
    { title: "Unusual Activity Detected", location: "Lab - Zone 3", timestamp: "2 min ago", severity: "high" as const, status: "new" as const },
    { title: "Camera Offline", location: "Parking Lot B", timestamp: "15 min ago", severity: "medium" as const, status: "acknowledged" as const },
    { title: "Motion After Hours", location: "Building C - Floor 2", timestamp: "1 hour ago", severity: "high" as const, status: "new" as const },
    { title: "Low Battery Alert", location: "Camera CAM-015", timestamp: "3 hours ago", severity: "low" as const, status: "resolved" as const },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-foreground mb-2">Dashboard Overview</h1>
        <p className="text-muted-foreground">Real-time monitoring security systems</p>
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
          title="Active Alerts"
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
                <Tabs defaultValue="all" className="w-auto">
                  <TabsList className="bg-secondary">
                    <TabsTrigger value="all">All</TabsTrigger>
                    <TabsTrigger value="active">Active</TabsTrigger>
                    <TabsTrigger value="alerts">Alerts</TabsTrigger>
                  </TabsList>
                </Tabs>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {cameras.map((camera) => (
                  <CameraFeed key={camera.id} {...camera} />
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        <div>
          <Card className="shadow-card border-border">
            <CardHeader>
              <CardTitle className="text-foreground">Recent Alerts</CardTitle>
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
  );
};

export default Dashboard;
