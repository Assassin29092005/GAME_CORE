# NEXTSTEP.md — Path to Ship (rewritten 2026-07-05, post ship-path wave; updated 2026-07-09)

> **State (2026-07-09):** ALL code components built. Remaining work is (a) training data
> (kiter/counter/chaotic overnight runs) and (b) human-only clicks (Part 0). M0–M4 done
> (map at its AAA pass: terrain v2, 24.5k ground cover, clouds/grade, floor ring +
> mountain backdrop; minions golem-bodied; feel layer + audio placeholders live).
> **M5 LIVE end-to-end**: real brains in-engine (turtle 110k = default, rusher 41k banked,
> kiter staged pending re-train), settings-driven archetype bank with measured centroids +
> mean-centered cosine, and the shipped-path memory lifecycle (GameFeelSubsystem
> load/record/save) that makes profile-matched selection actually run outside training.
> **M6 game-side code done** (login/telemetry/taunts/community difficulty — needs your
> Firebase keys). **M7 pages built** (taunts + World; needs deploy). **M8 cook smoke PASS.**
>
> **BossArena SHOWCASE (2026-07-09):** non-destructive minimalist + RL-visibility HUD
> landed (`Tools/apply_showcase_bossarena.py` + `bEnableRLShowcase` flag + 4 Slate panels:
> brain badge, action-mask row, 8-dim player-profile radar, taunt fade). Toggleable via
> Project Settings or `arena.Showcase 1/0`. Original arena look preserved when off.
> See `Docs/BOSSARENA_SHOWCASE.md`.
>
> **Overworld Tier 4 PAUSED (2026-07-09):** heightmap regenerated with real erosion +
> biome shaping + peak clustering (see memory `overworld-tier4-inflight.md`). Remaining
> Phase D dressing forks + encounter volume BP wiring + perf pass deferred until after
> release. Do NOT resume until M8 ships.
>
> Deep detail: [ROADMAP.md](ROADMAP.md) · [guide.md](guide.md) · [visuals.md](visuals.md) ·
> [Website/README.md](Website/README.md) (the Firestore schema contract) ·
> [Docs/BOSSARENA_SHOWCASE.md](Docs/BOSSARENA_SHOWCASE.md).

---

## PART 0 — BLOCKED ON YOU (the autonomy ledger — nothing else can do these)

| # | Item | Where / how | ~Time |
|---|---|---|---|
| 1 | **Golem AnimBP graph** | `Content/Arena/Minions/ABP_StoneGolem` → AnimGraph: State Machine (Idle: ThirdPersonIdle ↔ Move: ThirdPersonWalk on speed>10, speed from TryGetPawnOwner→GetVelocity→Length in Event Graph) → **Slot 'DefaultSlot' → Output Pose** → Compile+Save. Until then golems T-pose. | 10 min |
| 2 | **Sword grips** | BP_Boss + BP_NeuralHero → `WeaponMesh` under Mesh → Details → Sockets → Parent Socket = `weapon_r` → rotate in viewport until it sits in the palm. **Also**: hero's WeaponMesh → Static Mesh must be `OneHandSword_Mesh` (RamsterZ), not the red `SM_Sword`. | 5 min |
| 3 | **Ash motes system** | Content/Arena/FX → right-click → FX → Niagara System → *from selected emitter* → pick `NE_AshMotes_Emitter` → name **exactly** `NS_AshMotes` → Save → then `py "D:/GAME_CORE 5.8/Tools/ambient_particles.py"` (it tiles 6 ash volumes automatically). Snow: flip `DO_SNOWFALL=True` in that script and re-run. | 5 min |
| 4 | **Exposure re-meter** | Viewport → Show → Visualize → HDR (Eye Adaptation) → note settled EV100 in-arena → `ARENA_PostProcess` → Exposure Min/Max = that ±0.5. (Atmosphere changed twice since your last tune; the sky reads dark until this.) | 3 min |
| 5 | **Firebase go-live** | console.firebase.google.com → Add project → Authentication → Email/Password ON → Firestore create (production). Then paste **Web API Key + Project ID** into: `Config/DefaultGame.ini` under `[/Script/GAME_CORE.FirebaseAuthSubsystem]` (keys `WebApiKey=`, `ProjectId=`) **and** the web config object into `Website/src/firebase.js`. Deploy: `cd Website && npm run build && firebase deploy` (first time: `npm i -g firebase-tools; firebase login; firebase init hosting`, public dir `dist`, SPA yes). Push `Website/firestore.rules` via `firebase deploy --only firestore:rules`. | 30 min |
| 6 | **PIE verification session** | Checklist in Part 2 — the human eye pass nothing headless can replace. | 20 min |
| 7 | **BossArena showcase apply + screenshot** | Editor Cmd `py "D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py"` (defaults SHOWCASE_MODE=on). Then Project Settings → Game → Game Feel → Enable RL Showcase = on (or PIE + `arena.Showcase 1`). PIE, verify 4 panels + minimalist arena. Screenshot for paper Fig 1 / promo header. Revert: `py import os; os.environ['SHOWCASE_MODE']='off'; exec(open(r'D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py').read())`. See `Docs/BOSSARENA_SHOWCASE.md`. | 10 min |
| 8 | *(release day)* itch.io upload + link in `Website/src/pages/Download.jsx` | ROADMAP M8 | 20 min |

## PART 1 — TONIGHT, EVERY NIGHT: training (everything downstream waits on this)

```powershell
cd "D:\GAME_CORE 5.8"
powershell -ExecutionPolicy Bypass -File Tools\run_training.ps1 -Persona rusher -MapName BossArena
```
- Editor **closed** first. The harness now passes `-rlbridge` (NNE stands down) and
  `-NoTelemetry` (bot rounds never pollute community stats).
- Verify ~10 min in: `Saved/Logs/GAME_CORE.log` shows `RLBridge: Client connection
  established` + sustained combat; TensorBoard (`cd Python; .\venv\Scripts\activate;
  tensorboard --logdir tb_logs`) shows curves + the mask-restriction-rate scalar.
- Rotate personas nightly — remaining: `kiter` (re-run; the 6k-step attempt evals
  dodge-only), `counter`, `chaotic`. Done: `rusher` 41k (banked), `turtle` 110k (default
  brain). After ≥2 nights:
  `python train_world_model.py train`, `python train_transfer.py train_base`,
  `python train_maml.py meta_train` (no UE needed).
- Pipeline self-check anytime: `cd Python; .\venv\Scripts\python.exe smoke_test.py` (~3 s).

## PART 2 — PIE VERIFICATION CHECKLIST (do once after Part 0 items 1–4)

- [ ] Attacks/blocks/parry visible + audible (whoosh on swings, thud/bell on block/parry)
- [ ] Slash trails follow both blades; boss telegraphs red (heavy) / yellow (light)
- [ ] Golems: walk, chase, **swing visibly, die properly** (needs Part 0 #1)
- [ ] Walk pad 1 (17000,-4000) — collision probe says solid; confirm on foot
- [ ] `stat unit` during a fight: GPU ≤ ~14 ms. If over, dial in order: grass cull
      distances (ARENA_AAA_GC_* → HISM component), cloud View Sample Count Scale,
      grain/fringe off. Optional Nanite pass: flip `DO_NANITE=True` in
      `Tools/dress_arena.py`, re-run headlessly.
- [ ] `combat.DebugHUD 1` — buffer/cancel/commitment lines sane in a real exchange
- [ ] `arena.Showcase 1` — RL panels appear (brain badge top-left, mask row top-right,
      profile radar bottom-left, taunt fade center-right); combat behavior unchanged.
      `arena.Showcase 0` cleanly reverts.
- [ ] `WBP_HealthBars` — long-standing runtime warning spam when boss actor is None. Add
      `IsValid(BossActor)` guard around `GetPercent_0`'s read, return 0.0 on false. Editor
      Blueprint fix only, 3 minutes.

## PART 3 — PROMOTE THE FIRST REAL BRAIN (after 1+ overnight runs)

> **2026-07-05 21:45 (loop iter 1): rusher PROMOTED** — `boss_rusher.onnx` exported from
> tonight's 41k-step run, imported as `NNM_BossRusher`, wired as the default model, and
> verified in-world: `NNEBossPolicy: ready — model 'NNM_BossRusher' at 15 Hz`. Remaining
> personas follow this same flow (import script now takes NNE_ONNX_SRC/NNE_ASSET_NAME env).
> **02:05 (iter 3): turtle 110k promoted AND made the DEFAULT brain** — eval_archetypes.py
> (new, runnable anytime) scored turtle 40-0 vs the scripted duel (balanced 22/50/28
> attack/block/retreat kit); rusher (41k) is a dodge-only evasion specialist (needs more
> steps).
> **2026-07-06 (archetype-bank batch): DONE + built green + adversarially reviewed.**
> Settings-driven bank (`+NNEArchetypeBank` ini rows) compiled in; review fixes applied:
> mean-centered cosine (0.5-neutral centering — raw cosine saturated on all-positive
> profiles), duplicate-persona row guard, centroids filtered to bank-backed personas.
> **MAJOR review catch:** the bank was dead code in shipped play — nothing ever called
> `LoadMemory`/`RecordEncounterEnd` outside the Python bridge, so TotalEncounters was
> always 0 and the cosine match never ran. Fixed: `GameFeelSubsystem` now owns the memory
> lifecycle (LoadMemory with Firebase-UID-else-guest BEFORE NNE injection; RecordEncounterEnd
> + SaveMemory on round end, debounced; skipped under -rlbridge/live client). Centroids
> re-measured from replays (`Python/measure_centroids.py`, new) and pasted into the ini.
> `boss.NNESelfTest` pre-world fallback now reads GameFeelSettings.NNEBossModelData (old
> TODO cleared). **NNM_BossKiter imported but STAGED (ini row commented out):** the 6k-step
> kiter checkpoint evals dodge-only (94% dodge, 0W/0L/40D) — below turtle's promotion bar.
> NEXT TRAINING GAP: full overnight kiter run, re-eval, re-measure (4 eps is noise), then
> uncomment the row.

The per-persona promotion flow (current, post-archetype-bank — Claude does 1–4 headlessly):
1. Export: `cd Python` → `venv\Scripts\python.exe export_onnx.py --model
   checkpoints/<best>.zip --out ..\SourceArt\Models\boss_<persona>.onnx` (verifies
   torch/SB3 agreement itself).
2. **Eval gate** (the turtle-set bar): `venv\Scripts\python.exe eval_archetypes.py` —
   promote only on a competent, non-degenerate kit (wins + mixed action distribution;
   dodge-only = more training, see kiter). Losers stay staged like kiter.
3. Import: set `NNE_ONNX_SRC` + `NNE_ASSET_NAME=NNM_Boss<Persona>` env vars → headless
   `UnrealEditor-Cmd ... -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/import_onnx_model.py"`.
4. Wire: `venv\Scripts\python.exe measure_centroids.py` → paste the persona's
   `+NNEArchetypeBank=(...)` row into `Config/DefaultGame.ini` (measured centroid, never
   hand-authored). Only touch `NNEBossModelData=` if the new brain should REPLACE turtle
   as the profile-less default. (The bank is ini-driven now — no BP_Boss component wiring.)
5. Verify: `-game` launch WITHOUT Python → `boss.NNESelfTest` PASS + the
   `NNEBossPolicy: ready — model ... [archetype: ...]` log line → fight it.

## PART 4 — REMAINING DEV WORK (Claude-drivable, ask or /loop it)

**Priority order (2026-07-09 — all code is in; this is finishing work):**

1. **Training data — the one thing that gates real archetype variety.** Overnight runs
   for `kiter` (re-run: the 6k attempt evals dodge-only), `counter`, `chaotic`. Each
   promotes per Part 3 flow (export → eval gate → import → `+NNEArchetypeBank` row →
   `boss.NNESelfTest`). Rotate nightly via `Tools/run_training.ps1`.
2. **M2 locomotion** (guide.md Phase 2): motion-matching spike (Game Animation Sample —
   the one Fab pack still not added) or blendspace Option B. The last big feel gap.
3. **Tuning loops** (guide.md Phase 8): one variable → two fights → keep/revert.
   Everything lives in Project Settings → Game → Game Feel + the data assets.
4. **M8 packaging**: Project Settings → Packaging → Shipping; maps list (BossArena +
   future menu); Platforms → Windows → Package. Test on a UE-less machine per ROADMAP M8.
   **Cook smoke PASSED (2026-07-06):** headless `BuildCookRun -cook` — 3872/3872 packages,
   zero errors, BUILD SUCCESSFUL (~7 min; UE 5.8 cooks into the Zen store, so Saved/Cooked
   staying near-empty is normal — don't chase that). Still to verify at real packaging:
   NNM_* assets present in the staged pak (the DirectoriesToAlwaysCook insurance), maps
   list, Shipping config.
5. **Paper figure work (unblocked by BossArena showcase)** — capture Fig 1 (RL brain
   panels over minimalist arena), Fig 2 (four persona brains on the same fight snapshot),
   Fig 3 (player-profile radar evolution across a fight). Screenshot flow lives in
   `Docs/BOSSARENA_SHOWCASE.md`.
6. Upgrades queued behind taste: better whoosh/grunt audio (Sonniss/Freesound), grass MIC
   tints (grass/fern param names failed — stock green for now), MetaHuman skins (post-M2).

**Deferred (do NOT resume until release):**
- Overworld Tier 4 — heightmap regenerated 2026-07-09 but Phase D dressing + encounter
  wiring is ~3 weeks. Ships-first-then-open-world discipline.

## PART 5 — THE /loop PROMPT (autonomous completion)

Run `/loop` with the prompt below (no interval = self-paced). It works this file's ledger.

```
Ship GAME_CORE (D:\GAME_CORE 5.8) to ROADMAP.md M8 done-criteria, one verified step per
iteration. Each iteration: (1) ORIENT — read NEXTSTEP.md (Part 0 ledger + Part 4),
ROADMAP.md statuses, git log --oneline -5, git status; pick the single highest-leverage
UNBLOCKED task (broken things > training-data pipeline > checkpoint promotion (Part 3) >
M8 packaging readiness > M2 locomotion/audio polish > tuning/perf). (2) HARD RULES —
never two UE processes: if UnrealEditor.exe or UnrealEditor-Cmd.exe is running, do only
non-UE work (python/web/docs/review) this iteration; all editor automation headless via
UnrealEditor-Cmd -ExecutePythonScript (NEVER -run=pythonscript; NEVER in-editor py — it
crashes this machine); C++ = full Build.bat per CLAUDE.md with editor closed, treat
EDITOR_OPEN as skip-and-requeue; python only via Python\venv, validate with smoke_test.py;
Website changes must keep npm run build green; obey every CLAUDE.md gotcha (montage
mutation, struct-array write-backs silently fail, force-save + mtime-verify, override_
siblings, faction rules). (3) TRAINING — when no UE process is running and
Python/checkpoints lacks a fresh checkpoint for some persona (rusher, turtle, kiter,
counter, chaotic), launch Tools/run_training.ps1 -Persona <next> -MapName BossArena as a
background task and do non-UE work while it trains; verify health at ~10 min
(tb_logs growing, GAME_CORE.log sustained combat) and kill+diagnose if crash-looping;
when a persona has a good checkpoint, promote it per NEXTSTEP Part 3 (export -> headless
import -> ArchetypeBank/ini wiring -> boss.NNESelfTest PASS). (4) NEVER — fabricate
Firebase keys or secrets, drive launcher/store/browser UIs, delete user content, push to
remotes, package with Shipping signing, or attempt Part 0 human-only items: instead
append precise instructions to NEXTSTEP.md Part 0 and move on. (5) VERIFY+COMMIT — every
change proven by its harness (Build.bat green / script PASS summary + on-disk mtime /
smoke_test green / npm build green / boss.NNESelfTest), then one thematic commit ending
with Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>; update NEXTSTEP.md ledger +
ROADMAP.md status in the same iteration. (6) IDLE/STOP — if everything actionable is
blocked on Part 0, update the ledger and idle on long wake-ups until the repo changes;
declare done only when ROADMAP M8's checklist passes end-to-end.
```

## Appendix — commands
```powershell
# Build C++ (editor CLOSED)
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" GAME_COREEditor Win64 Development -Project="D:\GAME_CORE 5.8\GAME_CORE.uproject" -WaitMutex
# Overnight training
powershell -ExecutionPolicy Bypass -File Tools\run_training.ps1 -Persona rusher -MapName BossArena
# RL smoke (no UE)          # Headless editor script (the ONLY sanctioned way)
cd Python; .\venv\Scripts\python.exe smoke_test.py
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" "D:\GAME_CORE 5.8\GAME_CORE.uproject" -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/<script>.py" -unattended -nosplash -stdout
```

## Appendix — traps (all earned the hard way)
- Reflected C++ (UPROPERTY/UFUNCTION) → Build.bat, editor closed. Never Live Coding.
- In-editor `py` crashes this machine (python311 AV) — headless `-ExecutePythonScript`
  only; exit code 3 after a PASS summary = cosmetic teardown crash, saves are on disk.
- Editor-python saves silently no-op unless forced (`only_if_is_dirty=False` + mtime check).
- Struct-array write-backs from python fail silently; instanced-UObject edits stick.
- Montages are mutated at play — never share one asset across two characters.
- Combat montage slots: `Attack` / `Block` / `DefaultSlot` — a montage on a slot with no
  graph node plays invisibly (notifies fire, no pose). The sandbox ABP has all three now.
- Empty TensorBoard = crash-looping trainer → `Saved/Logs/GAME_CORE.log` (UTC).
- Fab packs are gitignored vendored content — fresh clones re-add them from the library.
