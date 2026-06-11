import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";
import { DIMENSIONS } from "../bossAssessment.js";

export default function ProfileRadar({ profile }) {
  if (!profile) {
    return (
      <div className="empty">
        NO PROFILE ON RECORD — play while signed in and the boss will start
        taking notes.
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
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <RadarChart data={data} outerRadius="78%">
            <PolarGrid stroke="#1d2b31" />
            <PolarAngleAxis
              dataKey="code"
              tick={{ fill: "#6e8087", fontSize: 10, fontFamily: "Sometype Mono" }}
            />
            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
            <Radar
              dataKey="value"
              stroke="#3dd6c3"
              strokeWidth={2}
              fill="#3dd6c3"
              fillOpacity={0.22}
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
