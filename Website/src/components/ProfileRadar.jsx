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
export default function ProfileRadar({ profile }) {
  if (!profile) {
    return (
      <div className="empty">
        No profile on record. Sign in and the boss starts taking notes.
      </div>
    );
  }

  const data = DIMENSIONS.map((d) => ({
    code: d.code,
    label: d.label,
    value: Number(((profile[d.key] ?? 0.5) * 100).toFixed(0)),
  }));

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
            <Radar
              dataKey="value"
              stroke="#6a9892"
              strokeWidth={1.5}
              fill="#6a9892"
              fillOpacity={0.18}
              isAnimationActive
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <div className="dims">
        {data.map((d) => (
          <div className="dim" key={d.code} title={d.label}>
            <span className="code">{d.code}</span>
            <span className="bar">
              <i style={{ width: `${d.value}%` }} />
            </span>
            <span className="val num">.{String(d.value).padStart(2, "0")}</span>
          </div>
        ))}
      </div>
    </>
  );
}
