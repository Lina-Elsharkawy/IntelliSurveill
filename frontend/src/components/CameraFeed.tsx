/**
 * IntelliSurveil — Camera Feed Dashboard
 * Drop-in React component with full CRUD connectivity.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  getAllCameras,
  createCamera,
  updateCamera,
  deleteCamera
} from "@/services/cameras";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface Camera {
  id: string; // e.g. "CAM-01"
  db_id: number;
  name: string;
  location: string;
  lab_id: number;
  status: "active" | "inactive" | "alert";
  thumbnail: string;
}

// Export alias so Cameras.tsx can still import CameraFeedData
export type CameraFeedData = Camera;

interface CameraFeedProps {
  cameras: Camera[];
}

const G = "rgb(46,213,115)";
const GA = (a: number) => `rgba(46,213,115,${a})`;

// ─── Sub-component: 3-D Camera Card ──────────────────────────────────────────

interface CardProps {
  cam: Camera;
  onPlay?: (cam: Camera) => void;
  onClick?: () => void;
  isActive?: boolean;
  width?: number | string;
  height?: number | string;
}

const GRID_ROWS = 5;
const GRID_COLS = 5;

export function CameraCard({ cam, onPlay, onClick, isActive = false, width = 680, height = 480 }: CardProps) {
  const cardRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState(false);
  const [tilt, setTilt] = useState({ rx: 0, ry: 0 });

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!isActive) return;
    const el = cardRef.current;
    if (!el) return;
    const { left, top, width, height } = el.getBoundingClientRect();
    const mx = (e.clientX - left) / width;
    const my = (e.clientY - top) / height;
    const col = Math.floor(mx * GRID_COLS);
    const row = Math.floor(my * GRID_ROWS);
    const ry = (col - (GRID_COLS - 1) / 2) * (8 / ((GRID_COLS - 1) / 2));
    const rx = ((GRID_ROWS - 1) / 2 - row) * (15 / ((GRID_ROWS - 1) / 2));
    setTilt({ rx, ry });
  }, [isActive]);

  const statusColor = {
    active: G,
    inactive: "rgba(255,255,255,0.3)",
    alert: "#ff4444",
  }[cam.status];

  return (
    <div
      onClick={onClick}
      style={{
        perspective: "1200px",
        width: width,
        height: height,
        flexShrink: 0,
        cursor: isActive ? "default" : "pointer",
        userSelect: "none",
        transition: "all 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
        transform: isActive ? "scale(1)" : "scale(0.8)",
        opacity: isActive ? 1 : 0.3,
        filter: isActive ? "none" : "grayscale(0.5)",
      }}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setTilt({ rx: 0, ry: 0 }); }}
    >
      <div
        ref={cardRef}
        style={{
          width: "100%", height: "100%", borderRadius: 24,
          background: "linear-gradient(145deg, #0a0a0a, #111)",
          border: isActive ? `1.5px solid ${hovered ? GA(0.8) : GA(0.4)}` : "1px solid rgba(255,255,255,0.1)",
          position: "relative", overflow: "hidden",
          boxShadow: isActive && hovered ? `0 25px 60px rgba(0,0,0,0.8), 0 0 40px rgba(46,213,115,0.2)` : "0 15px 40px rgba(0,0,0,0.5)",
          transition: "transform 150ms ease-out, border-color 300ms, box-shadow 400ms",
          transform: `rotateX(${tilt.rx}deg) rotateY(${tilt.ry}deg)`,
        }}
      >
        {/* Mirror Glare */}
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(135deg, rgba(255,255,255,0.05) 0%, transparent 40%, transparent 60%, rgba(255,255,255,0.02) 100%)", pointerEvents: "none", zIndex: 5 }} />

        {/* Scan lines overlay */}
        <div style={{ position: "absolute", inset: 0, backgroundImage: "repeating-linear-gradient(0deg, transparent 0px, rgba(46,213,115,0.03) 1px, transparent 2px)", backgroundSize: "100% 4px", zIndex: 4, pointerEvents: "none", opacity: isActive ? 1 : 0, transition: "opacity 0.6s" }} />

        {/* Visual Feed */}
        <div style={{ width: "100%", height: "100%", position: "relative" }}>
          <img src={cam.thumbnail} alt={cam.name} style={{ width: "100%", height: "100%", objectFit: "cover", filter: cam.status === "inactive" ? "grayscale(1) brightness(0.4)" : (isActive ? "brightness(0.9) contrast(1.1)" : "brightness(0.5) blur(1px)"), transition: "all 0.6s" }} />
          <div style={{ position: "absolute", inset: 0, background: "radial-gradient(circle, transparent 20%, rgba(0,0,0,0.5) 100%)", pointerEvents: "none" }} />
        </div>

        {/* Play Button HUD */}
        <div
          onClick={(e) => { e.stopPropagation(); onPlay(cam); }}
          style={{
            position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
            backgroundColor: "rgba(0,0,0,0.4)", backdropFilter: hovered ? "blur(6px)" : "blur(0px)",
            opacity: isActive && hovered ? 1 : 0, transition: "all 0.4s cubic-bezier(0.4, 0, 0.2, 1)", zIndex: 10, cursor: "pointer"
          }}
        >
          <div style={{ width: 90, height: 90, borderRadius: "50%", border: "2.5px solid rgba(46,213,115,0.9)", background: "rgba(0,0,0,0.8)", display: "flex", alignItems: "center", justifyContent: "center", transform: hovered ? "scale(1.1)" : "scale(0.8)", transition: "transform 0.4s", boxShadow: "0 0 35px rgba(46,213,115,0.5)" }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="rgb(46,213,115)"><path d="M8 5v14l11-7z" /></svg>
          </div>
          <div style={{ position: "absolute", bottom: "20%", color: "rgb(46,213,115)", fontSize: 11, fontFamily: "'Outfit', sans-serif", letterSpacing: 5, fontWeight: 700 }}>WATCH LIVE</div>
        </div>

        {/* Info Labels */}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: "32px", background: "linear-gradient(to top, rgba(0,0,0,0.98) 0%, rgba(0,0,0,0.7) 60%, transparent 100%)", zIndex: 6, opacity: isActive ? 1 : 0, transform: isActive ? "translateY(0)" : "translateY(20px)", transition: "all 0.5s ease 0.1s" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
                <div style={{ width: 10, height: 10, borderRadius: "50%", background: statusColor, boxShadow: `0 0 12px ${statusColor}` }} />
                <span style={{ fontSize: 10, fontFamily: "'Outfit', sans-serif", color: statusColor, letterSpacing: 3, fontWeight: 700 }}>{cam.status.toUpperCase()}</span>
              </div>
              <h2 style={{ fontSize: 32, fontFamily: "'Space Grotesk', sans-serif", fontWeight: 700, color: "#fff", textTransform: "uppercase", letterSpacing: "-0.01em", lineHeight: 1 }}>{cam.name}</h2>
              <div style={{ display: "flex", gap: 24, marginTop: 8 }}>
                <div style={{ fontSize: 13, opacity: 0.6, fontFamily: "'Manrope', sans-serif", letterSpacing: 1 }}>Loc: <span style={{ color: "#fff", fontWeight: 600 }}>{cam.location}</span></div>
                <div style={{ fontSize: 13, opacity: 0.6, fontFamily: "'Manrope', sans-serif", letterSpacing: 1 }}>Lab ID: <span style={{ color: "#fff", fontWeight: 600 }}>{cam.lab_id}</span></div>
              </div>
            </div>
            <div style={{ textAlign: "right", fontFamily: "'Space Grotesk', sans-serif" }}>
              <div style={{ fontSize: 20, color: "rgba(46,213,115,0.9)", fontWeight: 700 }}>{cam.id}</div>
              <div style={{ fontSize: 9, opacity: 0.4, letterSpacing: 3, marginTop: 2, fontFamily: "'Outfit', sans-serif", fontWeight: 600 }}>SECURED NODE</div>
            </div>
          </div>
        </div>

        {/* UI Accents */}
        <div style={{ position: "absolute", top: 24, left: 24, width: 24, height: 24, borderLeft: "2px solid rgba(46,213,115,0.5)", borderTop: "2px solid rgba(46,213,115,0.5)" }} />
        <div style={{ position: "absolute", top: 24, right: 24, width: 24, height: 24, borderRight: "2px solid rgba(46,213,115,0.5)", borderTop: "2px solid rgba(46,213,115,0.5)" }} />
      </div>
    </div>
  );
}

// ─── Modal Components ────────────────────────────────────────────────────────

interface ModalProps {
  onClose: () => void;
  onSave: (data: any) => void;
  cam?: Camera | null;
}

function CameraModal({ onClose, onSave, cam }: ModalProps) {
  const [f, setF] = useState({ name: cam?.name || "", loc: cam?.location || "", lab: cam?.lab_id || 1 });

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,.92)", backdropFilter: "blur(10px)", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: 440, background: "#0a0a0a", border: `1px solid ${GA(0.3)}`, clipPath: "polygon(0 0, calc(100% - 30px) 0, 100% 30px, 100% 100%, 30px 100%, 0 calc(100% - 30px))", position: "relative", padding: "40px" }}>
        <h3 style={{ fontFamily: "'Syne', sans-serif", fontSize: 24, fontWeight: 800, color: "#fff", marginBottom: 10 }}>{cam ? "UPDATE_NODE" : "REGISTER_NODE"}</h3>
        <p style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: GA(0.5), letterSpacing: 2, marginBottom: 30 }}>// {cam ? "MODIFYING SYSTEM POINT" : "CONNECTING NEW SURVEILLANCE POINT"}</p>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <input style={{ background: "#000", border: `1px solid ${GA(0.2)}`, padding: 12, color: "#fff" }} placeholder="Name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
          <input style={{ background: "#000", border: `1px solid ${GA(0.2)}`, padding: 12, color: "#fff" }} placeholder="Location" value={f.loc} onChange={e => setF({ ...f, loc: e.target.value })} />
          <input type="number" style={{ background: "#000", border: `1px solid ${GA(0.2)}`, padding: 12, color: "#fff" }} placeholder="Lab ID" value={f.lab} onChange={e => setF({ ...f, lab: parseInt(e.target.value) })} />
        </div>
        <div style={{ marginTop: 40, display: "flex", gap: 15 }}>
          <button onClick={onClose} style={{ flex: 1, padding: "12px", background: "transparent", border: "1px solid rgba(255,255,255,0.1)", color: "rgba(255,255,255,0.5)", fontFamily: "'JetBrains Mono'", fontSize: 11, cursor: "pointer" }}>CANCEL</button>
          <button onClick={() => onSave(f)} style={{ flex: 2, padding: "12px", background: GA(0.1), border: `1px solid ${G}`, color: G, fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 700, cursor: "pointer", letterSpacing: 2 }}>{cam ? "SAVE_CHANGES →" : "INITIALIZE →"}</button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function CameraFeed({ cameras: initialCameras }: CameraFeedProps) {
  const [cameras, setCameras] = useState<Camera[]>(initialCameras || []);
  const [activeIndex, setActiveIndex] = useState(0);
  const [fullscreenCam, setFullscreenCam] = useState<Camera | null>(null);
  const [modal, setModal] = useState<{ show: boolean, cam: Camera | null }>({ show: false, cam: null });

  useEffect(() => { setCameras(initialCameras); }, [initialCameras]);

  const refreshList = async () => {
    try {
      const resp = await getAllCameras();
      setCameras(resp.map((c: any) => ({
        db_id: c.id, id: `CAM-${c.id.toString().padStart(2, '0')}`,
        name: c.name, location: c.location, lab_id: c.lab_id,
        status: "active", thumbnail: "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800&q=80"
      })));
    } catch (e) { console.error(e); }
  };

  const handleSave = async (data: any) => {
    const payload = { name: data.name, location: data.loc, lab_id: data.lab };
    modal.cam ? await updateCamera(modal.cam.db_id, payload) : await createCamera(payload);
    await refreshList(); setModal({ show: false, cam: null });
  };

  const handleDelete = async () => {
    const activeCam = cameras[activeIndex];
    if (!activeCam || !window.confirm("CONFIRM TERMINATION?")) return;
    await deleteCamera(activeCam.db_id); await refreshList();
    if (activeIndex >= cameras.length - 1) setActiveIndex(Math.max(0, cameras.length - 2));
  };

  const CARD_WIDTH = 680;
  const CARD_GAP = 80;
  const canPrev = activeIndex > 0;
  const canNext = activeIndex < cameras.length - 1;

  const goTo = (idx: number) => setActiveIndex(Math.max(0, Math.min(cameras.length - 1, idx)));

  return (
    <div style={{ background: "#050505", minHeight: "100vh", width: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", overflow: "hidden", position: "relative", color: "#fff" }}>

      {/* HEADER */}
      <div style={{ position: "absolute", top: 40, left: 60, right: 60, zIndex: 20, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {/* Left: Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ position: "relative", width: 10, height: 10 }}>
            <div style={{ width: 10, height: 10, borderRadius: "50%", background: G, boxShadow: `0 0 10px ${G}` }} />
            <div className="pulse-ring" />
          </div>
          <div>
            <div style={{ fontFamily: "'Outfit', sans-serif", fontSize: 16, fontWeight: 800, color: GA(0.6), letterSpacing: 5, textTransform: "uppercase", marginBottom: 4 }}>IntelliSurveil · Live</div>
            <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 42, fontWeight: 700, color: "#fff", letterSpacing: "-0.02em", lineHeight: 1 }}>Camera Feeds</div>
          </div>
          <div style={{ marginLeft: 8, padding: "4px 14px", borderRadius: 100, border: `1px solid ${GA(0.2)}`, background: GA(0.06), display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: G }} />
            <span style={{ fontFamily: "'Outfit', sans-serif", fontSize: 11, color: GA(0.7), letterSpacing: 1, fontWeight: 600 }}>{cameras.filter(c => c.status === "active").length} active</span>
          </div>
        </div>

        {/* Right: Add Camera */}
        <button className="cam-btn cam-btn--add" onClick={() => setModal({ show: true, cam: null })} title="Add Camera">
          <svg className="cam-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>

      {/* SWIPING CAROUSEL */}
      <div style={{ display: "flex", alignItems: "center", gap: 40, zIndex: 15, position: "relative" }}>
        <button onClick={() => goTo(activeIndex - 1)} disabled={!canPrev} style={{ width: 76, height: 76, background: "rgba(10,10,10,0.6)", border: `1.5px solid ${canPrev ? GA(0.4) : "rgba(255,255,255,0.05)"}`, borderRadius: "50%", color: canPrev ? G : "rgba(255,255,255,0.1)", fontSize: 32, cursor: canPrev ? "pointer" : "not-allowed", transition: "0.3s", backdropFilter: "blur(8px)", boxShadow: canPrev ? `0 0 25px ${GA(0.1)}` : "none", zIndex: 30 }}>&lt;</button>

        <div style={{ width: CARD_WIDTH, height: 480, overflow: "visible", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
          <div style={{ display: "flex", gap: CARD_GAP, transition: "transform 0.7s cubic-bezier(0.16, 1, 0.3, 1)", transform: `translateX(calc(${-activeIndex} * (${CARD_WIDTH}px + ${CARD_GAP}px)))`, width: "100%" }}>
            {cameras.map((c, i) => (
              <CameraCard key={c.db_id} cam={c} isActive={i === activeIndex} onClick={() => goTo(i)} onPlay={setFullscreenCam} />
            ))}
          </div>
        </div>

        <button onClick={() => goTo(activeIndex + 1)} disabled={!canNext} style={{ width: 76, height: 76, background: "rgba(10,10,10,0.6)", border: `1.5px solid ${canNext ? GA(0.4) : "rgba(255,255,255,0.05)"}`, borderRadius: "50%", color: canNext ? G : "rgba(255,255,255,0.1)", fontSize: 32, cursor: canNext ? "pointer" : "not-allowed", transition: "0.3s", backdropFilter: "blur(8px)", boxShadow: canNext ? `0 0 25px ${GA(0.1)}` : "none", zIndex: 30 }}>&gt;</button>
      </div>

      {/* ACTIONS UNDER CARD — animated pill buttons */}
      <div className="cam-actions" style={{ marginTop: 28, display: "flex", gap: 20, zIndex: 20, alignItems: "center" }}>
        {/* Update Button */}
        <button
          className="cam-btn cam-btn--update"
          onClick={() => setModal({ show: true, cam: cameras[activeIndex] })}
          title="Update camera"
        >
          <svg className="cam-btn__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </svg>
        </button>

        {/* Delete Button */}
        <button
          className="cam-btn cam-btn--delete"
          onClick={handleDelete}
          title="Delete camera"
        >
          <svg className="cam-btn__icon" viewBox="0 0 448 512">
            <path d="M135.2 17.7L128 32H32C14.3 32 0 46.3 0 64S14.3 96 32 96H416c17.7 0 32-14.3 32-32s-14.3-32-32-32H320l-7.2-14.3C307.4 6.8 296.3 0 284.2 0H163.8c-12.1 0-23.2 6.8-28.6 17.7zM416 128H32L53.2 467c1.6 25.3 22.6 45 47.9 45H346.9c25.3 0 46.3-19.7 47.9-45L416 128z" />
          </svg>
        </button>
      </div>

      {/* INDICATOR BAR */}
      <div style={{ marginTop: 36, display: "flex", gap: 16 }}>
        {cameras.map((_, i) => (
          <div key={i} onClick={() => goTo(i)} style={{ width: i === activeIndex ? 40 : 8, height: 4, borderRadius: 2, background: i === activeIndex ? G : GA(0.15), boxShadow: i === activeIndex ? `0 0 10px ${GA(0.4)}` : "none", transition: "all 0.6s cubic-bezier(0.16, 1, 0.3, 1)", cursor: "pointer" }} />
        ))}
      </div>

      {modal.show && <CameraModal onClose={() => setModal({ show: false, cam: null })} onSave={handleSave} cam={modal.cam} />}

      {fullscreenCam && (
        <div onClick={() => setFullscreenCam(null)} style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(0,0,0,0.98)", display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(12px)", animation: "fadeIn 0.5s ease-out" }}>
          <div style={{ width: "90%", maxWidth: 1400, position: "relative", animation: "scaleUp 0.5s cubic-bezier(0.16, 1, 0.3, 1)" }}>
            <img src={fullscreenCam.thumbnail} style={{ width: "100%", borderRadius: 24, boxShadow: "0 0 120px rgba(0,0,0,1)", border: "1px solid rgba(255,255,255,0.05)" }} />
            <div style={{ position: "absolute", top: 40, left: 40, background: "rgba(0,0,0,0.7)", padding: "20px 30px", borderRadius: 16, border: `1px solid ${GA(0.2)}`, backdropFilter: "blur(10px)" }}>
              <div style={{ fontSize: 10, letterSpacing: 4, color: G, fontWeight: 700, marginBottom: 5 }}>ENCRYPTED_UP_LINK</div>
              <h2 style={{ fontFamily: "'Syne'", fontSize: 48, fontWeight: 800, textTransform: "uppercase" }}>{fullscreenCam.name}</h2>
              <p style={{ color: "rgba(255,255,255,0.5)", fontSize: 16, fontFamily: "'JetBrains Mono'" }}>{fullscreenCam.location} // {fullscreenCam.id}</p>
            </div>
            <button style={{ position: "absolute", top: 40, right: 40, width: 50, height: 50, background: "rgba(0,0,0,0.5)", border: "1px solid rgba(255,255,255,0.2)", color: "#fff", fontSize: 24, cursor: "pointer", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center" }}>✕</button>
          </div>
        </div>
      )}

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Manrope:wght@400;500;600&family=Outfit:wght@400;500;600;700&display=swap');
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes scaleUp { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        @keyframes pulse { 0% { transform: scale(1); opacity: 0.8; } 100% { transform: scale(2.4); opacity: 0; } }

        .pulse-ring {
          position: absolute;
          inset: 0;
          border-radius: 50%;
          border: 1.5px solid rgb(46,213,115);
          animation: pulse 1.8s ease-out infinite;
        }

        /* ── Animated action buttons ── */
        .cam-btn {
          width: 50px;
          height: 50px;
          border-radius: 50%;
          border: none;
          font-weight: 600;
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 0 20px rgba(0,0,0,0.3);
          cursor: pointer;
          transition: width 0.3s ease, border-radius 0.3s ease, background-color 0.3s ease;
          overflow: hidden;
          position: relative;
          font-family: 'Outfit', sans-serif;
          font-size: 0;
        }
        .cam-btn__icon {
          width: 14px;
          flex-shrink: 0;
          transition: width 0.3s ease, transform 0.3s ease;
        }
        .cam-btn::before {
          position: absolute;
          top: -20px;
          content: attr(title);
          color: #fff;
          font-size: 0;
          transition: font-size 0.2s ease, transform 0.3s ease, opacity 0.2s ease;
          opacity: 0;
          white-space: nowrap;
          font-family: 'Outfit', sans-serif;
          font-weight: 600;
          letter-spacing: 0.5px;
        }

        /* ADD button */
        .cam-btn--add {
          background-color: rgba(46, 213, 115, 0.15);
          border: 1.5px solid rgba(46, 213, 115, 0.5) !important;
        }
        .cam-btn--add .cam-btn__icon { stroke: rgb(46, 213, 115); fill: none; }
        .cam-btn--add:hover {
          width: 140px;
          border-radius: 50px;
          background-color: rgb(46, 213, 115);
        }
        .cam-btn--add:hover .cam-btn__icon {
          width: 44px;
          transform: translateY(60%);
        }
        .cam-btn--add:hover::before {
          content: 'Add Camera';
          font-size: 13px;
          opacity: 1;
          transform: translateY(30px);
        }

        /* UPDATE button */
        .cam-btn--update {
          background-color: rgb(20, 20, 20);
        }
        .cam-btn--update .cam-btn__icon { stroke: white; fill: none; }
        .cam-btn--update:hover {
          width: 140px;
          border-radius: 50px;
          background-color: rgb(46, 213, 115);
        }
        .cam-btn--update:hover .cam-btn__icon {
          width: 44px;
          transform: translateY(60%);
        }
        .cam-btn--update:hover::before {
          content: 'Update';
          font-size: 13px;
          opacity: 1;
          transform: translateY(30px);
        }

        /* DELETE button */
        .cam-btn--delete {
          background-color: rgb(20, 20, 20);
        }
        .cam-btn--delete .cam-btn__icon { fill: white; }
        .cam-btn--delete:hover {
          width: 140px;
          border-radius: 50px;
          background-color: rgb(255, 69, 69);
        }
        .cam-btn--delete:hover .cam-btn__icon {
          width: 44px;
          transform: translateY(60%);
        }
        .cam-btn--delete:hover::before {
          content: 'Delete';
          font-size: 13px;
          opacity: 1;
          transform: translateY(30px);
        }
      `}</style>
    </div>
  );
}