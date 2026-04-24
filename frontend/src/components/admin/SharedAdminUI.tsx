import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const isS3Ref = (value: any): boolean =>
  typeof value === "string" && value.startsWith("s3://");

export const copyText = async (label: string, value: string | number | null | undefined) => {
  if (value === null || value === undefined || value === "") return;
  try {
    await navigator.clipboard.writeText(String(value));
  } catch (err) {
    console.error(`Failed to copy ${label}:`, err);
  }
};

export const fmtScore = (value: any) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : "—";
};

export const getKnownUnknownBadge = (item: any) => {
  const isKnown = !!item?.detected_id || !!item?.identity_name;
  const label = isKnown ? "Known" : "Unknown";
  const className = isKnown
    ? "bg-emerald-600 hover:bg-emerald-600 text-white"
    : "bg-amber-600 hover:bg-amber-600 text-white";
  return <Badge className={className}>{label}</Badge>;
};

export const getAuthorizedBadge = (authorized: boolean | null | undefined) => {
  if (authorized === true) {
    return <Badge className="bg-emerald-600 hover:bg-emerald-600 text-white">Authorized</Badge>;
  }
  if (authorized === false) {
    return <Badge className="bg-red-600 hover:bg-red-600 text-white">Denied</Badge>;
  }
  return <Badge className="bg-zinc-600 hover:bg-zinc-600 text-white">Pending</Badge>;
};

export const getImageStateBadge = (key: string, hasS3: boolean, hasBlob: boolean, imageErrors: Record<string, string>) => {
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

export const PaginationBar = ({
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

export const SmallActionButton = ({
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
