import React from "react"
import { Badge } from "@/components/ui/badge"
import type { AnomalyCandidate } from "@/services/anomalyCandidatesService"

const fmt3 = (v?: number | null) => (v != null ? v.toFixed(3) : "N/A")

const getCardStyle = (severity: string, status: string) => {
  if (status === "discarded") return "status-discarded"
  if (status === "resolved") return "status-resolved"
  switch (severity) {
    case "high": return "severity-high"
    case "medium": return "severity-medium"
    default: return "severity-low"
  }
}

const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
  const rect = e.currentTarget.getBoundingClientRect()
  const x = e.clientX - rect.left
  const y = e.clientY - rect.top
  e.currentTarget.style.setProperty("--mouse-x", `${x}px`)
  e.currentTarget.style.setProperty("--mouse-y", `${y}px`)
}

const formatDate = (dateStr: string) => {
  try { return new Date(dateStr).toLocaleString() } catch { return dateStr }
}

interface AnomalyCardProps {
  anomaly: AnomalyCandidate
  onClick: (anomaly: AnomalyCandidate) => void
}

export function AnomalyCard({ anomaly, onClick }: AnomalyCardProps) {
  return (
    <div
      className={`anomaly-card ${getCardStyle(anomaly.severity, anomaly.status)}`}
      onClick={() => onClick(anomaly)}
      onMouseMove={handleMouseMove}
    >
      <div className="card-content-wrap">
        {/* Card header row */}
        <div className="flex justify-between items-start gap-2 mb-2">
          <p className="font-bold text-sm leading-tight tracking-wide font-['Montserrat']">Anomaly #{anomaly.id}</p>
          <div className="flex flex-wrap gap-1 justify-end">
            <Badge variant="outline" className="text-[9px] py-0 px-1.5 capitalize border-slate-600/50 text-slate-300 bg-slate-800/50 backdrop-blur-sm">
              {anomaly.status.replace(/_/g, " ")}
            </Badge>
          </div>
        </div>

        {/* Meta row */}
        <p className="text-xs text-slate-400 mb-2 font-medium">
          {anomaly.cameraId != null && <span>Cam {anomaly.cameraId}</span>}
          {anomaly.trackId != null && <span className="ml-1 text-slate-500">· Track {anomaly.trackId}</span>}
          <span className="ml-1 text-slate-500">· {formatDate(anomaly.createdAt)}</span>
        </p>

        {/* Scores */}
        {(anomaly.finalScore != null || anomaly.thresholdValue != null) && (
          <div className="flex items-center gap-2 mb-2">
            <div className="h-1.5 flex-1 bg-slate-800/50 rounded-full overflow-hidden">
              <div 
                className={`h-full rounded-full ${anomaly.finalScore && anomaly.thresholdValue && anomaly.finalScore > anomaly.thresholdValue ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.8)]' : 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'}`}
                style={{ width: `${Math.min(100, (anomaly.finalScore || 0) / Math.max(0.01, anomaly.thresholdValue || 1) * 100)}%` }}
              />
            </div>
            <p className="text-xs font-mono text-slate-300">
              <span className={anomaly.finalScore != null && anomaly.thresholdValue != null && anomaly.finalScore > anomaly.thresholdValue ? "text-red-400 font-bold" : ""}>
                {fmt3(anomaly.finalScore)}
              </span>
              <span className="text-slate-500"> / {fmt3(anomaly.thresholdValue)}</span>
            </p>
          </div>
        )}

        {/* Reasons */}
        {anomaly.candidateReasons.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {anomaly.candidateReasons.slice(0, 2).map((r, i) => (
              <Badge key={i} variant="outline" className="text-[9px] py-0.5 px-2 border-slate-700/60 bg-slate-900/40 text-slate-300">
                {r}
              </Badge>
            ))}
            {anomaly.candidateReasons.length > 2 && (
              <Badge variant="outline" className="text-[9px] py-0.5 px-1.5 border-slate-700/60 bg-slate-900/40 text-slate-400">
                +{anomaly.candidateReasons.length - 2}
              </Badge>
            )}
          </div>
        )}
      </div>

      {/* Hover: image + description */}
      <div className="hover-content">
        {anomaly.imageRef && (
          <div className="hover-image">
            <img src={anomaly.imageRef} alt="Preview" />
          </div>
        )}
        <p className="hover-description line-clamp-3">
          {anomaly.narrative ||
            anomaly.parsedDecision?.decision_reason ||
            anomaly.llmDecision ||
            "No description available."}
        </p>
      </div>
    </div>
  )
}
