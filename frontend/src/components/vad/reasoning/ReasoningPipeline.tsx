import { VadReasoningListItem } from "@/services/vad_api";
import { CheckCircle2, XCircle, AlertCircle, CircleDashed, ChevronRight } from "lucide-react";
import { getPythonFinalResult, getLlmReview, getVlmReview } from "./reasoningUtils";

export function ReasoningPipeline({ item }: { item: VadReasoningListItem }) {
  const isFailed = item.job.status === "failed";
  const hasVlm = !!getVlmReview(item);
  const hasLlm = !!getLlmReview(item);
  const hasPython = !!getPythonFinalResult(item);

  const stages = [
    { name: "Deep Candidate", status: "completed" },
    { name: "VLM Review", status: hasVlm ? "completed" : (isFailed && !hasVlm ? "failed" : "missing") },
    { name: "LLM Policy", status: hasLlm ? "completed" : (isFailed && hasVlm && !hasLlm ? "failed" : (isFailed ? "unavailable" : "missing")) },
    { name: "Python Guardrails", status: hasPython ? "completed" : (isFailed && hasLlm && !hasPython ? "failed" : (isFailed ? "unavailable" : "missing")) },
    { name: "Final Decision", status: isFailed ? "failed" : "completed" }
  ];

  return (
    <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-6">Reasoning Flow Summary</h3>
      
      <div className="flex items-center justify-between relative px-2 overflow-x-auto">
        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-full h-px bg-zinc-800 z-0"></div>
        
        {stages.map((stage, i) => (
          <div key={i} className="relative z-10 flex flex-col items-center gap-2 bg-zinc-950 px-3 min-w-max">
            <StageIcon status={stage.status} />
            <div className="flex flex-col items-center">
              <span className="text-[10px] font-bold text-slate-300 uppercase whitespace-nowrap">{stage.name}</span>
              <span className={`text-[9px] uppercase font-semibold ${getStatusColor(stage.status)}`}>{stage.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StageIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 size={24} className="text-emerald-500 bg-zinc-950 rounded-full" />;
  if (status === "failed") return <XCircle size={24} className="text-red-500 bg-zinc-950 rounded-full" />;
  if (status === "missing" || status === "unavailable") return <CircleDashed size={24} className="text-slate-600 bg-zinc-950 rounded-full" />;
  return <AlertCircle size={24} className="text-amber-500 bg-zinc-950 rounded-full" />;
}

function getStatusColor(status: string) {
  if (status === "completed") return "text-emerald-500/70";
  if (status === "failed") return "text-red-500/70";
  return "text-slate-500/70";
}
