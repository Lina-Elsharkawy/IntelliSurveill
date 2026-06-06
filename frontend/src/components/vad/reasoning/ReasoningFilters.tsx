import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { RefreshCw, Search } from "lucide-react";

export interface ReasoningFilterState {
  status: string;
  decision: string;
  caseId: string;
  onlyDeep: boolean;
}

interface ReasoningFiltersProps {
  filters: ReasoningFilterState;
  setFilters: (f: ReasoningFilterState) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export function ReasoningFilters({ filters, setFilters, onRefresh, isLoading }: ReasoningFiltersProps) {
  return (
    <div className="flex flex-col md:flex-row gap-4 mb-6 bg-zinc-950/50 p-4 rounded-xl border border-zinc-800/50 items-center justify-between">
      <div className="flex flex-wrap items-center gap-4 w-full md:w-auto">
        
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Job Status</label>
          <Select 
            value={filters.status} 
            onValueChange={(v) => setFilters({ ...filters, status: v })}
          >
            <SelectTrigger className="w-[140px] h-9 bg-zinc-900 border-zinc-800">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="queued">Queued</SelectItem>
              <SelectItem value="running">Running</SelectItem>
              <SelectItem value="succeeded">Succeeded</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="expired">Expired</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Final Decision</label>
          <Select 
            value={filters.decision} 
            onValueChange={(v) => setFilters({ ...filters, decision: v })}
          >
            <SelectTrigger className="w-[140px] h-9 bg-zinc-900 border-zinc-800">
              <SelectValue placeholder="All Decisions" />
            </SelectTrigger>
            <SelectContent className="bg-zinc-900 border-zinc-800">
              <SelectItem value="all">All Decisions</SelectItem>
              <SelectItem value="YES">YES</SelectItem>
              <SelectItem value="NO">NO</SelectItem>
              <SelectItem value="UNCERTAIN">UNCERTAIN</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1">Search Case ID</label>
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
            <Input 
              type="text"
              placeholder="e.g. 23"
              className="w-[120px] h-9 pl-9 bg-zinc-900 border-zinc-800 font-mono text-sm"
              value={filters.caseId}
              onChange={(e) => setFilters({ ...filters, caseId: e.target.value })}
            />
          </div>
        </div>

      </div>

      <div className="flex items-center gap-3">
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
