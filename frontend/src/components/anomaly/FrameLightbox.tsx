import React, { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import {
  ChevronLeft, ChevronRight, X, Play, Pause,
  Columns, ArrowLeftRight, Film, Users, Video
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { evidenceUrl } from "@/services/anomalyCandidatesService";

export type FrameType = "person" | "context" | "representative";

interface FrameLightboxProps {
  /** The frames shown by default (the "active" gallery) */
  frames: string[];
  initialIndex?: number;
  frameType: FrameType;
  /** Pass both arrays to enable compare mode */
  personFrames?: string[];
  contextFrames?: string[];
  representativeFrame?: string;
  /** Start autoplay immediately (used by Play Sequence buttons) */
  initialPlaying?: boolean;
  onClose: () => void;
}

const PLAYBACK_INTERVAL_MS = 400;

const TYPE_LABEL: Record<FrameType, string> = {
  person: "Person Crop",
  context: "Context Frame",
  representative: "Representative Frame",
};

const TYPE_COLOR: Record<FrameType, string> = {
  person: "bg-blue-600",
  context: "bg-emerald-700",
  representative: "bg-purple-700",
};

export function FrameLightbox({
  frames,
  initialIndex = 0,
  frameType,
  personFrames = [],
  contextFrames = [],
  representativeFrame,
  initialPlaying = false,
  onClose,
}: FrameLightboxProps) {
  const safeFrames = frames.filter(Boolean);
  const safeTotal = Math.max(1, safeFrames.length);
  const [idx, setIdx] = useState(Math.min(Math.max(initialIndex, 0), safeFrames.length > 0 ? safeFrames.length - 1 : 0));
  const [compareMode, setCompareMode] = useState(false);
  const [playing, setPlaying] = useState(initialPlaying);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const total = safeFrames.length;
  const canCompare =
    frameType !== "representative" &&
    personFrames.length > 0 &&
    contextFrames.length > 0;

  // ── Navigation helpers ────────────────────────────────────────────
  const goPrev = useCallback(() => setIdx(i => (i - 1 + safeTotal) % safeTotal), [safeTotal]);
  const goNext = useCallback(() => setIdx(i => (i + 1) % safeTotal), [safeTotal]);

  // ── Keyboard ─────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
      if (e.key === " ") { e.preventDefault(); setPlaying(p => !p); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [goPrev, goNext, onClose]);

  // ── Playback ─────────────────────────────────────────────────────
  useEffect(() => {
    if (playing) {
      intervalRef.current = setInterval(goNext, PLAYBACK_INTERVAL_MS);
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [playing, goNext]);

  // ── Compare: mirror index across arrays ──────────────────────────
  const pairedFrames = frameType === "person" ? contextFrames : personFrames;
  const compareIdx = pairedFrames.length > 0 ? Math.min(idx, pairedFrames.length - 1) : 0;

  const activeRef = safeFrames[idx] ?? representativeFrame ?? "";
  const mainUrl = evidenceUrl(activeRef) ?? "";
  const compareUrl = compareMode
    ? (frameType === "person"
        ? evidenceUrl(contextFrames[compareIdx])
        : evidenceUrl(personFrames[compareIdx]))
    : undefined;
  const compareLabel = frameType === "person" ? "Context Frame" : "Person Crop";

  return createPortal(
    <div
      className="fixed inset-0 z-[200] flex flex-col bg-black/95 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* ── Top bar ── */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-900/80 border-b border-slate-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          <Badge className={`text-white text-xs ${TYPE_COLOR[frameType]}`}>
            {TYPE_LABEL[frameType]}
          </Badge>
          <span className="text-slate-400 text-sm font-mono">
            Frame {total ? idx + 1 : 0} / {total}
          </span>
          <span className="hidden sm:inline text-xs text-slate-600">Esc closes · ←/→ navigates · Space plays</span>
        </div>

        <div className="flex items-center gap-2">
          {/* Playback */}
          <Button
            size="sm"
            variant="outline"
            className="border-slate-700 text-slate-300 hover:bg-slate-800 text-xs h-7 px-2 gap-1"
            onClick={() => setPlaying(p => !p)}
            disabled={total <= 1}
            title={playing ? "Pause (Space)" : "Play sequence (Space)"}
          >
            {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {playing ? "Pause" : "Play"}
          </Button>

          {/* Compare toggle */}
          {canCompare && (
            <Button
              size="sm"
              variant={compareMode ? "default" : "outline"}
              className={`text-xs h-7 px-2 gap-1 ${
                compareMode
                  ? "bg-blue-700 hover:bg-blue-600 text-white border-blue-600"
                  : "border-slate-700 text-slate-300 hover:bg-slate-800"
              }`}
              onClick={() => setCompareMode(c => !c)}
              title="Compare with paired frame"
            >
              <Columns className="h-3 w-3" />
              Compare
            </Button>
          )}

          <Button
            size="sm"
            variant="ghost"
            className="text-slate-400 hover:text-white h-7 w-7 p-0"
            onClick={onClose}
            title="Close (Esc)"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* ── Main viewer ── */}
      <div className="flex-1 min-h-0 flex items-center justify-center relative px-14 py-4">
        {/* Prev button */}
        <button
          onClick={goPrev}
          disabled={total <= 1}
          className="absolute left-2 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-10 w-10 rounded-full bg-slate-800/80 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed border border-slate-700 text-slate-300 hover:text-white transition-all"
          title="Previous (←)"
        >
          <ChevronLeft className="h-5 w-5" />
        </button>

        {/* Image(s) */}
        {total === 0 ? (
          <div className="rounded-lg border border-slate-800 bg-slate-900 px-6 py-4 text-sm text-slate-400">
            No frame image is available for this evidence item.
          </div>
        ) : compareMode && compareUrl ? (
          <div className="flex gap-3 h-full w-full max-w-5xl">
            <div className="flex-1 flex flex-col min-h-0">
              <span className="text-xs text-center text-blue-400 font-medium mb-1 flex items-center justify-center gap-1">
                <Users className="h-3 w-3" /> {TYPE_LABEL[frameType]} #{idx + 1}
              </span>
              <div className="flex-1 bg-slate-900 rounded-lg border border-slate-700 flex items-center justify-center overflow-hidden">
                <img
                  src={mainUrl}
                  alt={`${TYPE_LABEL[frameType]} ${idx + 1}`}
                  className="max-w-full max-h-full object-contain"
                  draggable={false}
                />
              </div>
            </div>
            <div className="flex items-center justify-center flex-shrink-0">
              <ArrowLeftRight className="h-4 w-4 text-slate-600" />
            </div>
            <div className="flex-1 flex flex-col min-h-0">
              <span className="text-xs text-center text-emerald-400 font-medium mb-1 flex items-center justify-center gap-1">
                <Video className="h-3 w-3" /> {compareLabel} #{compareIdx + 1}
              </span>
              <div className="flex-1 bg-slate-900 rounded-lg border border-slate-700 flex items-center justify-center overflow-hidden">
                <img
                  src={compareUrl}
                  alt={`${compareLabel} ${compareIdx + 1}`}
                  className="max-w-full max-h-full object-contain"
                  draggable={false}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="h-full max-w-4xl w-full flex items-center justify-center">
            <img
              key={idx}
              src={mainUrl}
              alt={`${TYPE_LABEL[frameType]} ${idx + 1}`}
              className="max-w-full max-h-full object-contain rounded-lg select-none"
              draggable={false}
              style={{ imageRendering: "crisp-edges" }}
            />
          </div>
        )}

        {/* Next button */}
        <button
          onClick={goNext}
          disabled={total <= 1}
          className="absolute right-2 top-1/2 -translate-y-1/2 z-10 flex items-center justify-center h-10 w-10 rounded-full bg-slate-800/80 hover:bg-slate-700 disabled:opacity-30 disabled:cursor-not-allowed border border-slate-700 text-slate-300 hover:text-white transition-all"
          title="Next (→)"
        >
          <ChevronRight className="h-5 w-5" />
        </button>
      </div>

      {/* ── Filmstrip / thumbnail strip ── */}
      <div className="flex-shrink-0 bg-slate-900/80 border-t border-slate-800 px-4 py-2">
        <div className="flex items-center gap-2 mb-1">
          <Film className="h-3 w-3 text-slate-500" />
          <span className="text-xs text-slate-500">All frames — click to jump</span>
          <span className="text-xs text-slate-600 ml-auto">← → or Space to play</span>
        </div>
        <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
          {safeFrames.map((ref, i) => {
            const url = evidenceUrl(ref);
            return (
              <button
                key={i}
                onClick={() => { setIdx(i); setPlaying(false); }}
                className={`flex-shrink-0 relative rounded border-2 transition-all overflow-hidden ${
                  i === idx
                    ? "border-blue-500 ring-1 ring-blue-400/40 scale-105"
                    : "border-slate-700 hover:border-slate-500 opacity-60 hover:opacity-100"
                }`}
                style={{ width: 48, height: 36 }}
                title={`Frame ${i + 1}`}
              >
                <img
                  src={url}
                  alt={`Frame ${i + 1}`}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
                {i === idx && (
                  <div className="absolute inset-0 border border-blue-400/30 rounded pointer-events-none" />
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>,
    document.body
  );
}
