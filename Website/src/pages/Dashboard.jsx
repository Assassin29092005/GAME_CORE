import { useEffect, useState } from "react";
import { useAuth } from "../useAuth.jsx";
import { computeStats, fetchFights, fetchProfile } from "../dataService.js";
import { bossAssessment } from "../bossAssessment.js";
import Panel from "../components/Panel.jsx";
import StatCards from "../components/StatCards.jsx";
import ProfileRadar from "../components/ProfileRadar.jsx";
import EmotionTimeline from "../components/EmotionTimeline.jsx";
import FightHistory from "../components/FightHistory.jsx";

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
        DECRYPTING FILE…
      </div>
    );
  }

  const callsign = demo ? "DEMO SUBJECT" : user?.displayName || user?.email || "UNKNOWN";
  const assessment = bossAssessment(profile);
  const stats = computeStats(fights);

  return (
    <>
      <div className="dossier-head reveal d1">
        <div>
          <div className="kicker">
            <span className="rec-dot" />
            SUBJECT FILE // ACTIVE SURVEILLANCE
          </div>
          <h1 className="subject-name">{callsign}</h1>
        </div>
        {assessment && (
          <div className="threat-badge">
            <span className="grade num">{assessment.threat}</span>
            <span className="lbl">
              Threat
              <br />
              Class
            </span>
          </div>
        )}
      </div>

      {assessment && (
        <blockquote className="boss-quote reveal d2">
          <span className="who">Boss assessment — generated from your behavior</span>
          “{assessment.lines[0]} {assessment.lines[1]}”
        </blockquote>
      )}

      <div className="grid">
        <div className="reveal d3">
          <StatCards stats={stats} />
        </div>

        <Panel
          title="Behavioral Signature"
          tag="8-DIM PROFILE // EMA"
          variant="live"
          className="reveal d4"
        >
          <ProfileRadar profile={profile} />
        </Panel>

        <Panel
          title="Affect Telemetry"
          tag="FRUSTRATION / FLOW / BOREDOM"
          className="reveal d5"
        >
          <EmotionTimeline fights={fights} />
        </Panel>

        <Panel
          title="Engagement Log"
          tag={`${fights.length} RECORDS`}
          variant="threat"
          className="full reveal d6"
        >
          <FightHistory fights={fights} />
        </Panel>
      </div>
    </>
  );
}
