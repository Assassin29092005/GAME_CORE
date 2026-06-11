const fmtDuration = (s) => {
  if (!s) return "0:00";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

export default function StatCards({ stats }) {
  return (
    <div className="stats">
      <div className="stat">
        <div className="v num">{stats.total}</div>
        <div className="k">Engagements</div>
      </div>
      <div className="stat accent">
        <div className="v num">
          {stats.winRate}
          <small>%</small>
        </div>
        <div className="k">Victory rate</div>
      </div>
      <div className="stat">
        <div className="v num">{fmtDuration(stats.avgDuration)}</div>
        <div className="k">Avg fight length</div>
      </div>
      <div className="stat">
        <div className="v num">
          {stats.flowShare}
          <small>%</small>
        </div>
        <div className="k">Fights in flow</div>
      </div>
    </div>
  );
}
