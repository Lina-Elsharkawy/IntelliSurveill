import { VadReasoningListItem } from "@/services/vad_api";
import { StatusBadge, DecisionBadge } from "./ReasoningBadges";
import { getFinalDecision, getShortError, getVlmReview, getFinalSeverity } from "./reasoningUtils";
import { formatDistanceToNow } from "date-fns";
import { AlertCircle, ChevronRight, Video } from "lucide-react";

export function ReasoningJobList({ 
  items, 
  selectedId, 
  onSelect 
}: { 
  items: VadReasoningListItem[], 
  selectedId: number | null, 
  onSelect: (item: VadReasoningListItem) => void 
}) {
  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-12 bg-zinc-950/50 rounded-xl border border-zinc-800">
        <AlertCircle className="h-8 w-8 text-slate-500 mb-3" />
        <p className="text-slate-400 font-medium">No reasoning jobs found.</p>
        <p className="text-slate-500 text-sm mt-1">Try adjusting your filters.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col gap-2 overflow-y-auto pr-2 min-h-0">
      {items.map((item) => {
        const isSelected = item.job.id === selectedId;
        const finalDecision = getFinalDecision(item);
        const severity = getFinalSeverity(item);
        const error = getShortError(item);
        const timeAgo = item.job.queued_at ? formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true }) : '';
        const vlm = getVlmReview(item);
        const eventType = vlm?.event_type || item.job.input_bundle_json?.event?.event_type || "Unknown Event";
        const streamKey = item.job.input_bundle_json?.event?.stream_key || "Unknown Camera";

        return (
          <div 
            key={item.job.id}
            onClick={() => onSelect(item)}
            className={`
              relative p-3 rounded-xl border cursor-pointer transition-all duration-200
              ${isSelected 
                ? 'bg-blue-900/20 border-blue-500/50 shadow-[0_0_15px_rgba(59,130,246,0.15)]' 
                : 'bg-zinc-950 hover:bg-zinc-900 border-zinc-800 hover:border-zinc-700'
              }
            `}
          >
            {isSelected && (
              <div className="absolute left-0 top-0 bottom-0 w-1 bg-blue-500 rounded-l-xl shadow-[0_0_8px_rgba(59,130,246,0.8)]" />
            )}

            <div className="flex justify-between items-start mb-2">
              <div className="flex flex-col">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-sm font-bold text-slate-200">
                    Case #{item.case?.id || item.job.case_id}
                  </span>
                  <span className="text-xs font-semibold text-slate-500">
                    Job #{item.job.id}
                  </span>
                </div>
              </div>
              <div className="flex flex-col items-end gap-1">
                <StatusBadge status={item.job.status} />
              </div>
            </div>

            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {item.job.status === 'succeeded' || item.job.status === 'completed' ? (
                  <DecisionBadge decision={finalDecision} />
                ) : null}
              </div>
              <span className="text-[10px] text-slate-500">{timeAgo}</span>
            </div>

            <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1.5 truncate">
              <Video size={10} />
              <span className="font-semibold">{streamKey}</span>
              <span className="text-zinc-600 px-1">•</span>
              <span className="truncate capitalize">{eventType.replace(/_/g, ' ')}</span>
            </div>

            <div className="text-[10px] text-slate-500 leading-snug italic truncate">
              {item.job.status === 'failed' ? (error || "Reasoning failed") : 
               (item.result?.python_final_result_json?.final_decision_reason || item.result?.llm_policy_review_json?.decision_reason || "Reasoning completed")}
            </div>
            
            {isSelected && <ChevronRight className="absolute right-3 top-1/2 -translate-y-1/2 text-blue-500 opacity-50" size={20} />}
          </div>
        );
      })}
    </div>
  );
}
