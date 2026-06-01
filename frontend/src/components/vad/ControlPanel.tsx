import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Play, Square, RefreshCw, Camera, Activity, Power } from "lucide-react";
import { VadStatus } from "@/services/vad_api";
import { useState } from "react";

export const ControlPanel = ({
  status,
  isLoading,
  autoRefresh,
  setAutoRefresh,
  lastRefreshed,
  handleStart,
  handleStop,
  handleRestart,
  fetchData
}: {
  status: VadStatus | null;
  isLoading: boolean;
  autoRefresh: boolean;
  setAutoRefresh: (val: boolean) => void;
  lastRefreshed: Date | null;
  handleStart: () => Promise<void>;
  handleStop: () => Promise<void>;
  handleRestart: () => Promise<void>;
  fetchData: () => void;
}) => {
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);

  const onStart = async () => {
    setIsStarting(true);
    await handleStart();
    setIsStarting(false);
  };

  const onStop = async () => {
    setIsStopping(true);
    await handleStop();
    setIsStopping(false);
  };

  const onRestart = async () => {
    setIsRestarting(true);
    await handleRestart();
    setIsRestarting(false);
  };

  const isAnyActionRunning = isStarting || isStopping || isRestarting || isLoading;

  return (
    <div className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(46,213,115,0.15)] hover:border-[rgba(46,213,115,0.3)] transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border border-zinc-800 rounded-xl overflow-hidden shadow-xl flex flex-col">
      <div className="bg-black/40 px-4 py-3 border-b border-white/5 flex justify-between items-center">
        <h3 className="font-semibold text-white text-sm flex items-center font-['Montserrat'] tracking-wide">
          <Activity className="w-4 h-4 mr-2 text-[rgb(46,213,115)]" />
          Pipeline Controls
        </h3>
      </div>
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <Button 
            className={`text-black font-semibold transition-all ${status?.running ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-[rgb(46,213,115)] hover:bg-[rgb(36,193,95)] hover:shadow-[0_0_15px_rgba(46,213,115,0.4)]'}`}
            onClick={onStart}
            disabled={status?.running || isAnyActionRunning}
          >
            {isStarting ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />} 
            {isStarting ? "Starting..." : "Start"}
          </Button>
          <Button 
            variant="destructive" 
            className={`transition-all font-semibold ${!status?.running ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-red-600 hover:bg-red-700'}`}
            onClick={onStop}
            disabled={!status?.running || isAnyActionRunning}
          >
            {isStopping ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <Square className="w-4 h-4 mr-2" />} 
            {isStopping ? "Stopping..." : "Stop"}
          </Button>
        </div>
        
        <div className="grid grid-cols-1">
           <Button 
             variant="outline" 
             className="w-full border-white/10 bg-white/5 hover:bg-white/10 text-xs text-slate-300" 
             onClick={onRestart}
             disabled={isAnyActionRunning}
           >
             {isRestarting ? <RefreshCw className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Power className="w-3.5 h-3.5 mr-2" />} 
             {isRestarting ? "Restarting..." : "Restart"}
           </Button>
        </div>
        
        <div className="grid grid-cols-1">
          <Button variant="outline" className="border-white/10 bg-white/5 hover:bg-white/10 text-xs text-slate-300" onClick={() => fetchData()} disabled={isLoading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-2 ${isLoading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>

        <div className="flex flex-col gap-2 pt-3 border-t border-white/5">
          <div className="flex items-center justify-between">
            <Label htmlFor="auto-refresh" className="text-slate-400 text-xs cursor-pointer">Auto-refresh (2s)</Label>
            <Switch id="auto-refresh" checked={autoRefresh} onCheckedChange={setAutoRefresh} />
          </div>

          {lastRefreshed && (
            <div className="text-[10px] text-slate-500 text-right font-mono mt-1">
              Updated: {lastRefreshed.toLocaleTimeString()}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
