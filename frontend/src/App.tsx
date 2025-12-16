  import { Toaster } from "@/components/ui/toaster";
  import { Toaster as Sonner } from "@/components/ui/sonner";
  import { TooltipProvider } from "@/components/ui/tooltip";
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { Routes, Route } from "react-router-dom";

  import Index from "./pages/Index";
  import Cameras from "./pages/Cameras";
  import Alerts from "./pages/Alerts";
  
  import Analytics from "./pages/Analytics";
  import Settings from "./pages/Settings";
  import NotFound from "./pages/NotFound";
  import Chatbot from "./components/ui/Chatbot";
  import Login from "./pages/Login";
  import ActivityLog from "./pages/ActivityLog";

  const queryClient = new QueryClient();

  const App = () => (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        {/* Notifications */}
        <Toaster />
        <Sonner />

        {/* Chatbot appears globally */}
        <Chatbot />

        <Routes>
          {/* Default page → Login */}
          <Route path="/" element={<Login />} />

          {/* Login route */}
          <Route path="/login" element={<Login />} />

          {/* Dashboard main */}
          <Route path="/dashboard" element={<Index />} />

          {/* Other dashboard routes */}
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/alerts" element={<Alerts />} />
        
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/activity-log" element={<ActivityLog />} />

          {/* 404 handler */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </TooltipProvider>
    </QueryClientProvider>
  );

  export default App;
