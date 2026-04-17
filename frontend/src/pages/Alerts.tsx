import { useState, useEffect } from "react"
import { AlertTriangle, CheckCircle, Clock, Filter, X, Camera } from "lucide-react"
import { DashboardLayout } from "@/components/DashboardLayout"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

const ANOMALY_API_BASE = "http://127.0.0.1:8000"

type AnomalyCandidate = {
  id: number
  status: string
  narrative?: string
  imageRef?: string
  createdAt: string
  cameraId?: string
  severity?: "high" | "medium" | "low"
}

const Alerts = () => {
  const [anomalies, setAnomalies] = useState<AnomalyCandidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [severityFilter, setSeverityFilter] = useState<"all" | "high" | "medium" | "low">("all")
  const [selectedAnomaly, setSelectedAnomaly] = useState<AnomalyCandidate | null>(null)

  const fetchAnomalies = async () => {
    try {
      setError(null)
      const res = await fetch(`${ANOMALY_API_BASE}/anomaly-candidates`)

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }

      const data = await res.json()

      // Map anomalies and assign severity based on status or other logic
      const mappedAnomalies: AnomalyCandidate[] = data.map((a: any) => ({
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

  // Determine severity based on anomaly properties
  const determineSeverity = (anomaly: any): "high" | "medium" | "low" => {
    // You can customize this logic based on your needs
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

  const getSeverityColor = (severity: "high" | "medium" | "low") => {
    switch (severity) {
      case "high":
        return "bg-red-500"
      case "medium":
        return "bg-blue-500"
      case "low":
        return "bg-green-500"
      default:
        return "bg-gray-500"
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
        <p className="text-muted-foreground">Loading anomalies...</p>
      </DashboardLayout>
    )
  }

  // Apply severity filter
  const filteredAnomalies =
    severityFilter === "all" ? anomalies : anomalies.filter(a => a.severity === severityFilter)

  const newAnomalies = filteredAnomalies.filter(a => a.status === "pending" || a.status === "sent_to_llm")
  const acknowledgedAnomalies = filteredAnomalies.filter(a => a.status === "acknowledged")
  const resolvedAnomalies = filteredAnomalies.filter(a => a.status === "resolved")

  return (
    <DashboardLayout>
      <div className="alerts-page-wrapper space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-foreground mb-2">Anomalies</h1>
            <p className="text-muted-foreground">Monitor and manage all anomaly alerts and incidents</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline">
              <Filter className="w-4 h-4 mr-2" />
              Filter
            </Button>
            <Button>Mark All as Read</Button>
          </div>
        </div>

        {/* Summary Cards */}
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

        {/* Alerts Tabs */}
        <Card className="shadow-card border-border">
          <CardHeader className="flex justify-between items-center">
            <CardTitle className="text-foreground">All Anomalies</CardTitle>
            <Select value={severityFilter} onValueChange={(val) => setSeverityFilter(val as any)}>
              <SelectTrigger className="w-48 bg-secondary border-border">
                <SelectValue placeholder="Filter by severity" />
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
                  New
                  <Badge className="ml-2 bg-destructive text-destructive-foreground">{newAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  In Progress
                  <Badge className="ml-2 bg-warning text-warning-foreground">{acknowledgedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="resolved">
                  Resolved
                  <Badge className="ml-2 bg-success text-success-foreground">{resolvedAnomalies.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="all">All ({filteredAnomalies.length})</TabsTrigger>
              </TabsList>

              {error && (
                <div className="text-red-500 p-4 mb-4 border border-red-500/30 rounded">
                  Error: {error}
                </div>
              )}

              <TabsContent value="new">
                {newAnomalies.length === 0 ? (
                  <p className="text-muted-foreground text-center py-8">No new anomalies</p>
                ) : (
                  <div className="anomaly-cards">
                    {newAnomalies.map((anomaly) => (
                      <div
                        key={anomaly.id}
                        className={`anomaly-card ${getSeverityColor(anomaly.severity!)}`}
                        onClick={() => setSelectedAnomaly(anomaly)}
                      >
                        <p className="tip">Anomaly #{anomaly.id}</p>
                        <p className="second-text">
                          {anomaly.cameraId && `Camera ${anomaly.cameraId} • `}
                          {formatDate(anomaly.createdAt)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="acknowledged">
                {acknowledgedAnomalies.length === 0 ? (
                  <p className="text-muted-foreground text-center py-8">No anomalies in progress</p>
                ) : (
                  <div className="anomaly-cards">
                    {acknowledgedAnomalies.map((anomaly) => (
                      <div
                        key={anomaly.id}
                        className={`anomaly-card ${getSeverityColor(anomaly.severity!)}`}
                        onClick={() => setSelectedAnomaly(anomaly)}
                      >
                        <p className="tip">Anomaly #{anomaly.id}</p>
                        <p className="second-text">
                          {anomaly.cameraId && `Camera ${anomaly.cameraId} • `}
                          {formatDate(anomaly.createdAt)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="resolved">
                {resolvedAnomalies.length === 0 ? (
                  <p className="text-muted-foreground text-center py-8">No resolved anomalies</p>
                ) : (
                  <div className="anomaly-cards">
                    {resolvedAnomalies.map((anomaly) => (
                      <div
                        key={anomaly.id}
                        className={`anomaly-card ${getSeverityColor(anomaly.severity!)}`}
                        onClick={() => setSelectedAnomaly(anomaly)}
                      >
                        <p className="tip">Anomaly #{anomaly.id}</p>
                        <p className="second-text">
                          {anomaly.cameraId && `Camera ${anomaly.cameraId} • `}
                          {formatDate(anomaly.createdAt)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="all">
                {filteredAnomalies.length === 0 ? (
                  <p className="text-muted-foreground text-center py-8">No anomalies found</p>
                ) : (
                  <div className="anomaly-cards">
                    {filteredAnomalies.map((anomaly) => (
                      <div
                        key={anomaly.id}
                        className={`anomaly-card ${getSeverityColor(anomaly.severity!)}`}
                        onClick={() => setSelectedAnomaly(anomaly)}
                      >
                        <p className="tip">Anomaly #{anomaly.id}</p>
                        <p className="second-text">
                          {anomaly.cameraId && `Camera ${anomaly.cameraId} • `}
                          {formatDate(anomaly.createdAt)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>

      {/* Detail Modal */}
      {selectedAnomaly && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-background border border-border rounded-lg w-full max-w-2xl max-h-[90vh] overflow-y-auto">
            <div className="sticky top-0 bg-background border-b border-border p-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h2 className="text-2xl font-bold text-foreground">
                  Anomaly #{selectedAnomaly.id}
                </h2>
                <Badge className={`${getSeverityColor(selectedAnomaly.severity!)} text-white`}>
                  {selectedAnomaly.severity?.toUpperCase()}
                </Badge>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSelectedAnomaly(null)}
              >
                <X className="w-5 h-5" />
              </Button>
            </div>

            <div className="p-6 space-y-6">
              {/* Image */}
              {selectedAnomaly.imageRef ? (
                <div className="rounded-lg overflow-hidden border border-border">
                  <img
                    src={selectedAnomaly.imageRef}
                    alt={`Anomaly ${selectedAnomaly.id}`}
                    className="w-full h-auto"
                    onError={(e) => {
                      e.currentTarget.style.display = 'none'
                    }}
                  />
                </div>
              ) : (
                <div className="w-full h-64 bg-secondary rounded-lg flex items-center justify-center">
                  <Camera className="w-16 h-16 text-muted-foreground" />
                </div>
              )}

              {/* Details */}
              <div className="space-y-4">
                <div>
                  <p className="text-sm font-semibold text-muted-foreground mb-1">Status</p>
                  <Badge variant="outline">{selectedAnomaly.status}</Badge>
                </div>

                {selectedAnomaly.cameraId && (
                  <div>
                    <p className="text-sm font-semibold text-muted-foreground mb-1">Camera</p>
                    <p className="text-foreground flex items-center gap-2">
                      <Camera className="w-4 h-4" />
                      Camera {selectedAnomaly.cameraId}
                    </p>
                  </div>
                )}

                <div>
                  <p className="text-sm font-semibold text-muted-foreground mb-1">Detected At</p>
                  <p className="text-foreground flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    {formatDate(selectedAnomaly.createdAt)}
                  </p>
                </div>

                {selectedAnomaly.narrative && (
                  <div>
                    <p className="text-sm font-semibold text-muted-foreground mb-1">Description</p>
                    <p className="text-foreground bg-secondary p-4 rounded-lg">
                      {selectedAnomaly.narrative}
                    </p>
                  </div>
                )}
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-4 border-t border-border">
                <Button variant="outline" className="flex-1">
                  Mark as Acknowledged
                </Button>
                <Button className="flex-1 bg-success hover:bg-success/90">
                  Resolve
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}

export default Alerts