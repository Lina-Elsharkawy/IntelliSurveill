import { MapPin, Camera, AlertTriangle, ZoomIn, ZoomOut, Maximize2 } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const CampusMap = () => {
  const zones = [
    { id: 1, name: "Building A", cameras: 24, alerts: 0, status: "active" as const },
    { id: 2, name: "Building B", cameras: 18, alerts: 0, status: "active" as const },
    { id: 3, name: "Building C", cameras: 20, alerts: 1, status: "alert" as const },
    { id: 4, name: "Parking West", cameras: 12, alerts: 0, status: "active" as const },
    { id: 5, name: "Parking East", cameras: 10, alerts: 0, status: "active" as const },
    { id: 6, name: "Sports Complex", cameras: 15, alerts: 0, status: "active" as const },
    { id: 7, name: "Library", cameras: 8, alerts: 2, status: "alert" as const },
    { id: 8, name: "Student Center", cameras: 14, alerts: 0, status: "active" as const },
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Campus Map</h1>
            <p className="text-muted-foreground">Interactive overview of all camera zones and coverage areas</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="icon">
              <ZoomIn className="w-4 h-4" />
            </Button>
            <Button variant="outline" size="icon">
              <ZoomOut className="w-4 h-4" />
            </Button>
            <Button variant="outline" size="icon">
              <Maximize2 className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-3">
            <Card className="shadow-card border-border">
              <CardContent className="p-0">
                <div className="aspect-video bg-secondary rounded-lg relative overflow-hidden">
                  {/* Map visualization placeholder */}
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="text-center space-y-4">
                      <MapPin className="w-16 h-16 mx-auto text-primary" />
                      <div>
                        <p className="text-lg font-semibold text-foreground">Interactive Campus Map</p>
                        <p className="text-sm text-muted-foreground mt-2">
                          Click on zones to view detailed camera coverage
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* Example zone markers */}
                  <div className="absolute top-20 left-32 group cursor-pointer">
                    <div className="relative">
                      <div className="w-12 h-12 bg-primary rounded-full flex items-center justify-center shadow-glow animate-pulse">
                        <Camera className="w-6 h-6 text-primary-foreground" />
                      </div>
                      <Badge className="absolute -top-2 -right-2 bg-success text-success-foreground">24</Badge>
                    </div>
                  </div>

                  <div className="absolute top-32 right-40 group cursor-pointer">
                    <div className="relative">
                      <div className="w-12 h-12 bg-destructive rounded-full flex items-center justify-center shadow-glow animate-pulse">
                        <AlertTriangle className="w-6 h-6 text-destructive-foreground" />
                      </div>
                      <Badge className="absolute -top-2 -right-2 bg-destructive text-destructive-foreground">2</Badge>
                    </div>
                  </div>

                  <div className="absolute bottom-24 left-48 group cursor-pointer">
                    <div className="relative">
                      <div className="w-12 h-12 bg-primary rounded-full flex items-center justify-center shadow-glow">
                        <Camera className="w-6 h-6 text-primary-foreground" />
                      </div>
                      <Badge className="absolute -top-2 -right-2 bg-success text-success-foreground">18</Badge>
                    </div>
                  </div>

                  <div className="absolute bottom-32 right-32 group cursor-pointer">
                    <div className="relative">
                      <div className="w-12 h-12 bg-primary rounded-full flex items-center justify-center shadow-glow">
                        <Camera className="w-6 h-6 text-primary-foreground" />
                      </div>
                      <Badge className="absolute -top-2 -right-2 bg-success text-success-foreground">15</Badge>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="flex gap-4 mt-4">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-success"></div>
                <span className="text-sm text-muted-foreground">Active Zone</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-destructive"></div>
                <span className="text-sm text-muted-foreground">Alert Zone</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-muted"></div>
                <span className="text-sm text-muted-foreground">Inactive Zone</span>
              </div>
            </div>
          </div>

          <div>
            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle className="text-foreground">Zone Overview</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {zones.map((zone) => (
                  <div
                    key={zone.id}
                    className="p-3 rounded-lg bg-secondary border border-border hover:border-primary transition-colors cursor-pointer"
                  >
                    <div className="flex items-start justify-between mb-2">
                      <h4 className="font-semibold text-foreground">{zone.name}</h4>
                      <Badge
                        className={
                          zone.status === "alert"
                            ? "bg-destructive text-destructive-foreground"
                            : "bg-success text-success-foreground"
                        }
                      >
                        {zone.status === "alert" ? "Alert" : "Active"}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1">
                        <Camera className="w-3 h-3" />
                        {zone.cameras} cameras
                      </div>
                      {zone.alerts > 0 && (
                        <div className="flex items-center gap-1 text-destructive">
                          <AlertTriangle className="w-3 h-3" />
                          {zone.alerts} alerts
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
};

export default CampusMap;
