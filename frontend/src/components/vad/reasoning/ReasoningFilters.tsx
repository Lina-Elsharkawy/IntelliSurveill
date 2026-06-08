import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { RefreshCw, Search } from "lucide-react";

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
  onRefresh: () => void;
  isLoading: boolean;
}

export function ReasoningFilters({ filters, setFilters, onRefresh, isLoading }: ReasoningFiltersProps) {
  return (
    <div className="flex flex-col gap-4 mb-6 bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/50">
      <div className="flex flex-wrap items-end gap-4 w-full">
        
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Gate</label>
          <Select 
            value={filters.gate} 
            onValueChange={(v) => setFilters({ ...filters, gate: v })}
          >
            <SelectTrigger className="w-[120px] h-9 bg-zinc-900 border-zinc-800">
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
            <SelectTrigger className="w-[120px] h-9 bg-zinc-900 border-zinc-800">
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
            <SelectTrigger className="w-[120px] h-9 bg-zinc-900 border-zinc-800">
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
            <SelectTrigger className="w-[120px] h-9 bg-zinc-900 border-zinc-800">
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
                className="w-[130px] h-9 pl-9 bg-zinc-900 border-zinc-800 font-mono text-sm"
                value={filters.caseId}
                onChange={(e) => setFilters({ ...filters, caseId: e.target.value })}
              />
            </div>
            <Input 
              type="text"
              placeholder="Session ID"
              className="w-[100px] h-9 bg-zinc-900 border-zinc-800 font-mono text-sm"
              value={filters.sessionId}
              onChange={(e) => setFilters({ ...filters, sessionId: e.target.value })}
            />
            <Input 
              type="text"
              placeholder="Track ID"
              className="w-[100px] h-9 bg-zinc-900 border-zinc-800 font-mono text-sm"
              value={filters.trackId}
              onChange={(e) => setFilters({ ...filters, trackId: e.target.value })}
            />
          </div>
        </div>

        <div className="flex items-center space-x-2 bg-zinc-900 border border-zinc-800 h-9 px-3 rounded-md ml-auto">
          <Switch 
            id="evidence-only" 
            checked={filters.evidenceOnly}
            onCheckedChange={(c) => setFilters({ ...filters, evidenceOnly: c })}
          />
          <Label htmlFor="evidence-only" className="text-xs text-slate-300 font-semibold cursor-pointer">Has Evidence</Label>
        </div>

        <Button 
          variant="outline" 
          size="sm"
          onClick={onRefresh}
          disabled={isLoading}
          className="h-9 bg-blue-500/10 text-blue-400 border-blue-500/20 hover:bg-blue-500/20"
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>
    </div>
  );
}
