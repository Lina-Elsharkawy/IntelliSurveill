/**
 * TopNav — Traditional sidebar navigation
 * Opens as a left sidebar with all menu items
 * Background blurs when open.
 */

import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Camera, AlertTriangle, BarChart3,
  ListCheck, UserCog, Building, GraduationCap, Calendar,
  LogOut, Shield, Settings, User, FileText
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const G = "rgb(46,213,115)";
const GA = (a: number) => `rgba(46,213,115,${a})`;

const ALL_NAV_ITEMS = [
  { title: "Dashboard", url: "/dashboard", Icon: LayoutDashboard },
  { title: "Live Cameras", url: "/cameras", Icon: Camera },
  { title: "Anomalies", url: "/anomaly", Icon: AlertTriangle },
  { title: "Anomaly Rules", url: "/anomaly-rules", Icon: FileText },
  { title: "Departments", url: "/departments", Icon: Building },
  { title: "Labs", url: "/labs", Icon: GraduationCap },
  { title: "Analytics", url: "/analytics", Icon: BarChart3 },
  { title: "Activity Log", url: "/activity-log", Icon: ListCheck },
  { title: "Schedules", url: "/schedules", Icon: Calendar },
  { title: "Settings", url: "/settings", Icon: Settings },
  { title: "Detected people", url: "/admin", Icon: UserCog, adminOnly: false },
  { title: "Users", url: "/admin-users", Icon: Shield, adminOnly: true },
];

export function TopNav() {
  const [open, setOpen] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const { logout, user, roles } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => { logout(); navigate("/login"); };

  const displayName = user?.name || user?.email?.split("@")[0] || "User";
  const userRole = roles[0] || "viewer";
  const isAdmin = roles.includes("admin");

  const NAV_ITEMS = ALL_NAV_ITEMS.filter(item => !item.adminOnly || isAdmin);

  return (
    <>
      {/* ── Fixed top bar ───────────────────────────── */}
      <header style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 1100,
        height: 64,
        background: open ? "rgba(5,5,5,0.0)" : "rgba(5,5,5,0.92)",
        backdropFilter: open ? "none" : "blur(20px)",
        borderBottom: open ? "none" : `1px solid ${GA(0.12)}`,
        display: "flex", alignItems: "center",
        padding: "0 32px", gap: 20,
        transition: "background 0.4s, border 0.4s",
        pointerEvents: "auto",
      }}>

        {/* Hamburger → X */}
        <button
          className={`tnav-burger${open ? " tnav-burger--open" : ""}`}
          onClick={() => setOpen(v => !v)}
          aria-label="Toggle menu"
          style={{ position: "relative", zIndex: 1200 }}
        >
          <span className="tnb1" /><span className="tnb2" />
          <span className="tnb3" /><span className="tnb4" />
        </button>

        {/* Brand — hidden when menu is open */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, opacity: open ? 0 : 1, transition: "opacity 0.3s" }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: GA(0.15), border: `1px solid ${GA(0.3)}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Shield size={15} color={G} />
          </div>
          <div>
            <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 16, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em", lineHeight: 1 }}>IntelliSurveil</div>
            <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 9, color: GA(0.5), letterSpacing: "0.2em", textTransform: "uppercase", marginTop: 2 }}>Security System</div>
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {/* Profile Section */}
        <div style={{ opacity: open ? 0 : 1, transition: "opacity 0.3s", display: "flex", alignItems: "center", gap: 15 }}>
          {/* Name and Role */}
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 13, fontWeight: 600, color: "#fff", lineHeight: 1.2 }}>{displayName}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: GA(0.5), letterSpacing: 2, textTransform: "uppercase" }}>{userRole}</div>
          </div>

          {/* Profile Icon Button */}
          <button
            onClick={() => setShowProfile(true)}
            style={{
              width: 40, height: 40, borderRadius: "50%",
              background: GA(0.08), border: `1px solid ${GA(0.3)}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              cursor: "pointer", transition: "0.2s", color: G
            }}
            onMouseEnter={e => { e.currentTarget.style.background = GA(0.15); e.currentTarget.style.borderColor = G; }}
            onMouseLeave={e => { e.currentTarget.style.background = GA(0.08); e.currentTarget.style.borderColor = GA(0.3); }}
          >
            <User size={20} />
          </button>

          {/* Logout */}
          <button
            onClick={handleLogout}
            style={{ background: "rgba(255,68,68,0.06)", border: "1px solid rgba(255,68,68,0.15)", color: "#ff6b6b", padding: "7px 18px", borderRadius: 8, cursor: "pointer", fontFamily: "'Outfit', sans-serif", fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", gap: 7 }}
            onMouseEnter={e => e.currentTarget.style.background = "rgba(255,68,68,0.15)"}
            onMouseLeave={e => e.currentTarget.style.background = "rgba(255,68,68,0.06)"}
          >
            <LogOut size={13} /> Logout
          </button>
        </div>
      </header>

      {/* ── Profile Info Modal ───────────────────────── */}
      {showProfile && (
        <div onClick={() => setShowProfile(false)} style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(0,0,0,0.85)", backdropFilter: "blur(10px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 400, background: "#0a0a0a", border: `1px solid ${GA(0.3)}`, borderRadius: 24, padding: 40, position: "relative", textAlign: "center", boxShadow: `0 0 50px rgba(0,0,0,0.5), 0 0 20px ${GA(0.1)}` }}>
            <button onClick={() => setShowProfile(false)} style={{ position: "absolute", top: 20, right: 20, background: "transparent", border: "none", color: "#fff", cursor: "pointer", fontSize: 20 }}>✕</button>

            <div style={{ width: 80, height: 80, borderRadius: "50%", background: GA(0.1), border: `2px solid ${G}`, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px", color: G }}>
              <User size={40} />
            </div>

            <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 26, fontWeight: 700, color: "#fff", marginBottom: 4, letterSpacing: "-0.01em" }}>{displayName}</h2>
            <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 10, color: G, letterSpacing: "0.15em", marginBottom: 32, textTransform: "uppercase", fontWeight: 500 }}>Verified Identity</div>

            <div style={{ display: "flex", flexDirection: "column", gap: 15, textAlign: "left" }}>
              <div style={{ padding: "14px 20px", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.05)" }}>
                <div style={{ fontSize: 9, color: GA(0.5), textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4, fontWeight: 600 }}>Email Address</div>
                <div style={{ fontSize: 13, fontFamily: "'Outfit'", color: "#fff" }}>{user?.email || "N/A"}</div>
              </div>
              <div style={{ padding: "14px 20px", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.05)" }}>
                <div style={{ fontSize: 9, color: GA(0.5), textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4, fontWeight: 600 }}>System Privileges</div>
                <div style={{ fontSize: 13, fontFamily: "'Outfit'", color: "#fff" }}>{roles.join(", ") || "Standard User"}</div>
              </div>
              <div style={{ padding: "14px 20px", background: "rgba(255,255,255,0.02)", borderRadius: 12, border: "1px solid rgba(255,255,255,0.05)" }}>
                <div style={{ fontSize: 9, color: GA(0.5), textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4, fontWeight: 600 }}>Account Status</div>
                <div style={{ fontSize: 13, fontFamily: "'Outfit'", color: G, fontWeight: 600 }}>Active Node</div>
              </div>
            </div>

            <button onClick={() => setShowProfile(false)} style={{ marginTop: 30, width: "100%", padding: "12px", background: G, color: "#000", border: "none", borderRadius: 12, fontFamily: "'Outfit'", fontWeight: 700, cursor: "pointer", transition: "0.2s" }} onMouseEnter={e => e.currentTarget.style.transform = "scale(1.02)"} onMouseLeave={e => e.currentTarget.style.transform = "scale(1)"}>Close</button>
          </div>
        </div>
      )}

      {/* ── Full-screen blur overlay ─────────────────── */}
      {open && (
        <div
          onClick={() => setOpen(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 1050,
            backdropFilter: "blur(18px)",
            background: "rgba(0,0,0,0.75)",
            animation: "tnav-fade 0.35s ease",
          }}
        />
      )}

      {/* ── Sidebar Navigation ─────────────────────────── */}
      <aside
        style={{
          position: "fixed",
          left: 0,
          top: 64,
          bottom: 0,
          width: 280,
          background: "rgba(10,10,10,0.98)",
          backdropFilter: "blur(20px)",
          borderRight: `1px solid ${GA(0.12)}`,
          zIndex: 1150,
          transform: open ? "translateX(0)" : "translateX(-100%)",
          transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
          overflowY: "auto",
          padding: "24px 0",
        }}
      >
        {/* Sidebar Header */}
        <div style={{ padding: "0 20px 20px", borderBottom: `1px solid rgba(255,255,255,0.05)`, marginBottom: 20 }}>
          <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 10, color: GA(0.5), letterSpacing: "0.15em", textTransform: "uppercase", fontWeight: 600 }}>Navigation</div>
        </div>

        {/* Menu Items */}
        <nav style={{ display: "flex", flexDirection: "column", gap: 4, padding: "0 12px" }}>
          {NAV_ITEMS.map((item, i) => (
            <NavLink
              key={item.url}
              to={item.url}
              end
              onClick={() => setOpen(false)}
              className="sidebar-nav-link"
              style={({ isActive }) => ({
                display: "flex",
                alignItems: "center",
                gap: 14,
                padding: "14px 16px",
                borderRadius: 12,
                textDecoration: "none",
                fontFamily: "'Outfit', sans-serif",
                fontSize: 14,
                fontWeight: 600,
                color: isActive ? G : "#fff",
                background: isActive ? GA(0.12) : "transparent",
                border: `1px solid ${isActive ? GA(0.3) : "transparent"}`,
                transition: "all 0.25s ease",
                cursor: "pointer",
                opacity: 0,
                transform: "translateX(-20px)",
                animation: open ? `slideIn 0.3s ease forwards ${i * 40}ms` : "none",
              })}
            >
              <item.Icon size={20} strokeWidth={2.5} />
              <span>{item.title}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Outfit:wght@400;500;600;700&display=swap');

        @keyframes tnav-fade {
          from { opacity: 0; }
          to   { opacity: 1; }
        }

        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateX(-20px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }

        /* ─── Burger ─── */
        .tnav-burger {
          width: 46px; height: 46px;
          background: rgb(20,20,20);
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 12px;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          gap: 5px; cursor: pointer;
          transition: border-color 0.3s, border-radius 0.4s;
          flex-shrink: 0;
        }
        .tnav-burger:hover { border-color: ${GA(0.5)}; border-radius: 23px; }
        .tnb1,.tnb2,.tnb3,.tnb4 {
          display: block; width: 22px; height: 2.5px;
          background: #fff; border-radius: 30px; transition: 0.35s;
        }
        .tnav-burger--open { border-color: ${GA(0.5)}; border-radius: 23px; }
        .tnav-burger--open .tnb1 { opacity: 0; transform: translateY(4px); }
        .tnav-burger--open .tnb4 { opacity: 0; transform: translateY(-4px); }
        .tnav-burger--open .tnb2 { transform: rotate(45deg); background: ${G}; }
        .tnav-burger--open .tnb3 { transform: rotate(-45deg) translateY(1px); background: ${G}; margin-top: -10px; }

        /* ─── Sidebar Nav Links ─── */
        .sidebar-nav-link:hover {
          background: ${GA(0.08)} !important;
          border-color: ${GA(0.2)} !important;
          transform: translateX(4px);
        }
      `}</style>
    </>
  );
}