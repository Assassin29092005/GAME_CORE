import {
  collection,
  doc,
  getDoc,
  getDocs,
  limit,
  orderBy,
  query,
} from "firebase/firestore";
import { db } from "./firebase.js";
import { DEMO_FIGHTS, DEMO_PROFILE } from "./demoData.js";

// ── Firestore schema (the contract the game writes — see Website/README.md) ──
// users/{uid}/profile/current   → { aggression, dodgeTendency, blockTendency,
//                                   openerAggression, pressureResponse, kitingScore,
//                                   comboCompletionRate, positionalVariance, updatedAt }
// users/{uid}/fights/{autoId}   → { startedAt, durationSeconds, outcome: "win"|"loss",
//                                   encounterType: "npc"|"boss", bossHpAtEnd, heroHpAtEnd,
//                                   emotion: { frustration, flow, boredom } }
// `outcome` is from the PLAYER's perspective ("win" = player won).

const toMillis = (v) => {
  if (v == null) return 0;
  if (typeof v === "number") return v;
  if (typeof v.toMillis === "function") return v.toMillis();
  return new Date(v).getTime() || 0;
};

export async function fetchProfile(uid, demo) {
  if (demo || !db) return DEMO_PROFILE;
  const snap = await getDoc(doc(db, "users", uid, "profile", "current"));
  return snap.exists() ? snap.data() : null;
}

export async function fetchFights(uid, demo) {
  if (demo || !db) return DEMO_FIGHTS;
  const q = query(
    collection(db, "users", uid, "fights"),
    orderBy("startedAt", "desc"),
    limit(60)
  );
  const snap = await getDocs(q);
  return snap.docs.map((d) => {
    const f = d.data();
    return {
      id: d.id,
      startedAt: toMillis(f.startedAt),
      durationSeconds: f.durationSeconds ?? 0,
      outcome: f.outcome === "win" ? "win" : "loss",
      encounterType: f.encounterType === "boss" ? "boss" : "npc",
      bossHpAtEnd: f.bossHpAtEnd ?? 0,
      heroHpAtEnd: f.heroHpAtEnd ?? 0,
      emotion: {
        frustration: f.emotion?.frustration ?? 0,
        flow: f.emotion?.flow ?? 0,
        boredom: f.emotion?.boredom ?? 0,
      },
    };
  });
}

export function computeStats(fights) {
  if (!fights.length) {
    return { total: 0, winRate: 0, avgDuration: 0, flowShare: 0 };
  }
  const wins = fights.filter((f) => f.outcome === "win").length;
  const avg =
    fights.reduce((s, f) => s + f.durationSeconds, 0) / fights.length;
  const flowDominant = fights.filter(
    (f) =>
      f.emotion.flow >= f.emotion.frustration &&
      f.emotion.flow >= f.emotion.boredom
  ).length;
  return {
    total: fights.length,
    winRate: Math.round((wins / fights.length) * 100),
    avgDuration: Math.round(avg),
    flowShare: Math.round((flowDominant / fights.length) * 100),
  };
}
