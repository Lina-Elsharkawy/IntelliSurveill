'use client';

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useAuth } from "@/context/AuthContext";
import { apiGet, apiPost } from "@/lib/api";

export default function AdminPage() {
  const { roles } = useAuth();
  const userRole = roles[0] || "user";

  const [identities, setIdentities] = useState<any[]>([]);
  const [unknowns, setUnknowns] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // ---------------- FETCH ----------------

  const fetchIdentities = async () => {
    try {
      const data = await apiGet("/api/admin/identities");  // ← add /api
      setIdentities(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching identities:", e);
      setIdentities([]);
    }
  };

  const fetchUnknowns = async () => {
    try {
      const data = await apiGet("/api/admin/pending-unknowns");  // ← add /api
      setUnknowns(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching unknowns:", e);
      setUnknowns([]);
    }
  };

  const fetchLogs = async () => {
    try {
      const data = await apiGet("/api/admin/recent-entry-logs");  // ← add /api
      setLogs(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching logs:", e);
      setLogs([]);
    }
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      await Promise.all([fetchIdentities(), fetchUnknowns(), fetchLogs()]);
      setLoading(false);
    };
    load();
  }, []);

  // ---------------- ACTIONS ----------------

  const registerIdentity = async (unknownFaceEventId: number) => {
    const name = prompt("Enter name for this identity:");
    if (!name) return;
    try {
      await apiPost("/api/admin/create-identity-from-unknown", {  // ← add /api
        unknown_face_event_id: unknownFaceEventId,
        name,
        promote_to_authoritative: true,
      });
      await fetchUnknowns();
      await fetchIdentities();
    } catch (e) {
      console.error("Error registering identity:", e);
    }
  };

  const assignToExisting = async (unknownFaceEventId: number) => {
    const detectedIdStr = prompt("Enter the existing identity ID:");
    if (!detectedIdStr) return;
    const detectedId = parseInt(detectedIdStr, 10);
    if (isNaN(detectedId)) return alert("Invalid ID");
    try {
      await apiPost("/api/admin/assign-unknown", {  // ← add /api
        unknown_face_event_id: unknownFaceEventId,
        detected_id: detectedId,
        promote_to_authoritative: false,
      });
      await fetchUnknowns();
    } catch (e) {
      console.error("Error assigning unknown:", e);
    }
  };

  // ---------------- UI ----------------

  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* HEADER */}
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold">Face Vector Admin</h1>
          <Badge className="uppercase">{userRole}</Badge>
        </div>

        {/* STATS */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Identities</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{identities.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Unknown Faces</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{unknowns.length}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Entry Logs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{logs.length}</div>
            </CardContent>
          </Card>
        </div>

        {/* TABS */}
        <Tabs defaultValue="identities" className="w-full">
          <TabsList>
            <TabsTrigger value="identities">Identities</TabsTrigger>
            <TabsTrigger value="unknown">Unknown Faces</TabsTrigger>
            <TabsTrigger value="logs">Entry Logs</TabsTrigger>
          </TabsList>

          {/* ---------------- IDENTITIES ---------------- */}
          <TabsContent value="identities" className="space-y-4 pt-4">
            <Input
              placeholder="Search identities..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="divide-y">
                    {identities
                      .filter(p =>
                        (p.name || '').toLowerCase().includes(searchQuery.toLowerCase())
                      )
                      .map(p => (
                        <div key={p.id} className="p-4 flex justify-between items-center">
                          <div>
                            <div className="font-semibold">{p.name || "Unnamed"}</div>
                            <div className="text-sm text-gray-500">
                              ID: {p.id} · Embeddings: {p.embedding_count ?? '—'}
                            </div>
                            <div className="text-xs text-gray-400">
                              {p.additional_info || "No additional info"}
                            </div>
                          </div>
                          <Badge variant="outline">
                            {p.embedding_count > 0 ? "Active" : "No embeddings"}
                          </Badge>
                        </div>
                      ))}
                    {identities.length === 0 && (
                      <div className="p-4 text-gray-400 text-sm">No identities found.</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ---------------- UNKNOWN ---------------- */}
          <TabsContent value="unknown" className="space-y-4 pt-4">
            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : unknowns.length === 0 ? (
              <div className="text-gray-400 text-sm">No unknown faces pending review.</div>
            ) : (
              unknowns.map(u => (
                <Card key={u.id}>
                  <CardContent className="p-4 flex justify-between items-center">
                    <div>
                      <div className="font-semibold">Unknown Face #{u.id}</div>
                      <div className="text-xs text-gray-500">
                        Event ID: {u.id} · Status: {u.review_status || "pending"}
                      </div>
                      <div className="text-xs text-gray-400">
                        Model: {u.embedding_model || "—"} · Notes: {u.notes || "—"}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button onClick={() => registerIdentity(u.id)}>
                        New Identity
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => assignToExisting(u.id)}
                      >
                        Assign Existing
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

          {/* ---------------- LOGS ---------------- */}
          <TabsContent value="logs" className="space-y-4 pt-4">
            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : logs.length === 0 ? (
              <div className="text-gray-400 text-sm">No entry logs found.</div>
            ) : (
              logs.map(l => (
                <Card key={l.id}>
                  <CardContent className="p-4 flex justify-between items-center">
                    <div>
                      <div className="font-semibold">
                        {l.identity_name || "Unknown"}
                      </div>
                      <div className="text-sm text-gray-500">
                        {l.location || "No location"} · Camera: {l.camera_id ?? "—"}
                      </div>
                      <div className="text-xs text-gray-400">
                        Type: {l.event_type || "—"} · Status: {l.device_status || "—"}
                      </div>
                    </div>
                    <Badge>
                      {l.created_at ? new Date(l.created_at).toLocaleString() : "—"}
                    </Badge>
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>

        </Tabs>
      </div>
    </DashboardLayout>
  );
}