import { X, Camera, Clock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AnomalyCandidate } from "@/services/anomalyCandidatesService";

interface Props {
  selectedAnomaly: AnomalyCandidate | null;
  onClose: () => void;
  getSeverityClass: (severity: string) => string;
  formatDate: (date: string) => string;
}

export function AnomalyDetailModal({ selectedAnomaly, onClose, getSeverityClass, formatDate }: Props) {
  if (!selectedAnomaly) return null;

  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-[2000] p-4 animate-in fade-in duration-300">
      <div className="bg-background border border-border rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
        <div className="sticky top-0 bg-background/80 backdrop-blur-md border-b border-border p-6 flex items-center justify-between z-10">
          <div className="flex items-center gap-4">
            <div className={`w-3 h-3 rounded-full animate-pulse ${getSeverityClass(selectedAnomaly.severity!) === 'red' ? 'bg-red-500' : 'bg-blue-500'}`} />
            <h2 className="text-2xl font-bold text-foreground">Anomaly #{selectedAnomaly.id}</h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full hover:bg-secondary">
            <X className="w-5 h-5" />
          </Button>
        </div>

        <div className="p-8 space-y-8">
          {selectedAnomaly.imageRef ? (
            <div className="rounded-xl overflow-hidden border-2 border-border shadow-lg">
              <img src={selectedAnomaly.imageRef} alt={`Anomaly ${selectedAnomaly.id}`} className="w-full h-auto object-cover max-h-[400px]" />
            </div>
          ) : (
            <div className="w-full h-64 bg-secondary rounded-xl flex flex-col items-center justify-center border-2 border-dashed border-border">
              <Camera className="w-16 h-16 text-muted-foreground/30 mb-2" />
              <p className="text-muted-foreground text-sm">Visual evidence not available</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-1">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Status</p>
              <Badge variant="secondary" className="px-3 py-1 font-mono">{selectedAnomaly.status.replace('_', ' ')}</Badge>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Camera Source</p>
              <p className="text-foreground font-medium flex items-center gap-2"><Camera className="w-4 h-4 text-primary" /> {selectedAnomaly.cameraId || "Unknown Asset"}</p>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Severity</p>
              <Badge className={`${getSeverityClass(selectedAnomaly.severity!)} text-white`}>{selectedAnomaly.severity?.toUpperCase()}</Badge>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Detection Time</p>
              <p className="text-foreground font-medium flex items-center gap-2"><Clock className="w-4 h-4 text-primary" /> {formatDate(selectedAnomaly.createdAt)}</p>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Detailed Narrative</p>
            <div className="text-foreground bg-secondary/50 p-6 rounded-xl border border-border leading-relaxed italic text-sm">
              "{selectedAnomaly.narrative || "System awaiting detailed LLM analysis of the visual data stream..."}"
            </div>
          </div>

          <div className="flex gap-4 pt-4 border-t border-border">
            <Button variant="outline" className="flex-1 h-12 font-bold" onClick={onClose}>Close View</Button>
            <Button className="flex-1 h-12 bg-primary hover:bg-primary/90 font-bold shadow-lg shadow-primary/20">Acknowledge</Button>
            <Button className="flex-1 h-12 bg-success hover:bg-success/90 font-bold shadow-lg shadow-success/20">Resolve Anomaly</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
