import { ReactNode } from "react";
import { TopNav } from "./TopNav";

interface DashboardLayoutProps {
  children: ReactNode;
}

export const DashboardLayout = ({ children }: DashboardLayoutProps) => {
  return (
    <div style={{ minHeight: "100vh", background: "#050505", color: "#fff" }}>
      <TopNav />
      {/* push content below the fixed top bar */}
      <main style={{ paddingTop: 64, padding: "80px 32px 32px 32px", minHeight: "100vh" }}>
        {children}
      </main>
    </div>
  );
};
