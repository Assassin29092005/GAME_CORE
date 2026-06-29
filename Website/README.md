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
  emotion: { frustration: 0–1, flow: 0–1, boredom: 0–1 }
}
```

Security: [firestore.rules](firestore.rules) restricts each user to their own
`users/{uid}` subtree. The game writes with the player's own ID token, so no
server key ships in the game.

## Where things live

| File | What it is |
|---|---|
| `src/firebase.js` | Config paste-point + demo-mode switch |
| `src/dataService.js` | All Firestore reads (and the demo fallback) |
| `src/demoData.js` | Sample data — also documents the expected shapes |
| `src/bossAssessment.js` | Profile dims metadata + the boss "voice" generator |
| `src/pages/Download.jsx` | Edit the `BUILD` object when you publish the .exe |
| `firestore.rules` | Per-user data isolation, deployed with `firebase deploy` |

## Notes

- The packaged game (.exe, multiple GB) should be hosted on **itch.io or
  GitHub Releases** — paste that link into `src/pages/Download.jsx`. Firebase's
  free Hosting/Storage tiers are too small for game builds.
- `npm run build` outputs to `dist/`, which `firebase.json` serves with SPA
  rewrites.
