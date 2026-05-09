import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000';



import { CameraParticles } from "@/components/ui/CameraParticles";

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const [formOpacity, setFormOpacity] = useState(0);
  const [beamActive, setBeamActive] = useState(false);
  const [loginRed, setLoginRed] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Login failed");
      }

      // Use context to update authentication state
      login(data.access_token, data.id_token);
      localStorage.setItem("loggedIn", "true");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Login failed";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFlash = () => {
    setBeamActive(true);
    setTimeout(() => {
      let op = 0;
      const step = () => { op = Math.min(op + 0.05, 1); setFormOpacity(op); if (op < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    }, 50);
  };

  // dot auto-toggles red every 2s regardless of click
  useEffect(() => {
    const id = setInterval(() => setLoginRed(r => !r), 1000);
    return () => clearInterval(id);
  }, []);

  const hue = loginRed ? "355deg" : "142deg";
  const btnBg = loginRed ? "#1f0a0a" : "#0a1f10";

  return (
    <div className="login-container" style={{ display: "flex", height: "100vh", background: "#000", overflow: "hidden", fontFamily: "system-ui,sans-serif", position: "relative" }}>

      {/* LEFT — camera particle canvas */}
      <div style={{ flex: "0 0 50%", position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", paddingBottom: 28 }}>
        <div className="co tl" /><div className="co tr" />
        <div className="co bl" /><div className="co br" />
        <CameraParticles onFlash={handleFlash} />
        <div style={{ position: "relative", zIndex: 10, textAlign: "center", pointerEvents: "none" }}>
          <h2 style={{ fontFamily: "'Syne',sans-serif", fontWeight: 800, fontSize: 20, color: "rgb(46,213,115)", letterSpacing: 5, textTransform: "uppercase" }}>IntelliSurveil</h2>
          <p style={{ fontSize: 10, color: "rgba(46,213,115,0.4)", letterSpacing: 3, marginTop: 4 }}>AI SURVEILLANCE PLATFORM</p>
        </div>
      </div>

      {/* RIGHT — form */}
      <div style={{ flex: "0 0 50%", position: "relative", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10 }}>

        <div style={{ position: "relative", zIndex: 10, width: 340, opacity: formOpacity }}>

          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 30 }}>
            <div style={{ width: 38, height: 38, borderRadius: 10, background: "rgba(46,213,115,0.07)", border: "1px solid rgba(46,213,115,0.22)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" stroke="rgb(46,213,115)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="12" cy="13" r="4" stroke="rgb(46,213,115)" strokeWidth="1.5" />
              </svg>
            </div>
            <div>
              <div style={{ fontFamily: "'Syne',sans-serif", fontWeight: 800, fontSize: 15, color: "#fff" }}>IntelliSurveil</div>
              <div style={{ fontSize: 10, color: "rgba(46,213,115,0.45)", letterSpacing: 2.5, textTransform: "uppercase" }}>AI Platform</div>
            </div>
          </div>

          <h1 style={{ fontFamily: "'Montserrat', sans-serif", fontWeight: 700, fontSize: 32, color: "#fff", lineHeight: 1.1, marginBottom: 12, whiteSpace: "nowrap", letterSpacing: "-0.5px" }}>
            Welcome <span style={{ color: "rgb(46,213,115)" }}>back</span>
          </h1>
          <p style={{ fontSize: 13, color: "rgba(255,255,255,0.4)", marginBottom: 28, lineHeight: 1.6, maxWidth: 300 }}>
            <span style={{ color: "rgba(46,213,115,0.8)", fontWeight: 600 }}>Welcome to IntelliSurveil.</span> Advanced AI surveillance system delivering real-time video intelligence, behavioral analysis and Intelligent access control with identity verification.
          </p>

          <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label className="lbl">Username</label>
              <input
                className="inp"
                type="text"
                placeholder="Email"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>
            <div>
              <label className="lbl">Password</label>
              <input
                className="inp"
                type="password"
                placeholder="••••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            {error && (
              <div style={{ 
                fontSize: 11, 
                color: "#ff3333", 
                background: "rgba(255,51,51,0.05)", 
                padding: "12px 16px", 
                borderRadius: 8, 
                border: "1px solid rgba(255,51,51,0.3)", 
                marginBottom: 4,
                display: "flex",
                alignItems: "center",
                gap: 10,
                fontFamily: "'Syne', sans-serif",
                textTransform: "uppercase",
                letterSpacing: 1.5,
                boxShadow: "0 0 15px rgba(255,51,51,0.1) inset, 0 0 5px rgba(255,51,51,0.2)"
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" style={{ flexShrink: 0 }}>
                  <path d="M12 8v4m0 4h.01M22 12c0 5.523-4.477 10-10 10S2 17.523 2 12 6.477 2 12 2s10 4.477 10 10z" stroke="#ff3333" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {error === "invalid_grant" || error === "Login failed" ? "Access Denied: Invalid Credentials" : error}
                </div>
              </div>
            )}

            {/* btn-wrapper — dot glows and auto-toggles red/green every 2s */}
            <div className="btn-wrapper" style={{ "--hue": hue, cursor: isLoading ? "wait" : "pointer" } as React.CSSProperties}>
              <button
                type="submit"
                className="btn"
                disabled={isLoading}
                style={{
                  background: `linear-gradient(rgba(255,255,255,0.07),rgba(0,0,0,0.04)),${btnBg}`,
                  boxShadow: "1px 1px 2px -1px rgba(255,255,255,0.5) inset,0 2px 1px #00000010,0 4px 2px #00000010,0 8px 4px #00000010,0 16px 8px #00000010,0 32px 16px #00000010"
                }}
              >
                <span className="btn-txt" style={{
                  backgroundImage: `linear-gradient(hsla(${hue},70%,65%,0.95),hsla(${hue},70%,40%,0.7))`,
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                }}>{isLoading ? "Authenticating..." : "Login"}</span>
              </button>
              <div className="dot" style={{ "--hue": hue } as React.CSSProperties} />
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}