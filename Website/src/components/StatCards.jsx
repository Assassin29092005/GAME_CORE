const fmtDuration = (s) => {
  if (!s) return "0:00";
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

export default function StatCards({ stats }) {
  return (
    <div className="stats">
      <div className="stat accent">
        <div className="k">Victory rate</div>
        <div className="v num">
          {stats.winRate}
          <small>%</small>
        </div>
      </div>
      <div className="stat">
        <div className="k">Engagements on file</div>
        <div className="v num">{stats.total}</div>
      </div>
      <div className="stat">
        <div className="k">Average length</div>
        <div className="v num">{fmtDuration(stats.avgDuration)}</div>
      </div>
      <div className="stat verdigris">
        <div className="k">Fights in flow</div>
        <div className="v num">
          {stats.flowShare}
          <small>%</small>
        </div>
      </div>
    </div>
  );
}
