import { Badge } from "@/components/ui/badge";
import { VadReasoningListItem } from "@/services/vad_api";
import { getFinalDecision, getRatioBand } from "./reasoningUtils";

export function StatusBadge({ status }: { status: string }) {
  if (!status) return null;
  const s = status.toLowerCase();
  if (s === "queued") return <Badge variant="outline" className="text-slate-400 border-slate-700 bg-slate-900/50 uppercase text-[10px]">Queued</Badge>;
  if (s === "running") return <Badge variant="outline" className="text-blue-400 border-blue-800 bg-blue-900/20 uppercase text-[10px] animate-pulse">Running</Badge>;
  if (s === "succeeded" || s === "completed") return <Badge variant="outline" className="text-emerald-400 border-emerald-800 bg-emerald-900/20 uppercase text-[10px]">Succeeded</Badge>;
  if (s === "failed") return <Badge variant="outline" className="text-red-400 border-red-800 bg-red-900/20 uppercase text-[10px]">Failed</Badge>;
  return <Badge variant="outline" className="uppercase text-[10px]">{s}</Badge>;
}

export function DecisionBadge({ decision }: { decision: string }) {
  if (!decision) return null;
  const d = decision.toUpperCase();
  if (d === "YES") return <Badge className="bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 font-bold uppercase text-[10px]">YES</Badge>;
  if (d === "NO") return <Badge className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 font-bold uppercase text-[10px]">NO</Badge>;
  if (d === "UNCERTAIN") return <Badge className="bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 font-bold uppercase text-[10px]">UNCERTAIN</Badge>;
  return <Badge variant="outline" className="uppercase text-[10px]">{d}</Badge>;
}

export function RatioBadge({ ratio }: { ratio: number }) {
  const band = getRatioBand(ratio);
  if (band === "weak") return <Badge variant="outline" className="text-slate-400 border-slate-700 bg-slate-900/50 uppercase text-[10px]">Weak Ratio</Badge>;
  if (band === "moderate") return <Badge variant="outline" className="text-amber-400 border-amber-800 bg-amber-900/20 uppercase text-[10px]">Moderate Ratio</Badge>;
  if (band === "strong") return <Badge variant="outline" className="text-red-400 border-red-800 bg-red-900/20 uppercase text-[10px]">Strong Ratio</Badge>;
  return null;
}
