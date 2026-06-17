import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { vadApi, VadStatus, VadConfig, VadEvent, VadEventDetails } from "@/services/vad_api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ShieldAlert, Activity, AlertCircle } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";

import { EventGrid } from "@/components/vad/EventGrid";
import { EventTable } from "@/components/vad/EventTable";
import { EvidenceModal } from "@/components/vad/EvidenceModal";
import { ControlPanel } from "@/components/vad/ControlPanel";
import { PipelineTelemetry } from "@/components/vad/PipelineTelemetry";
import { ConsoleLogs, LogEntry } from "@/components/vad/ConsoleLogs";
import { EventToolbar, EventFilters } from "@/components/vad/EventToolbar";
import { EmptyState } from "@/components/vad/EmptyState";
import { filterAndSortVadEvents, isStreamOffline as getIsStreamOffline } from "@/components/vad/vadLabUtils";

export const VadLab = () => {
  const { toast } = useToast();
  const [status, setStatus] = useState<VadStatus | null>(null);
  const [config, setConfig] = useState<VadConfig | null>(null);
  const [events, setEvents] = useState<VadEvent[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  
  const [filters, setFilters] = useState<EventFilters>({
    gate: 'all',
    status: 'all',
    evidence: 'all',
    sortBy: 'newest',
    viewMode: 'cards'
  });

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const itemsPerPage = 12;

  // Reset pagination when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [filters]);

  const [selectedEvent, setSelectedEvent] = useState<VadEvent | null>(null);
  const [evidenceData, setEvidenceData] = useState<VadEventDetails | null>(null);
  const [isEvidenceLoading, setIsEvidenceLoading] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  const addLog = useCallback((message: string, type: "info" | "error" | "success" = "info") => {
    setLogs(prev => [{ time: new Date().toLocaleTimeString(), message, type }, ...prev].slice(0, 50));
  }, []);

  const fetchData = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const [statusRes, configRes, eventsRes] = await Promise.all([
        vadApi.getStatus(),
        vadApi.getConfig(),
        vadApi.getEvents(undefined, 100)
      ]);
      setStatus(statusRes);
      setConfig(configRes);
      setEvents(eventsRes.events || []);
      setLastRefreshed(new Date());
    } catch (err: any) {
      if (!silent) {
        addLog(`Failed to fetch data: ${err.message}`, "error");
        toast({ title: "Connection Error", description: err.message, variant: "destructive" });
      }
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, [addLog, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (autoRefresh) {
      interval = setInterval(() => {
        fetchData(true);
      }, 2000);
    }
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const handleStart = async () => {
    try {
      await vadApi.start();
      addLog("RTSP Sampler started", "success");
      await fetchData();
    } catch (err: any) {
      addLog(`Failed to start: ${err.message}`, "error");
      toast({ title: "Start Error", description: err.message, variant: "destructive" });
    }
  };

  const handleStop = async () => {
    try {
      await vadApi.stop();
      addLog("RTSP Sampler stopped", "success");
      await fetchData();
    } catch (err: any) {
      addLog(`Failed to stop: ${err.message}`, "error");
      toast({ title: "Stop Error", description: err.message, variant: "destructive" });
    }
  };

  const handleRestart = async () => {
    try {
      addLog("Restarting sampler...", "info");
      await vadApi.stop();
      await new Promise(r => setTimeout(r, 1000));
      await vadApi.start();
      addLog("Sampler restarted successfully", "success");
      await fetchData();
    } catch (err: any) {
      addLog(`Failed to restart: ${err.message}`, "error");
      toast({ title: "Restart Error", description: err.message, variant: "destructive" });
    }
  };



  const viewEvidence = async (event: VadEvent) => {
    setSelectedEvent(event);
    setEvidenceData(null);
    setIsEvidenceLoading(true);
    try {
      const res = await vadApi.getEventDetails(event.id);
      setEvidenceData(res);
      addLog(`Loaded evidence for event ${event.id}`, "success");
    } catch (err: any) {
      addLog(`Failed to load evidence: ${err.message}`, "error");
      toast({ title: "Evidence Error", description: err.message, variant: "destructive" });
    } finally {
      setIsEvidenceLoading(false);
    }
  };

  // Only gate-name filtering is applied at the page level.
  // The status and evidence filters are intentionally delegated to the
  // EventGrid/EventTable components, which receive the full paginatedEvents slice.
  const filteredEvents = filterAndSortVadEvents(events, filters);

  const totalPages = Math.ceil(filteredEvents.length / itemsPerPage);
  const paginatedEvents = filteredEvents.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  const isStreamOffline = getIsStreamOffline(status);

  return (
    <DashboardLayout>
      <div className="anomaly-page-wrapper flex flex-col h-full space-y-6 w-full max-w-[1600px] mx-auto animate-in fade-in duration-500">
        
        {/* Header Area */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-border pb-6 relative z-10 mt-2">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-gradient-to-br from-emerald-500/20 to-emerald-500/5 rounded-xl border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.15)]">
                <ShieldAlert className="h-7 w-7 text-emerald-400" />
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-foreground" style={{ fontFamily: "'Montserrat', sans-serif" }}>
                VAD Security Lab
              </h1>
            </div>
          </div>
        </div>

        {/* Global System State Banner */}
        <div className={`p-4 rounded-xl border flex items-center justify-between shadow-lg ${
          !status?.running ? 'bg-slate-900/50 border-slate-700' :
          isStreamOffline ? 'bg-teal-950/30 border-teal-500/30' :
          'bg-[rgba(46,213,115,0.05)] border-[rgba(46,213,115,0.2)]'
        }`}>
          <div className="flex items-center gap-4">
            {status?.running ? (
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded-full ${isStreamOffline ? 'bg-teal-500' : 'bg-[rgb(46,213,115)] animate-pulse'}`}></div>
                <span className={`font-['Montserrat'] font-bold ${isStreamOffline ? 'text-teal-400' : 'text-[rgb(46,213,115)]'}`}>
                  {isStreamOffline ? 'WAITING FOR STREAM' : 'SYSTEM ACTIVE'}
                </span>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full bg-slate-500"></div>
                <span className="font-['Montserrat'] font-bold text-slate-400">System Stopped</span>
              </div>
            )}
            
            <div className="h-6 w-px bg-white/10 mx-2"></div>
            
            <div className="flex items-center gap-2">
              <span className="text-slate-500 text-xs uppercase tracking-widest font-semibold">Camera</span>
              <span className="text-slate-300 font-mono text-sm">
                {config?.camera_key ? config.camera_key.replace(/lab_cam_(\d+)/i, 'Lab Camera $1') : "N/A"}
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-6">
            <div className="flex flex-col text-right">
              <span className="text-slate-500 text-[10px] uppercase tracking-widest font-semibold">Stream Status</span>
              <span className={`font-mono text-sm ${!status?.running ? 'text-slate-400' : isStreamOffline ? 'text-teal-400' : 'text-emerald-400'}`}>
                {!status?.running ? 'Offline' : isStreamOffline ? 'Stream Offline' : 'Receiving'}
              </span>
            </div>
            {status?.running && !isStreamOffline && status?.actual_sample_fps !== undefined && (
              <div className="flex flex-col text-right">
                <span className="text-slate-500 text-[10px] uppercase tracking-widest font-semibold">FPS</span>
                <span className="text-emerald-400 font-mono text-sm font-bold">{status.actual_sample_fps.toFixed(1)}</span>
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
          
          {/* Left Column: Controls & Status (Col Span 3) */}
          <div className="space-y-6 xl:col-span-3">
            <ControlPanel 
              status={status}
              isLoading={isLoading}
              autoRefresh={autoRefresh}
              setAutoRefresh={setAutoRefresh}
              lastRefreshed={lastRefreshed}
              handleStart={handleStart}
              handleStop={handleStop}
              handleRestart={handleRestart}
              fetchData={fetchData}
            />

            <PipelineTelemetry status={status} />
          </div>

          {/* Right Column: Gates & Evidence (Col Span 9) */}
          <div className="space-y-6 xl:col-span-9 flex flex-col">
            


            {/* Visual Evidence Area */}
            <div className="hover:-translate-y-1 hover:shadow-[0_4px_20px_-4px_rgba(16,185,129,0.15)] hover:border-emerald-500/30 transition-all duration-300 bg-zinc-950/50 backdrop-blur-sm border border-zinc-800 rounded-xl flex-1 flex flex-col overflow-hidden p-6 shadow-xl">
              
                  <div className="border-b border-white/5 pb-4 mb-4">
                    <div className="flex justify-between items-center">
                      <div>
                        <h2 className="text-lg font-semibold text-white font-['Montserrat'] tracking-wide flex items-center">
                          Anomaly Evidence Explorer
                        </h2>
                        <p className="text-slate-400 text-sm mt-1">
                          Stored Evidence Objects: {status?.evidence_object_count?.toLocaleString() ?? 0}
                        </p>
                      </div>
                    </div>
                  </div>
                  
                  <EventToolbar filters={filters} setFilters={setFilters} />
                  
                  <div className="flex-1 flex flex-col">
                    {filters.viewMode === 'cards' ? (
                      <EventGrid items={paginatedEvents} viewEvidence={viewEvidence} />
                    ) : (
                      <EventTable items={paginatedEvents} viewEvidence={viewEvidence} />
                    )}
                  </div>

                  {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-6 pt-4 border-t border-white/5">
                      <span className="text-xs text-slate-500">
                        Showing {(currentPage - 1) * itemsPerPage + 1} - {Math.min(currentPage * itemsPerPage, filteredEvents.length)} of {filteredEvents.length} events
                      </span>
                      <div className="flex items-center gap-2">
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="bg-white/5 border-white/10 text-slate-300 hover:bg-white/10"
                          disabled={currentPage === 1}
                          onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                        >
                          Previous
                        </Button>
                        <span className="text-xs text-slate-400 font-mono px-3">
                          Page {currentPage} of {totalPages}
                        </span>
                        <Button 
                          variant="outline" 
                          size="sm" 
                          className="bg-white/5 border-white/10 text-slate-300 hover:bg-white/10"
                          disabled={currentPage === totalPages}
                          onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                        >
                          Next
                        </Button>
                      </div>
                    </div>
                  )}
            </div>

          </div>
        </div>
      </div>

      <EvidenceModal 
        selectedEvent={selectedEvent}
        evidenceData={evidenceData}
        isEvidenceLoading={isEvidenceLoading}
        onClose={() => setSelectedEvent(null)}
      />
    </DashboardLayout>
  );
};
export default VadLab;
