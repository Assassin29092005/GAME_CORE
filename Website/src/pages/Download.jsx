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
          <div className="dossier-meta">
            <div>
              Build
              <b>{BUILD.version}</b>
            </div>
            <div>
              Issued
              <b>{BUILD.date}</b>
            </div>
            <div>
              Size
              <b>{BUILD.sizeGb} GB</b>
            </div>
          </div>

          <h1 className="subject-name">
            Face it<br />
            <em>yourself</em>.
          </h1>
        </div>

        <div className="threat-block">
          <div className="stamp">For deployment</div>
        </div>
      </div>

      <section className="dl-hero reveal d2">
        <div className="dl-info">
          <div className="kicker ember" style={{ marginBottom: 14 }}>
            § Field issue
          </div>
          <p>
            A boss that learns how you fight. The opening hours are scouting —
            it watches your habits, files them away. By the time you reach the
            arena, the file is already complete.
          </p>
          <p>
            Sign in inside the game and this dossier writes itself.
          </p>
        </div>

        <div className="dl-cta">
          {ready ? (
            <a className="btn danger" href={BUILD.url}>
              Download for Windows
            </a>
          ) : (
            <button className="btn danger" disabled title="No packaged build yet">
              Build not published
            </button>
          )}
          <span className="dl-cta-note">
            Windows 64-bit · No installer · No Python · Sign-in optional
          </span>
        </div>
      </section>

      <div className="grid">
        <div className="col-log reveal d3">
          <section className="block">
            <header className="block-head">
              <h2 className="block-title">System requirements</h2>
              <span className="block-tag">§ 05 · Target 1080p / 60</span>
            </header>
            <table className="req-table">
              <tbody>
                <tr><td>Operating system</td><td>Windows 10 or 11, 64-bit</td></tr>
                <tr><td>Graphics</td><td>GTX 1660 or RTX 2060 minimum. RTX 4050 laptop reference.</td></tr>
                <tr><td>Memory</td><td>8 GB minimum, 16 GB recommended</td></tr>
                <tr><td>Storage</td><td>{BUILD.sizeGb} GB free</td></tr>
                <tr><td>Network</td><td>Optional. The game runs fully offline; online presence powers this dossier.</td></tr>
              </tbody>
            </table>
          </section>
        </div>

        <div className="col-log reveal d4">
          <section className="block">
            <header className="block-head">
              <h2 className="block-title">Field protocol</h2>
              <span className="block-tag">§ 06 · Install &amp; play</span>
            </header>
            <ol className="steps">
              <li>Download the archive. Extract anywhere.</li>
              <li>Run <span className="num" style={{ fontFamily: "var(--mono)", fontSize: 14, letterSpacing: "0.06em" }}>GAME_CORE.exe</span>. No installer.</li>
              <li>Sign in — or play as guest and link the file later.</li>
              <li>Fight the patrols. They're watching for someone else.</li>
              <li>Reach the arena. It already knows what you did to its minions.</li>
            </ol>
          </section>
        </div>
      </div>
    </>
  );
}
