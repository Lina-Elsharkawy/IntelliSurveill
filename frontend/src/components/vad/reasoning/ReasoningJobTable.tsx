import { VadReasoningListItem } from "@/services/vad_api";
import { getFinalDecision, getShortError, getGateDisplayName, getSeverity, getEvidenceKeys } from "./reasoningUtils";
import { formatDistanceToNow } from "date-fns";
import { AlertCircle, Camera, CheckCircle2, XCircle, HelpCircle, ShieldAlert } from "lucide-react";

export function ReasoningJobTable({ 
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
      <div className="flex flex-col items-center justify-center p-12 bg-zinc-950/50 rounded-xl border border-zinc-800 flex-1">
        <AlertCircle className="h-8 w-8 text-slate-500 mb-3" />
        <p className="text-slate-400 font-medium">No reasoning jobs found.</p>
        <p className="text-slate-500 text-sm mt-1">Try adjusting your filters.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 min-h-0 custom-scrollbar">
      <table className="w-full text-left text-xs text-slate-300">
        <thead className="bg-zinc-900/80 sticky top-0 z-10 border-b border-zinc-800 uppercase tracking-wider text-[10px] text-slate-500 font-semibold shadow-sm">
          <tr>
            <th className="px-3 py-3">Case / Event</th>
            <th className="px-3 py-3">Gate</th>
            <th className="px-3 py-3">Decision</th>
            <th className="px-3 py-3">Sev</th>
            <th className="px-3 py-3">Time</th>
            <th className="px-3 py-3">Evi</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {items.map((item) => {
            const isSelected = item.job.id === selectedId;
            const finalDecision = getFinalDecision(item);
            const severity = getSeverity(item);
            const error = getShortError(item);
            const timeAgo = item.job.queued_at ? formatDistanceToNow(new Date(item.job.queued_at), { addSuffix: true }) : '';
            const gateDisplayName = getGateDisplayName(item);
            const evidenceKeys = getEvidenceKeys(item);
            const evidenceCount = evidenceKeys.length;
            const status = item.job.status;

            // Row styling based on state
            let rowBorderClass = "border-transparent";
            let decisionColor = "text-slate-400";
            
            if (status === 'failed') {
              rowBorderClass = "border-red-900/50 bg-red-950/10";
              decisionColor = "text-red-400";
            } else if (status === 'queued' || status === 'running') {
              rowBorderClass = "border-blue-900/30 bg-blue-950/10";
              decisionColor = "text-blue-400";
            } else if (finalDecision === "YES") {
              rowBorderClass = "border-red-900/30 bg-red-950/5";
              decisionColor = "text-red-500 font-bold";
            } else if (finalDecision === "NO") {
              rowBorderClass = "border-emerald-900/30 bg-emerald-950/5";
              decisionColor = "text-emerald-500";
            } else if (finalDecision === "UNCERTAIN") {
              rowBorderClass = "border-blue-900/30 bg-blue-950/5";
              decisionColor = "text-blue-500 font-bold";
            }

            const activeClass = isSelected ? "bg-zinc-800/50 outline outline-1 outline-indigo-500/50" : "hover:bg-zinc-800/30 cursor-pointer";

            return (
              <tr 
                key={item.job.id} 
                onClick={() => onSelect(item)}
                className={`transition-colors border-l-[3px] ${rowBorderClass} ${activeClass}`}
              >
                <td className="px-3 py-3 align-top whitespace-nowrap">
                  <div className="flex flex-col justify-center h-full">
                    <span className="font-mono text-xs font-semibold text-slate-200">#{item.case?.id || "-"}</span>
                  </div>
                </td>
                <td className="px-3 py-3 align-top">
                  <div className="flex flex-col justify-center h-full">
                    <span className="font-semibold text-white">{gateDisplayName}</span>
                  </div>
                </td>
                <td className="px-3 py-3 align-top">
                  {status === 'failed' ? (
                    <span className="flex items-center gap-1 text-red-400 font-semibold" title={error}>
                      <ShieldAlert size={12} /> FAILED
                    </span>
                  ) : status === 'queued' || status === 'running' ? (
                    <span className="text-blue-400 font-semibold uppercase">{status}</span>
                  ) : (
                    <span className={`flex items-center gap-1 ${decisionColor}`}>
                      {finalDecision === 'YES' && <CheckCircle2 size={12} />}
                      {finalDecision === 'NO' && <XCircle size={12} />}
                      {finalDecision === 'UNCERTAIN' && <HelpCircle size={12} />}
                      {finalDecision}
                    </span>
                  )}
                </td>
                <td className="px-3 py-3 align-top font-semibold">
                   <span className={`${severity === 'HIGH' || severity === 'CRITICAL' ? 'text-red-400' : severity === 'MEDIUM' ? 'text-blue-400' : severity === 'LOW' ? 'text-emerald-400' : 'text-slate-400'}`}>
                     {severity || "-"}
                   </span>
                </td>
                <td className="px-3 py-3 align-top text-slate-400 whitespace-nowrap">
                  {timeAgo}
                </td>
                <td className="px-3 py-3 align-top text-center">
                  {evidenceCount > 0 ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-zinc-800 text-[10px] text-slate-300 border border-zinc-700">
                      <Camera size={10} /> {evidenceCount}
                    </span>
                  ) : (
                    <span className="text-slate-600">-</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
