import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const COLORS = { flow: "#3dd6c3", frustration: "#ff5c38", boredom: "#8b9dc3" };

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
    return <div className="empty">NO TELEMETRY YET — affect data appears after your first synced fight.</div>;
  }

  // oldest → newest, one point per fight
  const data = [...fights]
    .sort((a, b) => a.startedAt - b.startedAt)
    .map((f) => ({
      label: new Date(f.startedAt).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      }),
      flow: f.emotion.flow,
      frustration: f.emotion.frustration,
      boredom: f.emotion.boredom,
    }));

  return (
    <div style={{ width: "100%", height: 296 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -28 }}>
          <CartesianGrid stroke="#16212685" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: "#44545b", fontSize: 9, fontFamily: "Sometype Mono" }}
            tickLine={false}
            axisLine={{ stroke: "#1d2b31" }}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fill: "#44545b", fontSize: 9, fontFamily: "Sometype Mono" }}
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
              strokeWidth={key === "flow" ? 2.5 : 1.5}
              dot={false}
              activeDot={{ r: 3, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <div style={{ display: "flex", gap: 18, marginTop: 6, fontSize: 10, letterSpacing: "0.18em" }}>
        {Object.entries(COLORS).map(([key, color]) => (
          <span key={key} style={{ color }}>
            ▪ {key.toUpperCase()}
          </span>
        ))}
      </div>
    </div>
  );
}
