import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Maximize2 } from "lucide-react";
import { VadEvent } from "@/services/vad_api";
import { EmptyState } from "./EmptyState";

export const EventGrid = ({ items, gateName, viewEvidence }: { items: VadEvent[], gateName?: string, viewEvidence: (event: VadEvent) => void }) => {
  const formatGateName = (key: string) => {
    switch(key) {
      case 'pose': return 'Pose Motion';
      case 'deep': return 'Deep Visual';
      case 'homography_macro': return 'Homography Motion';
      default: return key;
    }
  };

  return (
  <div className="anomaly-cards-container grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
    {items.length === 0 ? (
      <div className="col-span-full">
        <EmptyState 
          type="no-events"
          message={`No events found`} 
          description="The system is running, but no anomaly matching these filters has been detected." 
        />
      </div>
    ) : (
      items.map(event => {
        const ratio = event.threshold_value > 0 ? (event.peak_score / event.threshold_value) : null;
        const severityClass = event.persistent 
          ? "severity-high" 
          : (ratio && ratio > 1.5) ? "severity-medium" 
          : "severity-low";
        
        return (
          <div key={event.id} className={`anomaly-card hover:-translate-y-1 hover:shadow-xl hover:shadow-[0_4px_20px_-4px_rgba(59,130,246,0.15)] transition-all duration-300 ${severityClass}`} onClick={() => viewEvidence(event)}>
            <div className="card-content-wrap flex flex-col h-full">
              <div className="flex justify-between items-start mb-3">
                <div className="flex gap-2">
                  <Badge variant="outline" className={`font-mono ${event.persistent ? 'bg-red-500/20 text-red-400 border-red-500/30' : 'bg-slate-800 text-slate-400 border-slate-700'}`}>
                    {event.persistent ? "PERSISTENT" : "RAW HIT"}
                  </Badge>
                  <Badge variant="outline" className="bg-black/40 text-slate-400 border-white/10 uppercase">
                    {formatGateName(event.gate_name)}
                  </Badge>
                </div>
                <span className="text-xs font-mono text-slate-500">#{event.id}</span>
              </div>
              
              <div className="text-2xl font-bold text-white font-['Space_Grotesk'] mb-1 flex items-baseline gap-2">
                {event.peak_score.toFixed(2)}
                <span className="text-[10px] font-normal text-slate-500 uppercase tracking-widest font-['Montserrat']">Peak Score</span>
                {ratio !== null && (
                  <span className={`ml-auto text-sm font-mono ${ratio > 1.5 ? 'text-emerald-400' : 'text-slate-400'}`}>
                    {ratio.toFixed(2)}x
                  </span>
                )}
              </div>
              
              <div className="text-xs text-slate-400 mb-4 flex items-center gap-2">
                <div className="w-full bg-slate-800/50 h-1.5 rounded-full overflow-hidden">
                  <div 
                    className={`h-full ${event.persistent ? 'bg-red-500' : 'bg-emerald-500'}`}
                    style={{ width: `${Math.min(100, ratio ? ratio * 50 : 0)}%` }}
                  />
                </div>
                <span className="whitespace-nowrap text-right font-mono text-[10px]">Threshold: {event.threshold_value.toFixed(1)}</span>
              </div>
              
              <div className="grid grid-cols-2 gap-2 text-xs mb-4 flex-1">
                <div>
                  <p className="text-[10px] text-slate-400 mb-0.5 uppercase tracking-widest font-semibold font-['Montserrat']">Detected</p>
                  <div className="text-slate-300">{new Date(event.start_ts).toLocaleTimeString()}</div>
                </div>
                <div>
                  <p className="text-[10px] text-slate-400 mb-0.5 uppercase tracking-widest font-semibold font-['Montserrat']">Track ID</p>
                  <div className="text-slate-300 font-mono">{event.tracker_track_id ?? "N/A"}</div>
                </div>
              </div>

              <div className="hover-content">
                 <Button 
                   variant="secondary" 
                   className="w-full bg-white/5 hover:bg-white/10 text-white border border-white/10 shadow-none transition-colors group mt-auto"
                 >
                   <Maximize2 className="w-3.5 h-3.5 mr-2 group-hover:scale-110 transition-transform" />
                   Analyze Evidence
                 </Button>
              </div>
            </div>
          </div>
        )
      })
    )}
  </div>
);
}
