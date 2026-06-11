import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth.jsx";

export default function Layout() {
  const { user, demo, signOutUser } = useAuth();
  const navigate = useNavigate();

  const callsign = demo
    ? "DEMO SUBJECT"
    : user?.displayName || user?.email || "UNKNOWN";

  const onSignOut = async () => {
    await signOutUser();
    navigate("/login", { replace: true });
  };

  return (
    <>
      <div className="atmos" aria-hidden="true" />
      <div className="scanlines" aria-hidden="true" />

      {demo && (
        <div className="demo-strip">
          Demo file — sample data. Connect Firebase to see real telemetry.
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          <div>
            <div className="brand-name">
              GAME<em>_</em>CORE
            </div>
            <div className="brand-sub">Adaptive Opponent Intelligence</div>
          </div>
        </div>

        <nav className="nav">
          <NavLink to="/dashboard" className={({ isActive }) => (isActive ? "active" : "")}>
            Dossier
          </NavLink>
          <NavLink to="/download" className={({ isActive }) => (isActive ? "active" : "")}>
            Deployment
          </NavLink>
        </nav>

        <div className="topbar-right">
          <span className="callsign">
            SUBJECT: <b>{callsign}</b>
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
        <span>GAME_CORE // reinforcement-learning boss project</span>
        <span>It watches. It learns. It remembers.</span>
      </footer>
    </>
  );
}
