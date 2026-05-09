import { useEffect, useState, useCallback } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, ChevronLeft, ChevronRight, Trash2, AlertCircle } from "lucide-react";
import { getAuditLogs, AuditLog, deleteAuditLog, clearAuditLogs } from "@/services/auditLogService";
import { useAuth } from "@/context/AuthContext";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

const PAGE_SIZE = 50;

const ACTION_STYLE: Record<string, string> = {
  CREATE: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  DELETE: "bg-red-500/10 text-red-400 border-red-500/30",
  LOGIN:  "bg-violet-500/10 text-violet-400 border-violet-500/30",
  LOGOUT: "bg-zinc-500/10 text-zinc-400 border-zinc-500/30",
};

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

export default function ActivityLog() {
  const { roles } = useAuth();
  const isAdmin = roles.includes("admin");

  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchLogs = useCallback(async (p = page) => {
    setLoading(true);
    try {
      const { total: t, logs: l } = await getAuditLogs({
        limit: PAGE_SIZE,
        offset: p * PAGE_SIZE,
      });
      setTotal(t);
      setLogs(l);
    } catch (err) {
      console.error("Failed to load audit logs:", err);
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { fetchLogs(0); }, []);
  useEffect(() => { fetchLogs(page); }, [page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const handleDelete = async (id: number) => {
    try {
      setIsDeleting(true);
      await deleteAuditLog(id);
      fetchLogs(page);
    } catch (err) {
      console.error("Failed to delete log:", err);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleClearAll = async () => {
    try {
      setIsDeleting(true);
      await clearAuditLogs();
      setPage(0);
      fetchLogs(0);
    } catch (err) {
      console.error("Failed to clear logs:", err);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="space-y-6">

        {/* Header */}
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs text-emerald-500/50 uppercase tracking-[4px] mb-1">System</p>
            <h1 className="text-3xl font-bold text-white">Activity Log</h1>
            <p className="text-zinc-500 text-sm mt-1">{total.toLocaleString()} recorded actions</p>
          </div>
          <div className="flex items-center gap-3">
            {isAdmin && logs.length > 0 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={loading || isDeleting}
                    className="border-red-900/50 text-red-500 hover:bg-red-500/10 hover:text-red-400"
                  >
                    <Trash2 className="w-4 h-4 mr-2" />
                    Clear All
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent className="bg-zinc-950 border border-zinc-800">
                  <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2 text-white">
                      <AlertCircle className="w-5 h-5 text-red-500" />
                      Clear all audit logs?
                    </AlertDialogTitle>
                    <AlertDialogDescription className="text-zinc-400">
                      This action cannot be undone. This will permanently delete all {total.toLocaleString()} audit logs from the database.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel className="bg-zinc-900 text-white hover:bg-zinc-800 border-zinc-700">Cancel</AlertDialogCancel>
                    <AlertDialogAction
                      onClick={handleClearAll}
                      className="bg-red-600 text-white hover:bg-red-700 focus:ring-red-600"
                    >
                      Yes, clear logs
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchLogs(page)}
              disabled={loading}
              className="border-zinc-700 text-zinc-400 hover:text-white hover:border-emerald-500/40"
            >
              <RefreshCw className={`w-4 h-4 mr-2 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Table */}
        <Card className="border-zinc-800 bg-zinc-950/50">
          <CardContent className="p-0 overflow-x-auto">
            {loading ? (
              <div className="flex justify-center items-center gap-2 py-20 text-zinc-600">
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span className="text-sm">Loading…</span>
              </div>
            ) : logs.length === 0 ? (
              <p className="text-center py-20 text-zinc-600 text-sm">No actions recorded yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-800">
                    <th className="px-6 py-4 text-left text-[11px] font-semibold text-white uppercase tracking-widest w-48">Date</th>
                    <th className="px-6 py-4 text-left text-[11px] font-semibold text-zinc-500 uppercase tracking-widest w-28">Action</th>
                    <th className="px-6 py-4 text-left text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Description</th>
                    <th className="px-6 py-4 text-left text-[11px] font-semibold text-white uppercase tracking-widest">User</th>
                    {isAdmin && (
                      <th className="px-6 py-4 text-right text-[11px] font-semibold text-zinc-500 uppercase tracking-widest w-20">
                        Manage
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log, i) => (
                    <tr
                      key={log.id}
                      className={`border-b border-zinc-900 hover:bg-white/[0.02] transition-colors ${i % 2 === 0 ? "" : "bg-zinc-950/30"}`}
                    >
                      <td className="px-6 py-3.5 text-white font-bold font-mono text-xs whitespace-nowrap">
                        {fmtDate(log.created_at)}
                      </td>
                      <td className="px-6 py-3.5">
                        <span className={`inline-flex items-center text-xs font-semibold px-2.5 py-1 rounded-full border ${ACTION_STYLE[log.action] ?? "bg-zinc-500/10 text-zinc-400 border-zinc-500/30"}`}>
                          {log.action}
                        </span>
                      </td>
                      <td className="px-6 py-3.5 text-zinc-200">
                        {(log.details as any)?.description || `${log.action} ${log.resource || ''}${log.resource_id ? ` #${log.resource_id}` : ''}`}
                      </td>
                      <td className="px-6 py-3.5 text-white text-xs">
                        {log.user_email}
                      </td>
                      {isAdmin && (
                        <td className="px-6 py-3.5 text-right">
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={isDeleting}
                            onClick={() => handleDelete(log.id)}
                            className="h-8 w-8 text-zinc-500 hover:text-red-400 hover:bg-red-500/10"
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-zinc-600">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline" size="sm"
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={page === 0 || loading}
                className="border-zinc-800 text-zinc-400 hover:text-white"
              >
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span className="text-xs text-zinc-500 px-2">{page + 1} / {totalPages}</span>
              <Button
                variant="outline" size="sm"
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1 || loading}
                className="border-zinc-800 text-zinc-400 hover:text-white"
              >
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          </div>
        )}

      </div>
    </DashboardLayout>
  );
}