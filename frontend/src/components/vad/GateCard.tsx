import { Badge } from "@/components/ui/badge";
import { GateScoreChart } from "./GateScoreChart";
import { VadStatus, VadGateStatus } from "@/services/vad_api";

export const GateCard = ({ 
  name, 
  data, 
  status
}: { 
  name: string, 
  data?: VadGateStatus, 
  status: VadStatus | null
}) => {
  // Model status
  const modelLoaded = data?.loaded;
  const modelEnabled = data?.enabled;
  const modelStatus = !modelEnabled ? "Model Not Loaded" : (modelLoaded ? "Model Loaded" : "Model Error");
  
  // Data status
  let dataStatus = "Stream Offline";
  let isReceiving = false;
  if (status?.running) {
    if (status.actual_sample_fps === 0 || !status.actual_sample_fps) {
      dataStatus = "Stream Offline";
    } else if (data?.fps && data.fps > 0) {
      dataStatus = "Receiving Frames";
      isReceiving = true;
    } else {
      dataStatus = "Waiting for Lab Stream";
    }
  } else {
    dataStatus = "System Stopped";
  }

  const statusClass = !modelEnabled 
    ? "opacity-50 border-zinc-800" 
    : (isReceiving ? "hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 border-emerald-500/10" : "hover:shadow-[0_4px_20px_-4px_rgba(251,191,36,0.15)] hover:border-amber-500/30 border-amber-500/20");

  return (
    <div className={`hover:-translate-y-1 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border rounded-xl overflow-hidden shadow-lg p-5 flex flex-col gap-4 relative ${statusClass}`}>
      <div className="flex justify-between items-start">
        <div className="flex flex-col">
          <h3 className="text-white font-['Montserrat'] text-lg font-semibold tracking-wide">
            {name === 'pose' ? 'Pose Micro-Motion Gate' : 
             name === 'deep' ? 'Deep Visual Similarity Gate' : 
             name === 'homography_macro' ? 'Homography Macro-Motion Gate' : 
             `${name} Gate`}
          </h3>
          <span className="text-xs font-normal text-slate-400 mt-0.5">
            {data?.fps ? `${data.fps} FPS | ${data.tubelet_frames || '?'} Frames` : 'No frame data'}
          </span>
        </div>
      </div>
      
      <div className="flex flex-col gap-2 bg-black/20 p-2 rounded-lg border border-white/5 text-xs">
        <div className="flex justify-between items-center">
          <span className="text-slate-400 font-['Montserrat']">Model Status:</span>
          <Badge variant="outline" className={modelLoaded ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"}>
            {modelStatus}
          </Badge>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-400 font-['Montserrat']">Data Status:</span>
          <Badge variant="outline" className={isReceiving ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" : (status?.running ? "bg-amber-500/10 text-amber-400 border-amber-500/20" : "bg-slate-800 text-slate-400 border-slate-700")}>
            {dataStatus}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-y-3 gap-x-4 mt-2">
        <div>
          <p className="text-[10px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Threshold</p>
          <p className="text-lg font-bold text-white font-['Space_Grotesk']">{data?.threshold?.toFixed(2) || 'N/A'}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Events</p>
          <p className="text-lg font-bold text-white font-['Space_Grotesk']">{data?.score_count ?? 0}</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Latest Score</p>
          <p className="text-sm font-bold text-slate-300 font-['Space_Grotesk']">N/A</p>
        </div>
        <div>
          <p className="text-[10px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Last Update</p>
          <p className="text-sm font-bold text-slate-300 font-['Space_Grotesk']">N/A</p>
        </div>
      </div>

      <GateScoreChart gateName={name} isOnline={status?.running ?? false} />
    </div>
  );
};
