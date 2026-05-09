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
import { PreviewModal } from "@/components/admin/PreviewModal";
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

  // ── Drawer helpers ────────────────────────────────────────────────────────
  const DetailRow = ({
    label,
    value,
    fallback,
    highlight,
  }: {
    label: string;
    value: string | number | null | undefined;
    fallback?: string;
    highlight?: boolean;
  }) => {
    const display = value != null && value !== "" ? String(value) : fallback ?? null;
    if (display === null) return null;
    return (
      <div className="flex items-start justify-between gap-2">
        <span className="text-zinc-500 shrink-0">{label}</span>
        <span className={highlight ? "font-semibold text-zinc-100" : "text-zinc-300"}>{display}</span>
      </div>
    );
  };

  const MetricCell = ({ label, value }: { label: string; value: string }) => (
    <div className="flex flex-col gap-0.5 bg-zinc-900/50 rounded-lg px-3 py-2 border border-zinc-800">
      <span className="text-[10px] text-zinc-500 uppercase tracking-wide">{label}</span>
      <span className="text-sm font-mono font-medium text-emerald-400">{value}</span>
    </div>
  );

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div className="flex flex-col gap-1 md:justify-center">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Face Surveillance Console</h1>
          <p className="text-sm text-muted-foreground">Identity registry, unknown face review, and entry log monitoring</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border-zinc-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400 tracking-wider uppercase">Identities</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-emerald-400 drop-shadow-[0_0_8px_rgba(16,185,129,0.3)]">{counts.identities}</div>
            </CardContent>
          </Card>

          <Card className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border-zinc-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400 tracking-wider uppercase">Unknown Faces</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.3)]">{counts.unknowns}</div>
            </CardContent>
          </Card>

          <Card className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border-zinc-800">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-zinc-400 tracking-wider uppercase">Entry Logs</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-blue-400 drop-shadow-[0_0_8px_rgba(96,165,250,0.3)]">{counts.logs}</div>
            </CardContent>
          </Card>
        </div>

        <Tabs defaultValue="identities" className="w-full">
          <TabsList className="bg-zinc-950/80 border border-zinc-800 p-1 rounded-xl shadow-inner shadow-black/50">
            <TabsTrigger value="identities" className="rounded-lg data-[state=active]:bg-emerald-500/10 data-[state=active]:text-emerald-400 data-[state=active]:shadow-sm transition-all duration-300">Identities</TabsTrigger>
            <TabsTrigger value="unknown" className="rounded-lg data-[state=active]:bg-emerald-500/10 data-[state=active]:text-emerald-400 data-[state=active]:shadow-sm transition-all duration-300">Unknown Faces</TabsTrigger>
            <TabsTrigger value="logs" className="rounded-lg data-[state=active]:bg-emerald-500/10 data-[state=active]:text-emerald-400 data-[state=active]:shadow-sm transition-all duration-300">Entry Logs</TabsTrigger>
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

        <PreviewModal
          open={preview.open}
          src={preview.src}
          title={preview.title}
          onClose={closePreview}
        />

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
                <div className="space-y-5">
                  {drawer.item && (
                    <>
                      {/* Evidence image */}
                      <div className="rounded-xl overflow-hidden border border-zinc-800 bg-zinc-950">
                        {imageState.imageUrls[`log-${drawer.item.id}`] ? (
                          <img
                            src={imageState.imageUrls[`log-${drawer.item.id}`]}
                            alt={`Entry log ${drawer.item.id}`}
                            className="w-full max-h-[320px] object-contain"
                          />
                        ) : (
                          <div className="h-48 flex flex-col items-center justify-center gap-2 text-zinc-600">
                            <span className="text-3xl">🎞️</span>
                            <span className="text-xs">No evidence image available</span>
                          </div>
                        )}
                      </div>

                      {/* ── Section: Identity ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          Identity
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          <DetailRow
                            label="Name"
                            value={drawer.item.identity_name}
                            fallback="Unknown"
                            highlight
                          />
                          {drawer.item.detected_id != null && (
                            <DetailRow label="Detected ID" value={drawer.item.detected_id} />
                          )}
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-zinc-500">Status</span>
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                              drawer.item.detected_id || drawer.item.identity_name
                                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                                : "bg-amber-500/10 text-amber-400 border-amber-500/30"
                            }`}>
                              {drawer.item.detected_id || drawer.item.identity_name ? "Known" : "Unknown"}
                            </span>
                          </div>
                        </div>
                      </section>

                      {/* ── Section: Event ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          Event
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          <DetailRow label="Log ID" value={drawer.item.id} />
                          <DetailRow
                            label="Timestamp"
                            value={drawer.item.timestamp ? new Date(drawer.item.timestamp).toLocaleString() : null}
                          />
                          {drawer.item.camera_id != null && (
                            <DetailRow label="Camera" value={`Camera ${drawer.item.camera_id}`} />
                          )}
                          {drawer.item.event_type && (
                            <DetailRow label="Event Type" value={drawer.item.event_type} />
                          )}
                          {drawer.item.location && (
                            <DetailRow label="Location" value={drawer.item.location} />
                          )}
                        </div>
                      </section>

                      {/* ── Section: Recognition Quality ── */}
                      {(drawer.item.quality_score != null || drawer.item.best_similarity != null) && (
                        <section>
                          <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                            Recognition Quality
                          </h3>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                            {drawer.item.quality_score != null && (
                              <MetricCell label="Quality" value={fmtScore(drawer.item.quality_score)} />
                            )}
                            {drawer.item.best_similarity != null && (
                              <MetricCell label="Best Match" value={fmtScore(drawer.item.best_similarity)} />
                            )}
                            {drawer.item.second_similarity != null && (
                              <MetricCell label="2nd Match" value={fmtScore(drawer.item.second_similarity)} />
                            )}
                            {drawer.item.margin != null && (
                              <MetricCell label="Margin" value={fmtScore(drawer.item.margin)} />
                            )}
                          </div>
                        </section>
                      )}

                      {/* ── Section: System ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          System
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          {drawer.item.model_version && (
                            <DetailRow label="Model Version" value={drawer.item.model_version} />
                          )}
                          {drawer.item.processing_time && (
                            <DetailRow label="Processing Time" value={drawer.item.processing_time} />
                          )}
                          {drawer.item.device_status && (
                            <DetailRow label="Device Status" value={drawer.item.device_status} />
                          )}
                          {drawer.item.image_video_ref && (
                            <div className="flex items-start justify-between gap-2">
                              <span className="text-zinc-500 shrink-0">Image Ref</span>
                              <span className="text-zinc-300 text-xs font-mono break-all text-right max-w-[60%]">
                                {drawer.item.image_video_ref}
                              </span>
                            </div>
                          )}
                          {drawer.item.unknown_face_event_id != null && (
                            <DetailRow label="Unknown Event ID" value={drawer.item.unknown_face_event_id} />
                          )}
                        </div>
                      </section>
                    </>
                  )}
                </div>
              ) : (
                <div className="space-y-5">
                  {drawer.item && (
                    <>
                      {/* Evidence image */}
                      <div className="rounded-xl overflow-hidden border border-zinc-800 bg-zinc-950">
                        {imageState.imageUrls[`unknown-${drawer.item.id}`] ? (
                          <img
                            src={imageState.imageUrls[`unknown-${drawer.item.id}`]}
                            alt={`Unknown face ${drawer.item.id}`}
                            className="w-full max-h-[320px] object-contain"
                          />
                        ) : (
                          <div className="h-48 flex flex-col items-center justify-center gap-2 text-zinc-600">
                            <span className="text-3xl">🎞️</span>
                            <span className="text-xs">No evidence image available</span>
                          </div>
                        )}
                      </div>

                      {/* ── Section: Identity ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          Identity
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          <DetailRow label="Unknown Face ID" value={drawer.item.id} highlight />
                          <DetailRow label="Entry Log ID" value={drawer.item.entry_log_id} />
                          {drawer.item.assigned_detected_id != null && (
                            <DetailRow label="Assigned To (ID)" value={drawer.item.assigned_detected_id} />
                          )}
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-zinc-500">Review Status</span>
                            <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${
                              drawer.item.status === "reviewed" || drawer.item.assigned_detected_id != null
                                ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
                                : "bg-amber-500/10 text-amber-400 border-amber-500/30"
                            }`}>
                              {drawer.item.status === "reviewed" || drawer.item.assigned_detected_id != null
                                ? "Reviewed"
                                : "Pending Review"}
                            </span>
                          </div>
                        </div>
                      </section>

                      {/* ── Section: Event ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          Event
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          <DetailRow
                            label="Created"
                            value={drawer.item.created_at ? new Date(drawer.item.created_at).toLocaleString() : null}
                          />
                          {drawer.item.camera_id != null && (
                            <DetailRow label="Camera" value={`Camera ${drawer.item.camera_id}`} />
                          )}
                          {drawer.item.event_type && (
                            <DetailRow label="Event Type" value={drawer.item.event_type} />
                          )}
                          {drawer.item.location && (
                            <DetailRow label="Location" value={drawer.item.location} />
                          )}
                        </div>
                      </section>

                      {/* ── Section: Recognition Quality ── */}
                      {(drawer.item.quality_score != null || drawer.item.best_similarity != null) && (
                        <section>
                          <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                            Recognition Quality
                          </h3>
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                            {drawer.item.quality_score != null && (
                              <MetricCell label="Quality" value={fmtScore(drawer.item.quality_score)} />
                            )}
                            {drawer.item.best_similarity != null && (
                              <MetricCell label="Best Match" value={fmtScore(drawer.item.best_similarity)} />
                            )}
                            {drawer.item.second_similarity != null && (
                              <MetricCell label="2nd Match" value={fmtScore(drawer.item.second_similarity)} />
                            )}
                            {drawer.item.margin != null && (
                              <MetricCell label="Margin" value={fmtScore(drawer.item.margin)} />
                            )}
                          </div>
                        </section>
                      )}

                      {/* ── Section: System ── */}
                      <section>
                        <h3 className="text-[10px] font-bold uppercase tracking-widest text-zinc-500 mb-2 pb-1 border-b border-zinc-800">
                          System
                        </h3>
                        <div className="space-y-1.5 text-sm">
                          {drawer.item.embedding_model && (
                            <DetailRow label="Embedding Model" value={drawer.item.embedding_model} />
                          )}
                          {drawer.item.notes && (
                            <DetailRow label="Notes" value={drawer.item.notes} />
                          )}
                          {drawer.item.image_video_ref && (
                            <div className="flex items-start justify-between gap-2">
                              <span className="text-zinc-500 shrink-0">Image Ref</span>
                              <span className="text-zinc-300 text-xs font-mono break-all text-right max-w-[60%]">
                                {drawer.item.image_video_ref}
                              </span>
                            </div>
                          )}
                        </div>
                      </section>
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
