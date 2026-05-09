import { useState, useMemo, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PaginationBar,
  SmallActionButton,
  copyText,
  isS3Ref,
  fmtScore,
  getKnownUnknownBadge,
  getImageStateBadge,
  TabLoadingState,
  TabEmptyState,
} from "./SharedAdminUI";

const PAGE_SIZE = 8;

const getEntryLogIdentityKey = (l: any): string | null => {
  if (!l) return null;
  const name = l.identity_name || l.personName || l.name || l.identityName;
  if (name) return name;
  const id = l.detected_id || l.identityId || l.personId || l.identity_id;
  if (id) return `ID: ${id}`;
  return null;
};

export function EntryLogsTab({
  logs,
  loading,
  openPreview,
  openDrawer,
  imageState,
}: {
  logs: any[];
  loading: boolean;
  openPreview: (src: string, title: string) => void;
  openDrawer: (kind: "log" | "unknown", item: any) => void;
  imageState: {
    imageUrls: Record<string, string>;
    imageErrors: Record<string, string>;
    fetchImage: (key: string, endpoint: string) => Promise<string | null>;
    imageUrlsRef: React.MutableRefObject<Record<string, string>>;
  };
}) {
  const [logsSearch, setLogsSearch] = useState("");
  const [logsFilter, setLogsFilter] = useState<"all" | "known" | "unknown">("all");
  const [identityFilter, setIdentityFilter] = useState<string | "all">("all");
  const [logsPage, setLogsPage] = useState(1);

  const availableIdentities = useMemo(() => {
    const ids = new Set<string>();
    logs.forEach((l) => {
      const key = getEntryLogIdentityKey(l);
      if (key) ids.add(key);
    });
    return Array.from(ids).sort();
  }, [logs]);

  const { imageUrls: logImageUrls, imageErrors, fetchImage, imageUrlsRef: logImageUrlsRef } = imageState;

  const fetchLogImage = async (logId: number) => {
    return await fetchImage(`log-${logId}`, `/api/admin/entry-logs/${logId}/image`);
  };

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
      }

      let matchesIdentity = true;
      if (identityFilter !== "all") {
        matchesIdentity = getEntryLogIdentityKey(l) === identityFilter;
      }

      return matchesSearch && matchesFilter && matchesIdentity;
    });
  }, [logs, logsSearch, logsFilter, identityFilter]);

  const paginate = <T,>(items: T[], page: number) => {
    const start = (page - 1) * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  };
  const totalPages = (count: number) => Math.max(1, Math.ceil(count / PAGE_SIZE));

  const pagedLogs = useMemo(
    () => paginate(filteredLogs, logsPage),
    [filteredLogs, logsPage]
  );

  useEffect(() => setLogsPage(1), [logsSearch, logsFilter, identityFilter]);

  return (
    <div className="space-y-4 pt-4">
      <div className="flex flex-col md:flex-row gap-3">
        <Input
          placeholder="Search by id, name, camera, event type…"
          value={logsSearch}
          onChange={(e) => setLogsSearch(e.target.value)}
          className="flex-1 bg-zinc-950/60 border-zinc-800 focus:border-emerald-500/50 placeholder:text-zinc-600 transition-colors"
        />
        <div className="flex gap-2 flex-wrap items-center">
          <Select value={identityFilter} onValueChange={setIdentityFilter}>
            <SelectTrigger className="w-[180px] bg-zinc-950/60 border-zinc-800 hover:border-emerald-500/40 focus:border-emerald-500/50 transition-colors text-sm">
              <SelectValue placeholder="All Identities" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-950 border-zinc-800">
              <SelectItem value="all">All Identities</SelectItem>
              {availableIdentities.map(id => (
                <SelectItem key={id} value={id}>{id}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {(["all", "known", "unknown"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setLogsFilter(f)}
              className={`text-xs font-medium px-3 py-1.5 rounded-md border transition-all duration-200 ${
                logsFilter === f
                  ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/40 shadow-[0_0_8px_rgba(16,185,129,0.12)]"
                  : "text-zinc-400 border-zinc-800 hover:border-emerald-500/30 hover:text-emerald-400 hover:bg-emerald-500/10"
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <TabLoadingState label="Loading entry logs…" />
      ) : pagedLogs.length === 0 ? (
        <TabEmptyState
          icon="📋"
          title={logsSearch || logsFilter !== "all" || identityFilter !== "all" ? "No logs match your filters" : "No entry logs recorded yet"}
          hint={logsSearch ? "Try a different search term or clear your filters" : undefined}
        />
      ) : (
        <>
          {pagedLogs.map((l) => (
            <Card key={l.id} className="hover:-translate-y-0.5 hover:shadow-md hover:shadow-emerald-900/10 hover:border-emerald-500/20 transition-all duration-300 bg-zinc-950/40 border-zinc-800">
              <CardContent className="p-4">
                <div className="flex justify-between items-start gap-4">
                  {/* Thumbnail */}
                  <button
                    type="button"
                    className="w-16 h-16 rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800 shrink-0 cursor-pointer hover:border-emerald-500/30 hover:shadow-md transition-all duration-200"
                    onClick={async () => {
                      if (!isS3Ref(l?.image_video_ref)) return;
                      const src = logImageUrlsRef.current[`log-${l.id}`] || (await fetchLogImage(l.id));
                      if (src) openPreview(src, `Entry Log ${l.id}`);
                    }}
                  >
                    {logImageUrls[`log-${l.id}`] ? (
                      <img
                        src={logImageUrls[`log-${l.id}`]}
                        alt={`Entry log ${l.id}`}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-[10px] text-zinc-600 text-center px-1">
                        {isS3Ref(l.image_video_ref) ? "📷" : "—"}
                      </div>
                    )}
                  </button>

                  {/* Main info */}
                  <div className="flex-1 min-w-0">
                    {/* Row 1: Name + status badges */}
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="font-semibold text-zinc-100 text-sm leading-tight">
                        {l.identity_name
                          ? l.identity_name
                          : l.detected_id
                          ? `Detected ID: ${l.detected_id}`
                          : l.unknown_face_event_id
                          ? `Unknown Face #${l.unknown_face_event_id}`
                          : "Unknown"}
                      </span>
                      {getKnownUnknownBadge(l)}
                      {getImageStateBadge(`log-${l.id}`, isS3Ref(l.image_video_ref), !!logImageUrls[`log-${l.id}`], imageErrors)}
                    </div>

                    {/* Row 2: location + camera */}
                    <div className="text-xs text-zinc-500 mb-1">
                      <span>{l.location || "No location"}</span>
                      {l.camera_id != null && <> · <span>Cam {l.camera_id}</span></>}
                    </div>

                    {/* Row 3: telemetry */}
                    <div className="text-[11px] text-zinc-600 leading-relaxed">
                      {l.event_type && <span>Type: {l.event_type}</span>}
                      {l.device_status && <> · Device: {l.device_status}</>}
                      {l.model_version && <> · Model: {l.model_version}</>}
                    </div>
                    <div className="text-[11px] text-zinc-600">
                      Quality: {fmtScore(l.quality_score)} · Best: {fmtScore(l.best_similarity)} · Margin: {fmtScore(l.margin)}
                    </div>

                    {imageErrors[`log-${l.id}`] && (
                      <div className="text-xs text-red-400/80 mt-1">⚠ {imageErrors[`log-${l.id}`]}</div>
                    )}
                  </div>

                  {/* Right: timestamp + actions */}
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <span className="text-[11px] text-zinc-500 font-mono">
                      {l.timestamp ? new Date(l.timestamp).toLocaleString() : "—"}
                    </span>
                    <div className="flex gap-1.5 flex-wrap justify-end">
                      <SmallActionButton label="Details" onClick={() => openDrawer("log", l)} />
                      <SmallActionButton label="Copy ID" onClick={() => copyText("log id", l.id)} />
                      <SmallActionButton label="Copy Ref" onClick={() => copyText("image ref", l.image_video_ref)} />
                    </div>
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
    </div>
  );
}
