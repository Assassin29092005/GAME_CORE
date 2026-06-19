# GAME_CORE — Master Roadmap

The single ordered path from **today's state** to a **released game + live
player dashboard**. The other documents stay the source of detail — this file
is the spine that tells you which one to open, when, and what "done" means at
each step.

| Document | Owns |
|---|---|
| [guide.md](guide.md) | Gameplay feel — 9 phases, click-level steps |
| [visuals.md](visuals.md) | Rendering, lighting, art, Blender terrain — RTX 4050 budget |
| [Website/README.md](Website/README.md) | Dashboard site setup, Firebase, Firestore schema |
| this file | Order, dependencies, done-criteria, and everything not covered above |

**Where you are now (2026-06-11):** combat bugs under diagnosis (M0); guide.md /
visuals.md written but not started; shipping architecture decided (ONNX + NNE
runtime, Firebase backend, BT-NPC profiling flow, local-first sync).

**Already built for you (this session, all inert until used):**
- `Website/` — the full dashboard site (login, profile radar, emotion timeline,
  fight log, download page). **Builds clean; demo mode works today** —
  `cd Website && npm install && npm run dev`.
- `Tools/run_training.ps1` — unattended UE + trainer supervisor for overnight runs.
- `Python/export_onnx.py` — SB3 checkpoint → ONNX with agreement verification.

---

## The map

```
M0 Fix combat ──► M1 Training automation ──► M2 Gameplay feel (guide.md)
                        │                         │
                        │ (overnight runs         ├──► M3 NPC encounters
                        │  in background           │
                        │  from here on)           ├──► M4 Visuals & terrain (visuals.md)
                        ▼                          ▼
                  M5 ONNX boss in-engine ──► M6 Accounts & sync ──► M7 Website live
                                                                        │
                                                                        ▼
                                                                  M8 Package & release
```

M2/M3/M4 interleave freely — they're week-scale tracks you can alternate.
M5 needs trained checkpoints (M1's overnight runs produce them). M6 needs M5's
decision honored (no Python on player machines). M7 is nearly free (site is
built). M8 is last.

---

## M0 — Fix the combat bugs *(1–2 days · you're mid-way through)*

**Goal:** one press = one hit at the configured damage; one death = one death
animation; verified with Python attached.

1. **Death-twice — fix identified:** open `Knock_Down_Death_Seq_Montage` →
   Asset Details → **uncheck `Enable Auto Blend Out`** → save. (Found checked
   in your screenshot; the montage was blending out and the AnimGraph replayed
   the pose. `ResetForNewRound` already calls `StopAllMontages(0.2f)`, so
   respawn still recovers.)
2. **One-hit kill — run the discriminating log test:** PIE → Output Log →
   filter `ANS_DealDamage` → ONE attack press → match the pattern against the
   table in our chat (multiple `NotifyBegin` = duplicate damage windows on the
   montage *or its source sequence*; `GuardWasSet=0` + `Dmg=10.0` = owner
   lookup failing; wrong `Dmg=` = wrong config entry; clean log + death = a
   second damage path in a Blueprint). `Combo_01-1_Seq` was verified clean —
   audit whichever combo the `SelectCombo →` log line names.
3. Confirm BP_Boss CombatComponent `MaxHealth` is the value you intend
   (was 150 at one point, you said 100).
4. **Verify with Python:** editor + level open → `Python\venv\Scripts\python.exe Python\infer.py`
   → boss acts at ~15 Hz; trade hits both ways; kill Python mid-fight (boss
   should idle, not freeze).
5. While you're in there: strip the leftover `LogTemp` diagnostics
   (`ANS_DealDamage` NotifyBegin/End logs, the rotation tick log) once bugs are
   closed — they cost frame time (guide.md Phase 0.1 step 9).

**Done when:** 5 consecutive PIE rounds with correct damage math, single death
anims both sides, and a clean infer.py round-trip.

## M1 — Training automation *(2–4 days · unlocks everything)*

**Goal:** the boss trains overnight with nobody at the keyboard.

1. **`AutoHeroComponent`** (new C++, on BP_NeuralHero — additive, won't disturb
   M0 work):
   - Members: `bEnabled`, persona params — `Aggression` (0–1 attack eagerness),
     `DodgeReactChance`, `BlockChance`, `PreferredRange` (cm),
     `ComboCommitment`, `DecisionInterval` (~0.25 s).
   - Tick state machine (only when enabled): read boss distance +
     `BossActionComponent::IsPerformingAction()` on the boss; **drive the pawn
     exclusively through the existing public API** — `SetMovementInput()` for
     approach/strafe/retreat, `RequestAttack()` for combos (vary WASD input
     before attacking to exercise all four directional configs!), dodge/block
     once those exist (guide.md 1.3 / 3.5).
   - Enable via launch arg in `BeginPlay`:
     `FString P; if (FParse::Value(FCommandLine::Get(), TEXT("AutoHero="), P)) { LoadPersona(P); bEnabled = true; }`
   - 4–6 personas (rusher / turtle / kiter / parry-fisher / chaotic): a
     `TMap<FString, FAutoHeroPersona>` or per-persona config assets. **Each
     persona = a synthetic player_id** — this is what makes MAML meta-training
     possible at all (it needs multi-player data you can't generate alone).
2. **Run it:** `powershell -File Tools\run_training.ps1 -Persona rusher` (script
   exists; add `-MapName <YourArenaMap>`). Verify an hour's run produces
   checkpoints + TensorBoard curves, then go to sleep and let it work.
3. Rotate personas across nights; replays land in `replays/{persona}/` for the
   offline trainers (`train_world_model.py`, `train_transfer.py`, `train_maml.py`
   need no UE attached).

**Done when:** an 8-hour unattended run survives (auto-restarts count), and
TensorBoard shows learning curves you didn't babysit.

**Status (2026-06-12): code complete and compiled.** `AutoHeroComponent` (5 personas:
rusher / turtle / kiter / counter / chaotic; `-AutoHero=` launch arg; drives only the
public combat API), `train.py --player-id` override, `replay_recorder.py` (the replay
write path existed but was never called — now wired into train.py behind
`transfer.record_replays`, which is flipped on), and the harness passes the persona to
both UE and Python. Remaining: add the component to BP_NeuralHero (Add Component →
Auto Hero), PIE smoke test with bEnabled ticked, then the first overnight run.

**Update (2026-06-12, second pass):** bot movement fixed (Enhanced Input injection via
`MoveAction` — the hero's Mover input producer ignores `AddMovementInput`; ASSIGN IA_Move
on the AutoHero component). Hero **dodge** (directional, root-motion, `RequestDodge`) and
**block** (Start→Idle-hold→Hit→End montage chain, frontal damage reduction,
`SetBlocking`) added to CombatComponent — this pre-completes the playback halves of
guide.md 1.3 and 3.5 (i-frames, parry, and cancel windows still pending there). Bot evades
now use the real dodge. `Tools/set_combo_damage.py` (editor Python) sets the 10/15/25
Light/Heavy scheme across all CombatAnimConfig assets.

## M2 — Gameplay feel *(2–4 weeks, interleaved · guide.md is the manual)*

Work guide.md's **"Suggested order of attack"** table exactly as written:
frame rate/bridge audit → input buffering + dodge → **boss execution layer
(Phase 4 — the signature work)** → cancel windows/weight/i-frames → locomotion
→ camera → reactions/audio/UI → tuning loops. Each phase has click-level steps
and a "Feels right when" gate. Overnight training (M1) keeps improving the
policy in parallel the whole time. **Done when:** the 60-seconds-muted test at
the end of guide.md passes.

## M3 — NPC encounters *(≈1 week · can interleave with M2/M4)*

**Goal:** the shipped game's opening — fight Behavior-Tree patrols whose only
secret job is feeding the boss's dossier.

1. **NPC pawn:** duplicate BP_NeuralHero's rig (Mover pawn + mesh + AnimBP),
   give it `CombatComponent`, `HitReactionComponent`, `HitFeedbackComponent` —
   the components don't care who owns them. One `CombatAnimConfig` with a short
   chain is enough per NPC type.
2. **Brain:** standard UE AI — `AIController`, Blackboard (keys: TargetActor,
   Distance, IsStaggered), Behavior Tree (Selector: dead → nothing; staggered →
   wait; in range → attack task calling `RequestAttack()`; else → Move To). BT
   *tasks* reuse the same component API the AutoHero bot drives — M1's design
   work is this milestone's head start.
3. **Profiling for free:** `PlayerProfileComponent` lives on the *hero* and
   tracks incoming/outgoing combat events regardless of opponent — NPC fights
   populate the profile with zero extra wiring. Confirm `OnHitReactionTriggered`
   /`OnAttackLanded` flow as expected in an NPC fight.
4. **Boss handoff:** `PlayerMemoryComponent` (cross-encounter memory) carries
   the accumulated profile into the boss arena; the boss starts pre-adapted
   (archetype selection lands in M5).
5. Level flow: patrol zone(s) → arena gate. Greybox is fine until M4.

**Done when:** a new player fights 2–3 patrols, and the boss's first-fight
observation JSON already contains a non-default profile.

## M4 — Visuals & terrain *(1–2 weeks · visuals.md is the manual)*

Order inside visuals.md: renderer settings (15 minutes, do early) → **Blender
arena via Pipeline B** (sculpt → FBX → Nanite, the full click-level pipeline is
written) → five-actor lighting rig → set dressing/bounds/foliage → scalability
baked into config. **Done when:** the arena holds 60 fps in a real fight at the
budgets in the VRAM table, and the grayscale-screenshot readability test passes.

## M5 — Boss in-engine: ONNX + NNE *(3–5 days)*

**Goal:** the shipped game runs the boss with **no Python anywhere**.

1. Export: `python export_onnx.py --model checkpoints/<best>.zip` (script
   verifies torch/ONNX/SB3 agreement automatically).
2. UE: Edit → Plugins → enable **Neural Network Engine (NNE)** → restart →
   import the `.onnx` (verify the runtime/import flow in your 5.7 build —
   NNE's API surface moved between 5.x versions).
3. **`NNEBossPolicyComponent`** (new C++ on BP_Boss): loads the model asset,
   and on the same ~15 Hz cadence builds the observation **reusing
   `StateObservationComponent`'s exact normalization**, runs CPU inference,
   argmaxes 5 logits → `BossActionComponent::ExecuteAction(idx)`. The Phase 4
   execution layer (commitment/hysteresis/mask) sits downstream untouched.
4. **Source switch:** `-rlbridge` launch flag (dev: TCP/Python keeps working
   forever) vs default NNE path (shipping). Both feed `ExecuteAction` — the
   rest of the game can't tell the difference.
5. **Archetype bank:** export N per-persona/MAML checkpoints
   (`boss_rusher.onnx`, …); at arena entry pick the nearest archetype to the
   player's profile (cosine similarity over the 8 dims). The cloud fine-tune
   loop (per-player ONNX downloaded from Firebase Storage) is a stretch goal —
   wire the selection first, it's 90% of the felt effect.

**Done when:** a `-game` launch with no Python process gives a competent,
profile-respecting boss fight.

## M6 — Accounts & local-first sync *(≈1 week)*

**Goal:** login in-game, telemetry uploads, dashboard fills itself.

1. Firebase project: follow **Website/README.md** ("Connect Firebase") — same
   project serves game and site.
2. **UE auth via Firebase REST** (no plugin needed — you already ship Json/Http
   modules… add `HTTP` to `GAME_CORE.Build.cs`): POST to
   `identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<apiKey>`
   (and `:signUp`) → store `idToken` + `localId` (= the player's UID) +
   `refreshToken` in `Saved/`. Login UMG screen before the level loads; **guest
   path skips it** (local-only until they sign in later).
3. **Local-first queue:** every round-end writes one JSON file to
   `Saved/Telemetry/pending/` (schema = **Website/README.md → Firestore
   schema**, exactly). An uploader (game instance subsystem) flushes the folder
   via Firestore REST (`PATCH .../users/{uid}/profile/current`, `POST
   .../users/{uid}/fights`) with the idToken; failures just stay queued. UID
   replaces the local `player_id` in the replay/profile pipeline.
4. Consent line on the signup screen ("style data syncs to power your dossier").

**Done when:** play 3 rounds offline → go online → the website shows them.

## M7 — Website live *(1–2 days · mostly done)*

The site is built and verified. Remaining: paste Firebase config into
`Website/src/firebase.js` → `firebase deploy` (steps in Website/README.md) →
test signup/login → later, paste the build link into `src/pages/Download.jsx`.
**Done when:** your real fights from M6 render on the live URL.

## M8 — Package & release *(3–5 days)*

1. Project Settings → Packaging: Shipping config; List of maps (login/menu +
   patrol + arena); exclude editor content. `-rlbridge` stays dev-only;
   NNE model assets must be cooked (verify they're referenced, not loose files).
2. Package Windows → test the build **on a machine/user account without UE,
   Python, or your project** — first-run shader compile, login, guest path,
   offline boss fight all work.
3. Upload to itch.io (or GitHub Releases) → paste the link in
   `Website/src/pages/Download.jsx` → `npm run build && firebase deploy`.
4. Release checklist: fresh-machine clean run · offline run · sync-after-offline
   · death/respawn loop ×10 · 60 fps in arena at High scalability · dashboard
   shows a stranger's account correctly.

**Done when:** someone you've never coached downloads, plays, and their dossier
appears.

---

## Standing rules (from hard-won project experience)

- Reflected C++ changes (`UPROPERTY`/`UFUNCTION`) = **Build.bat with the editor
  closed**, never Live Coding (CLAUDE.md build caveats). Batch them per milestone.
- One variable per tuning loop; the Output Log diagnostic patterns from M0 are
  reusable forever.
- Anything that costs frame time gets measured in a real fight (`stat unit`)
  before and after — guide.md Phase 0 is permanent law.
- End of each session: update the relevant milestone here (check off, adjust
  estimates) so the next session starts oriented.
