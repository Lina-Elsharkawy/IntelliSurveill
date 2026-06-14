import { VadReasoningListItem } from "@/services/vad_api";
import { EvidenceViewer } from "./EvidenceViewer";
import { VlmVisualReviewCard } from "./VlmVisualReviewCard";
import { LlmPolicyReviewCard } from "./LlmPolicyReviewCard";
import { FinalDecisionHeroCard } from "./FinalDecisionHeroCard";
import { RawJsonCard } from "./RawJsonCard";
import { Network } from "lucide-react";
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


  const decision = getFinalDecision(item);
  const severity = getSeverity(item);
  const confidence = getConfidence(item);
  const ratio = getScoreRatio(item);
  const evidenceCount = getEvidenceKeys(item).length;

  return (
    <div className="flex flex-col h-full overflow-hidden pb-1">
      <Tabs defaultValue="outcome" className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <TabsList className="bg-zinc-900/50 border border-zinc-800 mb-2 w-full justify-start h-auto flex-wrap p-1 shrink-0 grid grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-1">
          <TabsTrigger value="outcome" className="text-xs data-[state=active]:bg-zinc-800">Final Outcome</TabsTrigger>
          <TabsTrigger value="evidence" className="text-xs data-[state=active]:bg-zinc-800">Evidence Objects</TabsTrigger>
          <TabsTrigger value="visual" className="text-xs data-[state=active]:bg-zinc-800">VLM Observation</TabsTrigger>
          <TabsTrigger value="policy" className="text-xs data-[state=active]:bg-zinc-800">LLM Rule Decision</TabsTrigger>
          <TabsTrigger value="raw" className="text-xs data-[state=active]:bg-zinc-800">Raw JSON</TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-y-auto min-h-0 pr-1 custom-scrollbar-invisible">
          <TabsContent value="outcome" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <FinalDecisionHeroCard item={item} />
          </TabsContent>
          <TabsContent value="evidence" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col min-h-0 flex-1">
            <EvidenceViewer item={item} />
          </TabsContent>

          <TabsContent value="visual" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <VlmVisualReviewCard item={item} />
          </TabsContent>
          <TabsContent value="policy" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <LlmPolicyReviewCard item={item} />
          </TabsContent>

          <TabsContent value="raw" className="h-full mt-0 outline-none data-[state=active]:flex data-[state=active]:flex-col">
            <RawJsonCard item={item} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}


