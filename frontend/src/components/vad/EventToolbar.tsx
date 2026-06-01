import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { LayoutGrid, Table as TableIcon } from "lucide-react";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

export interface EventFilters {
  gate: string;
  status: string;
  evidence: string;
  sortBy: string;
  viewMode: 'cards' | 'table';
}

export const EventToolbar = ({ 
  filters, 
  setFilters 
}: { 
  filters: EventFilters, 
  setFilters: (f: EventFilters) => void 
}) => {
  return (
    <div className="flex flex-wrap gap-4 items-center justify-between p-4 bg-black/40 border border-white/5 rounded-lg mb-6">
      <div className="flex flex-wrap gap-4 items-center">
        <div className="flex flex-col gap-1.5">
          <Label className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Gate Filter</Label>
          <Select value={filters.gate} onValueChange={(v) => setFilters({...filters, gate: v})}>
            <SelectTrigger className="w-[140px] bg-white/5 border-white/10 h-8 text-xs">
              <SelectValue placeholder="All Gates" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Gates</SelectItem>
              <SelectItem value="pose">Pose Motion</SelectItem>
              <SelectItem value="deep">Deep Visual</SelectItem>
              <SelectItem value="homography_macro">Homography Motion</SelectItem>
            </SelectContent>
          </Select>
        </div>



        <div className="flex flex-col gap-1.5">
          <Label className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Sort By</Label>
          <Select value={filters.sortBy} onValueChange={(v) => setFilters({...filters, sortBy: v})}>
            <SelectTrigger className="w-[140px] bg-white/5 border-white/10 h-8 text-xs">
              <SelectValue placeholder="Newest" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="newest">Newest First</SelectItem>
              <SelectItem value="highest_score">Highest Score</SelectItem>
              <SelectItem value="highest_ratio">Highest Ratio</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="flex flex-col gap-1.5 ml-auto">
        <Label className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold text-right">View Mode</Label>
        <ToggleGroup type="single" value={filters.viewMode} onValueChange={(v) => { if(v) setFilters({...filters, viewMode: v as 'cards'|'table'}) }} className="justify-end">
          <ToggleGroupItem value="cards" aria-label="Card View" className="h-8 w-8 p-0 data-[state=on]:bg-white/10 data-[state=on]:text-white text-slate-500">
            <LayoutGrid className="h-4 w-4" />
          </ToggleGroupItem>
          <ToggleGroupItem value="table" aria-label="Table View" className="h-8 w-8 p-0 data-[state=on]:bg-white/10 data-[state=on]:text-white text-slate-500">
            <TableIcon className="h-4 w-4" />
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
    </div>
  );
};
