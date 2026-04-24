'use client';

import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { apiGet } from "@/lib/api";

import { useSecureImage } from "@/components/admin/useSecureImage";
import { IdentitiesTab } from "@/components/admin/IdentitiesTab";
import { UnknownFacesTab } from "@/components/admin/UnknownFacesTab";
import { EntryLogsTab } from "@/components/admin/EntryLogsTab";
import { fmtScore } from "@/components/admin/SharedAdminUI";

type AdminCounts = {
  identities: number;
  unknowns: number;
  logs: number;
};

type PreviewState = {
  open: boolean;
  src: string | null;
  title: string;
};

type DrawerState =
  | { open: false }
  | {
      open: true;
      kind: "log" | "unknown";
      item: any;
    };

const FETCH_LIMIT = 2000;

export default function AdminPage() {
  const { roles } = useAuth();
  const userRole = roles[0] || "user";

  const [counts, setCounts] = useState<AdminCounts>({
    identities: 0,
    unknowns: 0,
    logs: 0,
  });

  const [identities, setIdentities] = useState<any[]>([]);
  const [unknowns, setUnknowns] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const [preview, setPreview] = useState<PreviewState>({
    open: false,
    src: null,
    title: "",
  });

  const [drawer, setDrawer] = useState<DrawerState>({ open: false });

  const imageState = useSecureImage();

  // ---------------- FETCH ----------------

  const fetchCounts = async () => {
    try {
      const data = await apiGet("/api/admin/counts") as AdminCounts;
      setCounts({
        identities: Number(data?.identities || 0),
        unknowns: Number(data?.unknowns || 0),
        logs: Number(data?.logs || 0),
      });
    } catch (e) {
      console.error("Error fetching counts:", e);
      setCounts({ identities: 0, unknowns: 0, logs: 0 });
    }
  };

  const fetchIdentities = async () => {
    try {
      const data = await apiGet(`/api/admin/identities?limit=${FETCH_LIMIT}&offset=0`);
      setIdentities(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching identities:", e);
      setIdentities([]);
    }
  };

  const fetchUnknowns = async () => {
    try {
      const data = await apiGet(`/api/admin/pending-unknowns?limit=${FETCH_LIMIT}&offset=0`);
      setUnknowns(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching unknowns:", e);
      setUnknowns([]);
    }
  };

  const fetchLogs = async () => {
    try {
      const data = await apiGet(`/api/admin/recent-entry-logs?limit=${FETCH_LIMIT}&offset=0`);
      setLogs(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error("Error fetching logs:", e);
      setLogs([]);
    }
  };

  const loadData = async () => {
    setLoading(true);
    await Promise.all([fetchCounts(), fetchIdentities(), fetchUnknowns(), fetchLogs()]);
    setLoading(false);
  };

  useEffect(() => {
    loadData();
  }, []);

  // ---------------- HELPERS ----------------

  const openPreview = (src: string, title: string) => {
    setPreview({ open: true, src, title });
  };

  const closePreview = () => {
    setPreview({ open: false, src: null, title: "" });
  };

  const openDrawer = (kind: "log" | "unknown", item: any) => {
    setDrawer({ open: true, kind, item });
  };

  const closeDrawer = () => {
    setDrawer({ open: false });
  };

  // ---------------- KEYBOARD ----------------

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (preview.open) closePreview();
        if (drawer.open) closeDrawer();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [preview.open, drawer.open]);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <h1 className="text-3xl font-bold">Face Surveillance Console</h1>
          <div className="flex items-center gap-2">
            <Badge className="uppercase">{userRole}</Badge>
            <Badge variant="outline">Identities: {counts.identities}</Badge>
            <Badge variant="outline">Unknowns: {counts.unknowns}</Badge>
            <Badge variant="outline">Logs: {counts.logs}</Badge>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Identities</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{counts.identities}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Unknown Faces</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{counts.unknowns}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm text-gray-400">Entry Logs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{counts.logs}</div>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue="identities" className="w-full">
          <TabsList>
            <TabsTrigger value="identities">Identities</TabsTrigger>
            <TabsTrigger value="unknown">Unknown Faces</TabsTrigger>
            <TabsTrigger value="logs">Entry Logs</TabsTrigger>
          </TabsList>

          <TabsContent value="identities">
            <IdentitiesTab identities={identities} loading={loading} />
          </TabsContent>

          <TabsContent value="unknown">
            <UnknownFacesTab
              unknowns={unknowns}
              identities={identities}
              loading={loading}
              openPreview={openPreview}
              openDrawer={openDrawer}
              imageState={imageState}
              onReviewSubmitted={loadData}
            />
          </TabsContent>

          <TabsContent value="logs">
            <EntryLogsTab
              logs={logs}
              loading={loading}
              openPreview={openPreview}
              openDrawer={openDrawer}
              imageState={imageState}
            />
          </TabsContent>
        </Tabs>

        {preview.open && preview.src && (
          <div
            className="fixed inset-0 z-[100] bg-black/80 flex items-center justify-center p-6"
            onClick={closePreview}
          >
            <div
              className="relative max-w-3xl max-h-[90vh] w-full bg-zinc-950 border border-zinc-800 rounded-2xl p-4 shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="text-white font-semibold">{preview.title}</div>
                <button
                  type="button"
                  className="text-zinc-300 hover:text-white text-sm px-3 py-1 rounded-md border border-zinc-700"
                  onClick={closePreview}
                >
                  Close
                </button>
              </div>

              <div className="flex items-center justify-center overflow-auto max-h-[75vh] rounded-lg bg-black">
                <img
                  src={preview.src}
                  alt={preview.title}
                  className="max-w-full max-h-[75vh] object-contain"
                />
              </div>
            </div>
          </div>
        )}

        {drawer.open && (
          <div
            className="fixed inset-0 z-40 bg-black/50"
            onClick={closeDrawer}
          >
            <div
              className="absolute right-0 top-0 h-full w-full max-w-xl bg-zinc-950 border-l border-zinc-800 shadow-2xl p-5 overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <div className="text-lg font-semibold">
                  {drawer.kind === "log" ? "Entry Log Details" : "Unknown Face Details"}
                </div>
                <Button variant="outline" onClick={closeDrawer}>
                  Close
                </Button>
              </div>

              {drawer.kind === "log" ? (
                <div className="space-y-4">
                  {drawer.item && (
                    <>
                      <div className="rounded-xl overflow-hidden border border-zinc-800 bg-black">
                        {imageState.imageUrls[`log-${drawer.item.id}`] ? (
                          <img
                            src={imageState.imageUrls[`log-${drawer.item.id}`]}
                            alt={`Entry log ${drawer.item.id}`}
                            className="w-full max-h-[360px] object-contain"
                          />
                        ) : (
                          <div className="h-60 flex items-center justify-center text-zinc-500">
                            No preview image
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-sm break-words">
                        <div><span className="text-zinc-400">Log ID:</span> {drawer.item.id}</div>
                        <div><span className="text-zinc-400">Timestamp:</span> {drawer.item.timestamp ? new Date(drawer.item.timestamp).toLocaleString() : "—"}</div>
                        <div><span className="text-zinc-400">Identity:</span> {drawer.item.identity_name || drawer.item.detected_id || "Unknown"}</div>
                        <div><span className="text-zinc-400">Detected ID:</span> {drawer.item.detected_id ?? "—"}</div>
                        <div><span className="text-zinc-400">Unknown Face Event ID:</span> {drawer.item.unknown_face_event_id ?? "—"}</div>
                        <div><span className="text-zinc-400">Camera:</span> {drawer.item.camera_id ?? "—"}</div>
                        <div><span className="text-zinc-400">Location:</span> {drawer.item.location || "—"}</div>
                        <div><span className="text-zinc-400">Event Type:</span> {drawer.item.event_type || "—"}</div>
                        <div><span className="text-zinc-400">Device Status:</span> {drawer.item.device_status || "—"}</div>
                        <div><span className="text-zinc-400">Authorized:</span> {String(drawer.item.authorized)}</div>
                        <div><span className="text-zinc-400">Model Version:</span> {drawer.item.model_version || "—"}</div>
                        <div><span className="text-zinc-400">Quality Score:</span> {fmtScore(drawer.item.quality_score)}</div>
                        <div><span className="text-zinc-400">Best Similarity:</span> {fmtScore(drawer.item.best_similarity)}</div>
                        <div><span className="text-zinc-400">Second Similarity:</span> {fmtScore(drawer.item.second_similarity)}</div>
                        <div><span className="text-zinc-400">Margin:</span> {fmtScore(drawer.item.margin)}</div>
                        <div><span className="text-zinc-400">Processing Time:</span> {drawer.item.processing_time || "—"}</div>
                        <div className="break-all"><span className="text-zinc-400">Image Ref:</span> {drawer.item.image_video_ref || "—"}</div>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {drawer.item && (
                    <>
                      <div className="rounded-xl overflow-hidden border border-zinc-800 bg-black">
                        {imageState.imageUrls[`unknown-${drawer.item.id}`] ? (
                          <img
                            src={imageState.imageUrls[`unknown-${drawer.item.id}`]}
                            alt={`Unknown face ${drawer.item.id}`}
                            className="w-full max-h-[360px] object-contain"
                          />
                        ) : (
                          <div className="h-60 flex items-center justify-center text-zinc-500">
                            No preview image
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-sm break-words">
                        <div><span className="text-zinc-400">Unknown ID:</span> {drawer.item.id}</div>
                        <div><span className="text-zinc-400">Entry Log ID:</span> {drawer.item.entry_log_id}</div>
                        <div><span className="text-zinc-400">Created:</span> {drawer.item.created_at ? new Date(drawer.item.created_at).toLocaleString() : "—"}</div>
                        <div><span className="text-zinc-400">Status:</span> {drawer.item.status || "—"}</div>
                        <div><span className="text-zinc-400">Assigned Detected ID:</span> {drawer.item.assigned_detected_id ?? "—"}</div>
                        <div><span className="text-zinc-400">Camera:</span> {drawer.item.camera_id ?? "—"}</div>
                        <div><span className="text-zinc-400">Location:</span> {drawer.item.location || "—"}</div>
                        <div><span className="text-zinc-400">Event Type:</span> {drawer.item.event_type || "—"}</div>
                        <div><span className="text-zinc-400">Embedding Model:</span> {drawer.item.embedding_model || "—"}</div>
                        <div><span className="text-zinc-400">Quality Score:</span> {fmtScore(drawer.item.quality_score)}</div>
                        <div><span className="text-zinc-400">Best Similarity:</span> {fmtScore(drawer.item.best_similarity)}</div>
                        <div><span className="text-zinc-400">Second Similarity:</span> {fmtScore(drawer.item.second_similarity)}</div>
                        <div><span className="text-zinc-400">Margin:</span> {fmtScore(drawer.item.margin)}</div>
                        <div><span className="text-zinc-400">Notes:</span> {drawer.item.notes || "—"}</div>
                        <div className="break-all"><span className="text-zinc-400">Image Ref:</span> {drawer.item.image_video_ref || "—"}</div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
