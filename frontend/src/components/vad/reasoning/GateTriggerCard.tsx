import { VadReasoningListItem } from "@/services/vad_api";
import { ActivitySquare, AlertTriangle, ShieldX } from "lucide-react";
import { getDeepScore, getThresholdValue, getScoreRatio, getRatioBand, getGateName, getGateBadgeVariant, getTrackId } from "./reasoningUtils";

export function GateTriggerCard({ item }: { item: VadReasoningListItem }) {
  if (!item) return null;

  const score = getDeepScore(item);
  const threshold = getThresholdValue(item);
  const ratio = getScoreRatio(item);
  const ratioBand = getRatioBand(ratio);
  const gateName = getGateName(item);
  const badgeVariant = getGateBadgeVariant(item);
  const trackId = getTrackId(item);
  const sessionId = item.case?.session_id || "N/A";
  
  const pfr = item.job.python_final_result_json || {};
  const vlm = item.job.vlm_result_json || {};
  const eventType = vlm.event_type || item.job.input_bundle_json?.event?.event_type || "Unknown";
  
  // Extract correlation metadata if available
  const meta = item.job.metadata_json || {};
  const hasCorrelation = meta.overlapping_gate !== undefined;

  let bandColor = "text-slate-400";
  if (ratioBand === "weak") bandColor = "text-amber-400";
  else if (ratioBand === "moderate") bandColor = "text-blue-400";
  else if (ratioBand === "strong") bandColor = "text-red-400";

  if (gateName === "homography" || gateName === "macro") {
    return (
      <div className="p-4 bg-zinc-950 rounded-xl border border-zinc-800 flex flex-col items-center justify-center text-center py-12">
        <ShieldX size={32} className="text-slate-600 mb-4" />
        <h3 className="text-lg font-semibold text-slate-300 mb-2">Macro/Homography Gate</h3>
        <p className="text-slate-500 text-sm">No VLM/LLM reasoning by design.</p>
      </div>
    );
  }

  const isPose = gateName === "pose";
  const label = isPose ? "Pose Micro-Motion Gate" : "Deep Visual Similarity / Semantic Spatiotemporal Gate";

  return (
    <div className="p-2 flex flex-col gap-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200 flex items-center gap-2 border-b border-zinc-800 pb-2">
        <ActivitySquare size={16} className={badgeVariant.iconColor} /> {label}
      </h3>
      
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 p-3 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Peak Score</span>
          <span className="text-sm font-mono text-slate-300">{score ? score.toFixed(3) : "N/A"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Threshold Value</span>
          <span className="text-sm font-mono text-slate-300">{threshold ? threshold.toFixed(3) : "N/A"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Score Ratio</span>
          <span className="text-sm font-mono text-slate-300">{ratio ? ratio.toFixed(3) : "N/A"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Ratio Band</span>
          <span className={`text-sm font-bold uppercase ${bandColor}`}>{ratioBand || "N/A"}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 p-3 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Gate Decision</span>
          <span className="text-sm font-semibold text-slate-300">{item.job.input_bundle_json?.event?.is_anomaly ? "YES" : "NO"}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Session ID</span>
          <span className="text-sm font-mono text-slate-300 truncate" title={sessionId}>{sessionId}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Track ID</span>
          <span className="text-sm font-mono text-slate-300">{trackId}</span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">Event Type</span>
          <span className="text-sm font-semibold text-slate-300 capitalize">{eventType.replace(/_/g, ' ')}</span>
        </div>
      </div>
      
      {isPose && vlm.false_positive_risks && vlm.false_positive_risks.length > 0 && (
        <div className="flex flex-col gap-1.5 mt-2">
          <span className="text-[10px] text-slate-500 uppercase font-bold mb-1">False Positive Risks</span>
          <ul className="flex flex-col gap-1.5">
            {vlm.false_positive_risks.map((r: any, idx: number) => (
              <li key={idx} className="text-xs text-amber-400 bg-amber-950/20 p-2.5 rounded-lg border border-amber-900/30 leading-relaxed">
                {String(r)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasCorrelation && (
        <div className="mt-2 p-3 bg-indigo-950/20 border border-indigo-900/40 rounded-lg flex gap-3 items-start">
          <AlertTriangle size={16} className="text-indigo-400 mt-0.5 shrink-0" />
          <div>
            <div className="text-xs font-bold text-indigo-300 uppercase tracking-wider mb-1">Correlation Metadata Present</div>
            <div className="text-xs text-indigo-200/70">
              An overlapping event from the <span className="font-semibold text-indigo-300">{meta.overlapping_gate}</span> gate was detected (Event ID: {meta.overlapping_event_id}). 
              Overlap duration: {meta.overlap_seconds?.toFixed(1) || "?"}s.
            </div>
            <div className="text-[10px] text-indigo-400/60 mt-1 italic">
              Note: This is correlation only. Separate reasoning jobs are preserved for strict explainability.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
