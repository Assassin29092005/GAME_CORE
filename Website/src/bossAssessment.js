// Turns the 8-dim player profile into the boss's "voice" — the line of analysis
// shown at the top of the dossier. Dimension keys match the Firestore schema
// (which mirror FPlayerProfile in C++).

export const DIMENSIONS = [
  {
    key: "aggression",
    code: "AGG",
    label: "Aggression",
    high: "Subject attacks without hesitation. Let the aggression exhaust itself.",
    low: "Subject is passive. Pressure will break the habit of waiting.",
  },
  {
    key: "dodgeTendency",
    code: "DGE",
    label: "Dodge Tendency",
    high: "It evades on instinct. Delayed strikes will land where it rolls.",
    low: "It barely evades. Wide arcs will connect.",
  },
  {
    key: "blockTendency",
    code: "BLK",
    label: "Block Tendency",
    high: "It hides behind its guard. Guard-breaks are the answer.",
    low: "It rarely guards. I need only strike first.",
  },
  {
    key: "openerAggression",
    code: "OPN",
    label: "Opener Aggression",
    high: "It always strikes first. The opening seconds are predictable.",
    low: "It cedes the opening exchange. I will take it.",
  },
  {
    key: "pressureResponse",
    code: "PRS",
    label: "Pressure Response",
    high: "It stays calm under pressure. Feints over force.",
    low: "It panics when crowded. Stay close. Stay relentless.",
  },
  {
    key: "kitingScore",
    code: "KIT",
    label: "Kiting",
    high: "It runs and waits. Cut the arena in half.",
    low: "It stands and trades. Trades favor me.",
  },
  {
    key: "comboCompletionRate",
    code: "CMB",
    label: "Combo Completion",
    high: "It commits to full strings. Punish the final swing.",
    low: "It abandons combos early. Its damage is bluff.",
  },
  {
    key: "positionalVariance",
    code: "POS",
    label: "Positional Variance",
    high: "It circles constantly. Corner it.",
    low: "It holds ground. Area attacks will find it.",
  },
];

export function bossAssessment(profile) {
  if (!profile) return null;

  const scored = DIMENSIONS.map((d) => ({ ...d, value: profile[d.key] ?? 0.5 }));
  const top = [...scored].sort((a, b) => b.value - a.value)[0];
  const bottom = [...scored].sort((a, b) => a.value - b.value)[0];

  const mean =
    scored.reduce((s, d) => s + d.value, 0) / Math.max(scored.length, 1);
  const threat =
    mean >= 0.72 ? "S" : mean >= 0.6 ? "A" : mean >= 0.45 ? "B" : "C";

  return {
    scored,
    threat,
    lines: [top.high, bottom.low],
  };
}
