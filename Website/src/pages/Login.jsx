import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../useAuth.jsx";

const ERRORS = {
  "auth/invalid-credential": "Credentials rejected. Check email and password.",
  "auth/email-already-in-use": "That email is already enlisted. Sign in instead.",
  "auth/weak-password": "Password too weak — 6 characters minimum.",
  "auth/invalid-email": "That doesn't parse as an email address.",
};

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
      <div className="scanlines" aria-hidden="true" />

      <div className="login-brand">
        <div className="rings" aria-hidden="true" />
        <div className="reveal d1">
          <div className="kicker">// SUBJECT DOSSIER TERMINAL</div>
          <h1 className="login-title">
            GAME<em>_</em>CORE
          </h1>
          <p className="login-tag">
            You fought it. It was <b>paying attention</b>. Every dodge, every
            combo, every habit — filed, scored, and used against you. Sign in
            to read what the boss knows.
          </p>
        </div>
      </div>

      <div className="login-form-side">
        <div className="login-card reveal d2">
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
                  placeholder="How the dossier names you"
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
            <button className="btn ghost" type="button" onClick={demo} style={{ width: "100%" }}>
              View demo file
            </button>
          </div>

          {!isConfigured && (
            <p className="login-note">
              Backend not configured yet — paste your Firebase config into
              src/firebase.js to enable accounts. Demo mode works now.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
