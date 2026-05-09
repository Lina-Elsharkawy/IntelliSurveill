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
    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20 shadow-[0_0_8px_rgba(16,185,129,0.1)]"
    : "bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20 shadow-[0_0_8px_rgba(251,191,36,0.1)]";
  return <Badge variant="outline" className={className}>{label}</Badge>;
};

export const getAuthorizedBadge = (authorized: boolean | null | undefined) => {
  if (authorized === true) {
    return <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20">Authorized</Badge>;
  }
  if (authorized === false) {
    return <Badge variant="outline" className="bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20">Denied</Badge>;
  }
  return <Badge variant="outline" className="bg-zinc-500/10 text-zinc-400 border-zinc-500/30 hover:bg-zinc-500/20">Pending</Badge>;
};

export const getImageStateBadge = (key: string, hasS3: boolean, hasBlob: boolean, imageErrors: Record<string, string>) => {
  if (hasBlob) {
    return <Badge variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/20">Image OK</Badge>;
  }
  if (!hasS3) {
    return null; // Don't clutter the UI if there's simply no image reference
  }
  if (imageErrors[key]) {
    return <Badge variant="outline" className="bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20">Image Error</Badge>;
  }
  return <Badge variant="outline" className="bg-sky-500/10 text-sky-400 border-sky-500/30 hover:bg-sky-500/20 animate-pulse">Loading…</Badge>;
};

/** Shared loading skeleton placeholder for all tabs. */
export const TabLoadingState = ({ label = "Loading data" }: { label?: string }) => (
  <div className="flex flex-col items-center justify-center gap-3 py-16 text-zinc-500">
    <div className="flex gap-1.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-emerald-500/50 animate-bounce"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
    <p className="text-sm text-zinc-500 tracking-wide">{label}</p>
  </div>
);

/** Shared empty-state placeholder for all tabs. */
export const TabEmptyState = ({ icon, title, hint }: { icon: React.ReactNode; title: string; hint?: string }) => (
  <div className="flex flex-col items-center justify-center gap-3 py-16 border-2 border-dashed border-zinc-800 rounded-2xl text-zinc-500 bg-zinc-950/30">
    <div className="text-4xl opacity-30">{icon}</div>
    <p className="text-sm font-medium text-zinc-400">{title}</p>
    {hint && <p className="text-xs text-zinc-600">{hint}</p>}
  </div>
);

export const PaginationBar = ({
  page,
  setPage,
  total,
}: {
  page: number;
  setPage: (v: number) => void;
  total: number;
}) => (
  <div className="flex items-center justify-between pt-3 border-t border-zinc-800/50 mt-2">
    <div className="text-xs text-zinc-500 font-mono">
      Page <span className="text-zinc-300">{page}</span> / {total}
    </div>
    <div className="flex gap-2">
      <Button
        size="sm"
        variant="outline"
        disabled={page <= 1}
        onClick={() => setPage(page - 1)}
        className="border-zinc-800 hover:border-emerald-500/40 hover:text-emerald-400 hover:bg-emerald-500/10 transition-all duration-200 text-xs"
      >
        ← Prev
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={page >= total}
        onClick={() => setPage(page + 1)}
        className="border-zinc-800 hover:border-emerald-500/40 hover:text-emerald-400 hover:bg-emerald-500/10 transition-all duration-200 text-xs"
      >
        Next →
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
    className="text-xs font-medium text-zinc-400 hover:text-emerald-400 border border-zinc-800 hover:border-emerald-500/50 hover:bg-emerald-500/10 transition-all duration-200 rounded-md px-2.5 py-1.5"
  >
    {label}
  </button>
);
