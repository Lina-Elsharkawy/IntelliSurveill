import { Bell, Shield, Users, Database, Wifi, Moon, Lock, Info, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { useState } from "react";
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
import { updateAnomalyConfig } from "@/services";

const Settings = () => {
  // Anomaly Detection Configuration State
  const [threshold, setThreshold] = useState<number>(5);
  const [windowSeconds, setWindowSeconds] = useState<number>(30);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

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
        </Tabs>
      </div>
    </DashboardLayout>
  );
};

export default Settings;
