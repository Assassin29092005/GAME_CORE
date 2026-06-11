import Panel from "../components/Panel.jsx";

// ── Update these when you package a build (ROADMAP.md milestone M8) ────────
const BUILD = {
  version: "0.1.0-dev",
  date: "TBD",
  sizeGb: "~3",
  url: "#", // ← paste the itch.io / GitHub Releases link here
};

export default function Download() {
  const ready = BUILD.url !== "#";

  return (
    <>
      <div className="dossier-head reveal d1">
        <div>
          <div className="kicker">// DEPLOYMENT PACKAGE</div>
          <h1 className="subject-name">Face it yourself</h1>
        </div>
      </div>

      <div className="grid">
        <Panel title="Build" tag="WINDOWS 64-BIT" variant="live" className="span-rest full reveal d2">
          <div className="dl-hero">
            <div>
              <div className="dl-version num">
                VERSION {BUILD.version} · {BUILD.date} · {BUILD.sizeGb} GB
              </div>
              <p style={{ color: "var(--muted)", marginTop: 8, maxWidth: 520 }}>
                A boss that learns how you fight — profiling your style through
                every minion you cut down, then walking into the arena already
                knowing your habits. Sign in inside the game and this dossier
                fills itself.
              </p>
            </div>
            {ready ? (
              <a className="btn danger" href={BUILD.url}>
                Download for Windows
              </a>
            ) : (
              <button className="btn danger" disabled title="No packaged build yet">
                Build not published yet
              </button>
            )}
          </div>
        </Panel>

        <Panel title="System Requirements" tag="TARGET: 1080P / 60 FPS" className="full reveal d3">
          <table className="req-table">
            <tbody>
              <tr><td>OS</td><td>Windows 10 / 11, 64-bit</td></tr>
              <tr><td>GPU</td><td>GTX 1660 / RTX 2060 or better (RTX 4050 laptop = dev reference)</td></tr>
              <tr><td>RAM</td><td>8 GB minimum, 16 GB recommended</td></tr>
              <tr><td>Disk</td><td>{BUILD.sizeGb} GB free space</td></tr>
              <tr><td>Network</td><td>Optional — game is fully playable offline; online sync powers this dossier</td></tr>
            </tbody>
          </table>
        </Panel>

        <Panel title="Field Protocol" tag="INSTALL &amp; PLAY" className="full reveal d4">
          <ol className="steps">
            <li>Download the archive and extract it anywhere.</li>
            <li>Run GAME_CORE.exe. No installer, no Python, no setup.</li>
            <li>Sign in (or play as guest — your file syncs when you log in later).</li>
            <li>Fight the patrols. They are watching for someone else.</li>
            <li>Reach the arena. It already knows what you did to its minions.</li>
          </ol>
        </Panel>
      </div>
    </>
  );
}
