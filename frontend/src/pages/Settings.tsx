import { Bell, Shield, Users, Database, Wifi, Moon, Lock, Info, Loader2, CheckCircle2, AlertTriangle, Cloud, CloudUpload, RefreshCw, HardDrive, Clock } from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/DashboardLayout";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Slider } from "@/components/ui/slider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { toast } from "sonner";
import { updateAnomalyConfig, getBackupConfig, updateBackupConfig, getBackupStatus, triggerBackup } from "@/services";
import type { BackupConfig, BackupStatus } from "@/types/types";

const AVAILABLE_PREFIXES = [
  { value: "faces/", label: "Face Recognition Frames", description: "Detected face images from cameras" },
  { value: "anomalies/", label: "Anomaly Evidence", description: "Anomaly detection frame captures" },
];

const INTERVAL_OPTIONS = [
  { value: 1, label: "Every 1 hour" },
  { value: 3, label: "Every 3 hours" },
  { value: 6, label: "Every 6 hours" },
  { value: 12, label: "Every 12 hours" },
  { value: 24, label: "Every 24 hours" },
];

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return "Never";
  const date = new Date(ts);
  return date.toLocaleString();
}

const Settings = () => {
  // Anomaly Detection Configuration State
  const [threshold, setThreshold] = useState<number>(5);
  const [windowSeconds, setWindowSeconds] = useState<number>(30);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  // Cloud Backup State
  const [backupConfig, setBackupConfig] = useState<BackupConfig | null>(null);
  const [backupStatus, setBackupStatus] = useState<BackupStatus | null>(null);
  const [isLoadingBackup, setIsLoadingBackup] = useState(true);
  const [isSavingBackup, setIsSavingBackup] = useState(false);
  const [isTriggering, setIsTriggering] = useState(false);
  const [backupEnabled, setBackupEnabled] = useState(true);
  const [backupInterval, setBackupInterval] = useState(6);
  const [selectedPrefixes, setSelectedPrefixes] = useState<string[]>(["faces/"]);

  // Load backup config & status
  const loadBackupData = useCallback(async () => {
    setIsLoadingBackup(true);
    try {
      const [config, status] = await Promise.all([
        getBackupConfig(),
        getBackupStatus(),
      ]);
      setBackupConfig(config);
      setBackupStatus(status);
      setBackupEnabled(config.enabled);
      setBackupInterval(config.interval_hours);
      setSelectedPrefixes(config.prefixes);
    } catch (error) {
      console.error("Failed to load backup config:", error);
      // Don't toast on initial load failure — service may not be running yet
    } finally {
      setIsLoadingBackup(false);
    }
  }, []);

  useEffect(() => {
    loadBackupData();
  }, [loadBackupData]);

  // Handle anomaly config update
  const handleUpdateAnomalyConfig = async () => {
    // Validation
    if (threshold < 1 || threshold > 50) {
      toast.error("Invalid Threshold", {
        description: "Threshold must be between 1 and 50 attempts.",
      });
      return;
    }
    if (windowSeconds < 5 || windowSeconds > 300) {
      toast.error("Invalid Time Window", {
        description: "Time window must be between 5 and 300 seconds.",
      });
      return;
    }

    setIsUpdating(true);

    try {
      const response = await updateAnomalyConfig({ threshold, windowSeconds });
      setLastUpdated(new Date().toLocaleTimeString());
      toast.success("Configuration Updated", {
        description: `Anomaly detection rules updated successfully. Threshold: ${threshold}, Window: ${windowSeconds}s`,
        icon: <CheckCircle2 className="w-4 h-4 text-green-500" />,
      });
    } catch (error) {
      console.error("Failed to update anomaly config:", error);
      toast.error("Update Failed", {
        description: error instanceof Error ? error.message : "Failed to update anomaly detection configuration. Please try again.",
        icon: <AlertTriangle className="w-4 h-4 text-red-500" />,
      });
    } finally {
      setIsUpdating(false);
    }
  };

  // Handle backup config save
  const handleSaveBackupConfig = async () => {
    if (selectedPrefixes.length === 0) {
      toast.error("Invalid Configuration", {
        description: "Please select at least one data type to back up.",
      });
      return;
    }

    setIsSavingBackup(true);
    try {
      const updated = await updateBackupConfig({
        enabled: backupEnabled,
        interval_hours: backupInterval,
        prefixes: selectedPrefixes,
      });
      setBackupConfig(updated);
      toast.success("Backup Configuration Saved", {
        description: backupEnabled
          ? `Backup scheduled every ${backupInterval}h for ${selectedPrefixes.join(", ")}`
          : "Backup scheduling has been disabled.",
        icon: <CheckCircle2 className="w-4 h-4 text-green-500" />,
      });
    } catch (error) {
      console.error("Failed to save backup config:", error);
      toast.error("Save Failed", {
        description: error instanceof Error ? error.message : "Failed to save backup configuration.",
        icon: <AlertTriangle className="w-4 h-4 text-red-500" />,
      });
    } finally {
      setIsSavingBackup(false);
    }
  };

  // Handle manual backup trigger
  const handleTriggerBackup = async () => {
    setIsTriggering(true);
    try {
      const result = await triggerBackup();
      toast.success("Backup Complete", {
        description: `Synced ${result.objects_synced} objects (${formatBytes(result.bytes_transferred)}) in ${result.duration_seconds.toFixed(1)}s`,
        icon: <CloudUpload className="w-4 h-4 text-green-500" />,
      });
      // Refresh status
      const status = await getBackupStatus();
      setBackupStatus(status);
    } catch (error) {
      console.error("Backup trigger failed:", error);
      toast.error("Backup Failed", {
        description: error instanceof Error ? error.message : "Failed to trigger backup. Ensure the backup service is running.",
        icon: <AlertTriangle className="w-4 h-4 text-red-500" />,
      });
    } finally {
      setIsTriggering(false);
    }
  };

  // Toggle prefix selection
  const togglePrefix = (prefix: string) => {
    setSelectedPrefixes((prev) =>
      prev.includes(prefix)
        ? prev.filter((p) => p !== prefix)
        : [...prev, prefix]
    );
  };

  return (
    <DashboardLayout>
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">Settings</h1>
          <p className="text-muted-foreground">Manage system configuration and preferences</p>
        </div>

        <Tabs defaultValue="general">
          <TabsList className="bg-secondary">
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="notifications">Notifications</TabsTrigger>
            <TabsTrigger value="security">Security</TabsTrigger>
            <TabsTrigger value="system">System</TabsTrigger>
            <TabsTrigger value="cloud-backup" className="gap-1.5">
              <Cloud className="w-3.5 h-3.5" />
              Cloud Backup
            </TabsTrigger>
          </TabsList>

          <TabsContent value="general" className="space-y-6 mt-6">
            <Card className="shadow-card border-border">
              <CardHeader>
                <CardTitle className="text-foreground">General Settings</CardTitle>
                <CardDescription className="text-muted-foreground">
                  Configure basic system preferences
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <Label htmlFor="system-name">System Name</Label>
                  <Input
                    id="system-name"
                    defaultValue="Survelliance System"
                    className="bg-secondary border-border"
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Select defaultValue="utc">
                    <SelectTrigger id="timezone" className="bg-secondary border-border">
                      <SelectValue placeholder="Select timezone" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="utc">UTC</SelectItem>
                      <SelectItem value="est">Eastern Time (EST)</SelectItem>
                      <SelectItem value="pst">Pacific Time (PST)</SelectItem>
                      <SelectItem value="cst">Central Time (CST)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="language">Language</Label>
                  <Select defaultValue="en">
                    <SelectTrigger id="language" className="bg-secondary border-border">
                      <SelectValue placeholder="Select language" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="en">English</SelectItem>
                      <SelectItem value="es">Spanish</SelectItem>
                      <SelectItem value="fr">French</SelectItem>
                      <SelectItem value="de">German</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Separator className="bg-border" />

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Auto-refresh Dashboard</Label>
                    <p className="text-sm text-muted-foreground">
                      Automatically update data every 30 seconds
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Sound Alerts</Label>
                    <p className="text-sm text-muted-foreground">
                      Play audio notifications for high-priority alerts
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="notifications" className="space-y-6 mt-6">
            <Card className="shadow-card border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Bell className="w-5 h-5 text-primary" />
                  <CardTitle className="text-foreground">Notification Preferences</CardTitle>
                </div>
                <CardDescription className="text-muted-foreground">
                  Configure how you receive alerts and updates
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Email Notifications</Label>
                    <p className="text-sm text-muted-foreground">
                      Receive alerts via email
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>SMS Notifications</Label>
                    <p className="text-sm text-muted-foreground">
                      Receive critical alerts via text message
                    </p>
                  </div>
                  <Switch />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Push Notifications</Label>
                    <p className="text-sm text-muted-foreground">
                      Browser push notifications for real-time alerts
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <Separator className="bg-border" />

                <div className="space-y-4">
                  <Label>Alert Types</Label>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <Label className="font-normal">High Priority Alerts</Label>
                      <Switch defaultChecked />
                    </div>
                    <div className="flex items-center justify-between">
                      <Label className="font-normal">Medium Priority Alerts</Label>
                      <Switch defaultChecked />
                    </div>
                    <div className="flex items-center justify-between">
                      <Label className="font-normal">Low Priority Alerts</Label>
                      <Switch />
                    </div>
                    <div className="flex items-center justify-between">
                      <Label className="font-normal">System Updates</Label>
                      <Switch defaultChecked />
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="security" className="space-y-6 mt-6">
            <Card className="shadow-card border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Shield className="w-5 h-5 text-primary" />
                  <CardTitle className="text-foreground">Security Settings</CardTitle>
                </div>
                <CardDescription className="text-muted-foreground">
                  Manage access control and security policies
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Two-Factor Authentication</Label>
                    <p className="text-sm text-muted-foreground">
                      Add an extra layer of security to your account
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Session Timeout</Label>
                    <p className="text-sm text-muted-foreground">
                      Automatically log out after 30 minutes of inactivity
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <Separator className="bg-border" />

                <div className="space-y-2">
                  <Label>Password Requirements</Label>
                  <div className="space-y-2 text-sm text-muted-foreground">
                    <p>✓ Minimum 8 characters</p>
                    <p>✓ At least one uppercase letter</p>
                    <p>✓ At least one number</p>
                    <p>✓ At least one special character</p>
                  </div>
                </div>

                <Button className="w-full">Change Password</Button>
              </CardContent>
            </Card>

            {/* Anomaly Detection Rules Card - Enhanced UI */}
            <Card className="shadow-card border-border bg-gradient-to-br from-card to-card/80">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-primary/10">
                      <AlertTriangle className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-foreground">Anomaly Detection Rules</CardTitle>
                      <CardDescription className="text-muted-foreground">
                        Configure real-time brute force detection thresholds
                      </CardDescription>
                    </div>
                  </div>
                  {lastUpdated && (
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground bg-secondary px-2.5 py-1 rounded-full">
                      <CheckCircle2 className="w-3 h-3 text-green-500" />
                      <span>Last updated: {lastUpdated}</span>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-8">
                {/* Threshold Setting */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Label htmlFor="threshold-slider" className="text-base font-medium">
                        Detection Threshold
                      </Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-4 h-4 text-muted-foreground cursor-help hover:text-foreground transition-colors" />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-xs">
                          <p>Maximum number of failed access attempts before triggering an anomaly alert. Lower values are more sensitive but may cause false positives.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-2xl font-bold text-primary">{threshold}</span>
                      <span className="text-sm text-muted-foreground">attempts</span>
                    </div>
                  </div>

                  <div className="px-1">
                    <Slider
                      id="threshold-slider"
                      value={[threshold]}
                      onValueChange={(values) => setThreshold(values[0])}
                      min={1}
                      max={20}
                      step={1}
                      className="cursor-pointer"
                    />
                    <div className="flex justify-between text-xs text-muted-foreground mt-2">
                      <span>1 (Very Sensitive)</span>
                      <span>10 (Balanced)</span>
                      <span>20 (Relaxed)</span>
                    </div>
                  </div>
                </div>

                <Separator className="bg-border" />

                {/* Window Seconds Setting */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Label htmlFor="window-slider" className="text-base font-medium">
                        Time Window
                      </Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-4 h-4 text-muted-foreground cursor-help hover:text-foreground transition-colors" />
                        </TooltipTrigger>
                        <TooltipContent side="right" className="max-w-xs">
                          <p>The sliding time window for counting failed attempts. Shorter windows detect rapid attacks, while longer windows catch distributed attacks.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-2xl font-bold text-primary">{windowSeconds}</span>
                      <span className="text-sm text-muted-foreground">seconds</span>
                    </div>
                  </div>

                  <div className="px-1">
                    <Slider
                      id="window-slider"
                      value={[windowSeconds]}
                      onValueChange={(values) => setWindowSeconds(values[0])}
                      min={5}
                      max={120}
                      step={5}
                      className="cursor-pointer"
                    />
                    <div className="flex justify-between text-xs text-muted-foreground mt-2">
                      <span>5s (Quick)</span>
                      <span>60s (Standard)</span>
                      <span>120s (Extended)</span>
                    </div>
                  </div>
                </div>

                {/* Current Config Preview */}
                <div className="p-4 rounded-lg bg-secondary/50 border border-border/50">
                  <div className="flex items-center gap-2 mb-3">
                    <Lock className="w-4 h-4 text-muted-foreground" />
                    <span className="text-sm font-medium text-foreground">Current Rule Preview</span>
                  </div>
                  <p className="text-sm text-muted-foreground leading-relaxed">
                    An anomaly will be triggered when <span className="font-semibold text-foreground">{threshold} or more</span> failed
                    access attempts occur within a <span className="font-semibold text-foreground">{windowSeconds}-second</span> window
                    for the same identity or access point.
                  </p>
                </div>

                {/* Update Button */}
                <Button
                  className="w-full h-12 text-base font-medium transition-all duration-200 hover:scale-[1.01]"
                  onClick={handleUpdateAnomalyConfig}
                  disabled={isUpdating}
                >
                  {isUpdating ? (
                    <>
                      <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                      Updating Configuration...
                    </>
                  ) : (
                    <>
                      <Shield className="w-5 h-5 mr-2" />
                      Save Detection Rules
                    </>
                  )}
                </Button>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="system" className="space-y-6 mt-6">
            <Card className="shadow-card border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Database className="w-5 h-5 text-primary" />
                  <CardTitle className="text-foreground">System Configuration</CardTitle>
                </div>
                <CardDescription className="text-muted-foreground">
                  Advanced system settings and maintenance
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="space-y-2">
                  <Label>Storage Retention</Label>
                  <Select defaultValue="30">
                    <SelectTrigger className="bg-secondary border-border">
                      <SelectValue placeholder="Select retention period" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="7">7 Days</SelectItem>
                      <SelectItem value="30">30 Days</SelectItem>
                      <SelectItem value="90">90 Days</SelectItem>
                      <SelectItem value="365">1 Year</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>Recording Quality</Label>
                  <Select defaultValue="high">
                    <SelectTrigger className="bg-secondary border-border">
                      <SelectValue placeholder="Select quality" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low (720p)</SelectItem>
                      <SelectItem value="medium">Medium (1080p)</SelectItem>
                      <SelectItem value="high">High (4K)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <Separator className="bg-border" />

                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <Label>Automatic Backups</Label>
                    <p className="text-sm text-muted-foreground">
                      Daily backups at 2:00 AM
                    </p>
                  </div>
                  <Switch defaultChecked />
                </div>

                <div className="space-y-2">
                  <Label>System Information</Label>
                  <div className="p-4 rounded-lg bg-secondary border border-border space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Version:</span>
                      <span className="text-foreground font-medium">2.4.1</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Last Update:</span>
                      <span className="text-foreground font-medium">Oct 8, 2025</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Storage Used:</span>
                      <span className="text-foreground font-medium">2.4 TB / 5 TB</span>
                    </div>
                  </div>
                </div>


              </CardContent>
            </Card>
          </TabsContent>

          {/* ═══════════════════ Cloud Backup Tab ═══════════════════ */}
          <TabsContent value="cloud-backup" className="space-y-6 mt-6">

            {/* Backup Configuration Card */}
            <Card className="shadow-card border-border bg-gradient-to-br from-card to-card/80">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-blue-500/10">
                      <Cloud className="w-5 h-5 text-blue-500" />
                    </div>
                    <div>
                      <CardTitle className="text-foreground">Cloud Backup Configuration</CardTitle>
                      <CardDescription className="text-muted-foreground">
                        Configure automatic backup of evidence frames to AWS S3
                      </CardDescription>
                    </div>
                  </div>
                  {backupConfig && (
                    <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${backupEnabled
                      ? "bg-green-500/10 text-green-500"
                      : "bg-muted text-muted-foreground"
                      }`}>
                      <div className={`w-1.5 h-1.5 rounded-full ${backupEnabled ? "bg-green-500 animate-pulse" : "bg-muted-foreground"}`} />
                      <span>{backupEnabled ? "Active" : "Disabled"}</span>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                {isLoadingBackup ? (
                  <div className="flex items-center justify-center py-12">
                    <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                    <span className="ml-2 text-muted-foreground">Loading backup configuration…</span>
                  </div>
                ) : (
                  <>
                    {/* Enable / Disable */}
                    <div className="flex items-center justify-between">
                      <div className="space-y-1">
                        <Label className="text-base font-medium">Enable Scheduled Backup</Label>
                        <p className="text-sm text-muted-foreground">
                          Automatically sync MinIO evidence to AWS S3 on a schedule
                        </p>
                      </div>
                      <Switch
                        checked={backupEnabled}
                        onCheckedChange={setBackupEnabled}
                      />
                    </div>

                    <Separator className="bg-border" />

                    {/* Schedule */}
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <Clock className="w-4 h-4 text-muted-foreground" />
                        <Label className="text-base font-medium">Backup Schedule</Label>
                      </div>
                      <Select
                        value={String(backupInterval)}
                        onValueChange={(v) => setBackupInterval(Number(v))}
                        disabled={!backupEnabled}
                      >
                        <SelectTrigger className="bg-secondary border-border">
                          <SelectValue placeholder="Select interval" />
                        </SelectTrigger>
                        <SelectContent>
                          {INTERVAL_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={String(opt.value)}>
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <Separator className="bg-border" />

                    {/* Data Types to Backup */}
                    <div className="space-y-3">
                      <div className="flex items-center gap-2">
                        <HardDrive className="w-4 h-4 text-muted-foreground" />
                        <Label className="text-base font-medium">Data to Back Up</Label>
                      </div>
                      <div className="space-y-3">
                        {AVAILABLE_PREFIXES.map((prefix) => (
                          <div
                            key={prefix.value}
                            className={`flex items-center justify-between p-3 rounded-lg border transition-colors cursor-pointer ${selectedPrefixes.includes(prefix.value)
                              ? "border-primary/50 bg-primary/5"
                              : "border-border bg-secondary/50 hover:bg-secondary"
                              }`}
                            onClick={() => togglePrefix(prefix.value)}
                          >
                            <div className="space-y-0.5">
                              <span className="text-sm font-medium text-foreground">{prefix.label}</span>
                              <p className="text-xs text-muted-foreground">{prefix.description}</p>
                            </div>
                            <Switch
                              checked={selectedPrefixes.includes(prefix.value)}
                              onCheckedChange={() => togglePrefix(prefix.value)}
                            />
                          </div>
                        ))}
                      </div>
                    </div>

                    <Separator className="bg-border" />

                    {/* AWS S3 Target Info */}
                    {backupConfig && (
                      <div className="p-4 rounded-lg bg-secondary/50 border border-border/50">
                        <div className="flex items-center gap-2 mb-3">
                          <CloudUpload className="w-4 h-4 text-muted-foreground" />
                          <span className="text-sm font-medium text-foreground">AWS S3 Destination</span>
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-sm">
                          <span className="text-muted-foreground">Bucket:</span>
                          <span className="text-foreground font-mono text-xs">{backupConfig.aws_s3_bucket}</span>
                          <span className="text-muted-foreground">Region:</span>
                          <span className="text-foreground font-mono text-xs">{backupConfig.aws_s3_region}</span>
                        </div>
                      </div>
                    )}

                    {/* Save Button */}
                    <Button
                      className="w-full h-12 text-base font-medium transition-all duration-200 hover:scale-[1.01]"
                      onClick={handleSaveBackupConfig}
                      disabled={isSavingBackup}
                    >
                      {isSavingBackup ? (
                        <>
                          <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                          Saving Configuration...
                        </>
                      ) : (
                        <>
                          <Cloud className="w-5 h-5 mr-2" />
                          Save Backup Settings
                        </>
                      )}
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Backup Status Card */}
            <Card className="shadow-card border-border">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-primary/10">
                      <RefreshCw className="w-5 h-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-foreground">Backup Status</CardTitle>
                      <CardDescription className="text-muted-foreground">
                        Last sync results and manual trigger
                      </CardDescription>
                    </div>
                  </div>
                  {backupStatus?.is_running && (
                    <div className="flex items-center gap-1.5 text-xs text-amber-500 bg-amber-500/10 px-2.5 py-1 rounded-full">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      <span>Sync in progress</span>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-6">
                {isLoadingBackup ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                  </div>
                ) : (
                  <>
                    {/* Status Grid */}
                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-4 rounded-lg bg-secondary border border-border">
                        <p className="text-xs text-muted-foreground mb-1">Last Sync</p>
                        <p className="text-sm font-medium text-foreground">
                          {formatTimestamp(backupStatus?.last_sync_timestamp ?? null)}
                        </p>
                      </div>
                      <div className="p-4 rounded-lg bg-secondary border border-border">
                        <p className="text-xs text-muted-foreground mb-1">Duration</p>
                        <p className="text-sm font-medium text-foreground">
                          {backupStatus?.last_sync_duration
                            ? `${backupStatus.last_sync_duration.toFixed(1)}s`
                            : "—"}
                        </p>
                      </div>
                      <div className="p-4 rounded-lg bg-secondary border border-border">
                        <p className="text-xs text-muted-foreground mb-1">Objects Synced</p>
                        <p className="text-sm font-medium text-foreground">
                          {backupStatus?.last_sync_objects ?? 0}
                          {(backupStatus?.last_sync_failed ?? 0) > 0 && (
                            <span className="text-red-500 text-xs ml-1">
                              ({backupStatus?.last_sync_failed} failed)
                            </span>
                          )}
                        </p>
                      </div>
                      <div className="p-4 rounded-lg bg-secondary border border-border">
                        <p className="text-xs text-muted-foreground mb-1">Data Transferred</p>
                        <p className="text-sm font-medium text-foreground">
                          {formatBytes(backupStatus?.last_sync_bytes ?? 0)}
                        </p>
                      </div>
                    </div>

                    <Separator className="bg-border" />

                    {/* Manual Trigger */}
                    <Button
                      variant="outline"
                      className="w-full h-12 text-base font-medium transition-all duration-200 hover:scale-[1.01] hover:border-primary/50"
                      onClick={handleTriggerBackup}
                      disabled={isTriggering || backupStatus?.is_running}
                    >
                      {isTriggering ? (
                        <>
                          <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                          Running Backup...
                        </>
                      ) : (
                        <>
                          <CloudUpload className="w-5 h-5 mr-2" />
                          Run Backup Now
                        </>
                      )}
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>

          </TabsContent>
        </Tabs>
      </div>
    </DashboardLayout>
  );
};

export default Settings;