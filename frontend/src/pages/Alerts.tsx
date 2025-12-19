import { AlertTriangle, CheckCircle, Clock, Filter } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { AlertItem } from "@/components/AlertItem";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const Alerts = () => {
  const alerts = [
    { title: "Unusual Activity Detected", location: "Lab - Zone 3", timestamp: "2 min ago", severity: "high" as const, status: "new" as const },
    { title: "Unauthorized Access Attempt", location: "Lab Building - Room 302", timestamp: "8 min ago", severity: "high" as const, status: "new" as const },
    { title: "Camera Offline", location: "Parking Lot B - CAM-045", timestamp: "15 min ago", severity: "medium" as const, status: "acknowledged" as const },
    { title: "Motion After Hours", location: "Building C - Floor 2", timestamp: "1 hour ago", severity: "high" as const, status: "acknowledged" as const },
    { title: "Loitering Detected", location: "Main Entrance - East Wing", timestamp: "2 hours ago", severity: "medium" as const, status: "acknowledged" as const },
    { title: "Low Battery Alert", location: "Camera CAM-015", timestamp: "3 hours ago", severity: "low" as const, status: "resolved" as const },
    { title: "Network Connectivity Issue", location: "Building D - Floor 1", timestamp: "5 hours ago", severity: "medium" as const, status: "resolved" as const },
    { title: "Lab", location: "Section 4", timestamp: "6 hours ago", severity: "high" as const, status: "resolved" as const },
    { title: "Unusual Spots ", location: "Parking", timestamp: "8 hours ago", severity: "high" as const, status: "resolved" as const },
    { title: "Maintenance Required", location: "Camera CAM-088", timestamp: "12 hours ago", severity: "low" as const, status: "resolved" as const },
  ];

  const newAlerts = alerts.filter(a => a.status === "new");
  const acknowledgedAlerts = alerts.filter(a => a.status === "acknowledged");
  const resolvedAlerts = alerts.filter(a => a.status === "resolved");

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Anomalies</h1>
            <p className="text-muted-foreground">Monitor and manage all Anomaly alerts and incidents</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline">
              <Filter className="w-4 h-4 mr-2" />
              Filter
            </Button>
            <Button>Mark All as Read</Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="shadow-card border-border border-l-4 border-l-destructive">
            <CardContent className="p-6">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm text-muted-foreground mb-1">New Anomalies</p>
                  <p className="text-3xl font-bold text-foreground">{newAlerts.length}</p>
                </div>
                <div className="p-3 rounded-lg bg-destructive/10">
                  <AlertTriangle className="w-6 h-6 text-destructive" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border border-l-4 border-l-warning">
            <CardContent className="p-6">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm text-muted-foreground mb-1">In Progress</p>
                  <p className="text-3xl font-bold text-foreground">{acknowledgedAlerts.length}</p>
                </div>
                <div className="p-3 rounded-lg bg-warning/10">
                  <Clock className="w-6 h-6 text-warning" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border border-l-4 border-l-success">
            <CardContent className="p-6">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm text-muted-foreground mb-1">Resolved Today</p>
                  <p className="text-3xl font-bold text-foreground">{resolvedAlerts.length}</p>
                </div>
                <div className="p-3 rounded-lg bg-success/10">
                  <CheckCircle className="w-6 h-6 text-success" />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="shadow-card border-border">
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-foreground">All Anomalies</CardTitle>
              <Select defaultValue="all">
                <SelectTrigger className="w-48 bg-secondary border-border">
                  <SelectValue placeholder="Filter by severity" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Severities</SelectItem>
                  <SelectItem value="high">High Priority</SelectItem>
                  <SelectItem value="medium">Medium Priority</SelectItem>
                  <SelectItem value="low">Low Priority</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="new">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="new">
                  New
                  <Badge className="ml-2 bg-destructive text-destructive-foreground">{newAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  In Progress
                  <Badge className="ml-2 bg-warning text-warning-foreground">{acknowledgedAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="resolved">
                  Resolved
                  <Badge className="ml-2 bg-success text-success-foreground">{resolvedAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="all">All ({alerts.length})</TabsTrigger>
              </TabsList>

              <TabsContent value="new" className="space-y-3">
                {newAlerts.map((alert, index) => (
                  <AlertItem key={index} {...alert} />
                ))}
              </TabsContent>

              <TabsContent value="acknowledged" className="space-y-3">
                {acknowledgedAlerts.map((alert, index) => (
                  <AlertItem key={index} {...alert} />
                ))}
              </TabsContent>

              <TabsContent value="resolved" className="space-y-3">
                {resolvedAlerts.map((alert, index) => (
                  <AlertItem key={index} {...alert} />
                ))}
              </TabsContent>

              <TabsContent value="all" className="space-y-3">
                {alerts.map((alert, index) => (
                  <AlertItem key={index} {...alert} />
                ))}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
};

export default Alerts;
