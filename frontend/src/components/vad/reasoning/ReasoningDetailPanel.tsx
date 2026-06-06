import { VadReasoningListItem } from "@/services/vad_api";
import { DeepCandidateCard } from "./DeepCandidateCard";
import { EvidenceViewer } from "./EvidenceViewer";
import { VlmVisualReviewCard } from "./VlmVisualReviewCard";
import { LlmPolicyReviewCard } from "./LlmPolicyReviewCard";
import { PythonFinalGuardrailsCard } from "./PythonFinalGuardrailsCard";
import { FinalDecisionHeroCard } from "./FinalDecisionHeroCard";
import { Network } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { StatusBadge } from "./ReasoningBadges";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function ReasoningDetailPanel({ item }: { item: VadReasoningListItem | null }) {
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

  return (
    <div className="flex flex-col h-full overflow-hidden pb-2">
      <div className="flex flex-col mb-3 pb-3 border-b border-zinc-800 shrink-0">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xl font-bold tracking-tight text-white font-['Space_Grotesk'] flex items-center gap-2">
            Reasoning Trace 
            <span className="text-slate-500 font-mono text-sm ml-2 font-normal">#{item.job.id}</span>
          </h2>
          <StatusBadge status={item.job.status} />
        </div>
        
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-400">
          {item.job.queued_at && (
            <div className="flex items-center gap-1">
              <span className="font-semibold text-slate-500">Queued:</span>
              <span>{formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true })}</span>
            </div>
          )}
          {item.case && (
            <div className="flex items-center gap-1">
              <span className="font-semibold text-slate-500">Case:</span>
              <span className="font-mono text-slate-300">#{item.case.id}</span>
            </div>
          )}
          {item.job.input_bundle_json?.event?.stream_key && (
            <div className="flex items-center gap-1">
              <span className="font-semibold text-slate-500">Stream:</span>
              <span className="text-slate-300">{item.job.input_bundle_json.event.stream_key}</span>
            </div>
          )}
        </div>
      </div>

      <FinalDecisionHeroCard item={item} />
      
      <Tabs defaultValue="evidence" className="w-full mt-2 flex flex-col min-h-0 overflow-hidden">
        <TabsList className="bg-zinc-900/50 border border-zinc-800 mb-3 w-full flex justify-start h-auto flex-wrap p-1 shrink-0">
          <TabsTrigger value="evidence" className="text-xs data-[state=active]:bg-zinc-800">Evidence</TabsTrigger>
          <TabsTrigger value="visual" className="text-xs data-[state=active]:bg-zinc-800">Visual Review</TabsTrigger>
          <TabsTrigger value="policy" className="text-xs data-[state=active]:bg-zinc-800">Policy Review</TabsTrigger>
          <TabsTrigger value="guardrails" className="text-xs data-[state=active]:bg-zinc-800">Guardrails</TabsTrigger>
          <TabsTrigger value="deep" className="text-xs data-[state=active]:bg-zinc-800">Deep Context</TabsTrigger>
        </TabsList>

        <div className="mt-2 flex-1 min-h-0 overflow-hidden">
          <TabsContent value="evidence" className="h-full mt-0 outline-none overflow-hidden">
            <EvidenceViewer item={item} />
          </TabsContent>
          <TabsContent value="visual" className="h-full mt-0 outline-none overflow-hidden">
            <VlmVisualReviewCard item={item} />
          </TabsContent>
          <TabsContent value="policy" className="h-full mt-0 outline-none overflow-hidden">
            <LlmPolicyReviewCard item={item} />
          </TabsContent>
          <TabsContent value="guardrails" className="h-full mt-0 outline-none overflow-hidden">
            <PythonFinalGuardrailsCard item={item} />
          </TabsContent>
          <TabsContent value="deep" className="h-full mt-0 outline-none overflow-hidden">
            <DeepCandidateCard item={item} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
