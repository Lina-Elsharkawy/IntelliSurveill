import { useState, useEffect } from "react";
import { Bell, User, Search, LogOut, Settings } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { getRecentNotifications, getUnreadCount, markAllAsRead } from "@/services/notifications";
import type { Notification } from "@/types/types";
import { useAuth } from "@/context/AuthContext";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";

// Helper function to format relative time
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
  return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
}

// Helper function to get emoji based on notification type
function getNotificationEmoji(type?: string): string {
  switch (type) {
    case "motion": return "🚨";
    case "camera_offline": return "📷";
    case "low_battery": return "⚠️";
    case "anomaly": return "🔴";
    default: return "🔔";
  }
}

export const DashboardHeader = () => {
  const navigate = useNavigate();
  const { logout, user, roles } = useAuth();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch notifications and unread count
    const fetchData = async () => {
      try {
        const [notifs, countRes] = await Promise.all([
          getRecentNotifications(),
          getUnreadCount()
        ]);
        setNotifications(notifs);
        setUnreadCount(countRes.count);
      } catch (err) {
        console.error("Failed to fetch notifications:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleLogout = () => {
    logout();
  };

  const handleViewAll = () => {
    navigate("/alerts");
  };

  const handleMarkAllRead = async () => {
    try {
      await markAllAsRead();
      setUnreadCount(0);
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
    } catch (err) {
      console.error("Failed to mark all as read:", err);
    }
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
              {unreadCount > 0 && (
                <Badge className="absolute -top-1 -right-1 w-5 h-5 flex items-center justify-center p-0 bg-destructive text-destructive-foreground">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </Badge>
              )}
            </Button>
          </DropdownMenuTrigger>

          <DropdownMenuContent align="end" className="w-80">
            <div className="px-3 py-2 text-sm font-medium flex justify-between items-center">
              <span>Notifications</span>
              {unreadCount > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs h-6"
                  onClick={handleMarkAllRead}
                >
                  Mark all read
                </Button>
              )}
            </div>

            <DropdownMenuSeparator />

            {loading ? (
              <div className="px-3 py-4 text-sm text-muted-foreground text-center">
                Loading...
              </div>
            ) : notifications.length === 0 ? (
              <div className="px-3 py-4 text-sm text-muted-foreground text-center">
                No notifications
              </div>
            ) : (
              notifications.map((notification) => (
                <DropdownMenuItem
                  key={notification.id}
                  className={`flex flex-col items-start gap-1 ${!notification.is_read ? "bg-secondary/50" : ""}`}
                >
                  <span className="font-medium">
                    {getNotificationEmoji(notification.type)} {notification.title}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {notification.message} · {formatRelativeTime(notification.created_at)}
                  </span>
                </DropdownMenuItem>
              ))
            )}

            <DropdownMenuSeparator />

            <DropdownMenuItem
              className="justify-center text-sm text-muted-foreground cursor-pointer"
              onClick={handleViewAll}
            >
              View all notifications
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-sm font-medium text-foreground">
              {user?.name || user?.email || "User"}
            </p>
            <p className="text-xs text-muted-foreground">
              {roles.length > 0 ? roles.join(", ") : "User"}
            </p>
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="rounded-full">
                <User className="w-5 h-5" />
              </Button>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem
                onClick={() => navigate("/settings")}
                className="flex gap-2 cursor-pointer"
              >
                <Settings className="w-4 h-4" />
                Settings
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleLogout}
                className="flex gap-2 text-red-500 cursor-pointer"
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