import { VadReasoningListItem } from "@/services/vad_api";
import { Camera } from "lucide-react";
import { getDeepScore, getThresholdValue, getScoreRatio, getRatioBand } from "./reasoningUtils";

export function DeepCandidateCard({ item }: { item: VadReasoningListItem }) {
  if (!item) return null;

  const score = getDeepScore(item);
  const threshold = getThresholdValue(item);
  const ratio = getScoreRatio(item);
  const ratioBand = getRatioBand(ratio);

  let bandText = "Unknown ratio";
  let bandColor = "text-slate-400";
  
  if (ratioBand === "weak") {
    bandText = "Weak ratio";
    bandColor = "text-amber-400";
  } else if (ratioBand === "moderate") {
    bandText = "Moderate ratio";
    bandColor = "text-blue-400";
  } else if (ratioBand === "strong") {
    bandText = "Strong ratio";
    bandColor = "text-red-400";
  }

  return (
    <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
        <Camera size={14} /> Deep Candidate Context
      </h3>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Case / Job</div>
          <div className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            Case #{item.case?.id || item.job.case_id}
            <span className="text-zinc-600">|</span>
            Job #{item.job.id}
          </div>
        </div>
        
        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Gate / Version</div>
          <div className="text-sm font-semibold text-slate-300 flex flex-col">
            <span>{item.case?.primary_gate_name || "deep"}</span>
            <span className="text-zinc-600 text-[10px] truncate max-w-[120px]" title={item.job.prompt_version}>{item.job.prompt_version}</span>
          </div>
        </div>

        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Score / Threshold</div>
          <div className="text-sm font-mono text-slate-300">
            {score ? score.toFixed(3) : "N/A"} <span className="text-zinc-600">/</span> {threshold ? threshold.toFixed(3) : "N/A"}
          </div>
        </div>

        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Ratio Interpretation</div>
          <div className="flex flex-col">
            <span className={`text-sm font-bold ${bandColor}`}>
              {ratio ? ratio.toFixed(3) : "N/A"} ({bandText})
            </span>
            <span className="text-[10px] text-slate-400">
              {ratioBand === "weak" && "Policy should be conservative"}
              {ratioBand === "moderate" && "Visual evidence required"}
              {ratioBand === "strong" && "Strong isolated anomaly"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
