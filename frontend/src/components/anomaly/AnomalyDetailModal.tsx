import React, { useState, useEffect } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Camera, Activity, AlertTriangle, Target, Info, FileText,
  CheckCircle, XCircle, HelpCircle, Leaf, ChevronRight, Zap, Eye, Play, Maximize2
} from "lucide-react";
import {
  AnomalyCandidate, getAnomalyCandidate, reviewAnomalyCandidate, evidenceUrl
} from "@/services/anomalyCandidatesService";
import { FrameLightbox, FrameType } from "@/components/anomaly/FrameLightbox";
import { toast } from "sonner";

interface AnomalyDetailModalProps {
  selectedAnomaly: AnomalyCandidate | null;
  onClose: () => void;
  formatDate: (dateString: string) => string;
  onRefresh?: () => void;
}

const NORMAL_REASONS = [
  "Normal walking",
  "Expected staff movement",
  "Bad crop / tracking issue",
  "Camera or reflection artifact",
  "Other",
];

const fmt3 = (v?: number | null) =>
  v != null ? v.toFixed(3) : "N/A";

const SeverityBadge = ({ severity }: { severity: string }) => {
  const cls =
    severity === "high"
      ? "bg-red-500/10 text-red-400 border-red-500/30"
      : severity === "medium"
        ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
        : "bg-blue-500/10 text-blue-400 border-blue-500/30";
  return (
    <Badge variant="outline" className={cls}>
      {severity.toUpperCase()}
    </Badge>
  );
};

export function AnomalyDetailModal({
  selectedAnomaly,
  onClose,
  formatDate,
  onRefresh,
}: AnomalyDetailModalProps) {
  const [detail, setDetail] = useState<AnomalyCandidate | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [calibrationReason, setCalibrationReason] = useState<string>("Normal walking");

  // Lightbox state
  const [lightbox, setLightbox] = useState<{
    frames: string[];
    index: number;
    type: FrameType;
    initialPlaying?: boolean;
  } | null>(null);

  const openLightbox = (frames: string[], index: number, type: FrameType, initialPlaying = false) => {
    const safeFrames = frames.filter(Boolean);
    if (safeFrames.length === 0) return;
    setLightbox({ frames: safeFrames, index: Math.min(Math.max(index, 0), safeFrames.length - 1), type, initialPlaying });
  };

  // Fetch full detail when modal opens
  useEffect(() => {
    if (!selectedAnomaly) { setDetail(null); return; }
    setDetail(selectedAnomaly); // show list data immediately
    getAnomalyCandidate(selectedAnomaly.id)
      .then(setDetail)
      .catch(err => console.warn("Detail fetch failed, using list data:", err));
  }, [selectedAnomaly?.id]);

  if (!selectedAnomaly) return null;

  const a = detail ?? selectedAnomaly;
  const representativeRef = a.representativeFrameRef || a.imageRef || "";
  const personFrames = (a.personFrameRefs || []).filter(Boolean);
  const contextFrames = (a.contextFrameRefs || []).filter(Boolean);

  const handleReview = async (
    decision: "confirmed" | "dismissed" | "uncertain" | "normal_calibration",
    notes?: string
  ) => {
    try {
      setIsSubmitting(true);
      await reviewAnomalyCandidate(a.id, { decision, notes });
      const labels: Record<string, string> = {
        confirmed: "Confirmed as real anomaly",
        dismissed: "Dismissed as false positive",
        uncertain: "Marked as uncertain",
        normal_calibration: "Saved as calibration sample",
      };
      toast.success(labels[decision] ?? "Review saved");
      if (onRefresh) onRefresh();
      onClose();
    } catch (error) {
      console.error("Error reviewing anomaly:", error);
      toast.error("Failed to submit review");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Score interpretation
  const pn = a.personScoreNorm ?? 0;
  const cn = a.contextScoreNorm ?? 0;
  const BothHigh = pn > 0.5 && cn > 0.5;
  const scoreInterpretation =
    a.personScoreNorm != null && a.contextScoreNorm != null
      ? BothHigh
        ? "Both streams elevated"
        : pn > cn
          ? "Person stream dominant"
          : "Context stream dominant"
      : null;

  const isAboveThreshold =
    a.finalScore != null && a.thresholdValue != null && a.finalScore > a.thresholdValue;
  const llmSaysNormal =
    a.parsedDecision?.alert_decision?.toLowerCase() === "no";
  const contradictionNote =
    isAboveThreshold && llmSaysNormal
      ? "Distribution model flagged this event, but reasoning judged visible behavior as normal."
      : null;

  // Motion stats keys of interest
  const motionKeys = [
    "expected_frame_step", "raw_frame_gaps", "gap_count", "lost_frames",
    "track_instability", "max_speed_norm", "avg_speed_norm",
    "max_turn_angle", "avg_turn_angle", "max_turn_speed",
  ];

  return (
    <>
      <Dialog open={!!selectedAnomaly} onOpenChange={onClose}>
      <DialogContent
        className="max-w-6xl h-[92dvh] max-h-[92dvh] flex flex-col p-0 overflow-hidden anomaly-modal-glass text-slate-100"
        onPointerDownOutside={(e) => { if (lightbox) e.preventDefault(); }}
        onInteractOutside={(e) => { if (lightbox) e.preventDefault(); }}
        onEscapeKeyDown={(e) => { if (lightbox) e.preventDefault(); }}
      >

        {/* ── Header ── */}
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-white/5 flex-shrink-0 bg-white/5">
          <div className="flex items-start justify-between gap-4">
            <DialogTitle className="text-xl font-bold flex items-center gap-2">
              <AlertTriangle className={`h-5 w-5 flex-shrink-0 ${a.severity === "high" ? "text-red-400" :
                  a.severity === "medium" ? "text-amber-400" : "text-blue-400"
                }`} />
              Anomaly #{a.id}
              {isAboveThreshold && (
                <Badge className="ml-2 bg-red-600 text-white text-xs">ABOVE THRESHOLD</Badge>
              )}
            </DialogTitle>
            <div className="flex flex-wrap gap-2 justify-end">
              <SeverityBadge severity={a.severity} />
              <Badge variant="secondary" className="bg-slate-800 capitalize text-slate-300">
                {a.status.replace(/_/g, " ")}
              </Badge>
              {a.priority && (
                <Badge variant="outline" className="border-slate-600 text-slate-400 text-xs">
                  {a.priority.replace(/_/g, " ")}
                </Badge>
              )}
            </div>
          </div>
          <DialogDescription className="text-slate-400 text-xs mt-1">
            Cam {a.cameraId ?? "?"} · Track {a.trackId ?? "?"} · {formatDate(a.createdAt)}
          </DialogDescription>
        </DialogHeader>

        <div
          className="flex-1 min-h-0 overflow-y-auto overscroll-contain [&::-webkit-scrollbar]:w-2 [&::-webkit-scrollbar-track]:bg-slate-950 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-700 hover:[&::-webkit-scrollbar-thumb]:bg-slate-600"
          style={{ scrollbarWidth: "thin", scrollbarColor: "#334155 #020617" }}
        >
          <div className="p-6 space-y-6">

            {/* ── Row 1: Evidence visuals ── */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

              {/* Representative Frame */}
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-1">
                  <Eye className="h-3 w-3" /> Representative Frame
                </h4>
                {representativeRef ? (
                  <button
                    className="block w-full rounded-lg overflow-hidden border border-slate-700 bg-black aspect-video cursor-zoom-in group relative"
                    onClick={() => openLightbox([representativeRef], 0, "representative")}
                    title="Click to enlarge"
                  >
                    <img
                      src={evidenceUrl(representativeRef)}
                      alt="Representative Frame"
                      className="w-full h-full object-contain group-hover:brightness-110 transition-all"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <div className="bg-black/50 rounded-full p-2">
                        <Maximize2 className="h-5 w-5 text-white" />
                      </div>
                    </div>
                  </button>
                ) : (
                  <div className="rounded-lg border border-slate-700 bg-slate-800/50 aspect-video flex items-center justify-center">
                    <Camera className="h-8 w-8 text-slate-600" />
                  </div>
                )}
              </div>

              {/* Person Crop Frames */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-1">
                    <Camera className="h-3 w-3" /> Person Crop Frames
                    {personFrames.length > 0 && (
                      <span className="text-slate-500 normal-case font-normal">({personFrames.length})</span>
                    )}
                  </h4>
                  {personFrames.length > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 text-[10px] text-slate-400 hover:text-white gap-1"
                      onClick={() => openLightbox(personFrames, 0, "person", true)}
                    >
                      <Play className="h-3 w-3" /> Play
                    </Button>
                  )}
                </div>
                {personFrames.length > 0 ? (
                  <>
                    <p className="text-[10px] text-slate-600 italic">Click any frame to enlarge · +N to see all</p>
                    <div className="flex flex-wrap gap-1">
                      {personFrames.slice(0, 8).map((ref, i) => (
                        <button
                          key={i}
                          className="cursor-zoom-in rounded border border-slate-700 bg-slate-800 hover:border-blue-500 hover:ring-1 hover:ring-blue-500/30 transition-all overflow-hidden flex-shrink-0"
                          style={{ width: 56, height: 56 }}
                          onClick={() => openLightbox(personFrames, i, "person")}
                          title={`Person frame ${i + 1} — click to enlarge`}
                        >
                          <img
                            src={evidenceUrl(ref)}
                            alt={`Person ${i + 1}`}
                            className="w-full h-full object-cover hover:brightness-110 transition-all"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                        </button>
                      ))}
                      {personFrames.length > 8 && (
                        <button
                          className="cursor-pointer flex-shrink-0 flex flex-col items-center justify-center rounded border border-dashed border-blue-500/40 bg-blue-500/5 hover:bg-blue-500/10 text-blue-400 hover:text-blue-300 transition-all text-xs font-medium gap-0.5"
                          style={{ width: 56, height: 56 }}
                          onClick={() => openLightbox(personFrames, 8, "person")}
                          title={`View all ${personFrames.length} person frames`}
                        >
                          <span className="text-base leading-none">+{personFrames.length - 8}</span>
                          <span className="text-[9px] opacity-70">more</span>
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-slate-500 italic">No person frames</p>
                )}
              </div>

              {/* Context Frames */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wide flex items-center gap-1">
                    <Camera className="h-3 w-3" /> Context Frames
                    {contextFrames.length > 0 && (
                      <span className="text-slate-500 normal-case font-normal">({contextFrames.length})</span>
                    )}
                  </h4>
                  {contextFrames.length > 1 && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 text-[10px] text-slate-400 hover:text-white gap-1"
                      onClick={() => openLightbox(contextFrames, 0, "context", true)}
                    >
                      <Play className="h-3 w-3" /> Play
                    </Button>
                  )}
                </div>
                {contextFrames.length > 0 ? (
                  <>
                    <p className="text-[10px] text-slate-600 italic">Click any frame to enlarge · +N to see all</p>
                    <div className="flex flex-wrap gap-1">
                      {contextFrames.slice(0, 8).map((ref, i) => (
                        <button
                          key={i}
                          className="cursor-zoom-in rounded border border-slate-700 bg-slate-800 hover:border-emerald-500 hover:ring-1 hover:ring-emerald-500/30 transition-all overflow-hidden flex-shrink-0"
                          style={{ width: 56, height: 56 }}
                          onClick={() => openLightbox(contextFrames, i, "context")}
                          title={`Context frame ${i + 1} — click to enlarge`}
                        >
                          <img
                            src={evidenceUrl(ref)}
                            alt={`Context ${i + 1}`}
                            className="w-full h-full object-cover hover:brightness-110 transition-all"
                            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                          />
                        </button>
                      ))}
                      {contextFrames.length > 8 && (
                        <button
                          className="cursor-pointer flex-shrink-0 flex flex-col items-center justify-center rounded border border-dashed border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10 text-emerald-400 hover:text-emerald-300 transition-all text-xs font-medium gap-0.5"
                          style={{ width: 56, height: 56 }}
                          onClick={() => openLightbox(contextFrames, 8, "context")}
                          title={`View all ${contextFrames.length} context frames`}
                        >
                          <span className="text-base leading-none">+{contextFrames.length - 8}</span>
                          <span className="text-[9px] opacity-70">more</span>
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="text-xs text-slate-500 italic">No context frames</p>
                )}
              </div>
            </div>

            {/* ── Event Decision Summary ── */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className={`rounded-lg border p-3 ${isAboveThreshold ? "bg-red-500/10 border-red-500/25" : "bg-green-500/10 border-green-500/25"}`}>
                <span className="text-[10px] uppercase tracking-wide text-slate-500 block mb-1">Distribution Status</span>
                <span className={`text-sm font-semibold ${isAboveThreshold ? "text-red-300" : "text-green-300"}`}>
                  {isAboveThreshold ? "Above threshold" : "Below threshold"}
                </span>
                <div className="text-xs text-slate-500 mt-1 font-mono">{fmt3(a.finalScore)} / {fmt3(a.thresholdValue)}</div>
              </div>
              <div className={`rounded-lg border p-3 ${a.parsedDecision?.alert_decision?.toLowerCase() === "yes" ? "bg-red-500/10 border-red-500/25" : "bg-green-500/10 border-green-500/25"}`}>
                <span className="text-[10px] uppercase tracking-wide text-slate-500 block mb-1">Reasoning Decision</span>
                <span className={`text-sm font-semibold ${a.parsedDecision?.alert_decision?.toLowerCase() === "yes" ? "text-red-300" : "text-green-300"}`}>
                  {a.parsedDecision?.alert_decision ? `Alert ${a.parsedDecision.alert_decision.toUpperCase()}` : "Not available"}
                </span>
                {a.parsedDecision?.alert_decision?.toLowerCase() === "yes" ? (
                  <div className="text-xs text-slate-500 mt-1">Reasoning confirmed visible evidence or an active rule.</div>
                ) : isAboveThreshold ? (
                  <div className="text-xs text-slate-500 mt-1">Score flagged it, but reasoning did not confirm an alert.</div>
                ) : null}
              </div>
              <div className="rounded-lg border p-3 bg-slate-900/40 border-slate-700">
                <span className="text-[10px] uppercase tracking-wide text-slate-500 block mb-1">Review Status</span>
                <span className="text-sm font-semibold text-slate-300 capitalize">{a.status.replace(/_/g, " ")}</span>
                <div className="text-xs text-slate-500 mt-1">Human review controls are available below.</div>
              </div>
            </div>

            {/* ── Row 2: Score Breakdown + Reasoning ── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

              {/* Score Breakdown */}
              <div className="anomaly-panel-glass flex flex-col">
                <div className="pb-2 pt-4 px-4 flex items-center justify-between border-b border-white/5">
                  <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-200 tracking-wide font-['Montserrat']">
                    <Activity className="h-4 w-4 text-blue-400" /> Score Breakdown
                  </h3>
                  {isAboveThreshold && (
                    <Badge className="text-[10px] bg-red-600/80 text-white border-red-500 shadow-[0_0_10px_rgba(220,38,38,0.5)]">FLAGGED</Badge>
                  )}
                </div>
                <div className="px-4 py-4 space-y-4 flex-1">

                  {/* Main score row */}
                  <div className="flex items-center gap-3 p-2 rounded-md bg-slate-900/50 border border-slate-700">
                    <div className="flex-1">
                      <span className="text-slate-400 text-xs block">Final Score</span>
                      <span className={`text-lg font-mono font-bold ${isAboveThreshold ? "text-red-400" : "text-green-400"}`}>
                        {fmt3(a.finalScore)}
                      </span>
                    </div>
                    <ChevronRight className="h-4 w-4 text-slate-600" />
                    <div className="flex-1">
                      <span className="text-slate-400 text-xs block">Threshold ({a.thresholdName ?? "—"})</span>
                      <span className="text-lg font-mono font-bold text-slate-300">{fmt3(a.thresholdValue)}</span>
                    </div>
                  </div>

                  {/* Sub-scores */}
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: "Person Score", val: a.personScore },
                      { label: "Context Score", val: a.contextScore },
                      { label: "Person Score Norm", val: a.personScoreNorm },
                      { label: "Context Score Norm", val: a.contextScoreNorm },
                    ].map(({ label, val }) => (
                      <div key={label} className="bg-slate-900/40 rounded p-2">
                        <span className="text-slate-500 text-xs block">{label}</span>
                        <span className="text-slate-200 font-mono text-sm">{fmt3(val)}</span>
                      </div>
                    ))}
                  </div>

                  {/* Score interpretation */}
                  {scoreInterpretation && (
                    <div className={`text-xs p-2 rounded border flex items-center gap-2 ${BothHigh
                        ? "bg-red-500/10 border-red-500/20 text-red-300"
                        : "bg-amber-500/10 border-amber-500/20 text-amber-300"
                      }`}>
                      <Zap className="h-3 w-3 flex-shrink-0" />
                      {scoreInterpretation}
                    </div>
                  )}

                  {/* Candidate reasons */}
                  {a.candidateReasons.length > 0 && (
                    <div>
                      <span className="text-slate-500 text-xs block mb-1">Trigger Reasons</span>
                      <div className="flex flex-wrap gap-1">
                        {a.candidateReasons.map((r, i) => (
                          <Badge key={i} variant="outline" className="bg-red-500/10 text-red-400 border-red-500/20 text-xs">
                            {r}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Reasoning */}
              <div className="anomaly-panel-glass flex flex-col">
                <div className="pb-2 pt-4 px-4 flex items-center justify-between border-b border-white/5">
                  <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-200 tracking-wide font-['Montserrat']">
                    <Target className="h-4 w-4 text-emerald-400" /> LLM Reasoning
                  </h3>
                </div>
                <div className="px-4 py-4 space-y-4 flex-1">

                  {/* Contradiction note */}
                  {contradictionNote && (
                    <div className="text-xs p-2 rounded border bg-amber-500/10 border-amber-500/20 text-amber-300 flex items-start gap-2">
                      <Info className="h-3 w-3 flex-shrink-0 mt-0.5" />
                      {contradictionNote}
                    </div>
                  )}

                  {a.parsedDecision ? (
                    <div className="space-y-3">
                      <div className="flex gap-3">
                        <div>
                          <span className="text-slate-500 text-xs block">Alert</span>
                          <Badge variant="outline" className={
                            a.parsedDecision.alert_decision?.toLowerCase() === "yes"
                              ? "bg-red-500/10 text-red-400 border-red-500/30"
                              : "bg-green-500/10 text-green-400 border-green-500/30"
                          }>
                            {a.parsedDecision.alert_decision?.toUpperCase() ?? "—"}
                          </Badge>
                        </div>
                        <div>
                          <span className="text-slate-500 text-xs block">Severity</span>
                          <Badge variant="outline" className="border-slate-600 text-slate-300">
                            {a.parsedDecision.severity?.toUpperCase() ?? "N/A"}
                          </Badge>
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500 text-xs block mb-1">Decision Reason</span>
                        <p className="text-xs text-slate-300 bg-slate-900/50 p-2 rounded border border-slate-800 leading-relaxed">
                          {a.parsedDecision.decision_reason ?? "No reason provided."}
                        </p>
                      </div>
                    </div>
                  ) : a.llmDecision ? (
                    <p className="text-xs text-slate-300 bg-slate-900/50 p-2 rounded border border-slate-800 whitespace-pre-wrap leading-relaxed">
                      {a.llmDecision}
                    </p>
                  ) : (
                    <p className="text-xs text-slate-500 italic">No LLM decision available.</p>
                  )}

                  {a.narrative && (
                    <div>
                      <span className="text-slate-500 text-xs block mb-1">VLM Narrative</span>
                      <p className="text-xs text-slate-400 bg-slate-900/50 p-2 rounded border border-slate-800 italic leading-relaxed">
                        "{a.narrative}"
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ── Row 3: Gate Decisions + Motion Stats ── */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

              {/* Gate Decisions */}
              {a.gateDecisions && a.gateDecisions.length > 0 && (
                <div className="anomaly-panel-glass flex flex-col">
                  <div className="pb-2 pt-4 px-4 flex items-center justify-between border-b border-white/5">
                    <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-200 tracking-wide font-['Montserrat']">
                      <Zap className="h-4 w-4 text-amber-400" /> Gate Decisions
                    </h3>
                  </div>
                  <div className="px-4 py-4 space-y-3 flex-1">
                    {a.gateDecisions.map((gd, idx) => (
                      <div key={idx} className="flex items-start gap-2 text-xs bg-slate-900/40 rounded p-2 border border-slate-800">
                        <div className="flex-1">
                          <span className="font-medium text-slate-300 block">{gd.gateName}</span>
                          {gd.reason && <span className="text-slate-500 mt-0.5 block">{gd.reason}</span>}
                          {(gd.scoreValue != null || gd.thresholdValue != null) && (
                            <span className="text-slate-500 font-mono">
                              {fmt3(gd.scoreValue)} / {fmt3(gd.thresholdValue)}
                            </span>
                          )}
                        </div>
                        <Badge variant="outline" className={
                          gd.fired
                            ? "text-red-400 border-red-500/30 bg-red-500/10 flex-shrink-0"
                            : "text-green-400 border-green-500/30 bg-green-500/10 flex-shrink-0"
                        }>
                          {gd.fired ? "FIRED" : "PASSED"}
                        </Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Motion Stats */}
              {a.motionStats && Object.keys(a.motionStats).length > 0 && (
                <div className="anomaly-panel-glass flex flex-col">
                  <div className="pb-2 pt-4 px-4 flex items-center justify-between border-b border-white/5">
                    <h3 className="text-sm font-semibold flex items-center gap-2 text-slate-200 tracking-wide font-['Montserrat']">
                      <Activity className="h-4 w-4 text-purple-400" /> Motion Debug
                    </h3>
                  </div>
                  <div className="px-4 py-4 space-y-3 flex-1">

                    {/* Track stability indicator */}
                    {a.motionStats.track_instability === 0 || a.motionStats.track_instability === false ? (
                      <div className="flex items-center gap-2 text-xs text-green-400 mb-2">
                        <CheckCircle className="h-3 w-3" /> Track stable
                      </div>
                    ) : a.motionStats.track_instability ? (
                      <div className="flex items-center gap-2 text-xs text-amber-400 mb-2">
                        <AlertTriangle className="h-3 w-3" /> Track instability detected
                      </div>
                    ) : null}

                    {/* Lost frames warning */}
                    {(a.motionStats.gap_count > 0 || a.motionStats.lost_frames > 0) && (
                      <div className="text-xs text-amber-400 flex items-center gap-1 mb-2">
                        <AlertTriangle className="h-3 w-3" />
                        {a.motionStats.gap_count ?? 0} gaps / {a.motionStats.lost_frames ?? 0} lost frames
                      </div>
                    )}

                    {/* Key stats grid */}
                    <div className="grid grid-cols-2 gap-1">
                      {motionKeys
                        .filter(k => a.motionStats![k] !== undefined && a.motionStats![k] !== null)
                        .map(k => (
                          <div key={k} className="bg-slate-900/40 rounded p-1.5">
                            <span className="text-slate-500 text-[10px] block">{k}</span>
                            <span className="text-slate-300 font-mono text-xs">
                              {typeof a.motionStats![k] === "number"
                                ? a.motionStats![k].toFixed(3)
                                : String(a.motionStats![k])}
                            </span>
                          </div>
                        ))
                      }
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Clip download links (when available) */}
            {(a.personClipRef || a.contextClipRef) && (
              <div className="flex gap-4 text-xs">
                {a.personClipRef && (
                  <a href={evidenceUrl(a.personClipRef)} target="_blank" rel="noreferrer"
                    className="flex items-center gap-1 text-blue-400 hover:text-blue-300">
                    <FileText className="h-3 w-3" /> Person Clip
                  </a>
                )}
                {a.contextClipRef && (
                  <a href={evidenceUrl(a.contextClipRef)} target="_blank" rel="noreferrer"
                    className="flex items-center gap-1 text-blue-400 hover:text-blue-300">
                    <FileText className="h-3 w-3" /> Context Clip
                  </a>
                )}
              </div>
            )}

          </div>
        </div>

        {/* ── Footer: Review actions ── */}
        <DialogFooter className="px-6 py-4 border-t border-white/10 bg-black/40 flex-shrink-0 flex flex-wrap sm:flex-nowrap gap-2 justify-between">

          {/* Calibration group */}
          <div className="flex flex-wrap gap-2 items-center">
            <Select value={calibrationReason} onValueChange={setCalibrationReason}>
              <SelectTrigger className="h-8 text-xs w-48 bg-slate-800 border-slate-700 text-slate-300">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NORMAL_REASONS.map(r => (
                  <SelectItem key={r} value={r} className="text-xs">{r}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              className="border-green-600 text-green-400 hover:bg-green-600/10 text-xs"
              onClick={() => handleReview("normal_calibration", calibrationReason)}
              disabled={isSubmitting}
            >
              <Leaf className="h-3 w-3 mr-1" /> Mark Normal Sample
            </Button>
          </div>

          {/* Review buttons */}
          <div className="flex gap-2 items-center">
            <Button
              size="sm"
              className="bg-red-600 hover:bg-red-700 text-white text-xs"
              onClick={() => handleReview("confirmed")}
              disabled={isSubmitting}
            >
              <CheckCircle className="h-3 w-3 mr-1" /> Confirm
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="border-slate-600 text-slate-300 hover:bg-slate-800 text-xs"
              onClick={() => handleReview("dismissed")}
              disabled={isSubmitting}
            >
              <XCircle className="h-3 w-3 mr-1" /> Dismiss
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="bg-slate-800 text-slate-300 hover:bg-slate-700 text-xs"
              onClick={() => handleReview("uncertain")}
              disabled={isSubmitting}
            >
              <HelpCircle className="h-3 w-3 mr-1" /> Uncertain
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={onClose}
              disabled={isSubmitting}
              className="text-slate-500 hover:text-white text-xs"
            >
              Close
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
      </Dialog>
      {/* ── Lightbox (rendered outside Dialog via portal) ── */}
      {lightbox && (
        <FrameLightbox
          frames={lightbox.frames}
          initialIndex={lightbox.index}
          frameType={lightbox.type}
          personFrames={personFrames}
          contextFrames={contextFrames}
          representativeFrame={representativeRef}
          initialPlaying={lightbox.initialPlaying}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}
