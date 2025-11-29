import { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface StatsCardProps {
  title: string;
  value: string | number;
  icon: LucideIcon;
  trend?: {
    value: string;
    isPositive: boolean;
  };
  variant?: "default" | "success" | "warning" | "destructive";
}

export const StatsCard = ({ title, value, icon: Icon, trend, variant = "default" }: StatsCardProps) => {
  const variantStyles = {
    default: "bg-card",
    success: "bg-gradient-to-br from-card to-success/10 border-success/20",
    warning: "bg-gradient-to-br from-card to-warning/10 border-warning/20",
    destructive: "bg-gradient-to-br from-card to-destructive/10 border-destructive/20",
  };

  const iconStyles = {
    default: "bg-primary/10 text-primary",
    success: "bg-success/10 text-success",
    warning: "bg-warning/10 text-warning",
    destructive: "bg-destructive/10 text-destructive",
  };

  return (
    <Card className={cn("shadow-card border-border transition-all hover:shadow-glow", variantStyles[variant])}>
      <CardContent className="p-6">
        <div className="flex items-start justify-between">
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-3xl font-bold text-foreground">{value}</p>
            {trend && (
              <p className={cn("text-xs font-medium", trend.isPositive ? "text-success" : "text-destructive")}>
                {trend.value}
              </p>
            )}
          </div>
          <div className={cn("p-3 rounded-lg", iconStyles[variant])}>
            <Icon className="w-6 h-6" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
