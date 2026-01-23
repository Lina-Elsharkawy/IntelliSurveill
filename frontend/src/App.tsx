import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Routes, Route } from "react-router-dom";

import Index from "./pages/Index";
import Cameras from "./pages/Cameras";
import Alerts from "./pages/Alerts";
import Admin from "./pages/Admin";
import Analytics from "./pages/Analytics";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";
import Chatbot from "./components/ui/Chatbot";
import Login from "./pages/Login";
import ActivityLog from "./pages/ActivityLog";
import PrivateRoute from "./PrivateRoute";
import { AuthProvider, useAuth } from "@/context/AuthContext";

const queryClient = new QueryClient();

// Create a wrapper component to use the hook
const AppRoutes = () => {
  const { isAuthenticated } = useAuth();

  return (
    <Routes>
      <Route path="/" element={<Login />} />
      <Route path="/login" element={<Login />} />

      {/* Dashboard main */}
      <Route path="/dashboard" element={<PrivateRoute element={<Index />} isAuthenticated={isAuthenticated} />} />
      <Route path="/cameras" element={<PrivateRoute element={<Cameras />} isAuthenticated={isAuthenticated} />} />
      <Route path="/alerts" element={<PrivateRoute element={<Alerts />} isAuthenticated={isAuthenticated} />} />
      <Route path="/analytics" element={<PrivateRoute element={<Analytics />} isAuthenticated={isAuthenticated} />} />
      <Route path="/settings" element={<PrivateRoute element={<Settings />} isAuthenticated={isAuthenticated} />} />
      <Route path="/activity-log" element={<PrivateRoute element={<ActivityLog />} isAuthenticated={isAuthenticated} />} />
      <Route path="/admin" element={<PrivateRoute element={<Admin />} isAuthenticated={isAuthenticated} />} />

      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}

const App = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <Chatbot />
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;

