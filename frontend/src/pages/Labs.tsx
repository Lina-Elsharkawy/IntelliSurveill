import { useState, useEffect } from "react";
import { Grid3x3, List, Search, Edit, Trash } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
  getAllLabs,
  createLab,
  updateLab,
  deleteLab
} from "@/services/labs";

type LabType = {
  id: number;
  name: string;
};

export default function Labs() {
  const [labs, setLabs] = useState<LabType[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [search, setSearch] = useState("");

  const [editingLab, setEditingLab] = useState<LabType | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    getAllLabs()
      .then(setLabs)
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  // Add Lab
  const handleAdd = async () => {
    if (!name) return;
    try {
      const newLab = await createLab({ name });
      setLabs(prev => [...prev, newLab]);
      setName("");
    } catch (err) {
      console.error(err);
    }
  };

  // Edit Lab
  const handleUpdateClick = (lab: LabType) => {
    setEditingLab(lab);
    setName(lab.name);
  };

  const handleUpdateSubmit = async () => {
    if (!editingLab) return;
    try {
      const updated = await updateLab(editingLab.id, { name });
      setLabs(prev => prev.map(l => l.id === editingLab.id ? updated : l));
      setEditingLab(null);
      setName("");
    } catch (err) {
      console.error(err);
    }
  };

  // Delete Lab
  const handleDelete = async (id: number) => {
    try {
      await deleteLab(id);
      setLabs(prev => prev.filter(l => l.id !== id));
    } catch (err) {
      console.error(err);
    }
  };

  const filteredLabs = labs.filter(l => l.name.toLowerCase().includes(search.toLowerCase()));

  if (loading) return <DashboardLayout><p>Loading labs...</p></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* Add / Edit Form */}
        <Card className="p-4 mb-6 shadow-card border-border">
          <CardHeader>
            <CardTitle>{editingLab ? "Update Lab" : "Add Lab"}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col md:flex-row gap-2">
            <Input placeholder="Lab Name" value={name} onChange={e => setName(e.target.value)} />
            {editingLab ? (
              <>
                <Button onClick={handleUpdateSubmit}>Save</Button>
                <Button variant="outline" onClick={() => { setEditingLab(null); setName(""); }}>Cancel</Button>
              </>
            ) : (
              <Button onClick={handleAdd}>Add</Button>
            )}
          </CardContent>
        </Card>

        {/* Search & View Toggle */}
        <div className="flex items-center justify-between">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search labs..."
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

        {/* Labs Tabs */}
        <Card className="shadow-card border-border">
          <CardContent>
            <Tabs defaultValue="all">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="all">All ({filteredLabs.length})</TabsTrigger>
              </TabsList>

              <TabsContent value="all">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {filteredLabs.map(lab => (
                    <Card key={lab.id} className="shadow-card border-border p-4">
                      <div className="mb-2 font-bold text-lg">{lab.name}</div>
                      <div className="flex gap-2 justify-end">
                        <Button size="sm" onClick={() => handleUpdateClick(lab)}><Edit className="w-3 h-3 mr-1 inline" />Update</Button>
                        <Button size="sm" variant="outline" onClick={() => handleDelete(lab.id)}><Trash className="w-3 h-3 mr-1 inline" />Delete</Button>
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
}
