import { useState, useMemo, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  PaginationBar,
  SmallActionButton,
  copyText,
  isS3Ref,
  fmtScore,
  getKnownUnknownBadge,
  getAuthorizedBadge,
  getImageStateBadge,
} from "./SharedAdminUI";

const PAGE_SIZE = 8;

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
  const [logsFilter, setLogsFilter] = useState<"all" | "known" | "unknown" | "hasImage">("all");
  const [logsPage, setLogsPage] = useState(1);

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
      } else if (logsFilter === "hasImage") {
        matchesFilter = isS3Ref(l?.image_video_ref);
      }

      return matchesSearch && matchesFilter;
    });
  }, [logs, logsSearch, logsFilter]);

  const paginate = <T,>(items: T[], page: number) => {
    const start = (page - 1) * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  };
  const totalPages = (count: number) => Math.max(1, Math.ceil(count / PAGE_SIZE));

  const pagedLogs = useMemo(
    () => paginate(filteredLogs, logsPage),
    [filteredLogs, logsPage]
  );

  useEffect(() => setLogsPage(1), [logsSearch, logsFilter]);

  return (
    <div className="space-y-4 pt-4">
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

                      const src = logImageUrlsRef.current[`log-${l.id}`] || (await fetchLogImage(l.id));
                      if (src) {
                        openPreview(src, `Entry Log ${l.id}`);
                      }
                    }}
                  >
                    {logImageUrls[`log-${l.id}`] ? (
                      <img
                        src={logImageUrls[`log-${l.id}`]}
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
                        !!logImageUrls[`log-${l.id}`],
                        imageErrors
                      )}
                    </div>

                    <div className="text-sm text-gray-500 mt-1">
                      {l.location || "No location"} · Camera: {l.camera_id ?? "—"}
                    </div>

                    <div className="text-xs text-gray-400">
                      Type: {l.event_type || "—"} · Device: {l.device_status || "—"} · Model:{" "}
                      {l.model_version || "—"}
                    </div>
                    <div className="text-xs text-gray-400">
                      Quality: {fmtScore(l.quality_score)} · Best: {fmtScore(l.best_similarity)} · Second:{" "}
                      {fmtScore(l.second_similarity)} · Margin: {fmtScore(l.margin)}
                    </div>

                    <div className="text-xs text-gray-400">
                      Processing: {l.processing_time || "—"} · Unknown Event:{" "}
                      {l.unknown_face_event_id ?? "—"}
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
    </div>
  );
}
