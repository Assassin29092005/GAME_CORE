// "What the boss says about you" — renders the taunt lines the boss spoke
// during the latest fights. `taunts` is an OPTIONAL per-fight field (see
// Website/README.md); fights recorded before the field existed simply have
// none, and the panel degrades to its empty state.

const MAX_TAUNTS = 6;

const fmtDate = (ms) =>
  new Date(ms)
    .toLocaleDateString(undefined, { month: "short", day: "2-digit" })
    .toUpperCase();

export default function TauntPanel({ fights }) {
  // fights arrive newest-first from dataService; walk them in order and
  // collect the most recent spoken lines.
  const spoken = [];
  for (const f of fights ?? []) {
    for (const t of Array.isArray(f.taunts) ? f.taunts : []) {
      if (typeof t !== "string" || !t.trim()) continue;
      spoken.push({
        id: `${f.id}-${spoken.length}`,
        text: t.trim(),
        startedAt: f.startedAt,
        outcome: f.outcome,
      });
      if (spoken.length >= MAX_TAUNTS) break;
    }
    if (spoken.length >= MAX_TAUNTS) break;
  }

  if (!spoken.length) {
    return (
      <div className="empty">
        The boss has said nothing about you yet. It speaks mid-fight — sync a
        round and its words are filed here, verbatim.
      </div>
    );
  }

  return (
    <div className="taunt-row">
      {spoken.map((s) => (
        <figure className="taunt" key={s.id}>
          <blockquote className="text">{s.text}</blockquote>
          <figcaption className="meta">
            <span className="num">{fmtDate(s.startedAt)}</span>
            <span className={`chip ${s.outcome}`}>
              {s.outcome === "win" ? "You won" : "It won"}
            </span>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
