/**
 * Centralized navigation items configuration.
 * Single source of truth for all navigation menus.
 */

import {
  LayoutDashboard, Camera, AlertTriangle, BarChart3,
  ListCheck, UserCog, Building, GraduationCap,
  Settings, Shield, FileText, Network
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  title: string;
  url: string;
  Icon: LucideIcon;
  /** If true, only visible to admin users */
  adminOnly?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { title: "Dashboard", url: "/dashboard", Icon: LayoutDashboard },
  { title: "Live Cameras", url: "/cameras", Icon: Camera },
  { title: "Anomalies", url: "/anomaly", Icon: AlertTriangle },
  { title: "VAD Lab", url: "/vad-lab", Icon: Shield },
  { title: "VAD Reasoning", url: "/reasoning", Icon: Network },
  { title: "Anomaly Rules", url: "/anomaly-rules", Icon: FileText },
  { title: "Departments", url: "/departments", Icon: Building },
  { title: "Labs", url: "/labs", Icon: GraduationCap },
  { title: "Analytics", url: "/analytics", Icon: BarChart3 },
  { title: "Activity Log", url: "/activity-log", Icon: ListCheck, adminOnly: false },
  { title: "Settings", url: "/settings", Icon: Settings },
  { title: "Detected people", url: "/admin", Icon: UserCog, adminOnly: false },
  { title: "Users", url: "/admin-users", Icon: Shield, adminOnly: true },
];
