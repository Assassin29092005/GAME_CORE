import { useEffect, useState } from "react";
import { useAuth } from "../useAuth.jsx";
import { computeStats, fetchFights, fetchProfile } from "../dataService.js";
import { bossAssessment } from "../bossAssessment.js";
import Panel from "../components/Panel.jsx";
import StatCards from "../components/StatCards.jsx";
import ProfileRadar from "../components/ProfileRadar.jsx";
import EmotionTimeline from "../components/EmotionTimeline.jsx";
import TauntPanel from "../components/TauntPanel.jsx";
import FightHistory from "../components/FightHistory.jsx";

const fmtDate = (d) =>
  new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric",
  }).format(d).toUpperCase();

export default function Dashboard() {
  const { user, demo } = useAuth();
  const [profile, setProfile] = useState(null);
  const [fights, setFights] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      const uid = user?.uid ?? "demo";
      const [p, f] = await Promise.all([
        fetchProfile(uid, demo),
        fetchFights(uid, demo),
      ]);
      if (!alive) return;
      setProfile(p);
      setFights(f);
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
        Retrieving file…
      </div>
    );
  }

  const callsign = demo ? "Demo subject" : user?.displayName || user?.email || "Unknown";
  const assessment = bossAssessment(profile);
  const stats = computeStats(fights);

  // Earliest fight = "subject under observation since" date.
  const earliest = fights.length
    ? new Date(Math.min(...fights.map((f) => f.startedAt)))
    : new Date();

  return (
    <>
      <div className="dossier-head reveal d1">
        <div>
          <div className="dossier-meta">
            <div className="meta-field">
              File no.
              <b>GC—{(demo ? "DM00" : (user?.uid || "AN00").slice(0, 4)).toUpperCase()}</b>
            </div>
            <div className="meta-field">
              Opened
              <b>{fmtDate(earliest)}</b>
            </div>
            <div className="meta-field">
              Engagements
              <b>{stats.total}</b>
            </div>
          </div>

          <h1 className="subject-name">
            {callsign.split(" ").map((w, i, arr) =>
              i === arr.length - 1 ? <em key={i}>{w}</em> : <span key={i}>{w} </span>
            )}
          </h1>
        </div>

        {assessment && (
          <div className="threat-block">
            <div className="stamp" style={{ marginBottom: 14 }}>
              Surveillance active
            </div>
            <div className="threat-grade num">{assessment.threat}</div>
            <div className="threat-label">Threat<br />class</div>
          </div>
        )}
      </div>

      {assessment && (
        <blockquote className="assessment reveal d2">
          <div className="who">Analyst's note · written by the boss</div>
          <p className="body">
            {assessment.lines[0]} {assessment.lines[1]}
          </p>
        </blockquote>
      )}

      <div className="grid">
        <div className="col-stats reveal d3">
          <Panel
            title="Vital signs"
            tag="§ 01 · Aggregates"
          >
            <StatCards stats={stats} />
          </Panel>
        </div>

        <div className="col-radar reveal d4">
          <Panel
            title="Behavioral signature"
            tag="§ 02 · 8-dim EMA profile"
            variant="warm"
          >
            <ProfileRadar profile={profile} />
          </Panel>
        </div>

        <div className="col-affect reveal d5">
          <Panel
            title="Affect telemetry"
            tag="§ 03 · Frustration / Flow / Boredom"
          >
            <EmotionTimeline fights={fights} />
          </Panel>
        </div>

        <div className="col-taunts reveal d6">
          <Panel
            title="What the boss says about you"
            tag="§ 04 · Spoken mid-fight, filed verbatim"
          >
            <TauntPanel fights={fights} />
          </Panel>
        </div>

        <div className="col-log reveal d7">
          <Panel
            title="Engagement log"
            tag={`§ 05 · ${fights.length} records on file`}
          >
            <FightHistory fights={fights} />
          </Panel>
        </div>
      </div>
    </>
  );
}
