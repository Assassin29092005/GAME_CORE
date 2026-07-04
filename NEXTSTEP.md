# NEXTSTEP.md — Your Complete Path From Right Now → Shipped Game + Live Website

> **State check (2026-07-04):** everything below the line "YOUR PART STARTS HERE" was built
> and verified by automation this session. **You have not run anything yet.** This file is
> your ordered to-do list from the very first editor launch to the website serving your
> game's .exe with per-player boss intelligence. Work top to bottom; every step says exactly
> where to click. Deeper detail always lives in: [guide.md](guide.md) (feel),
> [visuals.md](visuals.md) (graphics), [ROADMAP.md](ROADMAP.md) (milestones),
> [Website/README.md](Website/README.md) (site + Firestore schema).

**Already done for you (don't redo):** BossArena map (arena + patrol zone + lighting +
blocking + NavMesh volume), minion AI (C++ + auto-created BP_Minion + spawners wired),
GoW feel layer (camera, boss HP bar, red/yellow telegraphs, buffering, cancel windows,
i-frames, parry, boss execution layer, fallback brain), montage notify windows placed,
renderer/scalability/60fps configs, MaskablePPO RL upgrade + mock-UE smoke harness,
`GameDefaultMap`/`EditorStartupMap` → BossArena, repo cleanup. All compiled and reviewed.

---

## PART 1 — TODAY: First launch + 15-minute verification

1. **Close Blender if open** (RAM rule: only two of Blender / UE / training at once).
2. **Launch the editor:** Epic Games Launcher → Unreal Engine tab → Library → 5.8 →
   Launch → select `GAME_CORE` (or double-click `GAME_CORE.uproject` in `D:\GAME_CORE 5.8`).
3. **Wait out the shader recompile.** Bottom-right corner shows a toast "Compiling Shaders
   (N remaining)" — renderer settings changed, so this first launch recompiles a lot
   (10–30 min). Do NOT judge performance until it hits zero.
4. The editor opens **BossArena** automatically (startup map is set). If not: Content
   Drawer (bottom-left button, or Ctrl+Space) → Content/Maps → double-click **BossArena**.
5. **PIE smoke test:** click the green **▶ Play** button in the top toolbar (or Alt+P).
   Verify each — every ✅ was machine-verified, this is the human pass:
   - [ ] Camera sits tighter over the shoulder (GoW framing), lags smoothly when you run.
   - [ ] **Boss HP bar top-center** with a gold poise bar under it.
   - [ ] Fight the boss (no Python needed — the **fallback brain** drives it): it approaches,
     commits to attacks, telegraphs, recovers. On its attack wind-ups you see the
     **red flash** (unblockable heavy — dodge/parry) or **yellow tick** (normal swing).
   - [ ] Blocked light hits chip; heavy breaks your block (red ones).
   - [ ] **Parry:** tap block within 0.15 s of an incoming hit → boss staggers hard.
   - [ ] Dodge through an attack — i-frames (10–60 % of the roll).
   - [ ] Walk out the arena's canyon (+X direction) → patrol zone → **golem-less minions**
     (UEFN mannequin placeholders) patrol the three pads, aggro, chase, attack.
   - [ ] Type <code>`</code> (backtick) → `combat.DebugHUD 1` → watch boss commitment /
     buffer / cancel-window lines live. `combat.DebugHUD 0` to hide.
   - [ ] `stat unit` in console: GPU and Game under ~14 ms during a fight.
6. **If the minion T-poses or doesn't swing:** open Content/Arena/Minions/BP_Minion →
   check Mesh + Anim Class on the Mesh component, and CombatComponent → Neutral Combo
   Config = `DA_MinionCombo`, Death Montage = `AM_Minion_Death`. (These were set by
   script and asserted, but this is the one thing headless verification can't fully prove.)
7. **Tune exposure once** (visuals.md lighting step 5): viewport **Show → Visualize →
   HDR (Eye Adaptation)** → note the settled EV100 in the arena → select
   `ARENA_PostProcess` in the Outliner → Details → Exposure → set Min/Max EV100 to that
   value ±0.5. (Script default 0.75–1.25.)

## PART 2 — TONIGHT: Start training the boss (M1 overnight loop)

The boss you fought used the scripted fallback. The *real* boss learns overnight:

1. **Pre-warm shaders once** (avoids the empty-TensorBoard trap): close the editor, then
   in PowerShell:
   ```powershell
   & "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" "D:\GAME_CORE 5.8\GAME_CORE.uproject" -game -windowed -ResX=1280 -ResY=720
   ```
   Let it load into the arena, wait ~2 min until smooth, close it.
2. **Launch the overnight run** (PowerShell, from `D:\GAME_CORE 5.8`):
   ```powershell
   powershell -File Tools\run_training.ps1 -Persona rusher -MapName BossArena
   ```
   This starts UE standalone with the `rusher` sparring bot + `train.py --player-id rusher`,
   auto-restarting on crashes. Replays land in `Python/replays/rusher/`.
3. **Verify it's actually learning (10 min in):**
   - `Saved/Logs/GAME_CORE.log` (timestamps are UTC) shows
     `RLBridge: Client connection established` and sustained combat — NOT reconnects
     every ~10 s.
   - New PowerShell window: `cd "D:\GAME_CORE 5.8\Python"; .\venv\Scripts\activate;`
     `tensorboard --logdir tb_logs` → open http://localhost:6006 → after ~3 min the newest
     `PPO_*`/`MaskablePPO_*` run shows reward curves (files > 88 bytes = alive).
   - Look for the **mask-restriction-rate** scalar — proof the boss is training with
     legal-action masking (the new upgrade).
4. **Rotate personas across nights:** `turtle`, `kiter`, `counter`, `chaotic` — one per
   night. Multi-persona data is what makes MAML meta-training possible.
5. **Offline trainers** (any time, no UE needed, after 2+ nights of replays):
   ```powershell
   cd "D:\GAME_CORE 5.8\Python"; .\venv\Scripts\activate
   python train_world_model.py train
   python train_transfer.py train_base
   python train_maml.py meta_train
   ```
6. **RL stack self-check without UE (any time):** `python smoke_test.py` from `Python/`
   — spins the mock UE server and validates the whole training loop in ~3 min.

## PART 3 — THIS WEEK: Fab marketplace downloads + integration

Open Epic Games Launcher → **Fab** tab (left sidebar) → **My Library**. For each item:
click the item card → **Add to Project** button → pick `GAME_CORE` in the project list →
confirm engine version. **If 5.8 is blocked** (older packs): click **Show all projects**
checkbox in that dialog if present; otherwise add to any allowed dummy project, then in
that project's Content Browser right-click the folder → Asset Actions → **Migrate** →
target `D:\GAME_CORE 5.8\Content`.

### Priority order (all in your library already)

| # | Pack | Use | After adding |
|---|---|---|---|
| 1 | **Stone Golem** (buxoided) | THE boss minion | Part 3.1 below |
| 2 | **Paragon: Agora & Monolith** (Epic) | Arena/zone dressing — theme-perfect stone ruins | Part 3.2 |
| 3 | **Fighter Animation Pack** (9CG) | New combo chains | Part 3.3 |
| 4 | **RamsterZ Free Anims Vol 1** | Reaction/idle variety | Part 3.3 |
| 5 | **Free Animations Pack** (SoerGame) | More combat anims | Part 3.3 |
| 6 | **Elemental Slash Trail** (SoftTofuVFX) | Weapon trails | Part 3.4 |
| 7 | **Thornblade Sword** (DZTFIX) | Boss weapon | Part 3.4 |
| 8 | **Weapons FREE** (ithappy) | Hero weapon options | Part 3.4 |
| 9 | **Medieval Modular Wall Pack** (Vampawn) | Patrol-zone ruins | Part 3.2 |
| 10 | **Medieval Castle** (Dexsoft) | Zone landmark structures | Part 3.2 |
| 11 | **Forest of Spikes** (Dave Berg) | Menace accents near arena gate | Part 3.2 |
| 12 | **Game Animation Sample** (Epic, several GB) | 500+ locomotion anims for guide.md Phase 2 | defer until Part 5 |

**Skip on this laptop** (Epic's own specs need 32 GB RAM / 8+ GB VRAM): City Sample + its
Crowds/Buildings, MetaHuman Crowd Sample, Electric Dreams, Virtual Studio, Soul: City.
**Skip for style** (breaks the desaturated stylized-realistic bar): FANTASTIC Dungeon Pack,
Stylized Lake Village, Platformer 8 Underworld, Stylized Log Cabin, sci-fi city kits.

**Free audio (browser downloads, for Part 5 audio pass):**
- Sonniss GDC Game Audio bundles — https://sonniss.com/gameaudiogdc (free, huge)
- Freesound — https://freesound.org (filter License = CC0; search "sword whoosh",
  "body impact", "metal parry")
- Kenney audio — https://kenney.nl/assets?q=audio (CC0)

### 3.1 Stone Golem → real minion (15 min)
1. Content Browser → the golem pack folder → find its Skeletal Mesh + AnimBP (or its
   anim sequences).
2. Open `Content/Arena/Minions/BP_Minion` → select **Mesh (CharacterMesh0)** component →
   Details → Skeletal Mesh Asset = golem mesh; Anim Class = the golem's AnimBP if it ships
   one (else leave mannequin anims and retarget later).
3. Golem attack animation → right-click → Create → **AnimMontage**. Open it → Notifies
   track (bottom) → right-click → Add Notify State → **ANS Deal Damage** → drag the bar
   over the swing's contact frames.
4. Open `DA_MinionCombo` → ComboChain[0] → Montage = your new golem attack montage.
   (Montage-mutation rule: this montage must be used by minions ONLY.)
5. Same for a golem death animation → montage → BP_Minion CombatComponent → DeathMontage.
6. PIE → walk to a pad → fight a golem.

### 3.2 Dress the map (any evening, iterative)
- Drag Paragon/Medieval meshes from Content Browser into the viewport. Snap: End key drops
  the selected actor to the ground. Duplicate: Alt+drag a gizmo axis.
- Keep the **fight floor (inner 36 m) clean** — dressing goes on the rim, pads, and canyon.
- Cap imported textures: right-click pack's Textures folder → select all → right-click →
  Asset Actions → Bulk Edit via Property Matrix → Compression → Maximum Texture Size = 2048.
- Per visuals.md: tint albedos toward stone-grey/cold-brown in material instances; one
  landmark silhouette per zone; grayscale-screenshot readability check at the end.

### 3.3 Animation packs → the mannequin (30 min once, then per-pack minutes)
1. Add pack (table above). Its anims are on the UE4/UE5 Mannequin skeleton.
2. Create the retargeter once: Content Browser → right-click → Animation → Retargeting →
   **IK Retargeter** → Source = the pack's skeleton, Target = `SK_UEFN_Mannequin`'s
   skeleton (5.8 auto-generates both IK Rigs; open the retargeter and eyeball the preview).
3. Edit `Tools/batch_retarget_anims.py` constants block (top of file): SOURCE_FOLDER =
   the pack's anim folder, TARGET_FOLDER = `/Game/Retargeted_Animations/<PackName>`,
   RETARGETER_ASSET = your retargeter's path, PREFIX as you like.
4. Editor → Output Log → **Cmd** console: `py "D:\GAME_CORE 5.8\Tools\batch_retarget_anims.py"`.
5. New attacks → montages (Ctrl+D duplicates per character!) → add `ANS_DealDamage` +
   `ANS_CancelWindow` windows → append entries to a `CombatAnimConfig` ComboChain →
   damage values via `Tools/set_combo_damage.py` conventions (10/15/20/25, Heavy finisher).

### 3.4 Weapons + trails (an hour)
1. Thornblade: open the boss mesh's Skeleton asset → Window → Socket Manager… actually
   simplest: BP_Boss → Mesh component → right-click `hand_r` bone in the Skeleton Tree →
   Add Socket → name `weapon_r` → drag the sword mesh onto BP_Boss as a Static Mesh
   component → Details → Parent Socket = `weapon_r`. Same pattern for hero + a Weapons
   FREE pick.
2. Slash trails: open each attack montage → Notifies track → right-click → Add Notify
   State → **Timed Niagara Effect** → System = the Elemental Slash Trail system → Socket =
   `weapon_r` → stretch the bar across the swing frames (≈ the ANS_DealDamage span).

## PART 4 — Tuning loops (ongoing, 20 min each)

Everything is live-tunable — **no rebuilds**:
- **Edit → Project Settings → Game → Game Feel** — camera (FOV 78 / arm 320 / lag),
  telegraph colors, boss-bar chip timing, toggles.
- BP Details panels — BossActionComponent (commitment/mask/fallback), CombatComponent
  (buffer/parry/warp), HitReactionComponent (stagger thresholds).
- The four `CombatAnimConfig` data assets — blend/rate/damage/hit-stop per attack.
Rules (guide.md Phase 8): one variable per loop → fight twice → keep/revert → note it.
Fresh playtester weekly; ask only "anything unfair?" and "anything unresponsive?".

## PART 5 — Finish M2: locomotion + audio

- **Locomotion (the big visible one):** guide.md Phase 2.1 — timebox a 1–2 day motion
  matching spike (Game Animation Sample from Part 3's table + PoseSearch, already enabled).
  If trajectory-vs-Mover fights you, take Option B (blendspace + start/stop/pivot anims)
  guilt-free. Every click is in guide.md Phase 2.
- **Audio (cheap 30% of feel):** guide.md 7.1 — whoosh notifies on swings, impact sounds
  in `HitFeedbackComponent` (ImpactSound property), parry *ting* (PlaySound2D), boss grunt
  at wind-up start (doubles as the off-screen warning). Placeholder sounds from Part 3's
  audio sources today beat perfect sounds next month.
- Optional: author real BT/Blackboard assets for minions (CLAUDE.md "NPC Minions" recipe)
  — until then the built-in fallback brain drives them identically.

## PART 6 — M5: The boss inside the shipped .exe (no Python on players' machines)

**How the shipped boss keeps learning (the design, so you know what you're building):**
1. **In-context adaptation (already trained-in):** the policy's observation includes your
   live 8-dim profile — a trained policy *changes its behavior as the profile changes*.
   That IS per-player adaptation, no gradients needed on the player's PC.
2. **Cross-session memory:** `PlayerMemoryComponent` persists the profile between sessions
   (with decay), so the boss starts fight #2 already knowing you.
3. **Archetype bank:** N ONNX checkpoints (one per persona) — at arena entry the game picks
   the closest archetype to your profile (cosine similarity over 8 dims). Feels like the
   boss "studied you".
4. **Community evolution (cloud, Part 7):** aggregate stats raise the global baseline.

Steps (3–5 days, ROADMAP M5 has the full spec):
1. After 3+ overnight runs: `python export_onnx.py --model checkpoints/<best>.zip` per
   persona → `boss_rusher.onnx`, etc. (script verifies torch/ONNX agreement).
2. Editor → Edit → Plugins → search **NNE** → enable **Neural Network Engine** + its
   ONNX runtime module → Restart Now (button in the toast).
3. Drag the .onnx files into Content — verify they import as NNE model assets in your 5.8.
4. `NNEBossPolicyComponent` (C++, new): mirrors `StateObservationComponent` normalization,
   CPU inference at ~15 Hz, applies the legal-action mask to the logits, argmax →
   `BossActionComponent::ExecuteAction`. The execution layer downstream is untouched.
   **Ask Claude to write this — one session including the archetype selector.**
5. `-rlbridge` launch flag keeps the TCP/Python path for dev forever.

## PART 7 — M6: Accounts, sync, taunts, and the evolving world

Follow ROADMAP M6 + Website/README.md ("Connect Firebase", Firestore schema). Additions
for your requirements:

1. **Firebase project:** https://console.firebase.google.com → Add project →
   `game-core-boss` → disable Analytics (simpler) → Create. Then: Build → Authentication →
   Get started → Sign-in method → **Email/Password → Enable → Save**. Build → Firestore
   Database → Create database → production mode → nearest region.
2. **In-game login:** UE-side REST auth (no plugin): POST to
   `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<WebAPIKey>`
   (key from Project settings ⚙ → General → Web API Key). Store idToken/refreshToken/UID
   under `Saved/`. Guest path skips login (local-only). UMG login screen before level load.
3. **Telemetry upload (local-first):** every round-end writes one JSON to
   `Saved/Telemetry/pending/` matching the Website/README.md Firestore schema EXACTLY;
   an uploader flushes when online. **Include in the payload:** the 8-dim profile, emotion
   timeline, fight outcome, AND `BossExplainabilityComponent`'s taunt/explanation strings —
   that's what the website shows as "what the boss learned about you."
4. **Community evolution (your "players are evolving" feature) — the spec:**
   - New Firestore doc `meta/global`: running aggregates — mean profile dims, global
     boss win-rate, total fights. Updated by a tiny Cloud Function trigger on each fight
     doc write (or client-side transaction increment to stay on the free tier).
   - At login the game GETs `meta/global` → maps global player skill (e.g., mean
     dodge-tendency + combo-completion) → a **difficulty scalar**: seeds the boss's
     starting archetype prior and the constrained-learning win-rate cap. New players face
     a boss whose *baseline* was raised by every player before them.
   - Website "World" page: a chart of the global aggregates over time — "the community is
     evolving, and so is the boss."
5. Consent line on signup ("style data syncs to power your dossier"). Done-when: play 3
   rounds offline → go online → your dossier fills itself.

## PART 8 — M7: Website live (1–2 days, mostly done)

1. `cd Website && npm install && npm run dev` → http://localhost:5173 → demo mode works
   today (no Firebase needed) — click through Dossier/Timeline/Fight log.
2. Firebase console → Project settings ⚙ → General → Your apps → **</>** (Web) → register
   → copy the `firebaseConfig` object → paste into `Website/src/firebase.js`.
3. `npm install -g firebase-tools; firebase login; firebase init hosting` (public dir:
   `dist`, SPA: yes) → `npm run build && firebase deploy` → your live URL.
4. Sign up on the live site → play synced rounds (Part 7) → dossier + taunts render.
5. Download page: after Part 9, paste the .exe link into `Website/src/pages/Download.jsx`
   → rebuild → redeploy.

## PART 9 — M8: Package the .exe and release

1. Editor → Edit → Project Settings → Project → Packaging: Build Configuration =
   **Shipping**; List of maps: login/menu map + BossArena (+ patrol/menu maps you add).
2. Verify NNE model assets are cooked (they're referenced by the boss BP → automatic).
3. Platforms dropdown (top toolbar) → Windows → **Package Project** → pick an output folder.
4. **Test on a machine/user without UE or Python:** first-run shader compile, guest path,
   offline boss fight, login + sync-after-offline, death/respawn ×10, 60 fps at High.
5. Zip → upload to itch.io (New project → Uploads) or GitHub Releases → link into
   `Download.jsx` (Part 8.5) → `npm run build && firebase deploy`.
6. Release checklist is in ROADMAP M8. Done-when: a stranger downloads, plays, and their
   dossier appears.

---

## Appendix A — command cheat sheet
```powershell
# Build C++ (editor CLOSED)
& "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" GAME_COREEditor Win64 Development -Project="D:\GAME_CORE 5.8\GAME_CORE.uproject" -WaitMutex
# Overnight training
powershell -File Tools\run_training.ps1 -Persona rusher -MapName BossArena
# RL smoke test (no UE needed)
cd Python; .\venv\Scripts\python.exe smoke_test.py
# Rebuild the whole level headlessly (re-runnable)
& "C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" "D:\GAME_CORE 5.8\GAME_CORE.uproject" -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/build_arena_level.py" -unattended -nosplash -stdout
```

## Appendix B — known traps (all hit once already so you don't have to)
- Reflected C++ changes (UPROPERTY/UFUNCTION) → full Build.bat with editor **closed**.
- Never share a montage asset between two characters (assets are mutated at play).
- Empty TensorBoard = crash-looping trainer → check `Saved/Logs/GAME_CORE.log` (UTC).
- `-run=pythonscript` commandlet crashes on level ops → always `-ExecutePythonScript`.
- Editor python "saves" can silently no-op → the tools now force-write and verify mtime.
- VS2026 solution build is broken on this machine → Build.bat only.
