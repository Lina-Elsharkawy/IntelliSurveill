import { VadReasoningListItem } from "@/services/vad_api";
import { getPythonFinalResult } from "./reasoningUtils";
import { ShieldCheck, ShieldAlert, Code } from "lucide-react";
import { DecisionBadge } from "./ReasoningBadges";
import { Badge } from "@/components/ui/badge";

export function PythonFinalGuardrailsCard({ item }: { item: VadReasoningListItem }) {
  const pfr = getPythonFinalResult(item);
  
  if (!pfr) {
    return (
      <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4 opacity-50">
        <div className="flex items-center gap-2 mb-2">
          <Code className="text-slate-500" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">Python Guardrails</h3>
        </div>
        <div className="text-xs text-slate-500">Not available for this job.</div>
      </div>
    );
  }

  const isAlert = pfr.final_alert_decision === "YES";
  const HeaderIcon = isAlert ? ShieldAlert : ShieldCheck;
  const iconColor = isAlert ? "text-red-500" : "text-emerald-500";

  return (
    <div className={`bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4`}>
      <div className="flex items-center justify-between mb-4 border-b border-zinc-800/50 pb-4">
        <div className="flex items-center gap-3">
          <HeaderIcon className={iconColor} size={18} />
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-200">Python Guardrails</h3>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Final Decision</span>
          <span className={`text-sm font-bold ${isAlert ? 'text-red-400' : pfr.final_alert_decision === 'NO' ? 'text-emerald-400' : 'text-amber-400'}`}>
            {pfr.final_alert_decision}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Final Severity</span>
          <span className="text-sm font-semibold text-slate-300">{pfr.final_severity}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Final Action</span>
          <span className="text-sm font-semibold text-slate-300">{pfr.final_recommended_action}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Final Confidence</span>
          <span className="text-sm font-semibold text-slate-300">{pfr.final_confidence?.toFixed(2)}</span>
        </div>
      </div>

      <div className="mb-5">
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest mb-1.5 block">Final Decision Reason</span>
        <p className="text-sm text-slate-300 bg-zinc-900/80 p-3.5 rounded-lg border border-zinc-800/80 leading-relaxed">
          {pfr.final_decision_reason}
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">Guardrail Actions Log</span>
        {pfr.guardrail_actions && pfr.guardrail_actions.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {pfr.guardrail_actions.map((act: any, idx: number) => {
              const ruleId = act.rule_id || act.action_type || act.rule || act.name || "GUARDRAIL";
              const effect = act.effect || "Altered decision";
              const reason = act.reason || "";
              
              return (
                <li key={idx} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Code size={12} className="text-slate-500" />
                    <span className="text-xs font-bold font-mono text-blue-400">{ruleId}</span>
                  </div>
                  <p className="text-xs font-semibold text-slate-300 ml-5 mb-1">{effect}</p>
                  {reason && <p className="text-xs text-slate-400 ml-5">{reason}</p>}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="text-xs text-slate-500 italic bg-zinc-900/30 p-2 rounded border border-zinc-800/30 text-center">
            No guardrails altered the LLM decision.
          </div>
        )}
      </div>

    </div>
  );
}
