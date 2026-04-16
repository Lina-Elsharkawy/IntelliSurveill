import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Routes, Route, Navigate, useLocation } from "react-router-dom";

import Index from "./pages/Index";
import Cameras from "./pages/Cameras";
import Anomaly from "./pages/Anomaly";
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
import Schedules from "./pages/Schedules"; // ← Import Schedules page
import AdminUsers from "./pages/AdminUsers";
import RoleBasedRoute from "@/components/RoleBasedRoute";

const queryClient = new QueryClient();

// Create a wrapper component to use the hook
const AppRoutes = () => {
  const { isAuthenticated, roles } = useAuth();

  const getHomeElement = () => {
    if (!isAuthenticated) return <Navigate to="/login" replace />;
    return <Navigate to="/dashboard" replace />;
  };

  return (
    <Routes>
      <Route path="/" element={getHomeElement()} />
      <Route path="/login" element={<PublicRoute element={<Login />} />} />

      {/* Dashboard main */}
      <Route path="/dashboard" element={<PrivateRoute element={<Index />} />} />
      <Route path="/cameras" element={<PrivateRoute element={<Cameras />} />} />
      <Route path="/anomaly" element={<PrivateRoute element={<Anomaly />} />} />
      <Route path="/analytics" element={<PrivateRoute element={<Analytics />} />} />
      <Route path="/settings" element={<PrivateRoute element={<Settings />} />} />
      <Route path="/activity-log" element={<PrivateRoute element={<ActivityLog />} />} />
      <Route path="/admin" element={<RoleBasedRoute element={<Admin />} allowedRoles={['admin', 'user']} />} />
      <Route path="/departments" element={<PrivateRoute element={<Departments />} />} />
      <Route path="/labs" element={<PrivateRoute element={<Labs />} />} />
      <Route path="/schedules" element={<PrivateRoute element={<Schedules />} />} /> {/* ← Added */}
      <Route path="/admin-users" element={<RoleBasedRoute element={<AdminUsers />} allowedRoles={['admin']} />} />

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
};

const App = () => {
  const location = useLocation();
  // Hide chatbot on admin users page
  const showChatbot = location.pathname !== '/admin-users';

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        {showChatbot && <Chatbot />}
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
};

export default App;
