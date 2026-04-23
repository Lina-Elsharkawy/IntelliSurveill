'use client';

import { useEffect, useMemo, useRef, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useAuth } from "@/context/AuthContext";
import { apiGet, apiPost } from "@/lib/api";

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

type UnknownReviewMode = "new" | "existing";

type UnknownReviewState = {
  open: boolean;
  item: any | null;
  mode: UnknownReviewMode;
  newIdentityName: string;
  existingDetectedId: string;
  notes: string;
  promoteToAuthoritative: boolean;
  submitting: boolean;
};

const PAGE_SIZE = 8;
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

  const [identitySearch, setIdentitySearch] = useState("");
  const [unknownSearch, setUnknownSearch] = useState("");
  const [logsSearch, setLogsSearch] = useState("");

  const [logsFilter, setLogsFilter] = useState<"all" | "known" | "unknown" | "hasImage">("all");
  const [unknownFilter, setUnknownFilter] = useState<"all" | "hasImage" | "camera1" | "cameraOther">("all");

  const [identityPage, setIdentityPage] = useState(1);
  const [unknownPage, setUnknownPage] = useState(1);
  const [logsPage, setLogsPage] = useState(1);

  const [logImageUrls, setLogImageUrls] = useState<Record<number, string>>({});
  const [unknownImageUrls, setUnknownImageUrls] = useState<Record<number, string>>({});
  const [imageErrors, setImageErrors] = useState<Record<string, string>>({});

  const logImageUrlsRef = useRef<Record<number, string>>({});
  const unknownImageUrlsRef = useRef<Record<number, string>>({});

  const [preview, setPreview] = useState<PreviewState>({
    open: false,
    src: null,
    title: "",
  });

  const [drawer, setDrawer] = useState<DrawerState>({ open: false });

  const [review, setReview] = useState<UnknownReviewState>({
    open: false,
    item: null,
    mode: "new",
    newIdentityName: "",
    existingDetectedId: "",
    notes: "",
    promoteToAuthoritative: true,
    submitting: false,
  });

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

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      await Promise.all([fetchCounts(), fetchIdentities(), fetchUnknowns(), fetchLogs()]);
      setLoading(false);
    };
    load();
  }, []);

  // ---------------- HELPERS ----------------

  const getAccessToken = (): string | null => {
    return (
      localStorage.getItem("access_token") ||
      localStorage.getItem("token") ||
      sessionStorage.getItem("access_token") ||
      sessionStorage.getItem("token")
    );
  };

  const isS3Ref = (value: any): boolean =>
    typeof value === "string" && value.startsWith("s3://");

  const copyText = async (label: string, value: string | number | null | undefined) => {
    if (value === null || value === undefined || value === "") return;
    try {
      await navigator.clipboard.writeText(String(value));
    } catch (err) {
      console.error(`Failed to copy ${label}:`, err);
    }
  };

  const openPreview = (src: string, title: string) => {
    setPreview({
      open: true,
      src,
      title,
    });
  };

  const closePreview = () => {
    setPreview({
      open: false,
      src: null,
      title: "",
    });
  };

  const closeDrawer = () => {
    setDrawer({ open: false });
  };

  const closeUnknownReview = () => {
    setReview({
      open: false,
      item: null,
      mode: "new",
      newIdentityName: "",
      existingDetectedId: "",
      notes: "",
      promoteToAuthoritative: true,
      submitting: false,
    });
  };

  const getKnownUnknownBadge = (item: any) => {
    const isKnown = !!item?.detected_id || !!item?.identity_name;
    const label = isKnown ? "Known" : "Unknown";
    const className = isKnown
      ? "bg-emerald-600 hover:bg-emerald-600 text-white"
      : "bg-amber-600 hover:bg-amber-600 text-white";
    return <Badge className={className}>{label}</Badge>;
  };

  const getAuthorizedBadge = (authorized: boolean | null | undefined) => {
    if (authorized === true) {
      return <Badge className="bg-emerald-600 hover:bg-emerald-600 text-white">Authorized</Badge>;
    }
    if (authorized === false) {
      return <Badge className="bg-red-600 hover:bg-red-600 text-white">Denied</Badge>;
    }
    return <Badge className="bg-zinc-600 hover:bg-zinc-600 text-white">Pending</Badge>;
  };

  const getImageStateBadge = (key: string, hasS3: boolean, hasBlob: boolean) => {
    if (hasBlob) {
      return <Badge className="bg-emerald-600 hover:bg-emerald-600 text-white">Image OK</Badge>;
    }
    if (!hasS3) {
      return <Badge className="bg-zinc-600 hover:bg-zinc-600 text-white">No Image</Badge>;
    }
    if (imageErrors[key]) {
      return <Badge className="bg-red-600 hover:bg-red-600 text-white">Image Error</Badge>;
    }
    return <Badge className="bg-sky-600 hover:bg-sky-600 text-white">Loading Image</Badge>;
  };

  const paginate = <T,>(items: T[], page: number) => {
    const start = (page - 1) * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  };

  const totalPages = (count: number) => Math.max(1, Math.ceil(count / PAGE_SIZE));

  const fmtScore = (value: any) => {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(3) : "—";
  };

  // ---------------- IMAGE FETCH ----------------

  const fetchLogImage = async (logId: number): Promise<string | null> => {
    try {
      if (logImageUrlsRef.current[logId]) {
        return logImageUrlsRef.current[logId];
      }

      const token = getAccessToken();
      if (!token) {
        console.warn(`No access token found for log image ${logId}`);
        setImageErrors((prev) => ({ ...prev, [`log-${logId}`]: "Missing token" }));
        return null;
      }

      const resp = await fetch(`/api/admin/entry-logs/${logId}/image`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
        cache: "no-store",
      });

      if (!resp.ok) {
        console.error(`Image fetch failed for log ${logId}:`, resp.status, resp.statusText);
        setImageErrors((prev) => ({
          ...prev,
          [`log-${logId}`]: `${resp.status} ${resp.statusText}`,
        }));
        return null;
      }

      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);

      logImageUrlsRef.current = {
        ...logImageUrlsRef.current,
        [logId]: objectUrl,
      };

      setLogImageUrls((prev) => ({
        ...prev,
        [logId]: objectUrl,
      }));

      setImageErrors((prev) => {
        const next = { ...prev };
        delete next[`log-${logId}`];
        return next;
      });

      return objectUrl;
    } catch (err) {
      console.error(`Error fetching image for log ${logId}:`, err);
      setImageErrors((prev) => ({ ...prev, [`log-${logId}`]: "Fetch error" }));
      return null;
    }
  };

  const fetchUnknownImage = async (unknownId: number, entryLogId: number) => {
    try {
      const token = getAccessToken();
      if (!token) {
        console.warn(`No access token found for unknown image ${unknownId}`);
        setImageErrors((prev) => ({ ...prev, [`unknown-${unknownId}`]: "Missing token" }));
        return;
      }

      const resp = await fetch(`/api/admin/entry-logs/${entryLogId}/thumbnail`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!resp.ok) {
        console.error(
          `Image fetch failed for unknown ${unknownId} (entry log ${entryLogId}):`,
          resp.status,
          resp.statusText
        );
        setImageErrors((prev) => ({
          ...prev,
          [`unknown-${unknownId}`]: `${resp.status} ${resp.statusText}`,
        }));
        return;
      }

      const blob = await resp.blob();
      const objectUrl = URL.createObjectURL(blob);

      setUnknownImageUrls((prev) => {
        if (prev[unknownId]) {
          try {
            URL.revokeObjectURL(prev[unknownId]);
          } catch {
            // ignore revoke failures
          }
        }
        const next = { ...prev, [unknownId]: objectUrl };
        unknownImageUrlsRef.current = next;
        return next;
      });

      setImageErrors((prev) => {
        const next = { ...prev };
        delete next[`unknown-${unknownId}`];
        return next;
      });
    } catch (err) {
      console.error(`Error fetching image for unknown ${unknownId}:`, err);
      setImageErrors((prev) => ({ ...prev, [`unknown-${unknownId}`]: "Fetch error" }));
    }
  };

  const openDrawer = async (kind: "log" | "unknown", item: any) => {
    if (kind === "log") {
      if (item?.id && isS3Ref(item?.image_video_ref)) {
        await fetchLogImage(item.id);
      }
    } else {
      if (
        item?.entry_log_id &&
        isS3Ref(item?.image_video_ref) &&
        !unknownImageUrlsRef.current[item.id] &&
        !imageErrors[`unknown-${item.id}`]
      ) {
        await fetchUnknownImage(item.id, item.entry_log_id);
      }
    }

    setDrawer({ open: true, kind, item });
  };

  const openUnknownReview = async (item: any, mode: UnknownReviewMode) => {
    if (
      item?.entry_log_id &&
      isS3Ref(item?.image_video_ref) &&
      !unknownImageUrlsRef.current[item.id] &&
      !imageErrors[`unknown-${item.id}`]
    ) {
      await fetchUnknownImage(item.id, item.entry_log_id);
    }

    setReview({
      open: true,
      item,
      mode,
      newIdentityName: "",
      existingDetectedId: "",
      notes: item?.notes || "",
      promoteToAuthoritative: mode === "new",
      submitting: false,
    });
  };

  // ---------------- CLEANUP ----------------

  useEffect(() => {
    return () => {
      Object.values(logImageUrlsRef.current).forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignore cleanup failures
        }
      });

      Object.values(unknownImageUrlsRef.current).forEach((url) => {
        try {
          URL.revokeObjectURL(url);
        } catch {
          // ignore cleanup failures
        }
      });
    };
  }, []);

  // ---------------- KEYBOARD ----------------

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (preview.open) closePreview();
        if (drawer.open) closeDrawer();
        if (review.open) closeUnknownReview();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [preview.open, drawer.open, review.open]);

  // ---------------- ACTIONS ----------------

  const submitUnknownReview = async () => {
    if (!review.item) return;

    try {
      setReview((prev) => ({ ...prev, submitting: true }));

      if (review.mode === "new") {
        if (!review.newIdentityName.trim()) {
          alert("Please enter a name for the new identity.");
          setReview((prev) => ({ ...prev, submitting: false }));
          return;
        }

        await apiPost("/api/admin/create-identity-from-unknown", {
          unknown_face_event_id: review.item.id,
          name: review.newIdentityName.trim(),
          notes: review.notes.trim() || undefined,
          promote_to_authoritative: review.promoteToAuthoritative,
        });
      } else {
        const detectedId = parseInt(review.existingDetectedId, 10);
        if (isNaN(detectedId)) {
          alert("Please choose a valid existing identity ID.");
          setReview((prev) => ({ ...prev, submitting: false }));
          return;
        }

        await apiPost("/api/admin/assign-unknown", {
          unknown_face_event_id: review.item.id,
          detected_id: detectedId,
          notes: review.notes.trim() || undefined,
          promote_to_authoritative: review.promoteToAuthoritative,
        });
      }

      closeUnknownReview();
      await Promise.all([fetchCounts(), fetchUnknowns(), fetchIdentities(), fetchLogs()]);
    } catch (e) {
      console.error("Error submitting unknown review:", e);
      alert("Failed to submit review. Check the console for details.");
      setReview((prev) => ({ ...prev, submitting: false }));
    }
  };

  // ---------------- FILTERED DATA ----------------

  const filteredIdentities = useMemo(() => {
    return identities.filter((p) => {
      const q = identitySearch.trim().toLowerCase();
      if (!q) return true;
      return (
        String(p?.id ?? "").includes(q) ||
        String(p?.name ?? "").toLowerCase().includes(q) ||
        String(p?.additional_info ?? "").toLowerCase().includes(q)
      );
    });
  }, [identities, identitySearch]);

  const filteredUnknowns = useMemo(() => {
    return unknowns.filter((u) => {
      const q = unknownSearch.trim().toLowerCase();

      const matchesSearch =
        !q ||
        String(u?.id ?? "").includes(q) ||
        String(u?.entry_log_id ?? "").includes(q) ||
        String(u?.embedding_model ?? "").toLowerCase().includes(q) ||
        String(u?.event_type ?? "").toLowerCase().includes(q) ||
        String(u?.camera_id ?? "").includes(q) ||
        String(u?.notes ?? "").toLowerCase().includes(q);

      let matchesFilter = true;
      if (unknownFilter === "hasImage") {
        matchesFilter = isS3Ref(u?.image_video_ref);
      } else if (unknownFilter === "camera1") {
        matchesFilter = Number(u?.camera_id) === 1;
      } else if (unknownFilter === "cameraOther") {
        matchesFilter = Number(u?.camera_id) !== 1;
      }

      return matchesSearch && matchesFilter;
    });
  }, [unknowns, unknownSearch, unknownFilter]);

  const filteredLogs = useMemo(() => {
    return logs.filter((l) => {
      const q = logsSearch.trim().toLowerCase();

      const label =
        l?.identity_name ||
        (l?.detected_id ? `detected id ${l.detected_id}` : "") ||
        (l?.unknown_face_event_id ? `unknown face ${l.unknown_face_event_id}` : "");

      const matchesSearch =
        !q ||
        String(l?.id ?? "").includes(q) ||
        String(l?.detected_id ?? "").includes(q) ||
        String(l?.unknown_face_event_id ?? "").includes(q) ||
        String(l?.camera_id ?? "").includes(q) ||
        String(l?.event_type ?? "").toLowerCase().includes(q) ||
        String(l?.location ?? "").toLowerCase().includes(q) ||
        String(l?.device_status ?? "").toLowerCase().includes(q) ||
        String(label).toLowerCase().includes(q);

      let matchesFilter = true;
      if (logsFilter === "known") {
        matchesFilter = !!l?.detected_id || !!l?.identity_name;
      } else if (logsFilter === "unknown") {
        matchesFilter = !l?.detected_id && !l?.identity_name;
      } else if (logsFilter === "hasImage") {
        matchesFilter = isS3Ref(l?.image_video_ref);
      }

      return matchesSearch && matchesFilter;
    });
  }, [logs, logsSearch, logsFilter]);

  const pagedIdentities = useMemo(
    () => paginate(filteredIdentities, identityPage),
    [filteredIdentities, identityPage]
  );

  const pagedUnknowns = useMemo(
    () => paginate(filteredUnknowns, unknownPage),
    [filteredUnknowns, unknownPage]
  );

  const pagedLogs = useMemo(
    () => paginate(filteredLogs, logsPage),
    [filteredLogs, logsPage]
  );

  useEffect(() => setIdentityPage(1), [identitySearch]);
  useEffect(() => setUnknownPage(1), [unknownSearch, unknownFilter]);
  useEffect(() => setLogsPage(1), [logsSearch, logsFilter]);

  // ---------------- UI HELPERS ----------------

  const PaginationBar = ({
    page,
    setPage,
    total,
  }: {
    page: number;
    setPage: (v: number) => void;
    total: number;
  }) => (
    <div className="flex items-center justify-between pt-2">
      <div className="text-xs text-gray-400">
        Page {page} of {total}
      </div>
      <div className="flex gap-2">
        <Button variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>
          Previous
        </Button>
        <Button variant="outline" disabled={page >= total} onClick={() => setPage(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );

  const SmallActionButton = ({
    onClick,
    label,
  }: {
    onClick: () => void;
    label: string;
  }) => (
    <button
      type="button"
      onClick={onClick}
      className="text-xs text-zinc-300 hover:text-white border border-zinc-700 rounded px-2 py-1"
    >
      {label}
    </button>
  );

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

          <TabsContent value="identities" className="space-y-4 pt-4">
            <Input
              placeholder="Search identities by id, name, or info..."
              value={identitySearch}
              onChange={(e) => setIdentitySearch(e.target.value)}
            />

            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : (
              <>
                <Card>
                  <CardContent className="p-0">
                    <div className="divide-y">
                      {pagedIdentities.map((p) => (
                        <div key={p.id} className="p-4 flex justify-between items-center gap-4">
                          <div className="min-w-0">
                            <div className="font-semibold">{p.name || "Unnamed"}</div>
                            <div className="text-sm text-gray-500">
                              ID: {p.id} · Embeddings: {p.embeddings_count ?? "—"} · Authoritative: {p.authoritative_count ?? "—"}
                            </div>
                            <div className="text-xs text-gray-400">
                              {p.additional_info || "No additional info"}
                            </div>
                          </div>

                          <div className="flex items-center gap-2">
                            <Badge variant="outline">
                              {p.embeddings_count > 0 ? "Active" : "No embeddings"}
                            </Badge>
                            <SmallActionButton
                              label="Copy ID"
                              onClick={() => copyText("identity id", p.id)}
                            />
                          </div>
                        </div>
                      ))}

                      {pagedIdentities.length === 0 && (
                        <div className="p-4 text-gray-400 text-sm">No identities found.</div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                <PaginationBar
                  page={identityPage}
                  setPage={setIdentityPage}
                  total={totalPages(filteredIdentities.length)}
                />
              </>
            )}
          </TabsContent>

          <TabsContent value="unknown" className="space-y-4 pt-4">
            <div className="flex flex-col md:flex-row gap-3">
              <Input
                placeholder="Search unknowns by id, entry log, camera, model, notes..."
                value={unknownSearch}
                onChange={(e) => setUnknownSearch(e.target.value)}
              />
              <div className="flex gap-2 flex-wrap">
                <Button
                  variant={unknownFilter === "all" ? "default" : "outline"}
                  onClick={() => setUnknownFilter("all")}
                >
                  All
                </Button>
                <Button
                  variant={unknownFilter === "hasImage" ? "default" : "outline"}
                  onClick={() => setUnknownFilter("hasImage")}
                >
                  Has Image
                </Button>
                <Button
                  variant={unknownFilter === "camera1" ? "default" : "outline"}
                  onClick={() => setUnknownFilter("camera1")}
                >
                  Camera 1
                </Button>
                <Button
                  variant={unknownFilter === "cameraOther" ? "default" : "outline"}
                  onClick={() => setUnknownFilter("cameraOther")}
                >
                  Other Cameras
                </Button>
              </div>
            </div>

            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : pagedUnknowns.length === 0 ? (
              <div className="text-gray-400 text-sm">No unknown faces pending review.</div>
            ) : (
              <>
                {pagedUnknowns.map((u) => (
                  <Card key={u.id}>
                    <CardContent className="p-4 flex justify-between items-center gap-4">
                      <div className="flex items-center gap-4 min-w-0">
                        <button
                          type="button"
                          className="w-20 h-20 rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 shrink-0 cursor-pointer hover:opacity-90 transition"
                          onClick={async () => {
                            if (
                              !unknownImageUrlsRef.current[u.id] &&
                              u?.entry_log_id &&
                              isS3Ref(u?.image_video_ref) &&
                              !imageErrors[`unknown-${u.id}`]
                            ) {
                              await fetchUnknownImage(u.id, u.entry_log_id);
                            }

                            const src = unknownImageUrlsRef.current[u.id];
                            if (src) {
                              openPreview(src, `Unknown Face #${u.id}`);
                            }
                          }}
                        >
                          {unknownImageUrls[u.id] ? (
                            <img
                              src={unknownImageUrls[u.id]}
                              alt={`Unknown face ${u.id}`}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-xs text-zinc-500 text-center px-1">
                              {isS3Ref(u.image_video_ref) ? `Unknown #${u.id}` : "No image"}
                            </div>
                          )}
                        </button>

                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <div className="font-semibold">Unknown Face #{u.id}</div>
                            <Badge className="bg-amber-600 hover:bg-amber-600 text-white">
                              Pending Review
                            </Badge>
                            {getImageStateBadge(
                              `unknown-${u.id}`,
                              isS3Ref(u.image_video_ref),
                              !!unknownImageUrls[u.id]
                            )}
                          </div>

                          <div className="text-xs text-gray-500 mt-1">
                            Entry Log ID: {u.entry_log_id} · Status: {u.status || "pending"} · Created:{" "}
                            {u.created_at ? new Date(u.created_at).toLocaleString() : "—"}
                          </div>

                          <div className="text-xs text-gray-400 mt-1">
                            Model: {u.embedding_model || "—"} · Camera: {u.camera_id ?? "—"} · Type: {u.event_type || "—"}
                          </div>
                          <div className="text-xs text-gray-400">
                            Quality: {fmtScore(u.quality_score)} · Best: {fmtScore(u.best_similarity)} · Second: {fmtScore(u.second_similarity)} · Margin: {fmtScore(u.margin)}
                          </div>
                          <div className="text-xs text-gray-400">
                            {u.location || "No location"} · Notes: {u.notes || "—"}
                          </div>

                          {imageErrors[`unknown-${u.id}`] && (
                            <div className="text-xs text-red-400 mt-1">
                              Image issue: {imageErrors[`unknown-${u.id}`]}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col gap-2 items-end">
                        <div className="flex gap-2">
                          <Button onClick={() => openUnknownReview(u, "new")}>
                            New Identity
                          </Button>
                          <Button variant="outline" onClick={() => openUnknownReview(u, "existing")}>
                            Assign Existing
                          </Button>
                        </div>

                        <div className="flex gap-2 flex-wrap justify-end">
                          <SmallActionButton
                            label="Details"
                            onClick={() => openDrawer("unknown", u)}
                          />
                          <SmallActionButton
                            label="Copy Unknown ID"
                            onClick={() => copyText("unknown id", u.id)}
                          />
                          <SmallActionButton
                            label="Copy Entry Log"
                            onClick={() => copyText("entry log id", u.entry_log_id)}
                          />
                          <SmallActionButton
                            label="Copy Image Ref"
                            onClick={() => copyText("image ref", u.image_video_ref)}
                          />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}

                <PaginationBar
                  page={unknownPage}
                  setPage={setUnknownPage}
                  total={totalPages(filteredUnknowns.length)}
                />
              </>
            )}
          </TabsContent>

          <TabsContent value="logs" className="space-y-4 pt-4">
            <div className="flex flex-col md:flex-row gap-3">
              <Input
                placeholder="Search logs by id, camera, name, detected id, unknown id, event type..."
                value={logsSearch}
                onChange={(e) => setLogsSearch(e.target.value)}
              />
              <div className="flex gap-2 flex-wrap">
                <Button
                  variant={logsFilter === "all" ? "default" : "outline"}
                  onClick={() => setLogsFilter("all")}
                >
                  All
                </Button>
                <Button
                  variant={logsFilter === "known" ? "default" : "outline"}
                  onClick={() => setLogsFilter("known")}
                >
                  Known
                </Button>
                <Button
                  variant={logsFilter === "unknown" ? "default" : "outline"}
                  onClick={() => setLogsFilter("unknown")}
                >
                  Unknown
                </Button>
                <Button
                  variant={logsFilter === "hasImage" ? "default" : "outline"}
                  onClick={() => setLogsFilter("hasImage")}
                >
                  Has Image
                </Button>
              </div>
            </div>

            {loading ? (
              <div className="text-gray-400 text-sm">Loading...</div>
            ) : pagedLogs.length === 0 ? (
              <div className="text-gray-400 text-sm">No entry logs found.</div>
            ) : (
              <>
                {pagedLogs.map((l) => (
                  <Card key={l.id}>
                    <CardContent className="p-4 flex justify-between items-center gap-4">
                      <div className="flex items-center gap-4 min-w-0">
                        <button
                          type="button"
                          className="w-20 h-20 rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 shrink-0 cursor-pointer hover:opacity-90 transition"
                          onClick={async () => {
                            if (!isS3Ref(l?.image_video_ref)) return;

                            const src = logImageUrlsRef.current[l.id] || await fetchLogImage(l.id);
                            if (src) {
                              openPreview(src, `Entry Log ${l.id}`);
                            }
                          }}
                        >
                          {logImageUrls[l.id] ? (
                            <img
                              src={logImageUrls[l.id]}
                              alt={`Entry log ${l.id}`}
                              className="w-full h-full object-cover"
                            />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-xs text-zinc-500 text-center px-1">
                              {isS3Ref(l.image_video_ref) ? `Entry log ${l.id}` : "No image"}
                            </div>
                          )}
                        </button>

                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <div className="font-semibold">
                              {l.identity_name
                                ? l.identity_name
                                : l.detected_id
                                  ? `Detected ID: ${l.detected_id}`
                                  : l.unknown_face_event_id
                                    ? `Unknown Face #${l.unknown_face_event_id}`
                                    : "Unknown"}
                            </div>
                            {getKnownUnknownBadge(l)}
                            {getAuthorizedBadge(l.authorized)}
                            {getImageStateBadge(
                              `log-${l.id}`,
                              isS3Ref(l.image_video_ref),
                              !!logImageUrls[l.id]
                            )}
                          </div>

                          <div className="text-sm text-gray-500 mt-1">
                            {l.location || "No location"} · Camera: {l.camera_id ?? "—"}
                          </div>

                          <div className="text-xs text-gray-400">
                            Type: {l.event_type || "—"} · Device: {l.device_status || "—"} · Model: {l.model_version || "—"}
                          </div>
                          <div className="text-xs text-gray-400">
                            Quality: {fmtScore(l.quality_score)} · Best: {fmtScore(l.best_similarity)} · Second: {fmtScore(l.second_similarity)} · Margin: {fmtScore(l.margin)}
                          </div>

                          <div className="text-xs text-gray-400">
                            Processing: {l.processing_time || "—"} · Unknown Event: {l.unknown_face_event_id ?? "—"}
                          </div>

                          {imageErrors[`log-${l.id}`] && (
                            <div className="text-xs text-red-400 mt-1">
                              Image issue: {imageErrors[`log-${l.id}`]}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-2">
                        <Badge>
                          {l.timestamp ? new Date(l.timestamp).toLocaleString() : "—"}
                        </Badge>

                        <div className="flex gap-2 flex-wrap justify-end">
                          <SmallActionButton
                            label="Details"
                            onClick={() => openDrawer("log", l)}
                          />
                          <SmallActionButton
                            label="Copy Log ID"
                            onClick={() => copyText("log id", l.id)}
                          />
                          <SmallActionButton
                            label="Copy Image Ref"
                            onClick={() => copyText("image ref", l.image_video_ref)}
                          />
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}

                <PaginationBar
                  page={logsPage}
                  setPage={setLogsPage}
                  total={totalPages(filteredLogs.length)}
                />
              </>
            )}
          </TabsContent>
        </Tabs>

        {preview.open && preview.src && (
          <div
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6"
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
                        {logImageUrls[drawer.item.id] ? (
                          <img
                            src={logImageUrls[drawer.item.id]}
                            alt={`Entry log ${drawer.item.id}`}
                            className="w-full max-h-[360px] object-contain"
                          />
                        ) : (
                          <div className="h-60 flex items-center justify-center text-zinc-500">
                            No preview image
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-sm">
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
                        {unknownImageUrls[drawer.item.id] ? (
                          <img
                            src={unknownImageUrls[drawer.item.id]}
                            alt={`Unknown face ${drawer.item.id}`}
                            className="w-full max-h-[360px] object-contain"
                          />
                        ) : (
                          <div className="h-60 flex items-center justify-center text-zinc-500">
                            No preview image
                          </div>
                        )}
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-sm">
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

        {review.open && review.item && (
          <div
            className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
            onClick={closeUnknownReview}
          >
            <div
              className="w-full max-w-2xl bg-zinc-950 border border-zinc-800 rounded-2xl shadow-2xl p-5"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <div className="text-lg font-semibold">
                  Review Unknown Face #{review.item.id}
                </div>
                <Button variant="outline" onClick={closeUnknownReview}>
                  Close
                </Button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-4">
                <div className="rounded-xl overflow-hidden border border-zinc-800 bg-black h-[180px] flex items-center justify-center">
                  {unknownImageUrls[review.item.id] ? (
                    <img
                      src={unknownImageUrls[review.item.id]}
                      alt={`Unknown face ${review.item.id}`}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="text-zinc-500 text-sm">No image</div>
                  )}
                </div>

                <div className="space-y-3">
                  <div className="flex gap-2">
                    <Button
                      variant={review.mode === "new" ? "default" : "outline"}
                      onClick={() => setReview((prev) => ({ ...prev, mode: "new", promoteToAuthoritative: true }))}
                    >
                      New Identity
                    </Button>
                    <Button
                      variant={review.mode === "existing" ? "default" : "outline"}
                      onClick={() => setReview((prev) => ({ ...prev, mode: "existing", promoteToAuthoritative: false }))}
                    >
                      Assign Existing
                    </Button>
                  </div>

                  {review.mode === "new" ? (
                    <div className="space-y-2">
                      <label className="text-sm text-zinc-300">New identity name</label>
                      <Input
                        value={review.newIdentityName}
                        onChange={(e) =>
                          setReview((prev) => ({ ...prev, newIdentityName: e.target.value }))
                        }
                        placeholder="Enter identity name"
                      />
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <label className="text-sm text-zinc-300">Select existing identity</label>
                      <select
                        className="w-full bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2 text-sm"
                        value={review.existingDetectedId}
                        onChange={(e) =>
                          setReview((prev) => ({ ...prev, existingDetectedId: e.target.value }))
                        }
                      >
                        <option value="">Choose identity</option>
                        {identities.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.id} — {p.name || "Unnamed"}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="flex items-center gap-3 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2">
                    <input
                      id="promoteToAuthoritative"
                      type="checkbox"
                      checked={review.promoteToAuthoritative}
                      onChange={(e) =>
                        setReview((prev) => ({
                          ...prev,
                          promoteToAuthoritative: e.target.checked,
                        }))
                      }
                      className="h-4 w-4"
                    />
                    <label htmlFor="promoteToAuthoritative" className="text-sm text-zinc-300">
                      Promote to authoritative
                    </label>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm text-zinc-300">Notes</label>
                    <textarea
                      className="w-full min-h-[110px] bg-zinc-900 border border-zinc-700 rounded-md px-3 py-2 text-sm"
                      value={review.notes}
                      onChange={(e) =>
                        setReview((prev) => ({ ...prev, notes: e.target.value }))
                      }
                      placeholder="Optional review notes"
                    />
                  </div>

                  <div className="text-xs text-zinc-400">
                    Entry Log ID: {review.item.entry_log_id} · Camera: {review.item.camera_id ?? "—"} · Model: {review.item.embedding_model || "—"} · Quality: {fmtScore(review.item.quality_score)} · Best: {fmtScore(review.item.best_similarity)} · Margin: {fmtScore(review.item.margin)}
                  </div>

                  <div className="flex justify-end">
                    <Button
                      onClick={submitUnknownReview}
                      disabled={review.submitting}
                    >
                      {review.submitting ? "Submitting..." : "Submit Review"}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
