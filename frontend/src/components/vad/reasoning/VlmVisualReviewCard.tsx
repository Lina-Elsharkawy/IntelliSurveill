import { VadReasoningListItem } from "@/services/vad_api";
import { getVlmReview } from "./reasoningUtils";
import { Eye, Check, AlertTriangle, Info, Image as ImageIcon } from "lucide-react";

export function VlmVisualReviewCard({ item }: { item: VadReasoningListItem }) {
  const vlm = getVlmReview(item);
  
  if (!vlm) {
    return (
      <div className="bg-zinc-950 rounded-xl border border-zinc-800 p-5 mb-4 opacity-50">
        <div className="flex items-center gap-2 mb-2">
          <Eye className="text-slate-500" size={18} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">VLM Visual Review</h3>
        </div>
        <div className="text-xs text-slate-500">Not available for this job. Job might be queued, running, or failed.</div>
      </div>
    );
  }

  return (
    <div className="p-2 flex flex-col gap-4">
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
        <div className="flex items-center gap-2">
          <Eye className="text-indigo-400" size={16} />
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">VLM Visual Perception</h3>
        </div>
      </div>
      
      <div className="p-3 bg-indigo-950/20 border border-indigo-900/40 rounded-lg flex gap-3 items-start text-xs text-indigo-200/70">
        <Info size={16} className="text-indigo-400 shrink-0 mt-0.5" />
        <span>VLM role: objective visual observer. It describes what is visible; it is not the final authority.</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-3 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
        <Metric label="Visual Decision" value={vlm.visual_alert_decision} colorClass={vlm.visual_alert_decision === 'YES' ? 'text-red-400' : vlm.visual_alert_decision === 'NO' ? 'text-emerald-400' : 'text-amber-400'} />
        <Metric label="Severity" value={vlm.visual_severity || "-"} colorClass={vlm.visual_severity === 'HIGH' ? 'text-red-400' : 'text-slate-300'} />
        <Metric label="Confidence" value={vlm.visual_confidence?.toFixed(2) || "-"} />
        <Metric label="Sufficiency" value={vlm.evidence_sufficiency || "-"} />
        <Metric label="Image Quality" value={vlm.image_quality || "-"} />
        <Metric label="Event Type" value={vlm.event_type?.replace(/_/g, ' ') || "-"} className="capitalize" />
      </div>

      <div className="flex flex-col gap-3">
        <TextField label="Visible Scene" text={vlm.visible_scene} />
        <TextField label="Person Observation" text={vlm.person_observation} />
        <TextField label="Motion Observation" text={vlm.motion_observation} />
        <TextField label="Decision Reason" text={vlm.visual_decision_reason} />
      </div>

      <div className="flex flex-col gap-3">
        <ListSection title="Anomaly Evidence" items={vlm.anomaly_evidence} icon={<AlertTriangle size={12} className="text-red-400" />} />
        <ListSection title="Normality Evidence" items={vlm.normality_evidence} icon={<Check size={12} className="text-emerald-400" />} />
        <ListSection title="False Positive Risks" items={vlm.false_positive_risks} icon={<Info size={12} className="text-amber-400" />} />
      </div>
    </div>
  );
}

function Metric({ label, value, colorClass = "text-slate-300", className = "" }: { label: string, value: string, colorClass?: string, className?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] text-slate-500 uppercase font-bold block mb-1">{label}</span>
      <span className={`text-sm font-bold ${colorClass} ${className}`}>{value}</span>
    </div>
  );
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

function ListSection({ title, items, icon }: { title: string, items: any[], icon: React.ReactNode }) {
  if (!items || !Array.isArray(items) || items.length === 0) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-widest">{title}</span>
      <ul className="flex flex-col gap-1.5">
        {items.map((item, idx) => (
          <li key={idx} className="flex items-start gap-2 text-xs text-slate-300 bg-zinc-900/50 p-2.5 rounded-lg border border-zinc-800/50">
            <span className="mt-0.5 shrink-0">{icon}</span>
            <span className="leading-relaxed">{String(item)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
