import { useState, useEffect, useCallback, useMemo } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { vadApi, VadReasoningListItem, VadReasoningSummary } from "@/services/vad_api";
import { useToast } from "@/components/ui/use-toast";
import { Network, ShieldAlert, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

import { ReasoningSummaryCards } from "@/components/vad/reasoning/ReasoningSummaryCards";
import { ReasoningFilters, ReasoningFilterState } from "@/components/vad/reasoning/ReasoningFilters";
import { ReasoningJobTable } from "@/components/vad/reasoning/ReasoningJobTable";
import { ReasoningDetailPanel } from "@/components/vad/reasoning/ReasoningDetailPanel";

export default function VadReasoning() {
  const { toast } = useToast();
  
  const [rawItems, setRawItems] = useState<VadReasoningListItem[]>([]);
  const [summary, setSummary] = useState<VadReasoningSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  
  const [filters, setFilters] = useState<ReasoningFilterState>({
    status: 'all',
    decision: 'all',
    severity: 'all',
    caseId: '',
    gate: 'all',
    sessionId: '',
    trackId: '',
    evidenceOnly: false,
  });

  const fetchData = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    setApiError(null);
    try {
      const res = await vadApi.getReasoningJobs({
        status: filters.status,
        decision: filters.decision,
        case_id: filters.caseId ? parseInt(filters.caseId) : undefined,
        limit: 100
      });
      
      setRawItems(res.items || []);
      setSummary(res.summary);
    } catch (err: any) {
      setApiError(err.message || "Failed to load reasoning jobs.");
      console.error("Reasoning fetch error:", err);
      if (!silent) {
        toast({ title: "Fetch Error", description: err.message, variant: "destructive" });
      }
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [filters.status, filters.decision, filters.caseId, toast]);

  useEffect(() => {
    fetchData();
  }, [filters.status, filters.decision]); // keep caseId manual-refresh friendly; local filters still update immediately

  const filteredItems = useMemo(
    () => applyClientFilters(rawItems, filters),
    [rawItems, filters],
  );

  // Auto-refresh every 30 seconds if there are active jobs
  useEffect(() => {
    const hasActiveJobs = filteredItems.some(i => i.job.status === 'queued' || i.job.status === 'running');
    if (!hasActiveJobs) return;

    const timer = setInterval(() => {
      fetchData(true);
    }, 30000);

    return () => clearInterval(timer);
  }, [filteredItems, fetchData]);

  const handleRefresh = () => {
    fetchData();
  };

  useEffect(() => {
    if (filteredItems.length === 0) {
      setSelectedJobId(null);
      return;
    }
    if (selectedJobId && filteredItems.some(i => i.job.id === selectedJobId)) return;
    const succeeded = filteredItems.find(i => i.job.status === 'succeeded' || i.job.status === 'completed');
    setSelectedJobId(succeeded ? succeeded.job.id : filteredItems[0].job.id);
  }, [filteredItems, selectedJobId]);

  const selectedItem = filteredItems.find(i => i.job.id === selectedJobId) || null;

  return (
    <DashboardLayout>
      <div className="anomaly-rules-page page-bg-grid h-[calc(100vh-120px)] overflow-hidden flex flex-col w-full max-w-[1800px] mx-auto animate-in fade-in duration-500 !p-4 !border-none !rounded-none">
        <div className="co tl"></div><div className="co tr"></div>
        <div className="co bl"></div><div className="co br"></div>
        
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-b border-zinc-800/50 pb-2 mb-2 z-10 shrink-0 relative">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-gradient-to-br from-indigo-500/20 to-indigo-500/5 rounded-lg border border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.15)]">
              <Network className="h-5 w-5 text-indigo-400" />
            </div>
            <div>
              <h1 className="welcome-heading !text-3xl !mb-0 flex items-center gap-2">
                VAD <span>Reasoning</span>
              </h1>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <Button 
              variant="outline" 
              size="sm"
              onClick={handleRefresh}
              disabled={isLoading}
              className="h-8 bg-blue-500/10 text-blue-400 border-blue-500/20 hover:bg-blue-500/20 shrink-0"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
          </div>
        </div>

        <div className="shrink-0 relative z-10">
          {summary && <ReasoningSummaryCards summary={summary} />}
        </div>
        


        <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-6 overflow-hidden relative z-10">
          
          {/* Left Pane: Job List */}
          <div className="xl:col-span-6 h-full min-h-0 flex flex-col">
            <div className="bg-zinc-950/50 rounded-xl border border-zinc-800 p-4 h-full flex flex-col shadow-xl overflow-hidden">
              <div className="flex items-center justify-between mb-2 border-b border-zinc-800 pb-2">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Reasoning Jobs</h2>
                <span className="text-xs text-slate-500 font-mono">{filteredItems.length} items</span>
              </div>
              <div className="shrink-0 mb-2">
                <ReasoningFilters 
                  filters={filters} 
                  setFilters={setFilters} 
                />
              </div>
              
              {apiError ? (
                <div className="flex flex-col items-center justify-center p-6 bg-red-950/30 rounded-xl border border-red-900/50 text-center">
                  <ShieldAlert className="h-8 w-8 text-red-500 mb-2" />
                  <p className="text-red-400 font-medium text-sm">Error Loading Data</p>
                  <p className="text-red-500/70 text-xs mt-1">{apiError}</p>
                </div>
              ) : (
                <ReasoningJobTable 
                  items={filteredItems} 
                  selectedId={selectedJobId} 
                  onSelect={(item) => setSelectedJobId(item.job.id)} 
                />
              )}
            </div>
          </div>

          {/* Right Pane: Detail Panel */}
          <div className="xl:col-span-6 h-full min-h-0 flex flex-col">
            <div className="bg-zinc-950/80 rounded-xl border border-zinc-800 p-4 lg:p-6 h-full shadow-2xl backdrop-blur-sm flex flex-col overflow-hidden">
              <ReasoningDetailPanel item={selectedItem} />
            </div>
          </div>

        </div>
      </div>
    </DashboardLayout>
  );
}

// Applies client-side filters to a list of reasoning items after the API fetch.
// Gate, severity, sessionId, trackId, and evidenceOnly are not sent to the API;
// they are applied locally so the API call stays simple and stable.
function applyClientFilters(
  items: VadReasoningListItem[],
  filters: ReasoningFilterState,
): VadReasoningListItem[] {
  let result = items;

  if (filters.gate && filters.gate !== 'all') {
    result = result.filter(i => {
      const gateName = i.job?.metadata_json?.source_gate_name ?? i.case?.primary_gate_name ?? "deep";
      return gateName === filters.gate;
    });
  }

  if (filters.severity && filters.severity !== 'all') {
    result = result.filter(i => {
      const sev = i.result?.python_final_result_json?.final_severity || i.result?.severity || 'LOW';
      return sev.toUpperCase() === filters.severity.toUpperCase();
    });
  }

  if (filters.caseId) {
    result = result.filter(i => {
      const ids = [i.case?.id, i.case?.event_id, i.job?.case_id, i.job?.id]
        .filter(v => v !== undefined && v !== null)
        .map(String);
      return ids.some(id => id.includes(filters.caseId));
    });
  }

  if (filters.sessionId) {
    result = result.filter(i => {
      const sid = String(i.case?.session_id || "");
      return sid.includes(filters.sessionId);
    });
  }

  if (filters.trackId) {
    result = result.filter(i => {
      const tid = String(i.case?.track_id || "");
      return tid.includes(filters.trackId);
    });
  }

  if (filters.evidenceOnly) {
    result = result.filter(i => {
      const evidenceKeys =
        i.job?.input_bundle_json?.visual_evidence?.object_keys ||
        i.case?.evidence_bundle_json?.object_keys ||
        (Array.isArray(i.case?.evidence_bundle_json)
          ? i.case?.evidence_bundle_json.map((e: any) => e.object_key)
          : []);
      return evidenceKeys && evidenceKeys.length > 0;
    });
  }

  return result;
}
