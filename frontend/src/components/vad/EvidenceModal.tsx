import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Maximize2, RefreshCw, Camera, FastForward, Play, Info, Copy, Download, Server } from "lucide-react";
import { VadEvent, VadEventDetails } from "@/services/vad_api";
import { FramePlayer } from "./FramePlayer";
import { EmptyState } from "./EmptyState";
import { useState, useEffect } from "react";

export const EvidenceModal = ({ 
  selectedEvent, 
  evidenceData, 
  isEvidenceLoading, 
  onClose 
}: { 
  selectedEvent: VadEvent | null, 
  evidenceData: VadEventDetails | null, 
  isEvidenceLoading: boolean, 
  onClose: () => void 
}) => {
  const [metadataJson, setMetadataJson] = useState<any>(null);

  useEffect(() => {
    if (evidenceData?.metadata_url) {
      fetch(evidenceData.metadata_url)
        .then(res => res.json())
        .then(data => setMetadataJson(data))
        .catch(err => console.error("Failed to fetch metadata json", err));
    } else {
      setMetadataJson(null);
    }
  }, [evidenceData?.metadata_url]);

  if (!selectedEvent) return null;

  const ratio = selectedEvent.threshold_value > 0 ? (selectedEvent.peak_score / selectedEvent.threshold_value).toFixed(2) : "N/A";
  
  const generateSummaryText = () => {
    const time = new Date(selectedEvent.start_ts).toLocaleTimeString();
    return `Event #${selectedEvent.id} was detected by the ${selectedEvent.gate_name} gate at ${time} for Track ID ${selectedEvent.tracker_track_id ?? 'N/A'}. The peak score was ${selectedEvent.peak_score.toFixed(2)} against a calibrated threshold of ${selectedEvent.threshold_value.toFixed(2)}, giving a ratio of ${ratio}x. The event was marked ${selectedEvent.persistent ? 'persistent after satisfying the configured persistence rule' : 'as a raw hit'}.`;
  };

  const copySummary = () => {
    navigator.clipboard.writeText(generateSummaryText());
  };

  const getExplanation = () => {
    switch (selectedEvent.gate_name) {
      case "pose":
        return "The Pose gate detected abnormal micro-motion. The peak score exceeded the calibrated normal threshold. The event became persistent after satisfying the persistence rule.";
      case "deep":
        return "The Deep gate detected a visual embedding that was far from the normal memory bank. The score exceeded the calibrated VideoMAE kNN threshold.";
      case "homography_macro":
        return "The Homography gate detected unusual ground-plane motion. The motion features exceeded the calibrated normal movement distribution.";
      default:
        return "An anomaly was detected exceeding the normal operational threshold.";
    }
  };

  const hasVisualEvidence = evidenceData && (evidenceData.annotated_frame_url || evidenceData.tubelet_montage_url || (evidenceData.frame_urls && evidenceData.frame_urls.length > 0));

  return (
    <Dialog open={!!selectedEvent} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-[1400px] w-[95vw] anomaly-modal-glass text-slate-100 p-0 overflow-hidden flex flex-col h-[90vh]">
        {/* Modal Header */}
        <div className="bg-black/40 px-6 py-4 border-b border-white/10 flex items-center justify-between flex-shrink-0">
          <DialogTitle className="flex items-center gap-3 text-xl font-bold tracking-tight font-['Montserrat']">
            <div className="p-1.5 bg-[rgba(46,213,115,0.15)] rounded border border-[rgba(46,213,115,0.3)]">
              <Maximize2 className="w-5 h-5 text-[rgb(46,213,115)]" />
            </div>
            Analysis Lab: Event #{selectedEvent.id}
          </DialogTitle>
          
          <div className="flex items-center gap-3 mr-8">
            <Badge variant="outline" className="bg-black/60 text-slate-300 border-white/10 px-3 py-1 font-mono text-sm uppercase">
              {selectedEvent.gate_name} GATE
            </Badge>
            {selectedEvent.persistent && (
              <Badge className="bg-red-500/20 text-red-400 border-red-500/30 px-3 py-1 font-mono text-sm uppercase">
                PERSISTENT
              </Badge>
            )}
          </div>
        </div>
        
        {/* Modal Content - Two Columns */}
        <div className="flex-1 flex overflow-hidden">
          
          {/* Left Column: Visual Evidence (65%) */}
          <div className="w-[65%] border-r border-white/5 flex flex-col p-6 overflow-y-auto">
            {isEvidenceLoading ? (
              <div className="flex flex-col items-center justify-center h-full text-slate-400 space-y-4">
                <RefreshCw className="w-10 h-10 animate-spin text-[rgb(46,213,115)]" />
                <p className="text-lg font-['Montserrat']">Fetching secure presigned evidence...</p>
              </div>
            ) : !hasVisualEvidence ? (
              <EmptyState 
                type="no-evidence"
                message="No evidence available"
                description="The event exists in the database, but no MinIO evidence objects were found."
                className="h-full border-none"
              />
            ) : (
              <div className="flex-1 flex flex-col min-h-[400px]">
                <FramePlayer 
                  frameUrls={evidenceData.frame_urls || []} 
                  fallbackMontageUrl={evidenceData.tubelet_montage_url} 
                />
              </div>
            )}
          </div>

          {/* Right Column: Metadata & Analysis (35%) */}
          <div className="w-[35%] bg-black/20 p-6 overflow-y-auto flex flex-col gap-6">
            
            {/* Event Summary */}
            <div className="flex flex-col gap-3">
              <h4 className="text-sm font-semibold text-white font-['Montserrat'] uppercase tracking-wider border-b border-white/10 pb-2 flex items-center justify-between">
                Event Summary
                <Button variant="ghost" size="icon" className="h-6 w-6 hover:bg-white/10" onClick={copySummary} title="Copy Summary">
                  <Copy className="h-3 w-3 text-slate-400" />
                </Button>
              </h4>
              <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-xs">
                <div><span className="text-slate-500 block mb-1">Time Detected</span><span className="text-slate-200">{new Date(selectedEvent.start_ts).toLocaleTimeString()}</span></div>
                <div><span className="text-slate-500 block mb-1">Track ID</span><span className="text-slate-200 font-mono">{selectedEvent.tracker_track_id ?? "N/A"}</span></div>
                <div><span className="text-slate-500 block mb-1">Peak Score</span><span className="text-red-400 font-bold font-mono text-sm">{selectedEvent.peak_score.toFixed(4)}</span></div>
                <div><span className="text-slate-500 block mb-1">Threshold</span><span className="text-slate-300 font-mono">{selectedEvent.threshold_value.toFixed(4)}</span></div>
                <div><span className="text-slate-500 block mb-1">Ratio</span><span className="text-emerald-400 font-mono font-bold text-sm">{ratio}x</span></div>
                <div><span className="text-slate-500 block mb-1">Evidence Frames</span><span className="text-slate-300 font-mono">{evidenceData?.frame_urls?.length ?? 0}</span></div>
              </div>
            </div>

            {/* Decision Explanation */}
            <div className="flex flex-col gap-3 bg-[rgba(46,213,115,0.05)] border border-[rgba(46,213,115,0.2)] rounded-lg p-4">
              <h4 className="text-xs font-semibold text-[rgb(46,213,115)] font-['Montserrat'] uppercase tracking-wider flex items-center">
                <Info className="w-4 h-4 mr-2" /> Decision Explanation
              </h4>
              <p className="text-sm text-slate-300 leading-relaxed">
                {getExplanation()}
              </p>
            </div>




          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
