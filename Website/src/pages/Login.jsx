import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth.jsx";

const ERRORS = {
  "auth/invalid-credential": "Credentials rejected. Re-enter and try once more.",
  "auth/email-already-in-use": "A file already exists under that address.",
  "auth/weak-password": "Password too brief — six characters minimum.",
  "auth/invalid-email": "That doesn't parse as an email address.",
};

// Today's date — used as the "OPENED" file-metadata stamp.
const fileDate = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit", month: "short", year: "numeric",
}).format(new Date()).toUpperCase();

export default function Login() {
  const { signIn, signUp, enterDemo, isConfigured } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [callsign, setCallsign] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!isConfigured) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "signin") await signIn(email, password);
      else await signUp(email, password, callsign.trim());
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(ERRORS[err?.code] || "Connection refused. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const demo = () => {
    enterDemo();
    navigate("/dashboard", { replace: true });
  };

  return (
    <div className="login">
      <div className="atmos" aria-hidden="true" />
      <aside className="page-margin" aria-hidden="true">
        <span className="file-no">FILE GC-OPEN · DOSSIER GC</span>
      </aside>

      <section className="login-brief">
        <div className="login-brief-meta reveal d1">
          <div className="field-meta">
            File no.
            <b>GC—∅001</b>
          </div>
          <div className="field-meta">
            Subject type
            <b>Adaptive analyst</b>
          </div>
          <div className="field-meta">
            Opened
            <b>{fileDate}</b>
          </div>
        </div>

        <div>
          <div className="kicker reveal d2" style={{ marginBottom: 18 }}>
            § Subject dossier · access terminal
          </div>
          <h1 className="login-title reveal d2">
            The boss<br />
            <em>kept a file</em><br />
            on you.
          </h1>
          <p className="login-tag reveal d3">
            Every dodge. Every combo. Every habit you didn't know you had. Filed,
            scored, and read back to you. Sign in to <b>open the file</b>.
          </p>
        </div>

        <div className="login-stamp-wrap reveal d4">
          <span className="stamp">Classified — Subject only</span>
          <div className="login-stamp-meta">
            Reference: GAME_CORE / RL-BOSS-PROJECT<br />
            Cleared for: SUBJECT &amp; ANALYST
          </div>
        </div>
      </section>

      <section className="login-form-side">
        <div className="login-card reveal d3">
          <header className="login-card-head">
            <div className="kicker">§ {mode === "signin" ? "Sign-in" : "Enlistment"}</div>
            <h2>
              {mode === "signin" ? (
                <>Open the <em>file</em>.</>
              ) : (
                <>Open a <em>new file</em>.</>
              )}
            </h2>
          </header>

          <div className="tabs">
            <button
              type="button"
              className={mode === "signin" ? "on" : ""}
              onClick={() => setMode("signin")}
            >
              Sign in
            </button>
            <button
              type="button"
              className={mode === "signup" ? "on" : ""}
              onClick={() => setMode("signup")}
            >
              Enlist
            </button>
          </div>

          {error && <div className="form-error">{error}</div>}

          <form onSubmit={submit}>
            {mode === "signup" && (
              <div className="field">
                <label htmlFor="callsign">Callsign</label>
                <input
                  id="callsign"
                  value={callsign}
                  onChange={(e) => setCallsign(e.target.value)}
                  placeholder="how the dossier names you"
                  maxLength={24}
                />
              </div>
            )}
            <div className="field">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
              />
            </div>
            <button className="btn" type="submit" disabled={busy || !isConfigured} style={{ width: "100%" }}>
              {busy ? "Authorizing…" : mode === "signin" ? "Open dossier" : "Create file"}
            </button>
          </form>

          <div className="login-alt">
            <span>or, without credentials —</span>
            <button className="btn ghost small" type="button" onClick={demo}>
              View demo file
            </button>
          </div>

          {!isConfigured && (
            <p className="login-note">
              Backend not configured — paste your Firebase config into
              src/firebase.js to enable accounts. Demo mode works now.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
