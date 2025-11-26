import { useEffect, useState } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

interface LogEntry {
  id: string;
  user: string;
  action: string;
  time: string;
}

export default function ActivityLog() {
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    // Sample data until backend integration
    setLogs([
      { id: "1", user: "admin", action: "Logged in", time: "2025-11-26 10:15" },
      { id: "2", user: "john_doe", action: "Checked Cameras", time: "2025-11-26 10:17" },
      { id: "3", user: "admin", action: "Acknowledged Alert", time: "2025-11-26 10:20" },
      { id: "4", user: "jane_doe", action: "Updated Settings", time: "2025-11-26 10:25" },
    ]);
  }, []);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <h1 className="text-3xl font-bold text-foreground mb-2">Activity Log</h1>
        <p className="text-muted-foreground">Recent actions performed by users in the system</p>

        <Card className="shadow-card border-border">
          <CardHeader>
            <CardTitle className="text-foreground">User Activity</CardTitle>
            <CardDescription className="text-muted-foreground">
              All recent actions recorded in the system
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="min-w-full border-collapse border border-border">
              <thead>
                <tr className="bg-muted">
                  <th className="border border-border px-4 py-2 text-left text-foreground font-semibold">User</th>
                  <th className="border border-border px-4 py-2 text-left text-foreground font-semibold">Action</th>
                  <th className="border border-border px-4 py-2 text-left text-foreground font-semibold">Time</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="text-center py-4 text-muted-foreground">
                      No activity logs available
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr key={log.id} className="hover:bg-secondary/20">
                      <td className="border border-border px-4 py-2 text-foreground">{log.user}</td>
                      <td className="border border-border px-4 py-2 text-foreground">{log.action}</td>
                      <td className="border border-border px-4 py-2 text-foreground">{log.time}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}
