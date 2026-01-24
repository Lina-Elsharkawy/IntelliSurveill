import { LayoutDashboard, Camera, AlertTriangle, Map, BarChart3, Shield, ListCheck, UserCog, Building, GraduationCap, Calendar } from "lucide-react";
import { NavLink } from "react-router-dom";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarHeader,
} from "@/components/ui/sidebar";

// Add Departments, Labs, and Schedules to menu items
const menuItems = [
  { title: "Dashboard", url: "/dashboard", icon: LayoutDashboard },
  { title: "Live Cameras", url: "/cameras", icon: Camera },
  { title: "Anomalies", url: "/alerts", icon: AlertTriangle },
  { title: "Departments", url: "/departments", icon: Building },
  { title: "Labs", url: "/labs", icon: GraduationCap },
  { title: "Admin", url: "/admin", icon: UserCog },
  { title: "Analytics", url: "/analytics", icon: BarChart3 },
  { title: "Activity Log", url: "/activity-log", icon: ListCheck },
  { title: "Schedules", url: "/schedules", icon: Calendar },
];

export function DashboardSidebar() {
  return (
    <Sidebar className="border-r border-border">
      <SidebarHeader className="border-b border-border p-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-primary flex items-center justify-center shadow-glow">
            <Shield className="w-6 h-6 text-primary-foreground" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-foreground">Surveillance Platform</h2>
            <p className="text-xs text-muted-foreground">Security System</p>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {menuItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild>
                    <NavLink
                      to={item.url}
                      end
                      className={({ isActive }) =>
                        isActive
                          ? "bg-sidebar-accent text-sidebar-primary font-medium"
                          : "text-sidebar-foreground hover:bg-sidebar-accent/50"
                      }
                    >
                      <item.icon className="w-4 h-4" />
                      <span>{item.title}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}


