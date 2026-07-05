import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth.jsx";

export default function Layout() {
  const { user, demo, signOutUser } = useAuth();
  const navigate = useNavigate();

  const callsign = demo
    ? "Demo subject"
    : user?.displayName || user?.email || "Unknown";

  const onSignOut = async () => {
    await signOutUser();
    navigate("/login", { replace: true });
  };

  // Synthetic file number — stable per-session, reads as archival metadata.
  const fileNo = "GC-" + (demo ? "DM" : (user?.uid || "AN").slice(0, 4)).toUpperCase();

  return (
    <>
      <div className="atmos" aria-hidden="true" />
      <aside className="page-margin" aria-hidden="true">
        <span className="file-no">FILE {fileNo} · DOSSIER GC</span>
      </aside>

      {demo && (
        <div className="demo-strip">
          Demo file — sample data. Connect Firebase to load real telemetry.
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <div>
            <div className="brand-name">
              GAME<em>·</em>CORE
            </div>
          </div>
          <div className="brand-sub">Adaptive Opponent Intelligence</div>
        </div>

        <nav className="nav">
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
            Dossier
          </NavLink>
          <NavLink to="/world" className={({ isActive }) => (isActive ? "active" : "")}>
            World
          </NavLink>
          <NavLink to="/download" className={({ isActive }) => (isActive ? "active" : "")}>
            Deployment
          </NavLink>
        </nav>

        <div className="topbar-right">
          <span className="callsign">
            Subject — <b>{callsign}</b>
          </span>
          <button className="btn ghost small" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="page">
        <Outlet />
      </main>

      <footer className="footer">
        <span>GAME_CORE — Reinforcement-learning boss project</span>
        <span>It watches. It learns. It remembers.</span>
      </footer>
    </>
  );
}
