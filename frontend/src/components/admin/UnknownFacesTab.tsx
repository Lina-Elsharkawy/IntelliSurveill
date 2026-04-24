import { useState, useMemo, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { apiPost } from "@/lib/api";
import {
  PaginationBar,
  SmallActionButton,
  copyText,
  isS3Ref,
  fmtScore,
  getImageStateBadge,
} from "./SharedAdminUI";

const PAGE_SIZE = 8;

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

export function UnknownFacesTab({
  unknowns,
  identities,
  loading,
  openPreview,
  openDrawer,
  imageState,
  onReviewSubmitted,
}: {
  unknowns: any[];
  identities: any[];
  loading: boolean;
  openPreview: (src: string, title: string) => void;
  openDrawer: (kind: "log" | "unknown", item: any) => void;
  imageState: {
    imageUrls: Record<string, string>;
    imageErrors: Record<string, string>;
    fetchImage: (key: string, endpoint: string) => Promise<string | null>;
    imageUrlsRef: React.MutableRefObject<Record<string, string>>;
  };
  onReviewSubmitted: () => void;
}) {
  const [unknownSearch, setUnknownSearch] = useState("");
  const [unknownFilter, setUnknownFilter] = useState<"all" | "hasImage" | "camera1" | "cameraOther">("all");
  const [unknownPage, setUnknownPage] = useState(1);

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

  const { imageUrls: unknownImageUrls, imageErrors, fetchImage, imageUrlsRef: unknownImageUrlsRef } = imageState;

  const fetchUnknownImage = async (unknownId: number, entryLogId: number) => {
    return await fetchImage(`unknown-${unknownId}`, `/api/admin/entry-logs/${entryLogId}/thumbnail`);
  };

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

  const paginate = <T,>(items: T[], page: number) => {
    const start = (page - 1) * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  };
  const totalPages = (count: number) => Math.max(1, Math.ceil(count / PAGE_SIZE));

  const pagedUnknowns = useMemo(
    () => paginate(filteredUnknowns, unknownPage),
    [filteredUnknowns, unknownPage]
  );

  useEffect(() => setUnknownPage(1), [unknownSearch, unknownFilter]);

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

  const openUnknownReview = async (item: any, mode: UnknownReviewMode) => {
    if (
      item?.entry_log_id &&
      isS3Ref(item?.image_video_ref) &&
      !unknownImageUrlsRef.current[`unknown-${item.id}`] &&
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
      onReviewSubmitted();
    } catch (e) {
      console.error("Error submitting unknown review:", e);
      alert("Failed to submit review. Check the console for details.");
      setReview((prev) => ({ ...prev, submitting: false }));
    }
  };

  return (
    <div className="space-y-4 pt-4">
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
                        !unknownImageUrlsRef.current[`unknown-${u.id}`] &&
                        u?.entry_log_id &&
                        isS3Ref(u?.image_video_ref) &&
                        !imageErrors[`unknown-${u.id}`]
                      ) {
                        await fetchUnknownImage(u.id, u.entry_log_id);
                      }

                      const src = unknownImageUrlsRef.current[`unknown-${u.id}`];
                      if (src) {
                        openPreview(src, `Unknown Face #${u.id}`);
                      }
                    }}
                  >
                    {unknownImageUrls[`unknown-${u.id}`] ? (
                      <img
                        src={unknownImageUrls[`unknown-${u.id}`]}
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
                        !!unknownImageUrls[`unknown-${u.id}`],
                        imageErrors
                      )}
                    </div>

                    <div className="text-xs text-gray-500 mt-1">
                      Entry Log ID: {u.entry_log_id} · Status: {u.status || "pending"} · Created:{" "}
                      {u.created_at ? new Date(u.created_at).toLocaleString() : "—"}
                    </div>

                    <div className="text-xs text-gray-400 mt-1">
                      Model: {u.embedding_model || "—"} · Camera: {u.camera_id ?? "—"} · Type:{" "}
                      {u.event_type || "—"}
                    </div>
                    <div className="text-xs text-gray-400">
                      Quality: {fmtScore(u.quality_score)} · Best: {fmtScore(u.best_similarity)} · Second:{" "}
                      {fmtScore(u.second_similarity)} · Margin: {fmtScore(u.margin)}
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
                {unknownImageUrls[`unknown-${review.item.id}`] ? (
                  <img
                    src={unknownImageUrls[`unknown-${review.item.id}`]}
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
                  Entry Log ID: {review.item.entry_log_id} · Camera: {review.item.camera_id ?? "—"} · Model:{" "}
                  {review.item.embedding_model || "—"} · Quality: {fmtScore(review.item.quality_score)} · Best:{" "}
                  {fmtScore(review.item.best_similarity)} · Margin: {fmtScore(review.item.margin)}
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
  );
}
