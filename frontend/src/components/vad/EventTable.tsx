import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eye } from "lucide-react";
import { VadEvent } from "@/services/vad_api";
import { EmptyState } from "./EmptyState";

export const EventTable = ({ items, gateName, viewEvidence }: { items: VadEvent[], gateName?: string, viewEvidence: (event: VadEvent) => void }) => {
  const formatGateName = (key: string) => {
    switch(key) {
      case 'pose': return 'Pose Motion';
      case 'deep': return 'Deep Visual';
      case 'homography_macro': return 'Homography Motion';
      default: return key;
    }
  };

  if (items.length === 0) {
    return (
      <EmptyState 
        type="no-events"
        message={`No events found`} 
        description="The system is running, but no anomaly matching these filters has been detected." 
      />
    );
  }

  return (
    <div className="w-full overflow-x-auto rounded-lg border border-white/10 bg-black/40">
      <table className="w-full text-sm text-left text-slate-300">
        <thead className="text-xs uppercase bg-black/60 text-slate-500 border-b border-white/10 font-['Montserrat']">
          <tr>
            <th className="px-4 py-3 font-semibold">Event</th>
            <th className="px-4 py-3 font-semibold">Gate</th>
            <th className="px-4 py-3 font-semibold">Time</th>
            <th className="px-4 py-3 font-semibold">Track ID</th>
            <th className="px-4 py-3 font-semibold text-right">Peak Score</th>
            <th className="px-4 py-3 font-semibold text-right">Threshold</th>
            <th className="px-4 py-3 font-semibold text-right">Ratio</th>
            <th className="px-4 py-3 font-semibold text-center">Persistent</th>
            <th className="px-4 py-3 font-semibold text-center">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map(event => {
            const ratio = event.threshold_value > 0 ? (event.peak_score / event.threshold_value) : null;
            
            return (
              <tr key={event.id} className="border-b border-white/5 hover:bg-white/5 transition-colors group cursor-pointer" onClick={() => viewEvidence(event)}>
                <td className="px-4 py-3 font-mono text-slate-400">#{event.id}</td>
                <td className="px-4 py-3">
                  <Badge variant="outline" className="bg-transparent border-white/10 text-slate-300 uppercase text-[10px]">
                    {formatGateName(event.gate_name)}
                  </Badge>
                </td>
                <td className="px-4 py-3 whitespace-nowrap">{new Date(event.start_ts).toLocaleTimeString()}</td>
                <td className="px-4 py-3 font-mono text-slate-400">{event.tracker_track_id ?? "N/A"}</td>
                <td className="px-4 py-3 text-right font-mono font-medium text-white">{event.peak_score.toFixed(2)}</td>
                <td className="px-4 py-3 text-right font-mono text-slate-500">{event.threshold_value.toFixed(2)}</td>
                <td className={`px-4 py-3 text-right font-mono font-bold ${ratio && ratio > 1.5 ? 'text-amber-400' : 'text-slate-400'}`}>
                  {ratio ? `${ratio.toFixed(2)}x` : 'N/A'}
                </td>
                <td className="px-4 py-3 text-center">
                  {event.persistent ? (
                    <span className="text-red-400 font-medium">Yes</span>
                  ) : (
                    <span className="text-slate-600">No</span>
                  )}
                </td>
                <td className="px-4 py-3 text-center">
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-slate-400 group-hover:text-[rgb(50,150,255)] group-hover:bg-[rgba(50,150,255,0.1)]">
                    <Eye className="h-4 w-4" />
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
