import { useState, useMemo, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  PaginationBar,
  SmallActionButton,
  copyText,
  TabLoadingState,
  TabEmptyState,
} from "./SharedAdminUI";

const PAGE_SIZE = 8;

export function IdentitiesTab({
  identities,
  loading,
}: {
  identities: any[];
  loading: boolean;
}) {
  const [identitySearch, setIdentitySearch] = useState("");
  const [identityPage, setIdentityPage] = useState(1);

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

  const paginate = <T,>(items: T[], page: number) => {
    const start = (page - 1) * PAGE_SIZE;
    return items.slice(start, start + PAGE_SIZE);
  };
  const totalPages = (count: number) => Math.max(1, Math.ceil(count / PAGE_SIZE));

  const pagedIdentities = useMemo(
    () => paginate(filteredIdentities, identityPage),
    [filteredIdentities, identityPage]
  );

  useEffect(() => setIdentityPage(1), [identitySearch]);

  return (
    <div className="space-y-4 pt-4">
      <Input
        placeholder="Search identities by id, name, or info…"
        value={identitySearch}
        onChange={(e) => setIdentitySearch(e.target.value)}
        className="bg-zinc-950/60 border-zinc-800 focus:border-emerald-500/50 focus:ring-emerald-500/20 placeholder:text-zinc-600 transition-colors"
      />

      {loading ? (
        <TabLoadingState label="Loading identities…" />
      ) : filteredIdentities.length === 0 ? (
        <TabEmptyState
          icon="🪪"
          title={identitySearch ? "No identities match your search" : "No identities registered yet"}
          hint={identitySearch ? "Try a different name or ID" : undefined}
        />
      ) : (
        <>
          <Card className="bg-zinc-950/40 border-zinc-800 shadow-xl overflow-hidden">
            <CardContent className="p-0">
              <div className="divide-y divide-zinc-800/50">
                {pagedIdentities.map((p) => (
                  <div
                    key={p.id}
                    className="px-4 py-3 flex justify-between items-center gap-4 hover:bg-zinc-900/50 transition-colors group"
                  >
                    {/* Left: identity info */}
                    <div className="min-w-0 flex items-center gap-3">
                      {/* Avatar circle */}
                      <div className="w-9 h-9 rounded-full bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold text-sm shrink-0">
                        {(p.name || "?")[0].toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <div className="font-semibold text-zinc-100 leading-tight truncate">
                          {p.name || "Unnamed"}
                        </div>
                        <div className="text-xs text-zinc-500 mt-0.5">
                          ID: {p.id}
                          {p.embeddings_count != null && (
                            <> · <span className="text-zinc-400">{p.embeddings_count} embeddings</span></>
                          )}
                          {p.authoritative_count != null && (
                            <> · {p.authoritative_count} authoritative</>
                          )}
                        </div>
                        {p.additional_info && (
                          <div className="text-xs text-zinc-600 mt-0.5 truncate">{p.additional_info}</div>
                        )}
                      </div>
                    </div>

                    {/* Right: badge + action */}
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge
                        variant="outline"
                        className={
                          p.embeddings_count > 0
                            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-xs"
                            : "bg-zinc-800/50 text-zinc-500 border-zinc-700 text-xs"
                        }
                      >
                        {p.embeddings_count > 0 ? "Active" : "No Embeddings"}
                      </Badge>
                      <SmallActionButton
                        label="Copy ID"
                        onClick={() => copyText("identity id", p.id)}
                      />
                    </div>
                  </div>
                ))}
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
    </div>
  );
}
