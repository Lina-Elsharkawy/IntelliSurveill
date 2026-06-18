import { VadReasoningSummary } from "@/services/vad_api";
import { Network, Activity, CheckCircle2, XCircle, AlertTriangle, ShieldCheck, ShieldAlert, CircleDashed } from "lucide-react";

export function ReasoningSummaryCards({ summary }: { summary: VadReasoningSummary }) {
  if (!summary) return null;
  
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-2 mb-2">
      <SummaryCard title={summary.returned !== undefined && summary.returned !== summary.total ? "Total Matches" : "Total Jobs"} value={summary.total} icon={<Network size={14} />} color="slate" />
      <SummaryCard title="Queued" value={summary.queued} icon={<CircleDashed size={14} />} color="slate" />
      <SummaryCard title="Running" value={summary.running} icon={<Activity size={14} />} color="blue" />
      <SummaryCard title="Succeeded" value={summary.succeeded} icon={<CheckCircle2 size={14} />} color="emerald" />
      <SummaryCard title="Failed" value={summary.failed} icon={<XCircle size={14} />} color="red" />
      <SummaryCard title="YES" value={summary.final_yes} icon={<ShieldAlert size={14} />} color="red" />
      <SummaryCard title="NO" value={summary.final_no} icon={<ShieldCheck size={14} />} color="emerald" />
      <SummaryCard title="UNCERTAIN" value={summary.final_uncertain} icon={<AlertTriangle size={14} />} color="blue" />
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


