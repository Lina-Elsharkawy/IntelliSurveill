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
import { Card, CardContent } from "@/components/ui/card";
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
  const [investigateCandidate, setInvestigateCandidate] = useState<any>(null);
  const [retrainStatus, setRetrainStatus] = useState<any>(null);

  // CRUD
  const [editPerson, setEditPerson] = useState<any>(null);
  const [addModal, setAddModal] = useState(false);
  const [addType, setAddType] = useState<"employee" | "visitor">("employee");
  const [addForm, setAddForm] = useState<any>({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
  const [editForm, setEditForm] = useState<any>({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
  const [searchQuery, setSearchQuery] = useState("");

  /* ---------------- HELPERS ---------------- */
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "employee": return <Building className="w-4 h-4" />;
      case "visitor": return <UserPlus className="w-4 h-4" />;
      default: return <Users className="w-4 h-4" />;
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "employee": return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      case "visitor": return "bg-orange-500/10 text-orange-400 border-orange-500/30";
      default: return "bg-gray-500/10 text-gray-400 border-gray-500/30";
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "pending": return "bg-yellow-500/20 text-yellow-400";
      case "resolved": return "bg-green-500/20 text-green-400";
      case "discarded": return "bg-gray-500/20 text-gray-400";
      case "failed": return "bg-red-500/20 text-red-400";
      case "sent_to_llm": return "bg-blue-500/20 text-blue-400";
      default: return "bg-gray-500/20 text-gray-400";
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  /* ---------------- API CALLS ---------------- */
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

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const data = await res.json();
      setAnomalyCandidates(data);
    } catch (err: any) {
      console.error("Failed to fetch anomalies:", err);
      setError(err.message || "Failed to load anomalies");
    }
  };

  const fetchRetrainStatus = async () => {
    try {
      const res = await fetch(`${ANOMALY_API_BASE}/retrain/status`);
      if (res.ok) {
        const data = await res.json();
        setRetrainStatus(data);
      }
    } catch (err) {
      console.error("Failed to fetch retrain status:", err);
    }
  };

  const submitFeedback = async (candidateId: number, label: string) => {
    try {
      const res = await fetch(`${ANOMALY_API_BASE}/anomaly-candidates/${candidateId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label, reviewer: "admin-ui" }),
      });

      if (res.ok) {
        await fetchAnomalies();
        await fetchRetrainStatus();
      }
    } catch (err) {
      console.error("Failed to submit feedback:", err);
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

  /* ---------------- CREATE ---------------- */
  const submitAdd = async () => {
    if (addType === "employee") {
      await createEmployee({ name: addForm.name, department_id: Number(addForm.department_id) });
    } else {
      await createVisitor({
        name: addForm.name,
        purpose: addForm.purpose,
        visit_date: addForm.visit_date,
        contact_info: addForm.contact_info,
      });
    }
    setAddModal(false);
    setAddForm({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
    fetchRegistered();
  };

  /* ---------------- UPDATE ---------------- */
  const submitEdit = async () => {
    if (editPerson.type === "employee") {
      await updateEmployee(editPerson.id, { name: editForm.name, department_id: Number(editForm.department_id) });
    } else if (editPerson.type === "visitor") {
      await updateVisitor(editPerson.id, {
        name: editForm.name,
        purpose: editForm.purpose,
        visit_date: editForm.visit_date,
        contact_info: editForm.contact_info,
      });
    }
    setEditPerson(null);
    setEditForm({ name: "", department_id: "", purpose: "", visit_date: "", contact_info: "" });
    fetchRegistered();
  };

  /* ---------------- EFFECTS ---------------- */
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchUnknown(), fetchRegistered(), fetchAnomalies(), fetchRetrainStatus()]).finally(() => setLoading(false));
  }, []);

  /* ---------------- COMBINED REGISTERED ---------------- */
  const registeredPeople = [
    ...employees.map(e => ({ ...e, type: "employee" })),
    ...visitors.map(v => ({ ...v, type: "visitor" })),
  ];

  /* ---------------- UI ---------------- */
  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">Admin Database Management</h1>
            <p className="text-gray-400">Unknown IDs • Registered People • Anomalies</p>
          </div>
          <div className="flex gap-2">
            <Button className="bg-green-600 hover:bg-green-700 text-black">
              <Upload className="w-4 h-4 mr-2" /> Import
            </Button>
            <Button variant="outline" className="border-green-500/30 text-green-400">
              <Download className="w-4 h-4 mr-2" /> Export
            </Button>
          </div>
        </div>

        {/* Top Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="bg-gray-900/95 border-green-500/30">
            <CardContent className="pt-6 flex justify-between">
              <div>
                <p className="text-gray-400">Registered</p>
                <p className="text-3xl font-bold text-green-400">{registeredPeople.length}</p>
              </div>
              <Users className="w-10 h-10 text-green-400/30" />
            </CardContent>
          </Card>

          <Card className="bg-gray-900/95 border-yellow-500/30">
            <CardContent className="pt-6 flex justify-between">
              <div>
                <p className="text-gray-400">Unknown</p>
                <p className="text-3xl font-bold text-yellow-400">{unknownIdentities.length}</p>
              </div>
              <UserPlus className="w-10 h-10 text-yellow-400/30" />
            </CardContent>
          </Card>

          <Card className="bg-gray-900/95 border-red-500/30">
            <CardContent className="pt-6 flex justify-between">
              <div>
                <p className="text-gray-400">Anomalies</p>
                <p className="text-3xl font-bold text-red-400">{anomalyCandidates.length}</p>
              </div>
              <AlertTriangle className="w-10 h-10 text-red-400/30" />
            </CardContent>
          </Card>

          {retrainStatus && (
            <Card className={`bg-gray-900/95 ${retrainStatus.retrain_recommended ? 'border-orange-500/30' : 'border-blue-500/30'}`}>
              <CardContent className="pt-6">
                <p className="text-gray-400 text-sm">False Positives</p>
                <p className="text-2xl font-bold text-orange-400">{retrainStatus.pending_false_positives} / {retrainStatus.threshold}</p>
                {retrainStatus.retrain_recommended && (
                  <Badge className="mt-2 bg-orange-500/20 text-orange-400">Retrain Ready</Badge>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Tabs */}
        <Tabs defaultValue="anomalies" className="space-y-4">
          <TabsList className="bg-gray-900/95 border border-green-500/30">
            <TabsTrigger value="unknown">Unknown</TabsTrigger>
            <TabsTrigger value="registered">Registered</TabsTrigger>
            <TabsTrigger value="anomalies">Anomalies ({anomalyCandidates.length})</TabsTrigger>
          </TabsList>

          {/* ========== UNKNOWN TAB ========== */}
          <TabsContent value="unknown" className="space-y-4">
            {unknownIdentities.length === 0 ? (
              <Card className="bg-black/40 border border-gray-500/20 p-8">
                <p className="text-gray-400 text-center">No unknown identities detected</p>
              </Card>
            ) : (
              unknownIdentities.map(u => (
                <Card key={u.id} className="bg-black/40 border border-yellow-500/20 p-4">
                  <div className="flex justify-between">
                    <div>
                      <p className="text-white font-semibold">{u.name || "Unknown Person"}</p>
                      <p className="text-gray-400 text-sm">{u.timestamp}</p>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" onClick={() => registerUnknown(u.id)} className="bg-green-600">Register</Button>
                      <Button size="sm" variant="outline" className="border-red-500/30 text-red-400" onClick={() => dismissUnknown(u.id)}>Dismiss</Button>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </TabsContent>

          {/* ========== REGISTERED TAB ========== */}
          <TabsContent value="registered" className="space-y-4">
            <div className="flex gap-2 mb-4">
              <Input placeholder="Search..." value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="border-green-500/30" />
              <Button onClick={() => setAddModal(true)} className="bg-green-600">
                <UserPlus className="w-4 h-4 mr-2" /> Add
              </Button>
            </div>

            {registeredPeople.filter(p => p.name.toLowerCase().includes(searchQuery.toLowerCase())).map(p => (
              <Card key={`${p.type}-${p.id}`} className="bg-black/40 border border-green-500/20 p-4">
                <div className="flex justify-between items-center">
                  <div>
                    <p className="text-white font-semibold flex items-center gap-1">{getTypeIcon(p.type)} {p.name}</p>

                    {p.type === "employee" && (
                      <p className="text-gray-400 text-sm">Department ID: {p.department_id}</p>
                    )}
                    {p.type === "visitor" && (
                      <p className="text-gray-400 text-sm"> {p.purpose} • {p.contact_info} • {new Date(p.visit_date).toLocaleDateString()}</p>
                    )}
                  </div>

                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" className="border-blue-500/30 text-blue-400"
                      onClick={() => {
                        setEditPerson(p);
                        setEditForm({ ...p });
                      }}>
                      <Edit className="w-4 h-4" />
                    </Button>

                    <Button size="sm" variant="outline" className="border-red-500/30 text-red-400" onClick={() => deletePerson(p)}>
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </Card>
            ))}

            {/* Add Modal */}
            {addModal && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                <div className="bg-gray-900 p-6 rounded-lg w-96">
                  <h2 className="text-white text-xl mb-4">Add {addType}</h2>

                  <div className="flex gap-2 mb-4">
                    <Button variant={addType === "employee" ? "default" : "outline"} onClick={() => setAddType("employee")}>Employee</Button>
                    <Button variant={addType === "visitor" ? "default" : "outline"} onClick={() => setAddType("visitor")}>Visitor</Button>
                  </div>

                  <Input placeholder="Name" value={addForm.name} onChange={e => setAddForm({ ...addForm, name: e.target.value })} className="mb-2" />

                  {addType === "employee" && <Input placeholder="Department ID" value={addForm.department_id} onChange={e => setAddForm({ ...addForm, department_id: e.target.value })} className="mb-2" />}

                  {addType === "visitor" && (
                    <>
                      <Input placeholder="Purpose" value={addForm.purpose} onChange={e => setAddForm({ ...addForm, purpose: e.target.value })} className="mb-2" />
                      <Input placeholder="Visit Date" type="date" value={addForm.visit_date} onChange={e => setAddForm({ ...addForm, visit_date: e.target.value })} className="mb-2" />
                      <Input placeholder="Contact Info" value={addForm.contact_info} onChange={e => setAddForm({ ...addForm, contact_info: e.target.value })} className="mb-2" />
                    </>
                  )}

                  <div className="flex justify-end gap-2 mt-4">
                    <Button variant="outline" onClick={() => setAddModal(false)}>Cancel</Button>
                    <Button className="bg-green-600" onClick={submitAdd}>Add</Button>
                  </div>
                </div>
              </div>
            )}

            {/* Edit Modal */}
            {editPerson && (
              <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
                <div className="bg-gray-900 p-6 rounded-lg w-96">
                  <h2 className="text-white text-xl mb-4">Edit {editPerson.type}</h2>

                  <Input placeholder="Name" value={editForm.name} onChange={e => setEditForm({ ...editForm, name: e.target.value })} className="mb-2" />

                  {editPerson.type === "employee" && <Input placeholder="Department ID" value={editForm.department_id} onChange={e => setEditForm({ ...editForm, department_id: e.target.value })} className="mb-2" />}

                  {editPerson.type === "visitor" && (
                    <>
                      <Input placeholder="Purpose" value={editForm.purpose} onChange={e => setEditForm({ ...editForm, purpose: e.target.value })} className="mb-2" />
                      <Input placeholder="Visit Date" type="date" value={editForm.visit_date} onChange={e => setEditForm({ ...editForm, visit_date: e.target.value })} className="mb-2" />
                      <Input placeholder="Contact Info" value={editForm.contact_info} onChange={e => setEditForm({ ...editForm, contact_info: e.target.value })} className="mb-2" />
                    </>
                  )}

                  <div className="flex justify-end gap-2 mt-4">
                    <Button variant="outline" onClick={() => setEditPerson(null)}>Cancel</Button>
                    <Button className="bg-blue-600" onClick={submitEdit}>Update</Button>
                  </div>
                </div>
              </div>
            )}

          </TabsContent>

          {/* ========== ANOMALIES TAB ========== */}
          <TabsContent value="anomalies" className="space-y-4">
            {loading && (
              <Card className="bg-black/40 border border-gray-500/20 p-8">
                <p className="text-gray-400 text-center">Loading anomalies...</p>
              </Card>
            )}

            {error && (
              <Card className="bg-black/40 border border-red-500/30 p-8">
                <p className="text-red-400 text-center">Error: {error}</p>
              </Card>
            )}

            {!loading && !error && anomalyCandidates.length === 0 && (
              <Card className="bg-black/40 border border-gray-500/20 p-8">
                <div className="text-center">
                  <AlertTriangle className="w-16 h-16 text-gray-600 mx-auto mb-4" />
                  <p className="text-gray-400">No anomalies detected yet</p>
                  <p className="text-gray-500 text-sm mt-2">Anomalies will appear here when detected by the system</p>
                </div>
              </Card>
            )}

            {!loading && anomalyCandidates.map((c, index) => (
              <Card key={c.id} className="bg-black/50 border border-yellow-500/20 hover:border-yellow-500/40 transition-all">
                <CardContent className="p-6">
                  <div className="flex gap-6 items-start">
                    {/* Image Thumbnail */}
                    <div className="flex-shrink-0">
                      <div className="w-24 h-24 bg-gray-800 rounded-lg border-2 border-yellow-500/30 overflow-hidden">
                        {c.imageRef ? (
                          <img
                            src={c.imageRef}
                            alt={`Anomaly ${c.id}`}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>';
                              e.currentTarget.classList.add('opacity-20');
                            }}
                          />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <Camera className="w-8 h-8 text-gray-600" />
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <span className="text-lg font-semibold text-white">Anomaly #{c.id}</span>
                        <Badge className={getStatusColor(c.status)}>
                          {c.status.replace('_', ' ')}
                        </Badge>
                        {c.cameraId && (
                          <div className="flex items-center gap-1 text-gray-400 text-sm">
                            <Camera className="w-3 h-3" />
                            <span>Camera {c.cameraId}</span>
                          </div>
                        )}
                      </div>

                      <div className="flex items-center gap-2 text-gray-500 text-xs">
                        <Clock className="w-3 h-3" />
                        <span>{formatDate(c.createdAt)}</span>
                      </div>
                    </div>

                    {/* Feedback Buttons - Right Side */}
                    <div className="flex gap-2 items-center">
                      <select
                        className="bg-black/50 border border-green-500/30 text-green-300 p-2 rounded text-sm"
                        defaultValue="Unreviewed"
                        onChange={(e) => {
                          const updated = [...anomalyCandidates];
                          updated[index].selectedFeedback = e.target.value;
                          setAnomalyCandidates(updated);
                        }}
                      >
                        <option>Unreviewed</option>
                        <option value="true_anomaly">True Anomaly</option>
                        <option value="false_positive">False Positive</option>
                        <option value="uncertain">Uncertain</option>
                      </select>
                      <Button
                        size="sm"
                        className="bg-green-600 hover:bg-green-700 text-black"
                        onClick={() => submitFeedback(c.id, c.selectedFeedback || "uncertain")}
                      >
                        Save Feedback
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-yellow-500/30 text-yellow-400"
                        onClick={() => setInvestigateCandidate(c)}
                      >
                        Investigate
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </TabsContent>

        </Tabs>

        {/* Investigate Modal */}
        {investigateCandidate && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
            <div className="bg-gray-900/95 p-6 rounded-lg w-1/2 max-w-2xl">
              <h2 className="text-xl font-bold text-green-400 mb-4">
                Anomaly Candidate #{investigateCandidate.id}
              </h2>

              {investigateCandidate.imageRef && (
                <img
                  src={investigateCandidate.imageRef}
                  alt={`Anomaly ${investigateCandidate.id}`}
                  className="w-full rounded-lg mb-4"
                />
              )}

              <div className="mb-4">
                <p className="text-gray-400 text-sm mb-1">Status:</p>
                <Badge className={getStatusColor(investigateCandidate.status)}>
                  {investigateCandidate.status}
                </Badge>
              </div>

              <div className="mb-4">
                <p className="text-gray-400 text-sm mb-1">Narrative:</p>
                <p className="text-gray-300">{investigateCandidate.narrative || "No narrative available"}</p>
              </div>

              <div className="mb-4">
                <p className="text-gray-400 text-sm mb-1">Detected:</p>
                <p className="text-gray-300">{formatDate(investigateCandidate.createdAt)}</p>
              </div>

              <div className="mt-6 text-right">
                <Button className="bg-red-600 hover:bg-red-700" onClick={() => setInvestigateCandidate(null)}>
                  Close
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}