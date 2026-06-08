import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { vadApi, VadReasoningListItem, VadReasoningSummary } from "@/services/vad_api";
import { useToast } from "@/components/ui/use-toast";
import { Network, ShieldAlert } from "lucide-react";

import { ReasoningSummaryCards } from "@/components/vad/reasoning/ReasoningSummaryCards";
import { ReasoningFilters, ReasoningFilterState } from "@/components/vad/reasoning/ReasoningFilters";
import { ReasoningJobTable } from "@/components/vad/reasoning/ReasoningJobTable";
import { ReasoningDetailPanel } from "@/components/vad/reasoning/ReasoningDetailPanel";

export default function VadReasoning() {
  const { toast } = useToast();
  
  const [items, setItems] = useState<VadReasoningListItem[]>([]);
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
      
      let fetchedItems = res.items || [];
      
      if (filters.gate && filters.gate !== 'all') {
        fetchedItems = fetchedItems.filter(i => {
          const gateName = i.job?.metadata_json?.source_gate_name ?? i.case?.primary_gate_name ?? "deep";
          return gateName === filters.gate;
        });
      }
      
      if (filters.severity && filters.severity !== 'all') {
        fetchedItems = fetchedItems.filter(i => {
          const sev = i.result?.python_final_result_json?.final_severity || i.result?.alert_severity || 'LOW';
          return sev.toUpperCase() === filters.severity.toUpperCase();
        });
      }

      if (filters.sessionId) {
        fetchedItems = fetchedItems.filter(i => {
          const sid = String(i.case?.session_id || "");
          return sid.includes(filters.sessionId);
        });
      }

      if (filters.trackId) {
        fetchedItems = fetchedItems.filter(i => {
          const tid = String(i.case?.track_id || "");
          return tid.includes(filters.trackId);
        });
      }

      if (filters.evidenceOnly) {
        fetchedItems = fetchedItems.filter(i => {
          const evidenceKeys = i.job?.input_bundle_json?.visual_evidence?.object_keys || 
                               i.case?.evidence_bundle_json?.object_keys || 
                               (Array.isArray(i.case?.evidence_bundle_json) ? i.case?.evidence_bundle_json.map((e: any) => e.object_key) : []);
          return evidenceKeys && evidenceKeys.length > 0;
        });
      }
      
      setItems(fetchedItems);
      setSummary(res.summary);
      
      // Select latest succeeded job if available, otherwise latest job
      if (!selectedJobId && fetchedItems.length > 0) {
        const succeeded = fetchedItems.find(i => i.job.status === 'succeeded' || i.job.status === 'completed');
        setSelectedJobId(succeeded ? succeeded.job.id : fetchedItems[0].job.id);
      }
    } catch (err: any) {
      setApiError(err.message || "Failed to load reasoning jobs.");
      console.error("Reasoning fetch error:", err);
      if (!silent) {
        toast({ title: "Fetch Error", description: err.message, variant: "destructive" });
      }
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [filters, selectedJobId, toast]);

  useEffect(() => {
    fetchData();
  }, [filters.status, filters.decision, filters.gate]); // intentionally not including caseId to allow typing without fetching per keystroke

  // Auto-refresh every 30 seconds if there are active jobs
  useEffect(() => {
    const hasActiveJobs = items.some(i => i.job.status === 'queued' || i.job.status === 'running');
    if (!hasActiveJobs) return;

    const timer = setInterval(() => {
      fetchData(true);
    }, 30000);

    return () => clearInterval(timer);
  }, [items, fetchData]);

  const handleRefresh = () => {
    fetchData();
  };

  const selectedItem = items.find(i => i.job.id === selectedJobId) || null;

  return (
    <DashboardLayout>
      <div className="h-[calc(100vh-120px)] overflow-hidden flex flex-col w-full max-w-[1800px] mx-auto animate-in fade-in duration-500">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-2 border-b border-border pb-2 mb-2 shrink-0">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-gradient-to-br from-indigo-500/20 to-indigo-500/5 rounded-lg border border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.15)]">
              <Network className="h-5 w-5 text-indigo-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white font-['Space_Grotesk'] flex items-center gap-2">
                VAD Reasoning
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">Multi-gate visual reasoning, LLM policy review, and Python final guardrails.</p>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <Badge label="Indoor Lab" />
            <Badge label="P2C Pipeline" />
            <Badge label="Live Monitoring" icon={<span className="relative flex h-2 w-2 mr-1.5"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span>} />
          </div>
        </div>

        <div className="shrink-0">
          {summary && <ReasoningSummaryCards summary={summary} />}
        </div>
        
        <div className="shrink-0 mb-3">
          <ReasoningFilters 
            filters={filters} 
            setFilters={setFilters} 
            onRefresh={handleRefresh} 
            isLoading={isLoading} 
          />
        </div>

        <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-12 gap-6 overflow-hidden">
          
          {/* Left Pane: Job List */}
          <div className="xl:col-span-6 h-full min-h-0 flex flex-col">
            <div className="bg-zinc-950/50 rounded-xl border border-zinc-800 p-4 h-full flex flex-col shadow-xl overflow-hidden">
              <div className="flex items-center justify-between mb-4 border-b border-zinc-800 pb-3">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Reasoning Jobs</h2>
                <span className="text-xs text-slate-500 font-mono">{items.length} items</span>
              </div>
              
              {apiError ? (
                <div className="flex flex-col items-center justify-center p-6 bg-red-950/30 rounded-xl border border-red-900/50 text-center">
                  <ShieldAlert className="h-8 w-8 text-red-500 mb-2" />
                  <p className="text-red-400 font-medium text-sm">Error Loading Data</p>
                  <p className="text-red-500/70 text-xs mt-1">{apiError}</p>
                </div>
              ) : (
                <ReasoningJobTable 
                  items={items} 
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

function Badge({ label, icon }: { label: string, icon?: React.ReactNode }) {
  return (
    <div className="px-2.5 py-1 bg-zinc-900 border border-zinc-800 rounded-full text-[10px] uppercase tracking-widest text-slate-400 font-semibold flex items-center">
      {icon}
      {label}
    </div>
  );
}
