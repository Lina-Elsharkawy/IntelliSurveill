import { VadReasoningListItem } from "@/services/vad_api";
import { getFinalDecision, getFinalSeverity, getFinalConfidence, getFinalRecommendedAction, getPythonFinalResult, getLlmReview } from "./reasoningUtils";
import { AlertTriangle, ShieldAlert, ShieldCheck, HelpCircle, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function FinalDecisionHeroCard({ item }: { item: VadReasoningListItem }) {
  if (item.job.status === "failed") {
    return (
      <div className="bg-red-950/20 border border-red-900/50 rounded-xl p-4 mb-4">
        <h2 className="text-xs font-bold uppercase tracking-wider text-red-500/70 mb-3 flex items-center gap-2">
          <XCircle size={16} /> Incident Summary
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
  const severity = getFinalSeverity(item);
  const action = getFinalRecommendedAction(item);
  const confidence = getFinalConfidence(item);

  const pfr = getPythonFinalResult(item);
  const llm = getLlmReview(item);
  const reason = pfr?.final_decision_reason || llm?.decision_reason || "Decision reasoning not available.";

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
    colorClasses = "bg-amber-950/20 border-amber-900/50";
    titleColor = "text-amber-500/70";
    badgeColor = "text-amber-500";
    icon = <AlertTriangle size={16} />;
  }

  return (
    <div className={`border rounded-xl p-4 mb-4 ${colorClasses}`}>
      <h2 className={`text-xs font-bold uppercase tracking-wider mb-3 flex items-center gap-2 ${titleColor}`}>
        {icon} Incident Summary
      </h2>
      
      <div className="flex flex-wrap items-baseline gap-4 mb-3">
        <div className={`text-3xl font-black tracking-tight ${badgeColor}`}>{decision}</div>
        
        <div className="flex items-center gap-3">
          <div className="flex flex-col items-start gap-1">
            <span className="text-[10px] text-slate-500 uppercase font-bold">Severity</span>
            <Badge variant="outline" className={`bg-zinc-900 ${severity === 'CRITICAL' ? 'text-red-500 border-red-500/50' : severity === 'HIGH' ? 'text-orange-500 border-orange-500/50' : severity === 'MEDIUM' ? 'text-amber-500 border-amber-500/50' : severity === 'LOW' ? 'text-blue-500 border-blue-500/50' : 'text-slate-400 border-slate-500/50'}`}>{severity}</Badge>
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

      <div className="mt-3">
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1 block">Why this decision?</span>
        <div className="bg-black/20 rounded-lg p-3 border border-white/5">
          <p className="text-slate-300 text-sm leading-relaxed">{reason}</p>
        </div>
      </div>
    </div>
  );
}
