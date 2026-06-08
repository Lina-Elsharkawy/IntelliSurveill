import { VadReasoningListItem } from "@/services/vad_api";
import { formatJson, getEvidenceKeys } from "./reasoningUtils";

export function RawJsonCard({ item }: { item: VadReasoningListItem | null }) {
  if (!item) return null;

  const inputBundle = formatJson(item.job.input_bundle_json);
  const metadata = formatJson(item.job.metadata_json);
  const vlmReview = formatJson(item.result?.vlm_visual_review_json || item.result?.structured_output_json?.vlm_visual_review);
  const llmReview = formatJson(item.result?.llm_policy_review_json || item.result?.structured_output_json?.llm_policy_review);
  const pythonFinal = formatJson(item.result?.python_final_result_json || item.result?.structured_output_json?.python_final_result);
  const matchedRules = formatJson(item.result?.matched_rules_json);
  const evidenceKeys = formatJson(getEvidenceKeys(item));

  return (
    <div className="p-2 space-y-4">
      <div className="text-sm font-semibold uppercase tracking-wider text-slate-200 mb-3 border-b border-zinc-800 pb-2">
        Raw JSON Trace
      </div>

      <JsonSection title="Job Metadata" content={metadata} />
      <JsonSection title="Input Bundle" content={inputBundle} />
      <JsonSection title="Evidence Keys" content={evidenceKeys} />
      {vlmReview && <JsonSection title="VLM Visual Review" content={vlmReview} />}
      {llmReview && <JsonSection title="LLM Policy Review" content={llmReview} />}
      {matchedRules && <JsonSection title="Matched Rules" content={matchedRules} />}
      {pythonFinal && <JsonSection title="Python Final Guardrails" content={pythonFinal} />}
    </div>
  );
}

function JsonSection({ title, content }: { title: string, content: string }) {
  if (!content || content === "{}" || content === "[]") return null;
  return (
    <div className="border border-zinc-800 rounded-lg overflow-hidden">
      <div className="bg-zinc-900 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-300 border-b border-zinc-800">
        {title}
      </div>
      <div className="bg-black/50 p-3 max-h-64 overflow-y-auto">
        <pre className="text-[10px] font-mono text-emerald-400/80 break-all whitespace-pre-wrap">
          {content}
        </pre>
      </div>
    </div>
  );
}
