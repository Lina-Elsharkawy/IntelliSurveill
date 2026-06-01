import { Cpu, Activity } from "lucide-react";
import { VadStatus } from "@/services/vad_api";

export const PipelineTelemetry = ({ status }: { status: VadStatus | null }) => {
  return (
    <>
      {/* Runtime Status */}
      <div className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(46,213,115,0.15)] hover:border-[rgba(46,213,115,0.3)] transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border border-zinc-800 rounded-xl overflow-hidden flex flex-col mb-6 shadow-xl">
        <div className="bg-black/40 px-4 py-3 border-b border-white/5 flex items-center">
          <h3 className="font-semibold text-white text-sm flex items-center font-['Montserrat'] tracking-wide">
            <Activity className="w-4 h-4 mr-2 text-[rgb(46,213,115)]" />
            Runtime Status
          </h3>
        </div>
        <div className="p-0">
          <div className="flex flex-col text-xs font-mono">
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">System Status</span>
              <span className={status?.running ? "text-[rgb(46,213,115)]" : "text-slate-500"}>
                {status?.running ? "Running" : "Stopped"}
              </span>
            </div>
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Camera</span>
              <span className="text-slate-200">
                {status?.camera_key ? status.camera_key.replace(/lab_cam_(\d+)/i, 'Lab Camera $1') : "N/A"}
              </span>
            </div>
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Session ID</span>
              <span className="text-slate-200">{status?.session_id ?? "N/A"}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Pipeline Telemetry */}
      <div className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(50,150,255,0.15)] hover:border-[rgba(50,150,255,0.3)] transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border border-zinc-800 rounded-xl overflow-hidden flex flex-col shadow-xl">
        <div className="bg-black/40 px-4 py-3 border-b border-white/5">
          <h3 className="font-semibold text-white text-sm flex items-center font-['Montserrat'] tracking-wide">
            <Cpu className="w-4 h-4 mr-2 text-[rgb(50,150,255)]" />
            Processing Telemetry
          </h3>
        </div>
        <div className="p-0">
          <div className="flex flex-col text-xs font-mono">
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Sampled Frames</span>
              <span className="text-slate-200">{status?.sampled_frame_count?.toLocaleString() ?? 0}</span>
            </div>
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Processed</span>
              <span className="text-slate-200">{status?.processed_frame_count?.toLocaleString() ?? 0}</span>
            </div>
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Dropped</span>
              <span className={`text-slate-200 ${status?.dropped_frame_count ? 'text-red-400' : ''}`}>
                {status?.dropped_frame_count?.toLocaleString() ?? 0}
              </span>
            </div>
            <div className="flex justify-between px-4 py-2 border-b border-white/5 hover:bg-white/5">
              <span className="text-slate-400">Active Tracks</span>
              <span className="text-slate-200">{status?.active_track_buffer_count ?? 0}</span>
            </div>
          </div>
          {status?.last_error && (
            <div className="m-3 mt-0 p-3 bg-red-500/10 border border-red-500/20 rounded-md text-red-400 text-xs">
              <strong className="block mb-1 text-red-300">Last Error:</strong>
              {status.last_error}
            </div>
          )}
        </div>
      </div>
    </>
  );
};
