import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

interface CameraFeedProps {
  id: string;
  name: string;
  location: string;
  status: "active" | "inactive" | "alert";
  thumbnail: string;
}

export const CameraFeed = ({ name, location, status, thumbnail }: CameraFeedProps) => {
  const statusConfig = {
    active: { color: "bg-success", label: "Active", className: "border-success/20" },
    inactive: { color: "bg-muted-foreground", label: "Inactive", className: "border-border" },
    alert: { color: "bg-destructive", label: "Alert", className: "border-destructive/50 shadow-glow" },
  };

  const config = statusConfig[status];

  return (
    <Card className={cn("shadow-card border transition-all hover:shadow-glow", config.className)}>
      <CardContent className="p-0">
        <div className="relative aspect-video bg-secondary overflow-hidden">
          <img 
            src={thumbnail} 
            alt={name}
            className="w-full h-full object-cover"
          />
          <div className="absolute top-2 right-2">
            <Badge variant="secondary" className="gap-1">
              <Circle className={cn("w-2 h-2 fill-current", config.color)} />
              {config.label}
            </Badge>
          </div>
        </div>
        <div className="p-4">
          <h3 className="font-semibold text-foreground">{name}</h3>
          <p className="text-sm text-muted-foreground">{location}</p>
        </div>
      </CardContent>
    </Card>
  );
};
