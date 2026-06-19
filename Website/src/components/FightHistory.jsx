const fmtDate = (ms) =>
  new Date(ms)
    .toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
    .toUpperCase();

const fmtDuration = (s) => {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};

const dominant = (e) => {
  const entries = [
    ["Flow", e.flow],
    ["Frustration", e.frustration],
    ["Boredom", e.boredom],
  ];
  return entries.sort((a, b) => b[1] - a[1])[0][0];
};

export default function FightHistory({ fights }) {
  if (!fights.length) {
    return (
      <div className="empty">
        No engagements on record. Fight while online (or sync later) and every
        round is filed here.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table className="log-table">
        <thead>
          <tr>
            <th>№</th>
            <th>Logged</th>
            <th>Opponent</th>
            <th>Outcome</th>
            <th>Duration</th>
            <th>Boss HP</th>
            <th>Your HP</th>
            <th>Dominant affect</th>
          </tr>
        </thead>
        <tbody>
          {fights.map((f, i) => (
            <tr key={f.id}>
              <td className="num">{String(fights.length - i).padStart(3, "0")}</td>
              <td className="num">{fmtDate(f.startedAt)}</td>
              <td className="opp-cell">
                {f.encounterType === "boss" ? "The boss" : "Patrol"}
              </td>
              <td>
                <span className={`chip ${f.outcome}`}>
                  {f.outcome === "win" ? "Victory" : "Defeat"}
                </span>
              </td>
              <td className="num">{fmtDuration(f.durationSeconds)}</td>
              <td className="num">{Math.round(f.bossHpAtEnd)}</td>
              <td className="num">{Math.round(f.heroHpAtEnd)}</td>
              <td className="opp-cell" style={{ fontSize: 13 }}>
                {dominant(f.emotion)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
