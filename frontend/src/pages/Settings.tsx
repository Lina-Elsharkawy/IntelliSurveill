import { Bell, Shield, Users, Database, Wifi, Moon, Lock } from "lucide-react";
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

const Settings = () => {
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
                    defaultValue="UniGuard AI Security System"
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

            <Card className="shadow-card border-border">
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Lock className="w-5 h-5 text-primary" />
                  <CardTitle className="text-foreground">Anomaly Detection Rules</CardTitle>
                </div>
                <CardDescription className="text-muted-foreground">
                  Configure real-time brute force detection thresholds
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-6">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="max-attempts">Max Attempts</Label>
                    <Input
                      id="max-attempts"
                      type="number"
                      defaultValue="5"
                      className="bg-secondary border-border"
                    />
                    <p className="text-xs text-muted-foreground">Threshold before alert</p>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="window-seconds">Time Window (Seconds)</Label>
                    <Input
                      id="window-seconds"
                      type="number"
                      defaultValue="30"
                      className="bg-secondary border-border"
                    />
                    <p className="text-xs text-muted-foreground">Sliding window duration</p>
                  </div>
                </div>
                <Button 
                  className="w-full"
                  onClick={async () => {
                    const threshold = (document.getElementById('max-attempts') as HTMLInputElement).value;
                    const windowSeconds = (document.getElementById('window-seconds') as HTMLInputElement).value;
                    
                    try {
                      const response = await fetch('/api/anomalies/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ 
                          threshold: parseInt(threshold), 
                          windowSeconds: parseInt(windowSeconds) 
                        })
                      });
                      
                      if (response.ok) {
                        alert('Rules updated successfully!');
                      } else {
                        alert('Failed to update rules');
                      }
                    } catch (e) {
                      console.error(e);
                      alert('Error updating rules');
                    }
                  }}
                >
                  Update Security Rules
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

                <div className="flex gap-3">
                  <Button variant="outline" className="flex-1">Check for Updates</Button>
                  <Button variant="outline" className="flex-1">Export Logs</Button>
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
