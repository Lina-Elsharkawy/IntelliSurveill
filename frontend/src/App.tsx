import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Routes, Route, Navigate } from "react-router-dom";

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
import PublicRoute from "./PublicRoute";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import Departments from "./pages/Departments";
import Labs from "./pages/Labs";
const queryClient = new QueryClient();

// Create a wrapper component to use the hook
const AppRoutes = () => {
  const { isAuthenticated } = useAuth();

  return (
    <Routes>
      <Route path="/" element={isAuthenticated ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />} />
      <Route path="/login" element={<PublicRoute element={<Login />} />} />

      {/* Dashboard main */}
      <Route path="/dashboard" element={<PrivateRoute element={<Index />} />} />
      <Route path="/cameras" element={<PrivateRoute element={<Cameras />} />} />
      <Route path="/alerts" element={<PrivateRoute element={<Alerts />} />} />
      <Route path="/analytics" element={<PrivateRoute element={<Analytics />} />} />
      <Route path="/settings" element={<PrivateRoute element={<Settings />} />} />
      <Route path="/activity-log" element={<PrivateRoute element={<ActivityLog />} />} />
      <Route path="/admin" element={<PrivateRoute element={<Admin />} />} />
      <Route path="/departments" element={<PrivateRoute element={<Departments />} />} />
      <Route path="/labs" element={<PrivateRoute element={<Labs />} />} />

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

