import { VadReasoningListItem } from "@/services/vad_api";
import { EvidenceViewer } from "./EvidenceViewer";
import { VlmVisualReviewCard } from "./VlmVisualReviewCard";
import { LlmPolicyReviewCard } from "./LlmPolicyReviewCard";
import { PythonFinalGuardrailsCard } from "./PythonFinalGuardrailsCard";
import { FinalDecisionHeroCard } from "./FinalDecisionHeroCard";
import { GateTriggerCard } from "./GateTriggerCard";
import { RawJsonCard } from "./RawJsonCard";
import { Network, ChevronRight, Copy, Activity } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { StatusBadge } from "./ReasoningBadges";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  getGateDisplayName, 
  getGateBadgeVariant, 
  getTrackId, 
  generateAnalysisSummary, 
  getEvidenceKeys,
  getFinalDecision,
  getSeverity,
  getConfidence,
  getScoreRatio
} from "./reasoningUtils";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

export function ReasoningDetailPanel({ item }: { item: VadReasoningListItem | null }) {
  const { toast } = useToast();

  if (!item) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-12 bg-zinc-950/30 rounded-xl border border-zinc-800 border-dashed">
        <div className="p-4 bg-zinc-900 rounded-full mb-4">
          <Network className="h-10 w-10 text-slate-500" />
        </div>
        <h2 className="text-lg font-semibold text-slate-300 mb-2 font-['Space_Grotesk']">No Reasoning Job Selected</h2>
        <p className="text-slate-500 text-sm text-center max-w-sm">
          Select a reasoning job from the list on the left to view its visual review, policy reasoning, and guardrail decisions.
        </p>
      </div>
    );
  }

  const handleCopySummary = () => {
    navigator.clipboard.writeText(generateAnalysisSummary(item));
    toast({ title: "Summary Copied", description: "Analysis summary copied to clipboard.", duration: 2000 });
  };

  const handleCopyEvidenceKeys = () => {
    const keys = getEvidenceKeys(item).join("\n");
    if (!keys) {
      toast({ title: "No Evidence", description: "This job has no evidence keys.", variant: "destructive", duration: 2000 });
      return;
    }
    navigator.clipboard.writeText(keys);
    toast({ title: "Evidence Keys Copied", description: "Keys copied to clipboard.", duration: 2000 });
  };

  const decision = getFinalDecision(item);
  const severity = getSeverity(item);
  const confidence = getConfidence(item);
  const ratio = getScoreRatio(item);
  const evidenceCount = getEvidenceKeys(item).length;

  return (
    <div className="flex flex-col h-full overflow-hidden pb-1">
      <Tabs defaultValue="outcome" className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <TabsList className="bg-zinc-900/50 border border-zinc-800 mb-2 w-full justify-start h-auto flex-wrap p-1 shrink-0 grid grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-1">
          <TabsTrigger value="outcome" className="text-xs data-[state=active]:bg-zinc-800">Final Outcome</TabsTrigger>
          <TabsTrigger value="evidence" className="text-xs data-[state=active]:bg-zinc-800">Evidence Objects</TabsTrigger>
          <TabsTrigger value="gate" className="text-xs data-[state=active]:bg-zinc-800">Gate Context</TabsTrigger>
          <TabsTrigger value="visual" className="text-xs data-[state=active]:bg-zinc-800">VLM Perception</TabsTrigger>
          <TabsTrigger value="policy" className="text-xs data-[state=active]:bg-zinc-800">LLM Policy</TabsTrigger>
          <TabsTrigger value="guardrails" className="text-xs data-[state=active]:bg-zinc-800">Guardrails</TabsTrigger>
          <TabsTrigger value="raw" className="text-xs data-[state=active]:bg-zinc-800">Raw JSON</TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-y-auto min-h-0 pr-1 custom-scrollbar-invisible">
          <TabsContent value="outcome" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <div className="flex flex-col mb-2 pb-2 border-b border-zinc-800 shrink-0">
              <div className="flex items-center justify-between mb-1">
                <h2 className="text-lg font-bold tracking-tight text-white font-['Space_Grotesk'] flex items-center gap-2">
                  Reasoning Trace 
                  <span className="text-slate-500 font-mono text-xs ml-2 font-normal">#{item.job.id}</span>
                </h2>
                <div className="flex items-center gap-1.5">
                  <Button variant="outline" size="sm" onClick={handleCopySummary} className="h-7 px-2 text-[10px] bg-zinc-900 border-zinc-800">
                    <Copy size={10} className="mr-1" /> Summary
                  </Button>
                  <Button variant="outline" size="sm" onClick={handleCopyEvidenceKeys} className="h-7 px-2 text-[10px] bg-zinc-900 border-zinc-800">
                    <Copy size={10} className="mr-1" /> Evidence
                  </Button>
                  <Button variant="outline" size="sm" className="h-7 px-2 text-[10px] bg-indigo-500/10 text-indigo-400 border-indigo-500/20 hover:bg-indigo-500/20">
                    <Activity size={10} className="mr-1" /> Open in Event Lab
                  </Button>
                </div>
              </div>
              
              {/* Expanded Header Context */}
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2 mt-2 mb-1">
                <HeaderStat label="Gate" value={getGateDisplayName(item)} colorClass={getGateBadgeVariant(item).color} />
                <HeaderStat label="Status" value={<StatusBadge status={item.job.status} />} />
                <HeaderStat label="Decision" value={decision} colorClass={decision === 'YES' ? 'text-red-500' : decision === 'NO' ? 'text-emerald-500' : 'text-amber-500'} />
                <HeaderStat label="Severity" value={severity || "-"} colorClass={severity === 'HIGH' ? 'text-red-400' : 'text-slate-300'} />
                <HeaderStat label="Confidence" value={confidence ? confidence.toFixed(2) : "-"} />
                <HeaderStat label="Ratio" value={ratio ? ratio.toFixed(2) : "-"} />
                
                <HeaderStat label="Case ID" value={`#${item.case?.id || "-"}`} className="font-mono" />
                <HeaderStat label="Event ID" value={`#${item.case?.event_id || "-"}`} className="font-mono" />
                <HeaderStat label="Session ID" value={item.case?.session_id || "-"} className="font-mono truncate" title={String(item.case?.session_id)} />
                <HeaderStat label="Track ID" value={getTrackId(item)} className="font-mono" />
                <HeaderStat label="Evidence" value={`${evidenceCount} files`} />
                <HeaderStat label="Queued" value={item.job.queued_at ? formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true }) : "-"} />
              </div>
            </div>

            <div className="shrink-0 mb-2 px-2 py-1 bg-zinc-900/40 border border-zinc-800/50 rounded flex items-center gap-1 text-[9px] font-mono tracking-tighter uppercase text-slate-500 overflow-x-auto custom-scrollbar">
              <span>0 Gate Trigger</span>
              <ChevronRight size={12} className="opacity-50 shrink-0 mx-0.5" />
              <span>1 Evidence</span>
              <ChevronRight size={12} className="opacity-50 shrink-0 mx-0.5" />
              <span>2 VLM Perception</span>
              <ChevronRight size={12} className="opacity-50 shrink-0 mx-0.5" />
              <span>3 LLM Cognition</span>
              <ChevronRight size={12} className="opacity-50 shrink-0 mx-0.5" />
              <span>4 Python Guardrails</span>
              <ChevronRight size={12} className="opacity-50 shrink-0 mx-0.5" />
              <span className="text-white font-bold tracking-widest">5 Final Decision</span>
            </div>

            <FinalDecisionHeroCard item={item} />
          </TabsContent>
          <TabsContent value="evidence" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col min-h-0 flex-1">
            <EvidenceViewer item={item} />
          </TabsContent>
          <TabsContent value="gate" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <GateTriggerCard item={item} />
          </TabsContent>
          <TabsContent value="visual" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <VlmVisualReviewCard item={item} />
          </TabsContent>
          <TabsContent value="policy" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <LlmPolicyReviewCard item={item} />
          </TabsContent>
          <TabsContent value="guardrails" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <PythonFinalGuardrailsCard item={item} />
          </TabsContent>
          <TabsContent value="raw" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <RawJsonCard item={item} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}

function HeaderStat({ label, value, colorClass = "text-slate-300", className = "", title }: { label: string, value: React.ReactNode, colorClass?: string, className?: string, title?: string }) {
  return (
    <div className="flex flex-col gap-0.5" title={title}>
      <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{label}</span>
      <span className={`text-xs font-semibold ${colorClass} ${className}`}>{value}</span>
    </div>
  );
}
