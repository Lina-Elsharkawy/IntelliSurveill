import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Index from "./pages/Index";
import Cameras from "./pages/Cameras";
import Alerts from "./pages/Alerts";
import CampusMap from "./pages/CampusMap";
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

      {/* Chatbot (appears globally on all pages) */}
      <Chatbot />

      {/* Routing */}
      <BrowserRouter>
        <Routes>
          {/* Login page as first page */}
          <Route path="/login" element={<Login />} />

          {/* Dashboard routes */}
          <Route path="/" element={<Index />} />
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/map" element={<CampusMap />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/activity-log" element={<ActivityLog />} />

          {/* Catch-all for 404 */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
