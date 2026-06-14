import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Search } from "lucide-react";

export interface ReasoningFilterState {
  status: string;
  decision: string;
  severity: string;
  caseId: string;
  gate: string;
  sessionId: string;
  trackId: string;
  evidenceOnly: boolean;
}

interface ReasoningFiltersProps {
  filters: ReasoningFilterState;
  setFilters: (f: ReasoningFilterState) => void;
}

export function ReasoningFilters({ filters, setFilters }: ReasoningFiltersProps) {
  return (
    <div className="flex flex-col gap-2 mb-2 bg-zinc-950/50 p-2 rounded-lg border border-zinc-800/50">
      <div className="flex flex-wrap items-end gap-2 w-full">
        
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Gate</label>
          <Select 
            value={filters.gate} 
            onValueChange={(v) => setFilters({ ...filters, gate: v })}
          >
            <SelectTrigger className="w-[100px] h-8 bg-zinc-900 border-zinc-800 text-xs">
              <SelectValue placeholder="All Gates" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All Gates</SelectItem>
              <SelectItem value="deep">Deep Gate</SelectItem>
              <SelectItem value="pose">Pose Gate</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Final Decision</label>
          <Select 
            value={filters.decision} 
            onValueChange={(v) => setFilters({ ...filters, decision: v })}
          >
            <SelectTrigger className="w-[100px] h-8 bg-zinc-900 border-zinc-800 text-xs">
              <SelectValue placeholder="All Decisions" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="YES">YES</SelectItem>
              <SelectItem value="NO">NO</SelectItem>
              <SelectItem value="UNCERTAIN">UNCERTAIN</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Status</label>
          <Select 
            value={filters.status} 
            onValueChange={(v) => setFilters({ ...filters, status: v })}
          >
            <SelectTrigger className="w-[100px] h-8 bg-zinc-900 border-zinc-800 text-xs">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="queued">Queued</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="succeeded">Succeeded</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Severity</label>
          <Select 
            value={filters.severity} 
            onValueChange={(v) => setFilters({ ...filters, severity: v })}
          >
            <SelectTrigger className="w-[100px] h-8 bg-zinc-900 border-zinc-800 text-xs">
              <SelectValue placeholder="All Severity" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="LOW">LOW</SelectItem>
              <SelectItem value="MEDIUM">MEDIUM</SelectItem>
              <SelectItem value="HIGH">HIGH</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">IDs</label>
          <div className="flex gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
              <Input 
                type="text"
                placeholder="Case/Event ID"
                className="w-[110px] h-8 pl-9 bg-zinc-900 border-zinc-800 font-mono text-[10px]"
                value={filters.caseId}
                onChange={(e) => setFilters({ ...filters, caseId: e.target.value })}
              />
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-2 bg-zinc-900 border border-zinc-800 h-8 px-2 rounded-md ml-auto shrink-0">
          <Switch 
            id="evidence-only" 
            checked={filters.evidenceOnly}
            onCheckedChange={(c) => setFilters({ ...filters, evidenceOnly: c })}
          />
          <Label htmlFor="evidence-only" className="text-xs text-slate-300 font-semibold cursor-pointer">Has Evidence</Label>
        </div>


      </div>
    </div>
  );
}
