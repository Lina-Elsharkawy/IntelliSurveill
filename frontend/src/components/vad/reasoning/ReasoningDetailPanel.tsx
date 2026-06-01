import { VadReasoningListItem } from "@/services/vad_api";
import { ReasoningPipeline } from "./ReasoningPipeline";
import { DeepCandidateCard } from "./DeepCandidateCard";
import { EvidenceViewer } from "./EvidenceViewer";
import { VlmVisualReviewCard } from "./VlmVisualReviewCard";
import { LlmPolicyReviewCard } from "./LlmPolicyReviewCard";
import { PythonFinalGuardrailsCard } from "./PythonFinalGuardrailsCard";
import { FinalDecisionHeroCard } from "./FinalDecisionHeroCard";
import { RawReasoningDebug } from "./RawReasoningDebug";
import { Network } from "lucide-react";

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
    <div className="flex flex-col h-full overflow-y-auto pr-2 custom-scrollbar" style={{ maxHeight: "calc(100vh - 180px)" }}>
      <div className="flex items-center justify-between mb-4 pb-2 border-b border-zinc-800">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white font-['Space_Grotesk'] flex items-center gap-2">
            Reasoning Trace 
            <span className="text-slate-500 font-mono text-sm ml-2 font-normal">#{item.job.id}</span>
          </h2>
        </div>
      </div>

      <FinalDecisionHeroCard item={item} />
      <ReasoningPipeline item={item} />
      <DeepCandidateCard item={item} />
      <VlmVisualReviewCard item={item} />
      <LlmPolicyReviewCard item={item} />
      <PythonFinalGuardrailsCard item={item} />
      <EvidenceViewer item={item} />
      
      <div className="mt-8 pt-4">
        <RawReasoningDebug item={item} />
      </div>
    </div>
  );
}
