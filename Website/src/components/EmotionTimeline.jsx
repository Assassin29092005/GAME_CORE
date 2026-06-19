import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Ember = frustration (boss accent), verdigris = flow (analyst pen), bone-dim = boredom.
const COLORS = { flow: "#88c0b7", frustration: "#ff6e32", boredom: "#c5bfae" };

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      <div className="t">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.stroke }}>
          {p.dataKey}: {Number(p.value).toFixed(2)}
        </div>
      ))}
    </div>
  );
}

export default function EmotionTimeline({ fights }) {
  if (!fights.length) {
    return (
      <div className="empty">
        No telemetry yet. Affect data appears after the first synced fight.
      </div>
    );
  }

  const data = [...fights]
    .sort((a, b) => a.startedAt - b.startedAt)
    .map((f) => ({
      label: new Date(f.startedAt)
        .toLocaleDateString(undefined, { month: "short", day: "numeric" })
        .toUpperCase(),
      flow: f.emotion.flow,
      frustration: f.emotion.frustration,
      boredom: f.emotion.boredom,
    }));

  return (
    <div style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 0, left: -20 }}>
          <CartesianGrid stroke="rgba(35, 38, 41, 0.5)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{
              fill: "#5a5d62",
              fontSize: 9,
              fontFamily: "JetBrains Mono",
              letterSpacing: "0.18em",
            }}
            tickLine={false}
            axisLine={{ stroke: "#232629" }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 1]}
            tick={{
              fill: "#5a5d62",
              fontSize: 9,
              fontFamily: "JetBrains Mono",
            }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip content={<Tip />} />
          {Object.entries(COLORS).map(([key, color]) => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={color}
              strokeWidth={key === "flow" ? 2 : 1.25}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div
        style={{
          display: "flex",
          gap: 28,
          marginTop: 14,
          fontFamily: "JetBrains Mono",
          fontSize: 9,
          letterSpacing: "0.28em",
          textTransform: "uppercase",
        }}
      >
        {Object.entries(COLORS).map(([key, color]) => (
          <span key={key} style={{ color, display: "flex", alignItems: "center", gap: 8 }}>
            <span
              style={{
                display: "inline-block",
                width: 18,
                height: 2,
                background: color,
              }}
            />
            {key}
          </span>
        ))}
      </div>
    </div>
  );
}
