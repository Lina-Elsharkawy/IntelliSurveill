'use client'

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import {
  Users,
  UserPlus,
  AlertTriangle,
  Trash2,
  Edit,
  Building,
  Camera,
  Clock,
  Download,
  Upload,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

import { apiGet, apiPost } from "@/lib/api";
import { getAllEmployees, deleteEmployee, createEmployee, updateEmployee } from "@/services/employees";
import { getAllVisitors, deleteVisitor, createVisitor, updateVisitor } from "@/services/visitors";

const ANOMALY_API_BASE = "http://127.0.0.1:8000";

export default function AdminPage() {
  const [unknownIdentities, setUnknownIdentities] = useState<any[]>([]);
  const [employees, setEmployees] = useState<any[]>([]);
  const [visitors, setVisitors] = useState<any[]>([]);
  const [anomalyCandidates, setAnomalyCandidates] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // CRUD
  const [editPerson, setEditPerson] = useState<any>(null);
  const [addModal, setAddModal] = useState(false);
  const [addType, setAddType] = useState<"employee" | "visitor">("employee");
  const [addForm, setAddForm] = useState<any>({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
  const [editForm, setEditForm] = useState<any>({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
  const [searchQuery, setSearchQuery] = useState("");

  const fetchUnknown = async () => {
    try {
      const data = await apiGet<any[]>("/api/detected-people/get_people");
      setUnknownIdentities(data);
    } catch (err) {
      console.error("Failed to fetch unknown identities:", err);
    }
  };

  const fetchRegistered = async () => {
    try {
      const [emps, visits] = await Promise.all([getAllEmployees(), getAllVisitors()]);
      setEmployees(emps);
      setVisitors(visits);
    } catch (err) {
      console.error("Failed to fetch registered people:", err);
    }
  };

  const fetchAnomalies = async () => {
    try {
      setError(null);
      const res = await fetch(`${ANOMALY_API_BASE}/anomaly-candidates`);
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      const data = await res.json();
      setAnomalyCandidates(data);
    } catch (err: any) {
      console.error("Failed to fetch anomalies:", err);
      setError(err.message || "Failed to load anomalies");
    }
  };

  const registerUnknown = async (id: number) => {
    await apiPost(`/api/detected-people/register/${id}`, {});
    fetchUnknown();
    fetchRegistered();
  };

  const dismissUnknown = async (id: number) => {
    await apiPost(`/api/detected-people/dismiss/${id}`, {});
    fetchUnknown();
  };

  const deletePerson = async (person: any) => {
    if (person.type === "employee") await deleteEmployee(person.id);
    else if (person.type === "visitor") await deleteVisitor(person.id);
    fetchRegistered();
  };

  useEffect(() => {
    setLoading(true);
    Promise.all([fetchUnknown(), fetchRegistered(), fetchAnomalies()]).finally(() => setLoading(false));
  }, []);

  const registeredPeople = [
    ...employees.map(e => ({ ...e, type: "employee" })),
    ...visitors.map(v => ({ ...v, type: "visitor" })),
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold">Database Management</h1>
          <Badge variant="outline" className="text-green-500 border-green-500/30">System Admin</Badge>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="bg-gray-900/50 border-gray-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">Total Registered</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{registeredPeople.length}</div>
            </CardContent>
          </Card>
          <Card className="bg-gray-900/50 border-gray-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">Unknown IDs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{unknownIdentities.length}</div>
            </CardContent>
          </Card>
          <Card className="bg-gray-900/50 border-gray-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-gray-400">Active Anomalies</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-red-500">{anomalyCandidates.length}</div>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue="registered" className="w-full">
          <TabsList className="bg-gray-900 border-gray-800">
            <TabsTrigger value="registered">Registered People</TabsTrigger>
            <TabsTrigger value="unknown">Unknown Identites</TabsTrigger>
            <TabsTrigger value="anomalies">Anomalies</TabsTrigger>
          </TabsList>

          <TabsContent value="registered" className="space-y-4 pt-4">
            <div className="flex gap-2">
              <Input
                placeholder="Search database..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-gray-900/50 border-gray-800"
              />
            </div>
            <Card className="bg-gray-900/50 border-gray-800">
              <CardContent className="p-0">
                <div className="divide-y divide-gray-800">
                  {registeredPeople.filter(p => p.name.toLowerCase().includes(searchQuery.toLowerCase())).map(p => (
                    <div key={`${p.type}-${p.id}`} className="p-4 flex items-center justify-between">
                      <div>
                        <div className="font-semibold">{p.name}</div>
                        <div className="text-sm text-gray-500 uppercase">{p.type}</div>
                      </div>
                      <Button variant="ghost" size="sm" className="text-red-500" onClick={() => deletePerson(p)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="unknown" className="space-y-4 pt-4">
            {unknownIdentities.map(u => (
              <Card key={u.id} className="bg-gray-900/50 border-gray-800">
                <CardContent className="p-4 flex items-center justify-between">
                  <div>
                    <div className="font-semibold">{u.name || "Unknown Person"}</div>
                    <div className="text-xs text-gray-500">{u.timestamp}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => registerUnknown(u.id)}>Register</Button>
                    <Button size="sm" variant="outline" className="text-red-500" onClick={() => dismissUnknown(u.id)}>Dismiss</Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </TabsContent>

          <TabsContent value="anomalies" className="space-y-4 pt-4">
            {anomalyCandidates.map(c => (
              <Card key={c.id} className="bg-gray-900/50 border-gray-800">
                <CardContent className="p-4 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <AlertTriangle className="w-5 h-5 text-yellow-500" />
                    <div>
                      <div className="font-semibold">Anomaly #{c.id}</div>
                      <div className="text-sm text-gray-500">{c.status}</div>
                    </div>
                  </div>
                  <Badge>{new Date(c.createdAt).toLocaleDateString()}</Badge>
                </CardContent>
              </Card>
            ))}
          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
}