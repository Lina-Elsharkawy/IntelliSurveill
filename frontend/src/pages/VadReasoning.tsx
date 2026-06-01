import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { vadApi, VadReasoningListItem, VadReasoningSummary } from "@/services/vad_api";
import { useToast } from "@/components/ui/use-toast";
import { Network, ShieldAlert } from "lucide-react";

import { ReasoningSummaryCards } from "@/components/vad/reasoning/ReasoningSummaryCards";
import { ReasoningFilters, ReasoningFilterState } from "@/components/vad/reasoning/ReasoningFilters";
import { ReasoningJobList } from "@/components/vad/reasoning/ReasoningJobList";
import { ReasoningDetailPanel } from "@/components/vad/reasoning/ReasoningDetailPanel";

export default function VadReasoning() {
  const { toast } = useToast();
  
  const [items, setItems] = useState<VadReasoningListItem[]>([]);
  const [rawItems, setRawItems] = useState<any[]>([]); // Added for debug
  const [summary, setSummary] = useState<VadReasoningSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  
  const [filters, setFilters] = useState<ReasoningFilterState>({
    status: 'all',
    decision: 'all',
    caseId: '',
    onlyDeep: true,
    onlyFailed: false
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
      console.log("Reasoning API response:", res);
      setRawItems(fetchedItems); // Store raw before filters
      
      if (filters.onlyDeep) {
        fetchedItems = fetchedItems.filter(i => {
          const gateName = i.case?.primary_gate_name;
          if (gateName && gateName !== 'deep') return false;
          return true;
        });
      }
      
      console.log("Reasoning items after filters:", fetchedItems);
      
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
  }, [filters.status, filters.decision, filters.onlyDeep]); // intentionally not including caseId to allow typing without fetching per keystroke

  const handleRefresh = () => {
    fetchData();
  };

  const selectedItem = items.find(i => i.job.id === selectedJobId) || null;

  return (
    <DashboardLayout>
      <div className="flex flex-col h-full w-full max-w-[1800px] mx-auto animate-in fade-in duration-500">
        
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-border pb-6 mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-gradient-to-br from-indigo-500/20 to-indigo-500/5 rounded-xl border border-indigo-500/30 shadow-[0_0_15px_rgba(99,102,241,0.15)]">
              <Network className="h-7 w-7 text-indigo-400" />
            </div>
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-white font-['Space_Grotesk'] flex items-center gap-2">
                VAD Reasoning
              </h1>
              <p className="text-sm text-slate-400 mt-1">Deep-gate visual reasoning, LLM policy review, and Python final guardrails.</p>
            </div>
          </div>
          
          <div className="flex items-center gap-2">
            <Badge label="Deep-only reasoning" />
            <Badge label="VLM → LLM → Python" />
            <Badge label="Ollama local" icon={<ShieldAlert size={12} className="mr-1 inline" />} />
          </div>
        </div>

        {summary && <ReasoningSummaryCards summary={summary} />}
        
        <ReasoningFilters 
          filters={filters} 
          setFilters={setFilters} 
          onRefresh={handleRefresh} 
          isLoading={isLoading} 
        />

        <details className="mb-6 group">
          <summary className="text-xs text-slate-500 hover:text-slate-300 cursor-pointer select-none pl-2 flex items-center gap-2 w-max">
            Developer Debug
          </summary>
          <div className="bg-blue-950/30 border border-blue-500/50 rounded-xl p-4 mt-2 font-mono text-[10px] text-blue-200">
            <h3 className="text-xs font-bold text-blue-400 mb-2 uppercase">Developer Debug Panel</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p><strong>API URL:</strong> /vad/rtsp/reasoning/jobs</p>
                <p><strong>Loading State:</strong> {isLoading ? 'true' : 'false'}</p>
                <p><strong>Error State:</strong> {apiError || 'null'}</p>
                <p><strong>Raw Item Count (before filters):</strong> {rawItems.length}</p>
                <p><strong>Filtered Item Count:</strong> {items.length}</p>
              </div>
              <div className="bg-black/50 p-2 rounded max-h-[150px] overflow-y-auto">
                <p className="font-bold mb-1">First Raw Item Preview:</p>
                <pre className="text-[9px] opacity-70">
                  {rawItems.length > 0 ? JSON.stringify(rawItems[0], null, 2) : 'No items'}
                </pre>
              </div>
            </div>
          </div>
        </details>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 flex-1 h-full min-h-0">
          
          {/* Left Pane: Job List */}
          <div className="xl:col-span-4 flex flex-col h-full">
            <div className="bg-zinc-950/50 rounded-xl border border-zinc-800 p-4 h-full flex flex-col shadow-xl">
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
                <ReasoningJobList 
                  items={items} 
                  selectedId={selectedJobId} 
                  onSelect={(item) => setSelectedJobId(item.job.id)} 
                />
              )}
            </div>
          </div>

          {/* Right Pane: Detail Panel */}
          <div className="xl:col-span-8 flex flex-col h-full">
            <div className="bg-zinc-950/80 rounded-xl border border-zinc-800 p-4 lg:p-6 h-full shadow-2xl backdrop-blur-sm">
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
