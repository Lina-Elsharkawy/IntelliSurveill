import { Camera, Filter, Grid3x3, List, Search } from "lucide-react";
import { useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { CameraFeed } from "@/components/CameraFeed";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import cameraFeed1 from "@/assets/camera-feed-1.jpg";
import cameraFeed2 from "@/assets/camera-feed-2.jpg";
import cameraFeed3 from "@/assets/camera-feed-3.jpg";
import cameraFeed4 from "@/assets/camera-feed-4.jpg";

const Cameras = () => {
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");

  const cameras = [
    { id: "cam-001", name: "Main Entrance", location: "Building A - Level 1", status: "active" as const, thumbnail: cameraFeed1 },
    { id: "cam-002", name: "Parking Lot West", location: "West Wing", status: "active" as const, thumbnail: cameraFeed2 },
    { id: "cam-003", name: "Lab", location: "Floor 2", status: "alert" as const, thumbnail: cameraFeed3 },
    { id: "cam-004", name: "Corridor 2B", location: "Building B - Floor 2", status: "active" as const, thumbnail: cameraFeed4 },
    { id: "cam-005", name: "Showroom", location: "Main", status: "active" as const, thumbnail: cameraFeed1 },
    { id: "cam-006", name: "Parking -1", location: "Level -1", status: "active" as const, thumbnail: cameraFeed2 },
    { id: "cam-007", name: "Lab 3A", location: "IT Building - Floor 2", status: "inactive" as const, thumbnail: cameraFeed3 },
    { id: "cam-008", name: "Auditorium", location: "Main Hall", status: "active" as const, thumbnail: cameraFeed4 },
    { id: "cam-009", name: "Parking Lot East", location: "East Wing", status: "active" as const, thumbnail: cameraFeed2 },
    { id: "cam-010", name: "Entrance A", location: "Main Entrance A", status: "active" as const, thumbnail: cameraFeed1 },
    { id: "cam-011", name: "Admin Building", location: "Administration", status: "active" as const, thumbnail: cameraFeed4 },
    { id: "cam-012", name: "Computer Lab", location: "IT Building - Floor 3", status: "inactive" as const, thumbnail: cameraFeed3 },
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Live Cameras</h1>
            <p className="text-muted-foreground">Monitor all active surveillance cameras across campus</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={viewMode === "grid" ? "default" : "outline"}
              size="icon"
              onClick={() => setViewMode("grid")}
            >
              <Grid3x3 className="w-4 h-4" />
            </Button>
            <Button
              variant={viewMode === "list" ? "default" : "outline"}
              size="icon"
              onClick={() => setViewMode("list")}
            >
              <List className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <Card className="shadow-card border-border">
          <CardHeader>
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1 relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search cameras by name or location..."
                  className="pl-10 bg-secondary border-border"
                />
              </div>
              <Select defaultValue="all">
                <SelectTrigger className="w-full md:w-48 bg-secondary border-border">
                  <SelectValue placeholder="Filter by status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Cameras</SelectItem>
                  <SelectItem value="active">Active Only</SelectItem>
                  <SelectItem value="alert">Alerts Only</SelectItem>
                  <SelectItem value="inactive">Inactive Only</SelectItem>
                </SelectContent>
              </Select>
              <Select defaultValue="all-zones">
                <SelectTrigger className="w-full md:w-48 bg-secondary border-border">
                  <SelectValue placeholder="Filter by zone" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all-zones">All Zones</SelectItem>
                  <SelectItem value="building-a">Building A</SelectItem>
                  <SelectItem value="building-b">Building B</SelectItem>
                  <SelectItem value="outdoor">Outdoor Areas</SelectItem>
                  <SelectItem value="residence">Residence Halls</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="all">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="all">All ({cameras.length})</TabsTrigger>
                <TabsTrigger value="active">Active ({cameras.filter(c => c.status === 'active').length})</TabsTrigger>
                <TabsTrigger value="alerts">Alerts ({cameras.filter(c => c.status === 'alert').length})</TabsTrigger>
                <TabsTrigger value="offline">Offline ({cameras.filter(c => c.status === 'inactive').length})</TabsTrigger>
              </TabsList>

              <TabsContent value="all">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {cameras.map((camera) => (
                    <CameraFeed key={camera.id} {...camera} />
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="active">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {cameras.filter(c => c.status === 'active').map((camera) => (
                    <CameraFeed key={camera.id} {...camera} />
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="alerts">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {cameras.filter(c => c.status === 'alert').map((camera) => (
                    <CameraFeed key={camera.id} {...camera} />
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="offline">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {cameras.filter(c => c.status === 'inactive').map((camera) => (
                    <CameraFeed key={camera.id} {...camera} />
                  ))}
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
};

export default Cameras;
