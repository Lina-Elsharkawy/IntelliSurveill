import { useState, useEffect } from "react";
import { Camera, Grid3x3, List, Search, Edit, Trash } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { CameraFeed } from "@/components/CameraFeed";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import {
  getAllCameras,
  createCamera,
  updateCamera,
  deleteCamera
} from "@/services/cameras";

type CameraType = {
  id: number;
  name: string;
  location: string;
  lab_id: number;
};

const Cameras = () => {
  const [cameras, setCameras] = useState<CameraType[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [search, setSearch] = useState("");

  // Add/Update state
  const [editingCamera, setEditingCamera] = useState<CameraType | null>(null);
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [labId, setLabId] = useState<number | "">("");

  // Fetch all cameras
  useEffect(() => {
    getAllCameras()
      .then(setCameras)
      .catch(err => console.error("Failed to fetch cameras:", err))
      .finally(() => setLoading(false));
  }, []);

  // Add Camera
  const handleAddCamera = async () => {
    if (!name || !location || !labId) return;
    try {
      const newCamera = await createCamera({ name, location, lab_id: Number(labId) });
      setCameras(prev => [...prev, newCamera]);
      setName(""); setLocation(""); setLabId("");
    } catch (err) {
      console.error("Failed to add camera:", err);
    }
  };

  // Update Camera
  const handleUpdateClick = (camera: CameraType) => {
    setEditingCamera(camera);
    setName(camera.name);
    setLocation(camera.location);
    setLabId(camera.lab_id);
  };

  const handleUpdateSubmit = async () => {
    if (!editingCamera) return;
    try {
      const updated = await updateCamera(editingCamera.id, {
        name,
        location,
        lab_id: Number(labId)
      });
      setCameras(prev => prev.map(c => c.id === editingCamera.id ? updated : c));
      setEditingCamera(null); setName(""); setLocation(""); setLabId("");
    } catch (err) {
      console.error("Failed to update camera:", err);
    }
  };

  // Delete Camera
  const handleDelete = async (id: number) => {
    try {
      await deleteCamera(id);
      setCameras(prev => prev.filter(c => c.id !== id));
    } catch (err) {
      console.error("Failed to delete camera:", err);
    }
  };

  // Filtered cameras by search
  const filteredCameras = cameras.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return <DashboardLayout><p>Loading cameras...</p></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* Add / Update Form */}
        <Card className="p-4 mb-6 shadow-card border-border">
          <CardHeader>
            <CardTitle>{editingCamera ? "Update Camera" : "Add Camera"}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col md:flex-row gap-2">
            <Input placeholder="Camera Name" value={name} onChange={e => setName(e.target.value)} />
            <Input placeholder="Location" value={location} onChange={e => setLocation(e.target.value)} />
            <Input placeholder="Lab ID" type="number" value={labId} onChange={e => setLabId(Number(e.target.value))} />
            {editingCamera ? (
              <>
                <Button onClick={handleUpdateSubmit}>Save</Button>
                <Button variant="outline" onClick={() => { setEditingCamera(null); setName(""); setLocation(""); setLabId(""); }}>Cancel</Button>
              </>
            ) : (
              <Button onClick={handleAddCamera}>Add</Button>
            )}
          </CardContent>
        </Card>

        {/* Header with Search & View Toggle */}
        <div className="flex items-center justify-between">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search cameras by name..."
              className="pl-10 bg-secondary border-border"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-2 ml-4">
            <Button variant={viewMode === "grid" ? "default" : "outline"} size="icon" onClick={() => setViewMode("grid")}><Grid3x3 className="w-4 h-4" /></Button>
            <Button variant={viewMode === "list" ? "default" : "outline"} size="icon" onClick={() => setViewMode("list")}><List className="w-4 h-4" /></Button>
          </div>
        </div>

        {/* Cameras Tabs */}
        <Card className="shadow-card border-border">
          <CardContent>
            <Tabs defaultValue="all">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="all">All ({filteredCameras.length})</TabsTrigger>
              </TabsList>

              <TabsContent value="all">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {filteredCameras.map(camera => (
                    <Card key={camera.id} className="shadow-card border-border p-4">
                      <div className="mb-2 font-bold text-lg">{camera.name}</div>
                      <div className="text-sm text-muted-foreground mb-2">{camera.location}</div>
                      <div className="text-sm text-muted-foreground mb-4">Lab ID: {camera.lab_id}</div>
                      <div className="flex gap-2 justify-end">
                        <Button size="sm" onClick={() => handleUpdateClick(camera)}><Edit className="w-3 h-3 mr-1 inline" />Update</Button>
                        <Button size="sm" variant="outline" onClick={() => handleDelete(camera.id)}><Trash className="w-3 h-3 mr-1 inline" />Delete</Button>
                      </div>
                    </Card>
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
