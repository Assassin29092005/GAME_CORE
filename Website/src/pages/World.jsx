import { useEffect, useState } from "react";
import { useAuth } from "../useAuth.jsx";
import { communityDifficulty, fetchGlobalStats, fetchProfile } from "../dataService.js";
import Panel from "../components/Panel.jsx";
import ProfileRadar from "../components/ProfileRadar.jsx";

const fmtInt = (n) => Number(n || 0).toLocaleString("en-US");

// The boss's "starting level" is derived from the community fight count —
// purely presentational (the real difficulty lives in the RL checkpoint), but
// it communicates the core loop: every synced fight trains the same mind.
const bossLevel = (totalFights) =>
  Math.min(99, 1 + Math.floor(Math.sqrt(Math.max(totalFights, 0) / 10)));

export default function World() {
  const { user, demo } = useAuth();
  const [global, setGlobal] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const uid = user?.uid ?? "demo";
      const [g, p] = await Promise.all([
        fetchGlobalStats(demo),
        fetchProfile(uid, demo),
      ]);
      if (!alive) return;
      setGlobal(g);
      setProfile(p);
      setLoading(false);
    })().catch(() => setLoading(false));
    return () => {
      alive = false;
    };
  }, [user, demo]);

  if (loading) {
    return (
      <div className="boot" style={{ minHeight: "50vh" }}>
        <span className="boot-mark" />
        Opening the world file…
      </div>
    );
  }

  if (!global) {
    return (
      <>
        <div className="dossier-head reveal d1">
          <div>
            <div className="dossier-meta">
              <div className="meta-field">
                File no.
                <b>GC—WORLD</b>
              </div>
            </div>
            <h1 className="subject-name">
              The <em>world</em> file
            </h1>
          </div>
        </div>
        <div className="empty reveal d2">
          The world file is empty — no fighter has synced a round yet. Play
          online and this page becomes the community's shared record.
        </div>
      </>
    );
  }

  const level = bossLevel(global.totalFights);
  const dominance = Math.round(global.bossWinRate * 100);
  // The SAME number the game computes at login via
  // UCommunityDifficultySubsystem::GetGlobalDifficultyScalar() — README.md
  // pins the formula so both sides always display one figure.
  const difficulty = communityDifficulty(global.profileMean);

  return (
    <>
      <div className="dossier-head reveal d1">
        <div>
          <div className="dossier-meta">
            <div className="meta-field">
              File no.
              <b>GC—WORLD</b>
            </div>
            <div className="meta-field">
              Fighters enlisted
              <b className="num">{fmtInt(global.fighters)}</b>
            </div>
            <div className="meta-field">
              Engagements logged
              <b className="num">{fmtInt(global.totalFights)}</b>
            </div>
          </div>

          <h1 className="subject-name">
            The <em>world</em> file
          </h1>
        </div>

        <div className="threat-block">
          <div className="stamp" style={{ marginBottom: 14 }}>
            One mind · many encounters
          </div>
          <div className="threat-grade num">{dominance}%</div>
          <div className="threat-label">
            Boss
            <br />
            dominance
          </div>
        </div>
      </div>

      <div className="world-callout reveal d2">
        <div className="lv">
          <span className="lv-tag">LV</span>
          <span className="lv-num num">{level}</span>
        </div>
        <div className="lv-copy">
          <div className="who">Difficulty briefing</div>
          <p>
            The boss's starting level: <b>{level}</b> — raised by{" "}
            <b className="num">{fmtInt(global.fighters)}</b> fighters before
            you. It does not reset between opponents. Every synced round —
            yours included — feeds the same policy, and the community's habits
            below are what it has learned to expect. Current community
            difficulty scalar: <b className="num">{difficulty.toFixed(2)}</b>{" "}
            (0.50 is a world of brand-new players) — the exact figure the game
            reads at login to set the boss's baseline.
          </p>
        </div>
      </div>

      <div className="grid">
        <div className="col-stats reveal d3">
          <Panel title="Community vitals" tag="§ 01 · Global aggregates">
            <div className="stats">
              <div className="stat accent">
                <div className="k">Boss win rate</div>
                <div className="v num">
                  {dominance}
                  <small>%</small>
                </div>
              </div>
              <div className="stat">
                <div className="k">Engagements worldwide</div>
                <div className="v num">{fmtInt(global.totalFights)}</div>
              </div>
              <div className="stat">
                <div className="k">Fighters enlisted</div>
                <div className="v num">{fmtInt(global.fighters)}</div>
              </div>
              <div className="stat verdigris">
                <div className="k">Community difficulty</div>
                <div className="v num">{difficulty.toFixed(2)}</div>
              </div>
            </div>
          </Panel>
        </div>

        <div className="col-radar reveal d4">
          <Panel
            title="You against the crowd"
            tag="§ 02 · Community-mean profile overlay"
            variant="warm"
          >
            <ProfileRadar
              profile={profile}
              compare={global.profileMean}
              profileLabel="Your signature"
              compareLabel="Community mean"
              emptyText="No community profile yet — means appear once fighters start syncing."
            />
            {!profile && global.profileMean && (
              <p className="world-note">
                No personal profile on record yet — the ember trace is the
                community mean. Fight once and your own signature is drawn
                over it.
              </p>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}
