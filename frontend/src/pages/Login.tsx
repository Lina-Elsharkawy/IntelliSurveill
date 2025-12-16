import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Lock, User, Shield, AlertCircle } from "lucide-react";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch("http://localhost:3000/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Login failed");
      }

      localStorage.setItem("access_token", data.access_token);
      localStorage.setItem("id_token", data.id_token);
      localStorage.setItem("loggedIn", "true");

      navigate("/dashboard");
    } catch (err: any) {
      setError(err.message || "Invalid username or password.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-background text-foreground">
      
      {/* LEFT SIDE – Branding */}
      <div className="hidden lg:flex flex-col justify-center items-center px-10">
        <div className="text-center space-y-6">
          <div className="flex justify-center">
            <div className="p-6 rounded-full border-2 border-green-500/30 bg-green-500/10">
              <Shield className="w-16 h-16 text-green-400" />
            </div>
          </div>
          <h1 className="text-4xl font-bold tracking-tight">
            Surveillance Platform
          </h1>
          <p className="text-muted-foreground text-lg max-w-md">
            Real-time monitoring, intelligent alerts, and secure campus
            protection — all in one unified system.
          </p>
        </div>
      </div>

      {/* RIGHT SIDE – Login */}
      <div className="flex items-center justify-center px-6">
        <Card className="w-full max-w-md bg-card border border-green-500/30 shadow-2xl">
          <CardHeader className="space-y-3 text-center">
            <CardTitle className="text-3xl font-bold text-green-400">
              Security Access
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              Enter your credentials to continue
            </CardDescription>
          </CardHeader>

          <form onSubmit={handleLogin}>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label className="flex items-center gap-2 text-foreground">
                  <User className="w-4 h-4 text-green-400" />
                  Username
                </Label>
                <Input
                  placeholder="Enter your username"
                  className="h-12 bg-background/50 border-green-500/30 text-green-300"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-2">
                <Label className="flex items-center gap-2 text-foreground">
                  <Lock className="w-4 h-4 text-green-400" />
                  Password
                </Label>
                <Input
                  type="password"
                  placeholder="Enter your password"
                  className="h-12 bg-background/50 border-green-500/30 text-green-300"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>

              {error && (
                <div className="flex gap-2 p-3 bg-destructive/10 border border-destructive/30 rounded-md">
                  <AlertCircle className="w-5 h-5 text-destructive" />
                  <p className="text-sm text-destructive">{error}</p>
                </div>
              )}
            </CardContent>

            <CardFooter className="flex flex-col gap-4">
              <Button
                type="submit"
                className="h-12 w-full bg-green-600 hover:bg-green-700 text-black font-semibold"
                disabled={isLoading}
              >
                {isLoading ? "Authenticating..." : "Sign In"}
              </Button>

              <p className="text-xs text-muted-foreground text-center">
                Secured with enterprise-grade encryption
              </p>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  );
}
