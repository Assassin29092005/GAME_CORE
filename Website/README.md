# GAME_CORE — Subject Dossier (player dashboard website)

The companion website for GAME_CORE: players log in and read **the boss's
intelligence file on them** — the 8-dim behavioral profile, emotion telemetry,
and full fight history the game recorded — plus the game download page.

Built with React + Vite + Firebase (Auth, Firestore, Hosting) + recharts.

## Run it right now (no Firebase needed)

```
cd "D:\GAME_CORE 5.8\Website"
npm install
npm run dev
```

Open the printed localhost URL → click **"View demo file"**. The whole
dashboard works immediately with sample data, so you can develop and restyle
before any backend exists. The yellow strip reminds you it's demo data.

## Connect Firebase (one-time, ~15 minutes)

1. Go to [console.firebase.google.com](https://console.firebase.google.com) →
   **Add project** (name it e.g. `game-core`). Disable Analytics — not needed.
2. **Build → Authentication → Get started → Sign-in method → Email/Password →
   Enable.**
3. **Build → Firestore Database → Create database → Start in production mode**
   (the rules file in this folder will govern access).
4. **Project settings (gear) → General → Your apps → Web (`</>`) → Register
   app.** Copy the `firebaseConfig` object it shows.
5. Paste those values into [src/firebase.js](src/firebase.js), replacing the
   `PASTE_…` placeholders. Demo mode turns itself off automatically; the login
   page now creates real accounts.
6. **Game side (same project):** paste the *Web API Key* and *project id* into
   `Config/DefaultGame.ini` under `[/Script/GAME_CORE.FirebaseAuthSubsystem]`
   (`WebApiKey=` / `ProjectId=`). While they're empty the game logs
   "Firebase not configured — guest mode only" and never uploads.

## Deploy (Firebase Hosting)

```
npm install -g firebase-tools
firebase login
cd "D:\GAME_CORE 5.8\Website"
firebase use --add        # pick the project you created
npm run build
firebase deploy           # deploys hosting (dist/) + firestore.rules
```

Your site is live at `https://<project-id>.web.app`.

## Firestore schema — the contract the game writes

This is the canonical schema. The UE-side uploader (ROADMAP.md milestone M6)
must write exactly these shapes; the dashboard reads them as-is. `{uid}` is the
Firebase Auth UID — it replaces the old local `player_id` everywhere.

```
users/{uid}/profile/current          ← one document, overwritten on update
{
  aggression:           0.0–1.0,     // FPlayerProfile.AggressionScore
  dodgeTendency:        0.0–1.0,     // .DodgeTendency
  blockTendency:        0.0–1.0,     // .BlockTendency
  openerAggression:     0.0–1.0,     // .OpenerAggression
  pressureResponse:     0.0–1.0,     // .PressureResponse
  kitingScore:          0.0–1.0,     // .KitingScore
  comboCompletionRate:  0.0–1.0,     // .ComboCompletionRate
  positionalVariance:   0.0–1.0,     // .PositionalVariance
  updatedAt:            timestamp
}

users/{uid}/fights/{autoId}          ← one document per completed round
{
  startedAt:        timestamp,
  durationSeconds:  number,
  outcome:          "win" | "loss",  // PLAYER's perspective
  encounterType:    "npc" | "boss",
  bossHpAtEnd:      number,
  heroHpAtEnd:      number,
  emotion: {
    frustration: 0–1, flow: 0–1, boredom: 0–1,
    dominant: "Neutral"|"Frustrated"|"Flow"|"Bored"  // OPTIONAL — the game
                                     // writes it; the dashboard may ignore it.
  },
  taunts:           string[]         // OPTIONAL — the lines the boss "spoke"
                                     // during the round (BossExplainability-
                                     // Component FBossInsight.TauntText).
                                     // Omit when empty; the dashboard
                                     // tolerates its absence.
}

meta/global                          ← ONE shared community document
{
  totalFights:      number,          // += 1 per completed round uploaded
  bossWins:         number,          // += 1 when outcome == "loss"
  fighters:         number,          // += 1 on a player's FIRST-ever upload
  profileSamples:   number,          // += 1 per profile snapshot folded in
  profileSum: {                      // += the player's CURRENT dim value
    aggression:           number,    //    (0–1) alongside each fight upload;
    dodgeTendency:        number,    //    community mean dim =
    blockTendency:        number,    //    profileSum[dim] / profileSamples
    openerAggression:     number,
    pressureResponse:     number,
    kitingScore:          number,
    comboCompletionRate:  number,
    positionalVariance:   number
  }
}
```

`meta/global` powers the **World** page (community evolution: headline stats,
community-mean profile overlay, boss difficulty indicator). There are **no
Cloud Functions** (free tier) — the game's uploader maintains it directly via
a Firestore REST `commit` with **`fieldTransforms` increments**, e.g.:

```
POST https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents:commit
{ "writes": [ { "transform": {
  "document": "projects/{pid}/databases/(default)/documents/meta/global",
  "fieldTransforms": [
    { "fieldPath": "totalFights",           "increment": { "integerValue": "1" } },
    { "fieldPath": "bossWins",              "increment": { "integerValue": "1" } },   // only on player loss
    { "fieldPath": "profileSamples",        "increment": { "integerValue": "1" } },
    { "fieldPath": "profileSum.aggression", "increment": { "doubleValue": 0.78 } }
    // … one increment per profile dim; add `fighters` += 1 on first upload only
  ] } } ] }
```

Never `set`/`update` absolute values on `meta/global` — the rules will reject
any write that shrinks a counter (see below), and increments are the only way
concurrent clients stay correct anyway.

Readers derive from `meta/global`:

- community mean profile dim = `profileSum[dim] / profileSamples`
- boss win rate = `bossWins / totalFights`
- **community difficulty scalar** =
  `clamp01((mean(dodgeTendency) + mean(comboCompletionRate)) / 2)` — 0.5 is a
  world of brand-new players; higher means the player base as a whole got
  better, and the boss baseline rises for everyone. The game computes this in
  `UCommunityDifficultySubsystem::GetGlobalDifficultyScalar()` at login; the
  World page should mirror the same formula so both sides show one number.

Game-side implementation (Source/GAME_CORE): `UTelemetryUploadSubsystem`
queues one plain-JSON file per round under `Saved/Telemetry/pending/` and
flushes every 30 s while signed in — `PATCH profile/current`, `POST fights`,
then the `:commit` above; the file is deleted only when all three succeed.
`fighters` is incremented once per uid via a local first-upload marker. If you
change any shape in this README, change that subsystem in the same commit —
this file is the contract both sides build against.

### Security rules ([firestore.rules](firestore.rules))

- `users/{uid}/**` — read/write only by that authenticated user. The game
  writes with the player's own ID token, so no server key ships in the game.
- `meta/global` — **readable by any signed-in user**; **deletes forbidden**;
  writes allowed only when
  1. the document has EXACTLY the schema keys above (`keys().hasOnly`),
  2. every counter/sum is a non-negative number, `bossWins <= totalFights`,
     and each `profileSum` dim `<= profileSamples` (dims are 0–1 per sample),
  3. **every field grows monotonically**: Firestore applies `fieldTransforms`
     *before* rules evaluate, so `request.resource.data` holds post-increment
     values — a decrement or reset fails
     `request.resource.data.x >= resource.data.x` and is rejected.
  A hostile client can at worst inflate the counters, never wipe or rewind
  the community record — the accepted trade-off for staying Cloud-Function-free.

## Where things live

| File | What it is |
|---|---|
| `src/firebase.js` | Config paste-point + demo-mode switch |
| `src/dataService.js` | All Firestore reads (and the demo fallback) |
| `src/demoData.js` | Sample data — also documents the expected shapes |
| `src/bossAssessment.js` | Profile dims metadata + the boss "voice" generator |
| `src/components/TauntPanel.jsx` | "What the boss says about you" (fight `taunts[]`) |
| `src/pages/World.jsx` | Community evolution page (reads `meta/global`) |
| `src/pages/Download.jsx` | Edit the `BUILD` object when you publish the .exe |
| `firestore.rules` | Per-user isolation + monotonic `meta/global` guard, deployed with `firebase deploy` |

## Notes

- The packaged game (.exe, multiple GB) should be hosted on **itch.io or
  GitHub Releases** — paste that link into `src/pages/Download.jsx`. Firebase's
  free Hosting/Storage tiers are too small for game builds.
- `npm run build` outputs to `dist/`, which `firebase.json` serves with SPA
  rewrites.
