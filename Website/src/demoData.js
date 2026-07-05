// Sample data shown in demo mode (and useful as a reference for the exact
// shapes the real Firestore documents should have).
//
// The demo tells a story: an aggressive player who rarely blocks, frustrated
// early while learning the boss, sliding into flow as they improve — while the
// boss's win rate keeps the fights close.

export const DEMO_PROFILE = {
  aggression: 0.78,
  dodgeTendency: 0.62,
  blockTendency: 0.27,
  openerAggression: 0.71,
  pressureResponse: 0.44,
  kitingScore: 0.33,
  comboCompletionRate: 0.58,
  positionalVariance: 0.52,
  updatedAt: Date.now(),
};

const DAY = 86_400_000;
const now = Date.now();

const fight = (daysAgo, mins, type, outcome, bossHp, heroHp, fr, fl, bo) => ({
  id: `demo-${daysAgo}-${type}-${outcome}-${bossHp}`,
  startedAt: now - daysAgo * DAY,
  durationSeconds: mins,
  outcome,
  encounterType: type,
  bossHpAtEnd: bossHp,
  heroHpAtEnd: heroHp,
  emotion: { frustration: fr, flow: fl, boredom: bo },
});

export const DEMO_FIGHTS = [
  fight(0.2, 184, "boss", "win", 0, 22, 0.18, 0.74, 0.08),
  fight(0.9, 201, "boss", "loss", 31, 0, 0.34, 0.58, 0.08),
  fight(1.1, 96, "npc", "win", 0, 64, 0.12, 0.61, 0.27),
  fight(2.0, 178, "boss", "win", 0, 9, 0.22, 0.69, 0.09),
  fight(2.8, 162, "boss", "loss", 18, 0, 0.41, 0.49, 0.10),
  fight(3.1, 88, "npc", "win", 0, 71, 0.10, 0.55, 0.35),
  fight(4.0, 149, "boss", "loss", 42, 0, 0.52, 0.38, 0.10),
  fight(4.9, 73, "npc", "win", 0, 58, 0.16, 0.52, 0.32),
  fight(5.2, 141, "boss", "loss", 55, 0, 0.61, 0.31, 0.08),
  fight(6.0, 95, "npc", "loss", 12, 0, 0.48, 0.40, 0.12),
  fight(6.8, 118, "boss", "loss", 64, 0, 0.67, 0.25, 0.08),
  fight(7.5, 81, "npc", "win", 0, 44, 0.22, 0.47, 0.31),
  fight(8.3, 104, "boss", "loss", 71, 0, 0.71, 0.21, 0.08),
  fight(9.0, 69, "npc", "win", 0, 39, 0.25, 0.44, 0.31),
  fight(9.6, 92, "npc", "loss", 8, 0, 0.55, 0.33, 0.12),
  fight(10.4, 61, "npc", "win", 0, 52, 0.20, 0.41, 0.39),
];

// Canned taunts — what the boss "said" during the most recent boss fights.
// Real fights carry an optional `taunts: string[]` field (see Website/README.md);
// demo mode gets three lines so the Dossier panel always has a voice.
DEMO_FIGHTS[0].taunts = [
  "You dodge on rhythm, not on read. I counted the beats.",
];
DEMO_FIGHTS[1].taunts = [
  "Your guard drops after the third swing. It always has.",
];
DEMO_FIGHTS[3].taunts = [
  "You fought the me of last week. I am not him anymore.",
];

// Demo community aggregate — the raw shape of the meta/global document the
// game's uploader maintains via Firestore increment fieldTransforms.
// Mean profile dim = profileSum[dim] / profileSamples.
export const DEMO_GLOBAL = {
  totalFights: 12847,
  bossWins: 7999,
  fighters: 1283,
  profileSamples: 12847,
  profileSum: {
    aggression: 7837,
    dodgeTendency: 6167,
    blockTendency: 5010,
    openerAggression: 7066,
    pressureResponse: 6038,
    kitingScore: 5396,
    comboCompletionRate: 6552,
    positionalVariance: 6295,
  },
};
