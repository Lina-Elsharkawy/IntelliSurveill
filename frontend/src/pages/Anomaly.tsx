import { useState, useEffect } from "react"
import { AlertTriangle, CheckCircle, Clock, Filter, X, Camera } from "lucide-react"
import { DashboardLayout } from "@/components/DashboardLayout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { getAnomalyCandidates, AnomalyCandidate } from "@/services/anomalyCandidatesService"
import { AnomalyDetailModal } from "@/components/anomaly/AnomalyDetailModal"

const Anomaly = () => {
  const [anomalies, setAnomalies] = useState<AnomalyCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<"all" | "high" | "medium" | "low">("all")
  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyCandidate | null>(null)

  const fetchAnomalies = async () => {
    try {
      setError(null)
      const data = await getAnomalyCandidates()
      setAnomalies(data)
    } catch (err: any) {
      console.error("Failed to fetch anomalies:", err)
      setError(err.message || "Failed to load anomalies")
    } finally {
      setLoading(false)
    }
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

      <AnomalyDetailModal 
        selectedAnomaly={selectedAnomaly} 
        onClose={() => setSelectedAnomaly(null)} 
        getSeverityClass={getSeverityClass} 
        formatDate={formatDate} 
      />
    </DashboardLayout>
  )
}

export default Anomaly