import { useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import {
  Users,
  UserPlus,
  AlertTriangle,
  Search,
  Filter,
  Download,
  Upload,
  Trash2,
  Edit,
  Check,
  X,
  UserCheck,
  Building,
  GraduationCap,
  UserCog
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";

export default function AdminPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState("all");

  const unknownIdentities = [
    { id: "unk-001", detectedAt: "2024-01-17 14:23", location: "Main Entrance", confidence: "87%", imageUrl: "/api/placeholder/100/100", status: "pending" },
    { id: "unk-002", detectedAt: "2024-01-17 13:45", location: "Parking Lot", confidence: "92%", imageUrl: "/api/placeholder/100/100", status: "pending" },
    { id: "unk-003", detectedAt: "2024-01-17 12:10", location: "Lab Zone 3", confidence: "78%", imageUrl: "/api/placeholder/100/100", status: "pending" },
    { id: "unk-004", detectedAt: "2024-01-17 11:30", location: "Building C", confidence: "95%", imageUrl: "/api/placeholder/100/100", status: "reviewed" },
  ];

  const registeredPeople = [
    { id: "emp-001", name: "John Smith", type: "employee", department: "Engineering", email: "john.smith@company.com", status: "active", lastSeen: "2024-01-17 15:30" },
    { id: "std-001", name: "Sarah Johnson", type: "student", department: "Computer Science", email: "sarah.j@university.edu", status: "active", lastSeen: "2024-01-17 14:15" },
    { id: "emp-002", name: "Michael Chen", type: "employee", department: "Security", email: "m.chen@company.com", status: "active", lastSeen: "2024-01-17 16:00" },
    { id: "ext-001", name: "David Wilson", type: "external", department: "Contractor", email: "david.w@external.com", status: "inactive", lastSeen: "2024-01-15 09:20" },
    { id: "std-002", name: "Emma Davis", type: "student", department: "Physics", email: "emma.d@university.edu", status: "active", lastSeen: "2024-01-17 13:45" },
    { id: "emp-003", name: "Lisa Anderson", type: "employee", department: "HR", email: "l.anderson@company.com", status: "active", lastSeen: "2024-01-17 15:50" },
  ];

  const anomalies = [
    { id: "ano-001", type: "Unauthorized Access", location: "Lab Zone 3", timestamp: "2024-01-17 14:30", severity: "high", description: "Unknown person detected in restricted area" },
    { id: "ano-002", type: "After Hours Activity", location: "Building A", timestamp: "2024-01-17 02:15", severity: "medium", description: "Motion detected outside business hours" },
    { id: "ano-003", type: "Tailgating Detected", location: "Main Entrance", timestamp: "2024-01-17 10:45", severity: "high", description: "Multiple persons entered with single badge scan" },
    { id: "ano-004", type: "Loitering", location: "Parking Lot B", timestamp: "2024-01-17 16:20", severity: "low", description: "Person remained in area for extended period" },
  ];

  const getTypeIcon = (type) => {
    switch (type) {
      case "employee": return <Building className="w-4 h-4" />;
      case "student": return <GraduationCap className="w-4 h-4" />;
      case "external": return <UserCog className="w-4 h-4" />;
      default: return <Users className="w-4 h-4" />;
    }
  };

  const getTypeColor = (type) => {
    switch (type) {
      case "employee": return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      case "student": return "bg-green-500/10 text-green-400 border-green-500/30";
      case "external": return "bg-purple-500/10 text-purple-400 border-purple-500/30";
      default: return "bg-gray-500/10 text-gray-400 border-gray-500/30";
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case "high": return "bg-red-500/10 text-red-400 border-red-500/30";
      case "medium": return "bg-yellow-500/10 text-yellow-400 border-yellow-500/30";
      case "low": return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      default: return "bg-gray-500/10 text-gray-400 border-gray-500/30";
    }
  };

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white-400 mb-2">Admin Database Management</h1>
            <p className="text-gray-400">Manage identities, monitor anomalies, and control access</p>
          </div>
          <div className="flex gap-2">
            <Button className="bg-green-600 hover:bg-green-700 text-black">
              <Upload className="w-4 h-4 mr-2" />
              Import Data
            </Button>
            <Button variant="outline" className="border-green-500/30 text-green-400 hover:bg-green-500/10">
              <Download className="w-4 h-4 mr-2" />
              Export
            </Button>
          </div>
        </div>

        {/* Stats Overview */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Card className="bg-gray-900/95 border-green-500/30">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-gray-400 text-sm">Total Registered</p>
                  <p className="text-3xl font-bold text-green-400">{registeredPeople.length}</p>
                </div>
                <Users className="w-10 h-10 text-green-400/30" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-gray-900/95 border-red-500/30">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-gray-400 text-sm">Unknown Identities</p>
                  <p className="text-3xl font-bold text-red-400">{unknownIdentities.filter(u => u.status === 'pending').length}</p>
                </div>
                <AlertTriangle className="w-10 h-10 text-red-400/30" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-gray-900/95 border-yellow-500/30">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-gray-400 text-sm">Active Anomalies</p>
                  <p className="text-3xl font-bold text-yellow-400">{anomalies.length}</p>
                </div>
                <AlertTriangle className="w-10 h-10 text-yellow-400/30" />
              </div>
            </CardContent>
          </Card>

          <Card className="bg-gray-900/95 border-blue-500/30">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-gray-400 text-sm">Active Users</p>
                  <p className="text-3xl font-bold text-blue-400">{registeredPeople.filter(p => p.status === 'active').length}</p>
                </div>
                <UserCheck className="w-10 h-10 text-blue-400/30" />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Main Content Tabs */}
        <Tabs defaultValue="unknown" className="space-y-4">
          <TabsList className="bg-gray-900/95 border border-green-500/30">
            <TabsTrigger value="unknown" className="data-[state=active]:bg-green-600 data-[state=active]:text-black">
              Unknown Identities ({unknownIdentities.filter(u => u.status === 'pending').length})
            </TabsTrigger>
            <TabsTrigger value="registered" className="data-[state=active]:bg-green-600 data-[state=active]:text-black">
              Registered People
            </TabsTrigger>
            <TabsTrigger value="anomalies" className="data-[state=active]:bg-green-600 data-[state=active]:text-black">
              Anomalies
            </TabsTrigger>
          </TabsList>

          {/* Unknown Identities Tab */}
          <TabsContent value="unknown" className="space-y-4">
            <Card className="bg-gray-900/95 border-green-500/30">
              <CardHeader>
                <CardTitle className="text-white-400 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5" />
                  Unknown Identities Detected
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {unknownIdentities.map((person) => (
                    <div key={person.id} className="bg-black/50 border border-green-500/20 rounded-lg p-4">
                      <div className="flex items-center gap-4">
                        <div className="w-20 h-20 bg-gray-800 rounded-lg border-2 border-green-500/30 flex items-center justify-center">
                          <Users className="w-10 h-10 text-green-400/50" />
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-semibold text-gray-200">ID: {person.id}</span>
                            <Badge className={person.status === 'pending' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-green-500/20 text-green-400'}>
                              {person.status}
                            </Badge>
                          </div>
                          <div className="text-sm text-gray-400 space-y-1">
                            <p>Detected: {person.detectedAt}</p>
                            <p>Location: {person.location}</p>
                            <p>Confidence: {person.confidence}</p>
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" className="bg-green-600 hover:bg-green-700 text-black">
                            <UserPlus className="w-4 h-4 mr-1" />
                            Register
                          </Button>
                          <Button size="sm" variant="outline" className="border-red-500/30 text-red-400 hover:bg-red-500/10">
                            <X className="w-4 h-4 mr-1" />
                            Dismiss
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Registered People Tab */}
          <TabsContent value="registered" className="space-y-4">
            <Card className="bg-gray-900/95 border-green-500/30">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-green-400">Registered People</CardTitle>
                  <div className="flex gap-2">
                    <div className="relative">
                      <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
                      <Input
                        placeholder="Search people..."
                        className="pl-10 bg-black/50 border-green-500/30 text-green-300"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                      />
                    </div>
                    <Select value={filterType} onValueChange={setFilterType}>
                      <SelectTrigger className="w-40 bg-black/50 border-green-500/30 text-green-300">
                        <Filter className="w-4 h-4 mr-2" />
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-gray-900 border-green-500/30">
                        <SelectItem value="all">All Types</SelectItem>
                        <SelectItem value="employee">Employee</SelectItem>
                        <SelectItem value="student">Student</SelectItem>
                        <SelectItem value="external">External</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {registeredPeople.map((person) => (
                    <div key={person.id} className="bg-black/50 border border-green-500/20 rounded-lg p-4 hover:border-green-500/40 transition-all">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="w-12 h-12 bg-gray-800 rounded-full border-2 border-green-500/30 flex items-center justify-center">
                            {getTypeIcon(person.type)}
                          </div>
                          <div>
                            <div className="flex items-center gap-2 mb-1">
                              <span className="font-semibold text-gray-200">{person.name}</span>
                              <Badge className={getTypeColor(person.type)}>
                                {person.type}
                              </Badge>
                              {person.status === 'active' ? (
                                <Badge className="bg-green-500/20 text-green-400">Active</Badge>
                              ) : (
                                <Badge className="bg-gray-500/20 text-gray-400">Inactive</Badge>
                              )}
                            </div>
                            <div className="text-sm text-gray-400">
                              <p>{person.department} • {person.email}</p>
                              <p className="text-xs">Last seen: {person.lastSeen}</p>
                            </div>
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" variant="outline" className="border-green-500/30 text-green-400 hover:bg-green-500/10">
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button size="sm" variant="outline" className="border-red-500/30 text-red-400 hover:bg-red-500/10">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Anomalies Tab */}
          <TabsContent value="anomalies" className="space-y-4">
            <Card className="bg-gray-900/95 border-green-500/30">
              <CardHeader>
                <CardTitle className="text-green-400 flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5" />
                  Security Anomalies
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {anomalies.map((anomaly) => (
                    <div key={anomaly.id} className="bg-black/50 border border-green-500/20 rounded-lg p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <span className="font-semibold text-gray-200">{anomaly.type}</span>
                            <Badge className={getSeverityColor(anomaly.severity)}>
                              {anomaly.severity}
                            </Badge>
                          </div>
                          <div className="text-sm text-gray-400 space-y-1">
                            <p><span className="text-gray-500">Location:</span> {anomaly.location}</p>
                            <p><span className="text-gray-500">Time:</span> {anomaly.timestamp}</p>
                            <p><span className="text-gray-500">Details:</span> {anomaly.description}</p>
                          </div>
                        </div>
                        <div className="flex gap-2">
                          <Button size="sm" className="bg-green-600 hover:bg-green-700 text-black">
                            <Check className="w-4 h-4 mr-1" />
                            Resolve
                          </Button>
                          <Button size="sm" variant="outline" className="border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/10">
                            <AlertTriangle className="w-4 h-4 mr-1" />
                            Investigate
                          </Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
}