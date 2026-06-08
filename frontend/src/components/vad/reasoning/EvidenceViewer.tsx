import { useState, useEffect, useRef } from "react";
import { VadReasoningListItem, vadApi } from "@/services/vad_api";
import { getEvidenceKeys, getGateName } from "./reasoningUtils";
import { Image as ImageIcon, FileJson, Info, Play, Pause, SkipBack, SkipForward, Maximize2, Copy, AlertTriangle, RefreshCw } from "lucide-react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

export function EvidenceViewer({ item }: { item: VadReasoningListItem }) {
  const gateName = getGateName(item);
  const evidenceKeys = getEvidenceKeys(item);
  const { toast } = useToast();
  
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [activeGroup, setActiveGroup] = useState<string | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [modalImage, setModalImage] = useState<string | null>(null);
  
  const playIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Group evidence
  const annotatedKey = evidenceKeys.find(k => k.includes("annotated_frame"));
  const montageKey = evidenceKeys.find(k => k.includes("tubelet_montage"));
  const frameKeys = evidenceKeys.filter(k => k.includes("frame_") && !k.includes("annotated")).sort();
  const otherKeys = evidenceKeys.filter(k => k !== annotatedKey && k !== montageKey && !frameKeys.includes(k));

  const fetchUrls = async () => {
    if (evidenceKeys.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const fetchedUrls = await vadApi.getEvidenceUrls(evidenceKeys);
      setUrls(fetchedUrls);
    } catch (err: any) {
      setError(err.message || "Failed to load evidence URLs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUrls();
    
    // Set initial active group
    if (annotatedKey) setActiveGroup("annotated");
    else if (montageKey) setActiveGroup("montage");
    else if (frameKeys.length > 0) setActiveGroup("frames");
    else if (otherKeys.length > 0) setActiveGroup(`other_0`);
    
  }, [item.job.id]);

  useEffect(() => {
    if (isPlaying && activeGroup === "frames" && frameKeys.length > 0) {
      playIntervalRef.current = setInterval(() => {
        setFrameIndex(prev => (prev + 1) % frameKeys.length);
      }, 500); // 2 FPS
    } else if (playIntervalRef.current) {
      clearInterval(playIntervalRef.current);
    }
    return () => {
      if (playIntervalRef.current) clearInterval(playIntervalRef.current);
    };
  }, [isPlaying, activeGroup, frameKeys.length]);

  if (!evidenceKeys || evidenceKeys.length === 0) {
    return (
      <div className="p-4 bg-zinc-950/50 rounded-xl border border-zinc-800">
        {gateName === "pose" && (
          <div className="mb-4 p-3 bg-blue-950/20 border border-blue-900/40 rounded-lg flex gap-3 items-start text-xs text-blue-200/70">
            <Info size={16} className="text-blue-400 shrink-0 mt-0.5" />
            <span>Pose skeleton/keypoint montage is a recommended future evidence type if not present.</span>
          </div>
        )}
        <div className="text-slate-500 text-sm py-6 text-center">Evidence unavailable. No object keys found for this job.</div>
      </div>
    );
  }

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: "Copied", description: "Object key copied to clipboard", duration: 2000 });
  };

  const renderActivePlayer = () => {
    if (loading && Object.keys(urls).length === 0) {
      return (
        <div className="w-full h-full min-h-[300px] flex items-center justify-center bg-black/40 rounded-lg border border-zinc-800">
          <RefreshCw className="h-6 w-6 text-slate-500 animate-spin" />
        </div>
      );
    }

    let currentKey = "";
    let title = "";
    let isSequence = false;

    if (activeGroup === "annotated" && annotatedKey) {
      currentKey = annotatedKey;
      title = "Annotated Peak Frame";
    } else if (activeGroup === "montage" && montageKey) {
      currentKey = montageKey;
      title = "Tubelet Montage";
    } else if (activeGroup === "frames" && frameKeys.length > 0) {
      currentKey = frameKeys[frameIndex];
      title = "Tubelet Frame Sequence";
      isSequence = true;
    } else if (activeGroup?.startsWith("other_")) {
      const idx = parseInt(activeGroup.split("_")[1]);
      currentKey = otherKeys[idx];
      title = "Additional Evidence";
    }

    if (!currentKey) return <div className="w-full h-full min-h-[300px] flex items-center justify-center bg-black/40 rounded-lg border border-zinc-800 text-slate-500 text-xs">No media selected</div>;

    const url = urls[currentKey];
    const isError = error || (Object.keys(urls).length > 0 && !url);

    return (
      <div className="flex flex-col h-full">
        <div className="flex-1 relative bg-black rounded-t-lg border border-zinc-800 overflow-hidden flex items-center justify-center min-h-[300px] group">
          {isError ? (
            <div className="flex flex-col items-center text-red-500/70 p-4 text-center">
              <AlertTriangle className="h-8 w-8 mb-2" />
              <span className="text-sm font-semibold text-red-400 mb-1">Failed to load media</span>
              <span className="text-xs break-all">{currentKey}</span>
            </div>
          ) : url ? (
            <>
              <img src={url} className="max-w-full max-h-full object-contain" alt={title} />
              <div 
                className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
                onClick={() => setModalImage(url)}
              >
                <Maximize2 className="text-white h-8 w-8" />
              </div>
            </>
          ) : (
            <RefreshCw className="h-6 w-6 text-slate-500 animate-spin" />
          )}
        </div>

        {/* Player Controls & Footer */}
        <div className="bg-zinc-900 border border-zinc-800 border-t-0 rounded-b-lg p-3 flex flex-col gap-3">
          {isSequence && (
            <div className="flex items-center justify-between bg-zinc-950 p-2 rounded border border-zinc-800">
              <span className="text-xs text-slate-400 font-mono w-20">Frame {frameIndex + 1}/{frameKeys.length}</span>
              <div className="flex items-center gap-2">
                <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300 hover:text-white" onClick={() => { setIsPlaying(false); setFrameIndex(prev => (prev === 0 ? frameKeys.length - 1 : prev - 1)); }}>
                  <SkipBack size={14} />
                </Button>
                <Button variant="outline" size="icon" className="h-8 w-8 bg-zinc-800 border-zinc-700 text-white" onClick={() => setIsPlaying(!isPlaying)}>
                  {isPlaying ? <Pause size={14} /> : <Play size={14} className="ml-0.5" />}
                </Button>
                <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-300 hover:text-white" onClick={() => { setIsPlaying(false); setFrameIndex(prev => (prev + 1) % frameKeys.length); }}>
                  <SkipForward size={14} />
                </Button>
              </div>
              <div className="w-20"></div> {/* Spacer for balance */}
            </div>
          )}

          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-col min-w-0">
              <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest truncate">{title}</span>
              <span className="text-xs text-slate-400 font-mono truncate select-all">{currentKey}</span>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              {isError && (
                <Button variant="outline" size="icon" className="h-7 w-7 bg-red-950/20 text-red-400 border-red-900/50" onClick={fetchUrls} title="Retry">
                  <RefreshCw size={12} />
                </Button>
              )}
              <Button variant="ghost" size="icon" className="h-7 w-7 text-slate-400 hover:text-white" onClick={() => handleCopy(currentKey)} title="Copy Object Key">
                <Copy size={12} />
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col lg:flex-row gap-4 h-full">
      {/* Left List */}
      <div className="w-full lg:w-64 shrink-0 flex flex-col gap-2">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest px-1">Evidence Objects</span>
        
        <div className="flex flex-col gap-1 overflow-y-auto custom-scrollbar pr-1 max-h-[300px] lg:max-h-full">
          {annotatedKey && (
            <button 
              onClick={() => setActiveGroup("annotated")}
              className={`flex items-center gap-2 p-2.5 rounded-lg border text-left transition-colors ${activeGroup === "annotated" ? "bg-indigo-500/10 border-indigo-500/30 text-indigo-300" : "bg-zinc-900/50 border-zinc-800/50 text-slate-400 hover:bg-zinc-800"}`}
            >
              <ImageIcon size={14} className="shrink-0" />
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-semibold truncate">Annotated Peak Frame</span>
              </div>
            </button>
          )}

          {montageKey && (
            <button 
              onClick={() => setActiveGroup("montage")}
              className={`flex items-center gap-2 p-2.5 rounded-lg border text-left transition-colors ${activeGroup === "montage" ? "bg-indigo-500/10 border-indigo-500/30 text-indigo-300" : "bg-zinc-900/50 border-zinc-800/50 text-slate-400 hover:bg-zinc-800"}`}
            >
              <ImageIcon size={14} className="shrink-0" />
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-semibold truncate">Tubelet Montage</span>
              </div>
            </button>
          )}

          {frameKeys.length > 0 && (
            <button 
              onClick={() => setActiveGroup("frames")}
              className={`flex items-center gap-2 p-2.5 rounded-lg border text-left transition-colors ${activeGroup === "frames" ? "bg-indigo-500/10 border-indigo-500/30 text-indigo-300" : "bg-zinc-900/50 border-zinc-800/50 text-slate-400 hover:bg-zinc-800"}`}
            >
              <Play size={14} className="shrink-0" />
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-semibold truncate">Tubelet Frame Sequence</span>
                <span className="text-[10px] opacity-70">{frameKeys.length} frames</span>
              </div>
            </button>
          )}

          {otherKeys.length > 0 && (
            <div className="mt-2 flex flex-col gap-1">
              <span className="text-[10px] font-bold text-slate-600 uppercase tracking-widest px-1 mb-1">Other Files</span>
              {otherKeys.map((key, idx) => {
                const isJson = key.includes('.json');
                const id = `other_${idx}`;
                return (
                  <button 
                    key={id}
                    onClick={() => setActiveGroup(id)}
                    className={`flex items-center gap-2 p-2.5 rounded-lg border text-left transition-colors ${activeGroup === id ? "bg-zinc-800 border-zinc-700 text-slate-200" : "bg-zinc-900/30 border-zinc-800/30 text-slate-500 hover:bg-zinc-800/80 hover:text-slate-300"}`}
                  >
                    {isJson ? <FileJson size={14} className="shrink-0" /> : <ImageIcon size={14} className="shrink-0" />}
                    <div className="flex flex-col min-w-0">
                      <span className="text-[11px] font-mono truncate">{key.split('/').pop() || key}</span>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Right Player */}
      <div className="flex-1 min-w-0 h-full">
        {renderActivePlayer()}
      </div>

      <Dialog open={!!modalImage} onOpenChange={(open) => !open && setModalImage(null)}>
        <DialogContent className="max-w-[90vw] max-h-[90vh] p-1 bg-black border-zinc-800 overflow-hidden flex items-center justify-center">
          {modalImage && <img src={modalImage} className="max-w-full max-h-full object-contain" alt="Enlarged Evidence" />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
