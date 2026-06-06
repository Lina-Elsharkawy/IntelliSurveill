import { VadReasoningListItem } from "@/services/vad_api";
import { Camera, Clock } from "lucide-react";
import { getDeepScore, getThresholdValue, getScoreRatio, getRatioBand } from "./reasoningUtils";
import { formatDistanceToNow } from "date-fns";

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
    <div className="p-2">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3 flex items-center gap-2 border-b border-zinc-800 pb-2">
        <Camera size={16} className="text-blue-400" /> Deep Candidate Context
      </h3>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Gate</div>
          <div className="text-sm font-semibold text-slate-300">
            Deep Visual Similarity
          </div>
        </div>
        
        <div>
          <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Queue & Attempts</div>
          <div className="text-sm font-semibold text-slate-300 flex flex-col">
            <span className="flex items-center gap-1">
              <Clock size={12} className="text-slate-500" /> 
              {item.job.queued_at ? formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true }) : "Unknown"}
            </span>
            <span className="text-zinc-500 text-xs">Attempts: {item.job.attempts} / {item.job.max_attempts}</span>
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
