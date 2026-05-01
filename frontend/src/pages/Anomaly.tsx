import { useState, useEffect } from "react"
import { AlertTriangle, CheckCircle, Clock, Filter, X, Camera } from "lucide-react"
import { DashboardLayout } from "@/components/DashboardLayout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { apiGet } from "@/lib/api"

type AnomalyCandidate = {
  id: number
  status: string
  narrative?: string
  imageRef?: string
  createdAt: string
  cameraId?: string
  severity?: "high" | "medium" | "low"
}

const Anomaly = () => {
  const [anomalies, setAnomalies] = useState<AnomalyCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<"all" | "high" | "medium" | "low">("all")
  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyCandidate | null>(null)

  const fetchAnomalies = async () => {
    try {
      setError(null)
      const data = await apiGet<any[]>("/api/anomaly-candidates")

      const mappedAnomalies: AnomalyCandidate[] = data.map((a) => ({
        ...a,
        severity: determineSeverity(a),
      }))
      
      setAnomalies(mappedAnomalies)
    } catch (err: any) {
      console.error("Failed to fetch anomalies:", err)
      setError(err.message || "Failed to load anomalies")
    } finally {
      setLoading(false)
    }
  }

  const determineSeverity = (anomaly: any): "high" | "medium" | "low" => {
    if (anomaly.status === "pending" || anomaly.status === "sent_to_llm") {
      return "high"
    } else if (anomaly.status === "resolved") {
      return "low"
    }
    return "medium"
  }

  useEffect(() => {
    fetchAnomalies()
  }, [])

  const getSeverityClass = (severity: "high" | "medium" | "low") => {
    switch (severity) {
      case "high": return "red"
      case "medium": return "blue"
      case "low": return "green"
      default: return "gray"
    }
  }

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleString()
    } catch {
      return dateStr
    }
  }

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[400px]">
          <p className="text-muted-foreground animate-pulse">Scanning for anomalies...</p>
        </div>
      </DashboardLayout>
    )
  }

  const filteredAnomalies =
    severityFilter === "all" ? anomalies : anomalies.filter(a => a.severity === severityFilter)

  const newAnomalies = filteredAnomalies.filter(a => a.status === "pending" || a.status === "sent_to_llm")
  const acknowledgedAnomalies = filteredAnomalies.filter(a => a.status === "acknowledged")
  const resolvedAnomalies = filteredAnomalies.filter(a => a.status === "resolved")

  const renderAnomalyCards = (items: AnomalyCandidate[]) => (
    <div className="anomaly-cards-container">
      {items.map((anomaly) => (
        <div
          key={anomaly.id}
          className={`anomaly-card ${getSeverityClass(anomaly.severity!)}`}
          onClick={() => setSelectedAnomaly(anomaly)}
        >
          <div className="card-header-info">
            <p className="tip">Anomaly #{anomaly.id}</p>
            <p className="second-text">
              {anomaly.cameraId && `Cam ${anomaly.cameraId} • `}
              {formatDate(anomaly.createdAt)}
            </p>
          </div>
          
          <div className="hover-content">
            {anomaly.imageRef && (
              <div className="hover-image">
                <img src={anomaly.imageRef} alt="Anomaly Preview" />
              </div>
            )}
            <p className="hover-description">
              {anomaly.narrative || "No description available."}
            </p>
          </div>
        </div>
      ))}
    </div>
  )

  return (
    <DashboardLayout>
      <div className="anomaly-page-wrapper space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Anomalies</h1>
            <p className="text-muted-foreground">Monitor and manage all anomaly alerts and incidents</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={fetchAnomalies}>
              <Clock className="w-4 h-4 mr-2" />
              Refresh
            </Button>
            <Button>Mark All as Read</Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="shadow-card border-border border-l-4 border-l-destructive">
            <CardContent className="p-6 flex justify-between items-start">
              <div>
                <p className="text-sm text-muted-foreground mb-1">New Anomalies</p>
                <p className="text-3xl font-bold text-foreground">{newAnomalies.length}</p>
              </div>
              <div className="p-3 rounded-lg bg-destructive/10">
                <AlertTriangle className="w-6 h-6 text-destructive" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border border-l-4 border-l-warning">
            <CardContent className="p-6 flex justify-between items-start">
              <div>
                <p className="text-sm text-muted-foreground mb-1">In Progress</p>
                <p className="text-3xl font-bold text-foreground">{acknowledgedAnomalies.length}</p>
              </div>
              <div className="p-3 rounded-lg bg-warning/10">
                <Clock className="w-6 h-6 text-warning" />
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-card border-border border-l-4 border-l-success">
            <CardContent className="p-6 flex justify-between items-start">
              <div>
                <p className="text-sm text-muted-foreground mb-1">Resolved Today</p>
                <p className="text-3xl font-bold text-foreground">{resolvedAnomalies.length}</p>
              </div>
              <div className="p-3 rounded-lg bg-success/10">
                <CheckCircle className="w-6 h-6 text-success" />
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="shadow-card border-border">
          <CardHeader className="flex flex-row justify-between items-center">
            <CardTitle className="text-foreground">All Anomalies</CardTitle>
            <Select value={severityFilter} onValueChange={(val) => setSeverityFilter(val as any)}>
              <SelectTrigger className="w-48 bg-secondary border-border">
                <SelectValue placeholder="Severity" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Severities</SelectItem>
                <SelectItem value="high">High Priority</SelectItem>
                <SelectItem value="medium">Medium Priority</SelectItem>
                <SelectItem value="low">Low Priority</SelectItem>
              </SelectContent>
            </Select>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="new">
              <TabsList className="bg-secondary mb-6">
                <TabsTrigger value="new">
                  New <Badge className="ml-2 bg-destructive">{newAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  In Progress <Badge className="ml-2 bg-warning">{acknowledgedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="resolved">
                  Resolved <Badge className="ml-2 bg-success">{resolvedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="all">All ({filteredAnomalies.length})</TabsTrigger>
              </TabsList>

              {error && (
                <div className="text-red-500 p-4 mb-4 border border-red-500/30 rounded bg-red-500/5">
                  Error: {error}
                </div>
              )}

              <TabsContent value="new">
                {newAnomalies.length === 0 ? (
                  <div className="text-center py-12 border-2 border-dashed border-border rounded-xl">
                    <AlertTriangle className="w-12 h-12 text-muted-foreground/20 mx-auto mb-4" />
                    <p className="text-muted-foreground">No pending anomalies detected</p>
                  </div>
                ) : renderAnomalyCards(newAnomalies)}
              </TabsContent>

              <TabsContent value="acknowledged">
                {acknowledgedAnomalies.length === 0 ? (
                  <div className="text-center py-12 border-2 border-dashed border-border rounded-xl">
                    <Clock className="w-12 h-12 text-muted-foreground/20 mx-auto mb-4" />
                    <p className="text-muted-foreground">No anomalies currently in progress</p>
                  </div>
                ) : renderAnomalyCards(acknowledgedAnomalies)}
              </TabsContent>

              <TabsContent value="resolved">
                {resolvedAnomalies.length === 0 ? (
                  <div className="text-center py-12 border-2 border-dashed border-border rounded-xl">
                    <CheckCircle className="w-12 h-12 text-muted-foreground/20 mx-auto mb-4" />
                    <p className="text-muted-foreground">No resolved anomalies found</p>
                  </div>
                ) : renderAnomalyCards(resolvedAnomalies)}
              </TabsContent>

              <TabsContent value="all">
                {filteredAnomalies.length === 0 ? (
                  <div className="text-center py-12 border-2 border-dashed border-border rounded-xl">
                    <Filter className="w-12 h-12 text-muted-foreground/20 mx-auto mb-4" />
                    <p className="text-muted-foreground">No anomalies match your criteria</p>
                  </div>
                ) : renderAnomalyCards(filteredAnomalies)}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>

      {selectedAnomaly && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-[2000] p-4 animate-in fade-in duration-300">
          <div className="bg-background border border-border rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
            <div className="sticky top-0 bg-background/80 backdrop-blur-md border-b border-border p-6 flex items-center justify-between z-10">
              <div className="flex items-center gap-4">
                <div className={`w-3 h-3 rounded-full animate-pulse ${getSeverityClass(selectedAnomaly.severity!) === 'red' ? 'bg-red-500' : 'bg-blue-500'}`} />
                <h2 className="text-2xl font-bold text-foreground">Anomaly #{selectedAnomaly.id}</h2>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setSelectedAnomaly(null)} className="rounded-full hover:bg-secondary">
                <X className="w-5 h-5" />
              </Button>
            </div>

            <div className="p-8 space-y-8">
              {selectedAnomaly.imageRef ? (
                <div className="rounded-xl overflow-hidden border-2 border-border shadow-lg">
                  <img src={selectedAnomaly.imageRef} alt={`Anomaly ${selectedAnomaly.id}`} className="w-full h-auto object-cover max-h-[400px]" />
                </div>
              ) : (
                <div className="w-full h-64 bg-secondary rounded-xl flex flex-col items-center justify-center border-2 border-dashed border-border">
                  <Camera className="w-16 h-16 text-muted-foreground/30 mb-2" />
                  <p className="text-muted-foreground text-sm">Visual evidence not available</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-1">
                  <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Status</p>
                  <Badge variant="secondary" className="px-3 py-1 font-mono">{selectedAnomaly.status.replace('_', ' ')}</Badge>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Camera Source</p>
                  <p className="text-foreground font-medium flex items-center gap-2"><Camera className="w-4 h-4 text-primary" /> {selectedAnomaly.cameraId || "Unknown Asset"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Severity</p>
                  <Badge className={`${getSeverityClass(selectedAnomaly.severity!)} text-white`}>{selectedAnomaly.severity?.toUpperCase()}</Badge>
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Detection Time</p>
                  <p className="text-foreground font-medium flex items-center gap-2"><Clock className="w-4 h-4 text-primary" /> {formatDate(selectedAnomaly.createdAt)}</p>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest">Detailed Narrative</p>
                <div className="text-foreground bg-secondary/50 p-6 rounded-xl border border-border leading-relaxed italic text-sm">
                  "{selectedAnomaly.narrative || "System awaiting detailed LLM analysis of the visual data stream..."}"
                </div>
              </div>

              <div className="flex gap-4 pt-4 border-t border-border">
                <Button variant="outline" className="flex-1 h-12 font-bold" onClick={() => setSelectedAnomaly(null)}>Close View</Button>
                <Button className="flex-1 h-12 bg-primary hover:bg-primary/90 font-bold shadow-lg shadow-primary/20">Acknowledge</Button>
                <Button className="flex-1 h-12 bg-success hover:bg-success/90 font-bold shadow-lg shadow-success/20">Resolve Anomaly</Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}

export default Anomaly