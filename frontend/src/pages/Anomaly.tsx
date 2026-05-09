import { useState, useEffect, useMemo } from "react"
import { AlertTriangle, CheckCircle, Clock, Filter, RefreshCw } from "lucide-react"
import { DashboardLayout } from "@/components/DashboardLayout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { getAnomalyCandidates, AnomalyCandidate } from "@/services/anomalyCandidatesService"
import { AnomalyDetailModal } from "@/components/anomaly/AnomalyDetailModal"

import { AnomalyCard } from "@/components/anomaly/AnomalyCard"

const ITEMS_PER_PAGE = 9

const isNew = (a: AnomalyCandidate) =>
  a.status === "pending" || a.status === "sent_to_llm" || a.status === "sent_to_reasoning"

const Anomaly = () => {
  const [anomalies, setAnomalies] = useState<AnomalyCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [severityFilter, setSeverityFilter] = useState<"all" | "high" | "medium" | "low">("all")
  const [cameraFilter, setCameraFilter] = useState<string>("all")
  const [reasonFilter, setReasonFilter] = useState<string>("all")

  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyCandidate | null>(null)
  const [activeTab, setActiveTab] = useState("new")
  const [currentPage, setCurrentPage] = useState(1)

  const fetchAnomalies = async () => {
    try {
      setError(null)
      const data = await getAnomalyCandidates()
      // Sort newest first
      const sorted = [...data].sort(
        (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      )
      setAnomalies(sorted)
    } catch (err: any) {
      console.error("Failed to fetch anomalies:", err)
      setError(err.message || "Failed to load anomalies")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAnomalies() }, [])

  const formatDate = (dateStr: string) => {
    try { return new Date(dateStr).toLocaleString() } catch { return dateStr }
  }

  // Unique camera IDs for filter
  const cameraIds = useMemo(() => {
    const ids = new Set(anomalies.map(a => a.cameraId).filter(Boolean))
    return Array.from(ids).sort() as number[]
  }, [anomalies])

  // Unique reasons for filter
  const allReasons = useMemo(() => {
    const reasons = new Set<string>()
    anomalies.forEach(a => a.candidateReasons.forEach(r => reasons.add(r)))
    return Array.from(reasons).sort()
  }, [anomalies])

  const filtered = useMemo(() => {
    return anomalies.filter(a => {
      if (severityFilter !== "all" && a.severity !== severityFilter) return false
      if (cameraFilter !== "all" && String(a.cameraId) !== cameraFilter) return false
      if (reasonFilter !== "all" && !a.candidateReasons.includes(reasonFilter)) return false
      return true
    })
  }, [anomalies, severityFilter, cameraFilter, reasonFilter])

  const newAnomalies = filtered.filter(isNew)
  const acknowledgedAnomalies = filtered.filter(a => a.status === "acknowledged")
  const resolvedAnomalies = filtered.filter(a => a.status === "resolved")
  const discardedAnomalies = filtered.filter(a => a.status === "discarded")

  // Stats based on full dataset (unfiltered)
  const totalNew = anomalies.filter(isNew).length
  const totalAck = anomalies.filter(a => a.status === "acknowledged").length
  const totalResolved = anomalies.filter(a => a.status === "resolved").length

  const switchTab = (val: string) => { setActiveTab(val); setCurrentPage(1) }

  const renderCards = (items: AnomalyCandidate[]) => {
    const total = items.length
    const totalPages = Math.ceil(total / ITEMS_PER_PAGE)
    const start = (currentPage - 1) * ITEMS_PER_PAGE
    const page = items.slice(start, start + ITEMS_PER_PAGE)

    if (total === 0) return null

    return (
      <div className="space-y-4">
        <div className="anomaly-cards-container">
          {page.map((anomaly) => (
            <AnomalyCard 
              key={anomaly.id} 
              anomaly={anomaly} 
              onClick={setSelectedAnomaly} 
            />
          ))}
        </div>

        {totalPages > 1 && (
          <div className="flex items-center justify-between pt-3 border-t border-slate-800">
            <span className="text-xs text-slate-500">
              {start + 1}–{Math.min(start + ITEMS_PER_PAGE, total)} of {total}
            </span>
            <div className="flex gap-2 items-center">
              <Button size="sm" variant="outline" onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1}>
                Previous
              </Button>
              <span className="text-xs text-slate-400">Page {currentPage}/{totalPages}</span>
              <Button size="sm" variant="outline" onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    )
  }

  const EmptyState = ({ icon: Icon, msg }: { icon: any, msg: string }) => (
    <div className="text-center py-10 border-2 border-dashed border-border rounded-xl">
      <Icon className="w-10 h-10 text-muted-foreground/20 mx-auto mb-3" />
      <p className="text-muted-foreground text-sm">{msg}</p>
    </div>
  )

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[400px]">
          <p className="text-muted-foreground animate-pulse">Scanning for anomalies...</p>
        </div>
      </DashboardLayout>
    )
  }

  return (
    <DashboardLayout>
      <div className="anomaly-page-wrapper space-y-6">

        {/* Page title + actions */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-3xl font-bold text-foreground">Anomalies</h1>
            <p className="text-muted-foreground text-sm mt-1">Monitor and debug anomaly detection events</p>
          </div>
          <Button variant="outline" size="sm" onClick={fetchAnomalies}>
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="anomaly-stat-card destructive p-5 flex justify-between items-center">
            <div>
              <p className="text-[11px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Pending / Active</p>
              <p className="text-3xl font-bold text-white font-['Space_Grotesk']">{totalNew}</p>
            </div>
            <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20">
              <AlertTriangle className="w-6 h-6 text-red-400 drop-shadow-[0_0_8px_rgba(248,113,113,0.5)]" />
            </div>
          </div>

          <div className="anomaly-stat-card warning p-5 flex justify-between items-center">
            <div>
              <p className="text-[11px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">In Progress</p>
              <p className="text-3xl font-bold text-white font-['Space_Grotesk']">{totalAck}</p>
            </div>
            <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
              <Clock className="w-6 h-6 text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.5)]" />
            </div>
          </div>

          <div className="anomaly-stat-card success p-5 flex justify-between items-center">
            <div>
              <p className="text-[11px] text-slate-400 mb-1 uppercase tracking-widest font-semibold font-['Montserrat']">Resolved</p>
              <p className="text-3xl font-bold text-white font-['Space_Grotesk']">{totalResolved}</p>
            </div>
            <div className="p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
              <CheckCircle className="w-6 h-6 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
            </div>
          </div>
        </div>

        {/* Main list card */}
        <div className="anomaly-panel-glass p-5 mt-8">
          <div className="flex flex-row flex-wrap gap-3 items-center justify-between pb-4 border-b border-white/5 mb-4">
            <h2 className="text-lg font-semibold text-white font-['Montserrat'] tracking-wide">All Anomalies ({filtered.length})</h2>
            <div className="flex flex-wrap gap-2">
              {/* Severity filter */}
              <Select value={severityFilter} onValueChange={(v) => { setSeverityFilter(v as any); setCurrentPage(1) }}>
                <SelectTrigger className="w-36 h-8 text-xs bg-secondary border-border">
                  <SelectValue placeholder="Severity" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Severities</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="low">Low</SelectItem>
                </SelectContent>
              </Select>

              {/* Camera filter */}
              {cameraIds.length > 1 && (
                <Select value={cameraFilter} onValueChange={(v) => { setCameraFilter(v); setCurrentPage(1) }}>
                  <SelectTrigger className="w-32 h-8 text-xs bg-secondary border-border">
                    <SelectValue placeholder="Camera" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Cameras</SelectItem>
                    {cameraIds.map(id => (
                      <SelectItem key={id} value={String(id)}>Cam {id}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}

              {/* Reason filter */}
              {allReasons.length > 1 && (
                <Select value={reasonFilter} onValueChange={(v) => { setReasonFilter(v); setCurrentPage(1) }}>
                  <SelectTrigger className="w-40 h-8 text-xs bg-secondary border-border">
                    <SelectValue placeholder="Reason" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Reasons</SelectItem>
                    {allReasons.map(r => (
                      <SelectItem key={r} value={r}>{r}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>

          <div>
            {error && (
              <div className="text-red-400 text-sm p-3 mb-4 border border-red-500/30 rounded bg-red-500/5">
                {error}
              </div>
            )}

            <Tabs value={activeTab} onValueChange={switchTab}>
              <TabsList className="bg-secondary mb-5">
                <TabsTrigger value="new">
                  Pending <Badge className="ml-2 bg-destructive text-white text-xs">{newAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  In Progress <Badge className="ml-2 bg-warning text-white text-xs">{acknowledgedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="resolved">
                  Resolved <Badge className="ml-2 bg-success text-white text-xs">{resolvedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="discarded">
                  Discarded <Badge className="ml-2 bg-secondary text-muted-foreground text-xs">{discardedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="all">
                  All ({filtered.length})
                </TabsTrigger>
              </TabsList>

              <TabsContent value="new">
                {renderCards(newAnomalies) ?? <EmptyState icon={AlertTriangle} msg="No pending anomalies" />}
              </TabsContent>
              <TabsContent value="acknowledged">
                {renderCards(acknowledgedAnomalies) ?? <EmptyState icon={Clock} msg="No anomalies in progress" />}
              </TabsContent>
              <TabsContent value="resolved">
                {renderCards(resolvedAnomalies) ?? <EmptyState icon={CheckCircle} msg="No resolved anomalies" />}
              </TabsContent>
              <TabsContent value="discarded">
                {renderCards(discardedAnomalies) ?? <EmptyState icon={Filter} msg="No discarded anomalies" />}
              </TabsContent>
              <TabsContent value="all">
                {renderCards(filtered) ?? <EmptyState icon={Filter} msg="No anomalies match your criteria" />}
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </div>

      <AnomalyDetailModal
        selectedAnomaly={selectedAnomaly}
        onClose={() => setSelectedAnomaly(null)}
        formatDate={formatDate}
        onRefresh={fetchAnomalies}
      />
    </DashboardLayout>
  )
}

export default Anomaly