import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Clock } from "lucide-react";
import { cn } from "@/lib/utils";

interface AlertItemProps {
  title: string;
  location: string;
  timestamp: string;
  severity: "high" | "medium" | "low";
  status: "new" | "acknowledged" | "resolved";
}

export const AlertItem = ({ title, location, timestamp, severity, status }: AlertItemProps) => {
  const severityConfig = {
    high: "bg-destructive text-destructive-foreground",
    medium: "bg-warning text-warning-foreground",
    low: "bg-muted text-muted-foreground",
  };

  const statusConfig = {
    new: "border-l-4 border-l-destructive",
    acknowledged: "border-l-4 border-l-warning",
    resolved: "border-l-4 border-l-success opacity-60",
  };

  return (
    <Card className={cn("shadow-card border-border", statusConfig[status])}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between mb-2">
          <h4 className="font-semibold text-foreground">{title}</h4>
          <Badge className={severityConfig[severity]}>
            {severity.toUpperCase()}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground mb-2">{location}</p>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="w-3 h-3" />
          {timestamp}
        </div>
      </CardContent>
    </Card>
  );
};
