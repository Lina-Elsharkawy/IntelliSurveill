import { Bell, User, Search, LogOut } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SidebarTrigger } from "@/components/ui/sidebar";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

export const DashboardHeader = () => {
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.clear();
    navigate("/login");
  };

  return (
    <header className="h-16 border-b border-border bg-card flex items-center justify-between px-6">
      <div className="flex items-center gap-4">
        <SidebarTrigger />
        <div className="relative w-96">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search cameras, zones, or alerts..."
            className="pl-10 bg-secondary border-border"
          />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="ghost" size="icon" className="relative">
      <Bell className="w-5 h-5" />
      <Badge className="absolute -top-1 -right-1 w-5 h-5 flex items-center justify-center p-0 bg-destructive text-destructive-foreground">
        3
      </Badge>
    </Button>
  </DropdownMenuTrigger>

  <DropdownMenuContent align="end" className="w-80">
    <div className="px-3 py-2 text-sm font-medium">
      Notifications
    </div>

    <DropdownMenuSeparator />

    <DropdownMenuItem className="flex flex-col items-start gap-1">
      <span className="font-medium">🚨 Motion Detected</span>
      <span className="text-xs text-muted-foreground">
        Lab – Zone 3 · 2 min ago
      </span>
    </DropdownMenuItem>

    <DropdownMenuItem className="flex flex-col items-start gap-1">
      <span className="font-medium">📷 Camera Offline</span>
      <span className="text-xs text-muted-foreground">
        Parking Lot B · 15 min ago
      </span>
    </DropdownMenuItem>

    <DropdownMenuItem className="flex flex-col items-start gap-1">
      <span className="font-medium">⚠️ Low Battery</span>
      <span className="text-xs text-muted-foreground">
        Camera CAM-015 · 3 hours ago
      </span>
    </DropdownMenuItem>

    <DropdownMenuSeparator />

    <DropdownMenuItem className="justify-center text-sm text-muted-foreground">
      View all notifications
    </DropdownMenuItem>
  </DropdownMenuContent>
</DropdownMenu>


        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-sm font-medium text-foreground">Admin User</p>
            <p className="text-xs text-muted-foreground">Security Officer</p>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full">
                <User className="w-5 h-5" />
              </Button>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="end" className="w-32">
              <DropdownMenuItem
                onClick={handleLogout}
                className="flex gap-2 text-red-500"
              >
                <LogOut className="w-4 h-4" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
};