import { VadReasoningListItem } from "@/services/vad_api";
import { getVlmReview } from "./reasoningUtils";
import { Eye, Check, AlertTriangle, Info } from "lucide-react";
import { DecisionBadge } from "./ReasoningBadges";

export function VlmVisualReviewCard({ item }: { item: VadReasoningListItem }) {
  const vlm = getVlmReview(item);
  
  if (!vlm) {
    return (
      <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4 opacity-50">
        <div className="flex items-center gap-2 mb-2">
          <Eye className="text-slate-500" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">VLM Visual Review</h3>
        </div>
        <div className="text-xs text-slate-500">Not available for this job.</div>
      </div>
    );
  }

  return (
    <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4">
      <div className="flex items-center justify-between mb-4 border-b border-zinc-800 pb-3">
        <div className="flex items-center gap-2">
          <Eye className="text-indigo-400" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">VLM Visual Review</h3>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Visual Decision</span>
          <span className={`text-sm font-bold ${vlm.visual_alert_decision === 'YES' ? 'text-red-400' : vlm.visual_alert_decision === 'NO' ? 'text-emerald-400' : 'text-amber-400'}`}>
            {vlm.visual_alert_decision}
          </span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Event Type</span>
          <span className="text-sm font-semibold text-slate-300">{vlm.event_type}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Sufficiency</span>
          <span className="text-sm font-semibold text-slate-300">{vlm.evidence_sufficiency}</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">Visual Confidence</span>
          <span className="text-sm font-semibold text-slate-300">{vlm.visual_confidence?.toFixed(2)}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
        <div className="flex flex-col gap-2">
          <SectionTitle>Visible Scene</SectionTitle>
          <p className="text-xs text-slate-300 bg-zinc-900 p-3 rounded-lg border border-zinc-800 leading-relaxed h-full">{vlm.visible_scene}</p>
        </div>
        <div className="flex flex-col gap-2">
          <SectionTitle>Person & Action</SectionTitle>
          <p className="text-xs text-slate-300 bg-zinc-900 p-3 rounded-lg border border-zinc-800 leading-relaxed h-full">{vlm.person_observation}</p>
        </div>
        <div className="flex flex-col gap-2">
          <SectionTitle>Motion Observation</SectionTitle>
          <p className="text-xs text-slate-300 bg-zinc-900 p-3 rounded-lg border border-zinc-800 leading-relaxed h-full">{vlm.motion_observation}</p>
        </div>
      </div>

      <div className="mb-5 flex flex-col gap-2">
        <SectionTitle>Decision Reason</SectionTitle>
        <p className="text-sm text-slate-300 bg-zinc-900 p-3 rounded-lg border border-zinc-800 leading-relaxed">{vlm.visual_decision_reason}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <ListSection title="Anomaly Evidence" items={vlm.anomaly_evidence} icon={<AlertTriangle size={12} className="text-red-400" />} />
        <ListSection title="Normality Evidence" items={vlm.normality_evidence} icon={<Check size={12} className="text-emerald-400" />} />
        <ListSection title="False Positive Risks" items={vlm.false_positive_risks} icon={<Info size={12} className="text-amber-400" />} />
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{children}</span>;
}

function ListSection({ title, items, icon }: { title: string, items: any[], icon: React.ReactNode }) {
  if (!items || !Array.isArray(items) || items.length === 0) return (
    <div className="flex flex-col gap-2">
      <SectionTitle>{title}</SectionTitle>
      <div className="text-xs text-slate-600 bg-zinc-900/30 p-2 rounded border border-zinc-800/30 italic text-center">None</div>
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      <SectionTitle>{title}</SectionTitle>
      <ul className="flex flex-col gap-1.5">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-1.5 text-xs text-slate-300 bg-zinc-900/50 p-2 rounded border border-zinc-800/50">
            <span className="mt-0.5 shrink-0">{icon}</span>
            <span>{String(item)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
