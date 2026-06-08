import { VadReasoningSummary } from "@/services/vad_api";
import { Network, Activity, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, ShieldAlert, CircleDashed } from "lucide-react";

export function ReasoningSummaryCards({ summary }: { summary: VadReasoningSummary }) {
  if (!summary) return null;
  
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-9 gap-2 mb-2">
      <SummaryCard title="Total Jobs" value={summary.total} icon={<Network size={14} />} color="slate" />
      <SummaryCard title="Queued" value={summary.queued} icon={<CircleDashed size={14} />} color="slate" />
      <SummaryCard title="Running" value={summary.running} icon={<Activity size={14} />} color="blue" />
      <SummaryCard title="Succeeded" value={summary.succeeded} icon={<CheckCircle2 size={14} />} color="emerald" />
      <SummaryCard title="Failed" value={summary.failed} icon={<XCircle size={14} />} color="red" />
      
      <div className="col-span-2 md:col-span-5 lg:col-span-4 grid grid-cols-3 gap-2 bg-zinc-900/50 border border-zinc-800 rounded-lg p-1.5">
        <div className="col-span-3 flex items-center gap-1.5 mb-1 px-1">
          <ShieldCheck size={12} className="text-slate-400" />
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Final Guardrail Outcomes</span>
        </div>
        <OutcomeStat label="YES" value={summary.final_yes} color="text-red-400" />
        <OutcomeStat label="NO" value={summary.final_no} color="text-emerald-400" />
        <OutcomeStat label="UNCERTAIN" value={summary.final_uncertain} color="text-amber-400" />
      </div>
    </div>
  );
}

function SummaryCard({ title, value, icon, color }: { title: string, value: number, icon: React.ReactNode, color: string }) {
  const colorClasses: Record<string, string> = {
    slate: "text-slate-400 border-slate-800/50 bg-slate-900/20",
    blue: "text-blue-400 border-blue-800/50 bg-blue-900/20",
    emerald: "text-emerald-400 border-emerald-800/50 bg-emerald-900/20",
    red: "text-red-400 border-red-800/50 bg-red-900/20",
    amber: "text-amber-400 border-amber-800/50 bg-amber-900/20",
  };
  
  const iconColorClasses: Record<string, string> = {
    slate: "text-slate-500",
    blue: "text-blue-500",
    emerald: "text-emerald-500",
    red: "text-red-500",
    amber: "text-amber-500",
  };

  return (
    <div className={`rounded-lg border p-2.5 flex flex-col justify-between ${colorClasses[color]}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider opacity-80">{title}</span>
        <div className={iconColorClasses[color]}>{icon}</div>
      </div>
      <div className="text-lg font-bold font-mono leading-none">{value.toLocaleString()}</div>
    </div>
  );
}

function OutcomeStat({ label, value, color }: { label: string, value: number, color: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-1 rounded bg-black/20 border border-white/5">
      <span className={`text-base font-bold font-mono leading-none ${color}`}>{value.toLocaleString()}</span>
      <span className="text-[9px] font-semibold text-slate-500 uppercase tracking-widest mt-0.5">{label}</span>
    </div>
  );
}
