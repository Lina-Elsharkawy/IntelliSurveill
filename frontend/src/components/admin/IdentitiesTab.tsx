import { useState, useMemo, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { PaginationBar, SmallActionButton, copyText } from "./SharedAdminUI";

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
                        ID: {p.id} · Embeddings: {p.embeddings_count ?? "—"} · Authoritative:{" "}
                        {p.authoritative_count ?? "—"}
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
    </div>
  );
}
