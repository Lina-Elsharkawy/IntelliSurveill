import { useState, useEffect } from "react";
import { Grid3x3, List, Search, Edit, Trash } from "lucide-react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
  getAllDepartments,
  createDepartment,
  updateDepartment,
  deleteDepartment
} from "@/services/departments";

type DepartmentType = {
  id: number;
  name: string;
};

export default function Departments() {
  const [departments, setDepartments] = useState<DepartmentType[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [search, setSearch] = useState("");

  const [editingDept, setEditingDept] = useState<DepartmentType | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    getAllDepartments()
      .then(setDepartments)
      .catch(err => console.error(err))
      .finally(() => setLoading(false));
  }, []);

  const handleAdd = async () => {
    if (!name) return;
    try {
      const newDept = await createDepartment({ name });
      setDepartments(prev => [...prev, newDept]);
      setName("");
    } catch (err) {
      console.error(err);
    }
  };

  const handleUpdateClick = (dept: DepartmentType) => {
    setEditingDept(dept);
    setName(dept.name);
  };

  const handleUpdateSubmit = async () => {
    if (!editingDept) return;
    try {
      const updated = await updateDepartment(editingDept.id, { name });
      setDepartments(prev => prev.map(d => d.id === editingDept.id ? updated : d));
      setEditingDept(null);
      setName("");
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteDepartment(id);
      setDepartments(prev => prev.filter(d => d.id !== id));
    } catch (err) {
      console.error(err);
    }
  };

  const filteredDepartments = departments.filter(d => d.name.toLowerCase().includes(search.toLowerCase()));

  if (loading) return <DashboardLayout><p>Loading departments...</p></DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* Add / Update Form */}
        <Card className="p-4 mb-6 shadow-card border-border">
          <CardHeader>
            <CardTitle>{editingDept ? "Update Department" : "Add Department"}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col md:flex-row gap-2">
            <Input placeholder="Department Name" value={name} onChange={e => setName(e.target.value)} />
            {editingDept ? (
              <>
                <Button onClick={handleUpdateSubmit}>Save</Button>
                <Button variant="outline" onClick={() => { setEditingDept(null); setName(""); }}>Cancel</Button>
              </>
            ) : (
              <Button onClick={handleAdd}>Add</Button>
            )}
          </CardContent>
        </Card>

        {/* Header with Search & View Toggle */}
        <div className="flex items-center justify-between">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search departments..."
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

        {/* Departments Tabs */}
        <Card className="shadow-card border-border">
          <CardContent>
            <Tabs defaultValue="all">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="all">All ({filteredDepartments.length})</TabsTrigger>
              </TabsList>

              <TabsContent value="all">
                <div className={viewMode === "grid" ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-4"}>
                  {filteredDepartments.map(dept => (
                    <Card key={dept.id} className="shadow-card border-border p-4">
                      <div className="mb-2 font-bold text-lg">{dept.name}</div>
                      <div className="flex gap-2 justify-end">
                        <Button size="sm" onClick={() => handleUpdateClick(dept)}><Edit className="w-3 h-3 mr-1 inline" />Update</Button>
                        <Button size="sm" variant="outline" onClick={() => handleDelete(dept.id)}><Trash className="w-3 h-3 mr-1 inline" />Delete</Button>
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
