import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { DIMENSIONS } from "../bossAssessment.js";

// Ink-on-paper radar: the verdigris pen stroke against the warm card.
// Optionally overlays a second profile (`compare`, drawn in ember) — the World
// page uses this to plot the community mean against the player's signature.
export default function ProfileRadar({
  profile,
  compare = null,
  profileLabel = "You",
  compareLabel = "Community mean",
  emptyText = "No profile on record. Sign in and the boss starts taking notes.",
}) {
  if (!profile && !compare) {
    return <div className="empty">{emptyText}</div>;
  }

  const pct = (src, key) => Number(((src[key] ?? 0.5) * 100).toFixed(0));

  const data = DIMENSIONS.map((d) => ({
    code: d.code,
    label: d.label,
    value: profile ? pct(profile, d.key) : 0,
    ref: compare ? pct(compare, d.key) : 0,
  }));

  const showBoth = Boolean(profile && compare);

  return (
    <>
      <div style={{ width: "100%", height: 320 }}>
        <ResponsiveContainer>
          <RadarChart data={data} outerRadius="78%">
            <PolarGrid stroke="rgba(106, 152, 146, 0.18)" strokeDasharray="2 4" />
            <PolarAngleAxis
              dataKey="code"
              tick={{
                fill: "#7a7c82",
                fontSize: 10,
                fontFamily: "JetBrains Mono",
                letterSpacing: "0.16em",
              }}
            />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            {compare && (
              <Radar
                dataKey="ref"
                stroke="#d4501a"
                strokeWidth={1.25}
                strokeDasharray="4 3"
                fill="#d4501a"
                fillOpacity={0.1}
                isAnimationActive
              />
            )}
            {profile && (
              <Radar
                dataKey="value"
                stroke="#6a9892"
                strokeWidth={1.5}
                fill="#6a9892"
                fillOpacity={0.18}
                isAnimationActive
              />
            )}
          </RadarChart>
        </ResponsiveContainer>
      </div>

      {compare && (
        <div className="radar-legend">
          {profile && (
            <span className="verd">
              <i />
              {profileLabel}
            </span>
          )}
          <span className="emb">
            <i />
            {compareLabel}
          </span>
        </div>
      )}

      <div className="dims">
        {data.map((d) => (
          <div className="dim" key={d.code} title={d.label}>
            <span className="code">{d.code}</span>
            <span className="bar">
              <i style={{ width: `${profile ? d.value : d.ref}%` }} />
              {showBoth && <b className="ref-mark" style={{ left: `${d.ref}%` }} />}
            </span>
            <span className="val num">
              .{String(profile ? d.value : d.ref).padStart(2, "0")}
              {showBoth && <small className="ref-val"> /.{String(d.ref).padStart(2, "0")}</small>}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}
