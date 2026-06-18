import { VadReasoningListItem } from "@/services/vad_api";
import {
  getFinalDecision,
  getSeverity,
  getConfidence,
  getFinalRecommendedAction,
  getShortReason,
  getGateDisplayName,
  getFinalEventType,
  getGateCandidateEventType,
  getNeedsHumanReview,
  getScoreRatio,
  getDeepScore,
  getThresholdValue,
  getSourceGateEventId,
} from "./reasoningUtils";
import { StatusBadge } from "./ReasoningBadges";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, ShieldAlert, ShieldCheck, HelpCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function FinalDecisionHeroCard({ item }: { item: VadReasoningListItem }) {
  if (item.job.status === "failed") {
    return (
      <div className="bg-red-950/20 border border-red-900/50 rounded-xl p-4 mb-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-red-500/70 mb-3 flex items-center gap-2">
          <XCircle size={16} /> Final Reasoning Outcome
        </h2>
        <div className="flex items-center gap-4 mb-3">
          <div className="text-3xl font-black tracking-tight text-red-500">FAILED</div>
        </div>
        <p className="text-slate-300 font-medium mb-1">Reasoning did not complete</p>
        <p className="text-red-400/80 text-sm">{item.job.error_json?.error || item.job.error_json?.message || "Internal reasoning failure"}</p>
      </div>
    );
  }

  const decision = getFinalDecision(item);
  const severity = getSeverity(item);
  const action = getFinalRecommendedAction(item);
  const confidence = getConfidence(item);
  const reason = getShortReason(item);
  const gateDisplayName = getGateDisplayName(item);
  const finalEventType = getFinalEventType(item);
  const gateCandidateEventType = getGateCandidateEventType(item);
  const needsHumanReview = getNeedsHumanReview(item);
  const ratio = getScoreRatio(item);
  const peakScore = getDeepScore(item);
  const thresholdValue = getThresholdValue(item);
  const sourceGateEventId = getSourceGateEventId(item);

  let colorClasses = "bg-zinc-900/50 border-zinc-800";
  let titleColor = "text-slate-500";
  let badgeColor = "text-slate-300";
  let icon = <HelpCircle size={16} />;

  if (decision === "YES") {
    colorClasses = "bg-red-950/20 border-red-900/50";
    titleColor = "text-red-500/70";
    badgeColor = "text-red-500";
    icon = <ShieldAlert size={16} />;
  } else if (decision === "NO") {
    colorClasses = "bg-emerald-950/20 border-emerald-900/50";
    titleColor = "text-emerald-500/70";
    badgeColor = "text-emerald-500";
    icon = <ShieldCheck size={16} />;
  } else if (decision === "UNCERTAIN") {
    colorClasses = "bg-blue-950/20 border-blue-900/50";
    titleColor = "text-blue-500/70";
    badgeColor = "text-blue-500";
    icon = <AlertTriangle size={16} />;
  }

  return (
    <div className={`border rounded-xl p-6 flex flex-col flex-1 min-h-[400px] ${colorClasses}`}>
      <div className="flex items-center justify-between mb-6 border-b border-zinc-800/50 pb-4">
        <h2 className={`text-sm font-bold uppercase tracking-wider flex items-center gap-2 ${titleColor}`}>
          {icon} Final Reasoning Outcome
        </h2>
        <div className="text-[10px] uppercase tracking-widest font-bold text-slate-500 border border-slate-700/50 px-3 py-1 rounded-full bg-black/20">
          Authority: Python Validation
        </div>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 flex-1">
        {/* Left side: Primary Decision */}
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-baseline gap-4">
            <div className={`text-3xl font-black tracking-tight ${badgeColor}`}>{decision}</div>
            <div className="flex items-center gap-3">
              <div className="flex flex-col items-start gap-1">
                <span className="text-[10px] text-slate-500 uppercase font-bold">Severity</span>
                <Badge variant="outline" className={`bg-zinc-900 ${severity === 'CRITICAL' ? 'text-red-500 border-red-500/50' : severity === 'HIGH' ? 'text-red-500 border-red-500/50' : severity === 'MEDIUM' ? 'text-blue-500 border-blue-500/50' : severity === 'LOW' ? 'text-emerald-500 border-emerald-500/50' : 'text-slate-400 border-slate-500/50'}`}>{severity}</Badge>
              </div>
              <div className="h-8 w-px bg-zinc-800"></div>
              <div className="flex flex-col">
                <span className="text-[10px] text-slate-500 uppercase font-bold">Action</span>
                <span className="text-sm font-semibold text-slate-200">{action}</span>
              </div>
              <div className="h-8 w-px bg-zinc-800"></div>
              <div className="flex flex-col">
                <span className="text-[10px] text-slate-500 uppercase font-bold">Confidence</span>
                <span className="text-sm font-semibold text-slate-200">{confidence.toFixed(2)}</span>
              </div>
            </div>
          </div>

          <div className="flex flex-col">
            <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1 block">Final Reasoning Explanation</span>
            <div className="bg-black/20 rounded-lg p-3 border border-white/5">
              <p className="text-slate-300 text-sm leading-relaxed">{reason}</p>
            </div>
          </div>
          
          {needsHumanReview && (
            <div className="bg-blue-950/30 border border-blue-900/50 rounded p-2 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-blue-500" />
              <span className="text-xs font-semibold text-blue-400">Human Review Recommended</span>
            </div>
          )}
        </div>

        {/* Right side: Event & Score Context */}
        <div className="flex flex-col gap-4 border-l border-zinc-800/50 pl-6">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Gate Trigger</span>
              <span className="text-xs font-semibold text-slate-300">{gateDisplayName}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Final Event Type</span>
              <span className="text-xs font-semibold text-slate-300 capitalize">{finalEventType.replace(/_/g, ' ')}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Gate Candidate</span>
              <span className="text-xs font-semibold text-slate-300 capitalize">{gateCandidateEventType.replace(/_/g, ' ')}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Score / Threshold</span>
              <span className="text-xs font-mono text-slate-300">
                {peakScore ? peakScore.toFixed(2) : "N/A"} / {thresholdValue ? thresholdValue.toFixed(2) : "N/A"}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Score Ratio</span>
              <span className="text-xs font-mono text-slate-300">{ratio ? ratio.toFixed(2) : "N/A"}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Case ID</span>
              <span className="text-xs font-mono text-slate-300">#{item.case?.id || item.job.case_id || "N/A"}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Event ID</span>
              <span className="text-xs font-mono text-slate-300">#{sourceGateEventId}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Status</span>
              <StatusBadge status={item.job.status} />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1">Queued</span>
              <span className="text-xs font-semibold text-slate-300">{item.job.queued_at ? formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true }) : "-"}</span>
            </div>
          </div>
          

        </div>
      </div>
    </div>
  );
}
