import { VadReasoningListItem } from "@/services/vad_api";
import { getLlmReview } from "./reasoningUtils";
import { Brain, Gavel, Scale, FileText } from "lucide-react";

export function LlmPolicyReviewCard({ item }: { item: VadReasoningListItem }) {
  const llm = getLlmReview(item);
  
  if (!llm) {
    return (
      <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4 opacity-50">
        <div className="flex items-center gap-2 mb-2">
          <Brain className="text-slate-500" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">LLM Policy Review</h3>
        </div>
        <div className="text-xs text-slate-500">Not available for this job. Job might be queued, running, or failed.</div>
      </div>
    );
  }

  return (
    <div className="p-2 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
        <div className="flex items-center gap-2">
          <Brain className="text-fuchsia-400" size={16} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">LLM Policy Review</h3>
        </div>
      </div>

      <div className="p-3 bg-fuchsia-950/20 border border-fuchsia-900/40 rounded-lg flex gap-3 items-start text-xs text-fuchsia-200/70">
        <FileText size={16} className="text-fuchsia-400 shrink-0 mt-0.5" />
        <span>LLM role: applies laboratory anomaly rules to the VLM perception text and gate metadata.</span>
      </div>

      <div className="flex flex-col gap-3">
        <TextField label="Policy Interpretation / Reason" text={llm.decision_reason} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
        <div className="flex flex-col gap-2">
          <SectionTitle>Limitations / Uncertainty</SectionTitle>
          <ul className="flex flex-col gap-1.5">
            {llm.limitations.map((r: any, idx: number) => (
              <li key={idx} className="flex items-start gap-2 text-xs text-amber-300 bg-amber-950/20 p-2.5 rounded-lg border border-amber-900/30">
                <Scale size={14} className="mt-0.5 text-amber-500 shrink-0" />
                <span className="leading-relaxed">{String(r)}</span>
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

function TextField({ label, text }: { label: string, text: string }) {
  if (!text) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{label}</span>
      <p className="text-xs text-slate-300 bg-zinc-900/50 p-3 rounded-lg border border-zinc-800/50 leading-relaxed">{text}</p>
    </div>
  );
}

function RuleList({ rules, isTrigger }: { rules: any[], isTrigger: boolean }) {
  if (!rules || !Array.isArray(rules) || rules.length === 0) {
    return <div className="text-xs text-slate-600 bg-zinc-900/30 p-2.5 rounded-lg border border-zinc-800/30 italic text-center">No rules matched</div>;
  }

  const iconColor = isTrigger ? "text-red-400" : "text-emerald-400";
  const bgColor = isTrigger ? "bg-red-900/10 border-red-900/30" : "bg-emerald-900/10 border-emerald-900/30";

  return (
    <ul className="flex flex-col gap-2">
      {rules.map((rule, idx) => {
        const ruleId = rule.rule_id || rule.rule || (typeof rule === 'string' ? rule : "RULE");
        const reason = rule.reason || "";
        return (
          <li key={idx} className={`p-3 rounded-lg border ${bgColor} flex flex-col gap-1.5`}>
            <div className="flex items-center gap-1.5">
              <Gavel size={12} className={iconColor} />
              <span className={`text-xs font-bold font-mono ${iconColor}`}>{ruleId}</span>
              {rule.rule_name && <span className="text-xs text-slate-300 ml-1">{rule.rule_name}</span>}
            </div>
            {reason && <p className="text-xs text-slate-400 pl-4 border-l-2 border-zinc-700 ml-1.5 leading-relaxed">{reason}</p>}
          </li>
        );
      })}
    </ul>
  );
}
