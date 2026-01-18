import { useState, useEffect } from "react"
import { AlertTriangle, CheckCircle, Clock, Filter } from "lucide-react"
import { DashboardLayout } from "@/components/DashboardLayout"
import { AlertItem } from "@/components/AlertItem"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { getAllAnomalies } from "@/services/anomalies"

type Alert = {
  title: string
  location: string
  timestamp: string
  severity: "high" | "medium" | "low"
  status: "new" | "acknowledged" | "resolved"
}

const Alerts = () => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [severityFilter, setSeverityFilter] = useState<"all" | "high" | "medium" | "low">("all")

  useEffect(() => {
    getAllAnomalies()
      .then((data: any[]) => {
        const mappedAlerts: Alert[] = data.map((a: any) => ({
          title: a.description || "Unknown Anomaly",
          location: `ID: ${a.id}`, // fallback location
          timestamp: new Date().toLocaleString(),
          severity: (a.severity_level || "low").toLowerCase() as "high" | "medium" | "low",
          status: "new", // default all to "new"
        }))
        setAlerts(mappedAlerts)
      })
      .catch((err) => console.error("Failed to fetch anomalies:", err))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <DashboardLayout>
        <p className="text-muted-foreground">Loading anomalies...</p>
      </DashboardLayout>
    )
  }

  // Apply severity filter
  const filteredAlerts =
    severityFilter === "all" ? alerts : alerts.filter(a => a.severity === severityFilter)

  const filteredNewAlerts = filteredAlerts.filter(a => a.status === "new")
  const filteredAcknowledgedAlerts = filteredAlerts.filter(a => a.status === "acknowledged")
  const filteredResolvedAlerts = filteredAlerts.filter(a => a.status === "resolved")

  return (
    <DashboardLayout>
      <div className="space-y-6">
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
                <p className="text-3xl font-bold text-foreground">{filteredNewAlerts.length}</p>
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
                <p className="text-3xl font-bold text-foreground">{filteredAcknowledgedAlerts.length}</p>
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
                <p className="text-3xl font-bold text-foreground">{filteredResolvedAlerts.length}</p>
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
                  <Badge className="ml-2 bg-destructive text-destructive-foreground">{filteredNewAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="acknowledged">
                  In Progress
                  <Badge className="ml-2 bg-warning text-warning-foreground">{filteredAcknowledgedAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="resolved">
                  Resolved
                  <Badge className="ml-2 bg-success text-success-foreground">{filteredResolvedAlerts.length}</Badge>
                </TabsTrigger>
                <TabsTrigger value="all">All ({filteredAlerts.length})</TabsTrigger>
              </TabsList>

              <TabsContent value="new" className="space-y-3">
                {filteredNewAlerts.map((alert) => <AlertItem key={alert.title} {...alert} />)}
              </TabsContent>
              <TabsContent value="acknowledged" className="space-y-3">
                {filteredAcknowledgedAlerts.map((alert) => <AlertItem key={alert.title} {...alert} />)}
              </TabsContent>
              <TabsContent value="resolved" className="space-y-3">
                {filteredResolvedAlerts.map((alert) => <AlertItem key={alert.title} {...alert} />)}
              </TabsContent>
              <TabsContent value="all" className="space-y-3">
                {filteredAlerts.map((alert) => <AlertItem key={alert.title} {...alert} />)}
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  )
}

export default Alerts
