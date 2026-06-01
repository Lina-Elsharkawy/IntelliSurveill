import { Server } from "lucide-react";

export interface LogEntry {
  time: string;
  message: string;
  type: "info" | "error" | "success";
}

export const ConsoleLogs = ({ logs }: { logs: LogEntry[] }) => {
  return (
    <div className="anomaly-panel-glass flex flex-col h-[300px] overflow-hidden">
      <div className="bg-black/40 px-4 py-3 border-b border-white/5 flex-shrink-0">
        <h3 className="font-semibold text-white text-sm flex items-center font-['Montserrat'] tracking-wide">
          <Server className="w-4 h-4 mr-2 text-[rgb(255,180,50)]" />
          Console Logs
        </h3>
      </div>
      <div className="p-3 overflow-y-auto space-y-1.5 text-xs flex-1 font-mono">
        {logs.length === 0 ? (
          <div className="text-slate-500 text-center italic py-8">Awaiting logs...</div>
        ) : (
          logs.map((log, i) => (
            <div key={i} className="flex gap-2 items-start break-words">
              <span className="text-slate-500 whitespace-nowrap">[{log.time}]</span>
              <span className={log.type === "error" ? "text-red-400" : log.type === "success" ? "text-[rgb(46,213,115)]" : "text-slate-300"}>
                {log.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
