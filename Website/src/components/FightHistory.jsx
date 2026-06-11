const fmtDate = (ms) =>
  new Date(ms).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

const fmtDuration = (s) => {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

const dominant = (e) => {
  const entries = [
    ["FLOW", e.flow],
    ["FRUSTRATION", e.frustration],
    ["BOREDOM", e.boredom],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0][0];
};

export default function FightHistory({ fights }) {
  if (!fights.length) {
    return (
      <div className="empty">
        NO ENGAGEMENTS ON RECORD — fight while online (or sync later) and every
        round is filed here.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="log-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Logged</th>
            <th>Opponent</th>
            <th>Outcome</th>
            <th>Duration</th>
            <th>Boss HP left</th>
            <th>Your HP left</th>
            <th>Dominant affect</th>
          </tr>
        </thead>
        <tbody>
          {fights.map((f, i) => (
            <tr key={f.id}>
              <td className="num">{String(fights.length - i).padStart(3, "0")}</td>
              <td className="num">{fmtDate(f.startedAt)}</td>
              <td>
                <span className={`chip ${f.encounterType}`}>
                  {f.encounterType === "boss" ? "BOSS" : "PATROL"}
                </span>
              </td>
              <td>
                <span className={`chip ${f.outcome}`}>
                  {f.outcome === "win" ? "VICTORY" : "DEFEAT"}
                </span>
              </td>
              <td className="num">{fmtDuration(f.durationSeconds)}</td>
              <td className="num">{Math.round(f.bossHpAtEnd)}</td>
              <td className="num">{Math.round(f.heroHpAtEnd)}</td>
              <td>{dominant(f.emotion)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
