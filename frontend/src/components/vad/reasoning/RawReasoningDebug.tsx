import { useState } from "react";
import { VadReasoningListItem } from "@/services/vad_api";
import { formatJson } from "./reasoningUtils";
import { Code, ChevronDown, ChevronRight, Bug } from "lucide-react";

export function RawReasoningDebug({ item }: { item: VadReasoningListItem }) {
  if (!item) return null;

  return (
    <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-4 mt-6">
      <div className="flex items-center gap-2 mb-4 border-b border-zinc-800 pb-3">
        <Bug className="text-slate-500" size={18} />
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">Raw Debug Data</h3>
      </div>
      
      <div className="flex flex-col gap-2">
        <DebugAccordion title="Job Error JSON" data={item.job.error_json} forceOpen={!!item.job.error_json} />
        <DebugAccordion title="Python Final Result" data={item.result?.python_final_result_json} />
        <DebugAccordion title="LLM Policy Review" data={item.result?.llm_policy_review_json} />
        <DebugAccordion title="VLM Visual Review" data={item.result?.vlm_visual_review_json} />
        <DebugAccordion title="Structured Output (Fallback)" data={item.result?.structured_output_json} />
        <DebugAccordion title="Job Input Bundle" data={item.job.input_bundle_json} />
        <DebugAccordion title="Case Evidence Bundle" data={item.case?.evidence_bundle_json} />
        <DebugAccordion title="Case Score Summary" data={item.case?.score_summary_json} />
        <DebugAccordion title="Result Uncertainty" data={item.result?.uncertainty_json} />
      </div>
    </div>
  );
}

function DebugAccordion({ title, data, forceOpen = false }: { title: string, data: any, forceOpen?: boolean }) {
  const [isOpen, setIsOpen] = useState(forceOpen);
  
  if (!data || (typeof data === 'object' && Object.keys(data).length === 0)) {
    return null; // Skip empty sections
  }

  return (
    <div className="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/50">
      <button 
        className="w-full flex items-center justify-between p-3 bg-zinc-900 hover:bg-zinc-800 transition-colors text-left"
        onClick={() => setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2">
          <Code size={14} className="text-slate-500" />
          <span className="text-xs font-semibold text-slate-300 font-mono">{title}</span>
        </div>
        {isOpen ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
      </button>
      
      {isOpen && (
        <div className="p-0 border-t border-zinc-800 max-h-[400px] overflow-y-auto custom-scrollbar">
          <pre className="p-3 text-[10px] sm:text-xs font-mono text-slate-400 whitespace-pre-wrap break-all">
            {formatJson(data)}
          </pre>
        </div>
      )}
    </div>
  );
}
