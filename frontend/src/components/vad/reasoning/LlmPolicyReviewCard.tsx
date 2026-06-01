import { VadReasoningListItem } from "@/services/vad_api";
import { getLlmReview } from "./reasoningUtils";
import { Brain, Gavel, Scale, FileText } from "lucide-react";
import { DecisionBadge } from "./ReasoningBadges";
import { Badge } from "@/components/ui/badge";

export function LlmPolicyReviewCard({ item }: { item: VadReasoningListItem }) {
  const llm = getLlmReview(item);
  
  if (!llm) {
    return (
      <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4 opacity-50">
        <div className="flex items-center gap-2 mb-2">
          <Brain className="text-slate-500" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">LLM Policy Review</h3>
        </div>
        <div className="text-xs text-slate-500">Not available for this job.</div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4">
      <div className="flex items-center justify-between mb-4 border-b border-zinc-800 pb-3">
        <div className="flex items-center gap-2">
          <Brain className="text-fuchsia-400" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">LLM Policy Review</h3>
        </div>
      </div>

      <div className="bg-fuchsia-500/5 border border-fuchsia-500/10 rounded-lg p-3 mb-4 flex items-start gap-2">
        <FileText size={14} className="text-fuchsia-500/50 mt-0.5" />
        <p className="text-xs text-fuchsia-200/60 italic">
          The LLM policy layer reasons over the structured VLM visual review, score context, and active rules. It does not inspect images directly.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Policy Decision</span>
          <span className={`text-sm font-bold ${llm.policy_alert_decision === 'YES' ? 'text-red-400' : llm.policy_alert_decision === 'NO' ? 'text-emerald-400' : 'text-amber-400'}`}>
            {llm.policy_alert_decision}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Severity</span>
          <span className="text-sm font-semibold text-slate-300">{llm.policy_severity}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Recommended Action</span>
          <span className="text-sm font-semibold text-slate-300">{llm.recommended_action}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Policy Confidence</span>
          <span className="text-sm font-semibold text-slate-300">{llm.policy_confidence?.toFixed(2)}</span>
        </div>
      </div>

      <div className="mb-5 flex flex-col gap-2">
        <SectionTitle>Decision Reason</SectionTitle>
        <p className="text-sm text-slate-300 bg-zinc-900 p-3 rounded-lg border border-zinc-800">{llm.decision_reason}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <div className="flex flex-col gap-2">
          <SectionTitle>Matched Trigger Rules</SectionTitle>
          <RuleList rules={llm.matched_trigger_rules} isTrigger={true} />
        </div>
        <div className="flex flex-col gap-2">
          <SectionTitle>Matched Suppress Rules</SectionTitle>
          <RuleList rules={llm.matched_suppress_rules} isTrigger={false} />
        </div>
      </div>
      
      {llm.limitations && llm.limitations.length > 0 && (
        <div className="mb-4 flex flex-col gap-2">
          <SectionTitle>Limitations / Uncertainty</SectionTitle>
          <ul className="flex flex-col gap-1.5">
            {llm.limitations.map((r: any, idx: number) => (
              <li key={idx} className="flex items-start gap-2 text-xs text-amber-400/80 bg-amber-950/20 p-2 rounded border border-amber-900/30">
                <Scale size={14} className="mt-0.5 text-amber-500/50 shrink-0" />
                <span>{String(r)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{children}</span>;
}

function RuleList({ rules, isTrigger }: { rules: any[], isTrigger: boolean }) {
  if (!rules || !Array.isArray(rules) || rules.length === 0) {
    return <div className="text-xs text-slate-600 bg-zinc-900/30 p-2 rounded border border-zinc-800/30 italic text-center">No rules matched</div>;
  }

  const iconColor = isTrigger ? "text-red-400" : "text-emerald-400";
  const bgColor = isTrigger ? "bg-red-900/10 border-red-900/30" : "bg-emerald-900/10 border-emerald-900/30";

  return (
    <ul className="flex flex-col gap-2">
      {rules.map((rule, idx) => {
        const ruleId = rule.rule_id || rule.rule || (typeof rule === 'string' ? rule : "RULE");
        const reason = rule.reason || "";
        return (
          <li key={idx} className={`p-2 rounded-lg border ${bgColor} flex flex-col gap-1`}>
            <div className="flex items-center gap-1.5">
              <Gavel size={12} className={iconColor} />
              <span className={`text-xs font-bold font-mono ${iconColor}`}>{ruleId}</span>
              {rule.rule_name && <span className="text-xs text-slate-300 ml-1">{rule.rule_name}</span>}
            </div>
            {reason && <p className="text-xs text-slate-400 pl-4 border-l-2 border-zinc-800 ml-1.5">{reason}</p>}
          </li>
        );
      })}
    </ul>
  );
}
