# Overworld Playtest Checklist — Tier 4 Phase G

This is the human-in-the-loop verification the Tier 4 overworld feature needs
before it can be considered ready to cook (Phase H). It runs entirely in the
editor / packaged build; nothing scriptable substitutes for eyes on the screen.

Do it once end-to-end after Phases A–F have all landed and compiled.

---

## G0 — Preconditions (5 min)

- [ ] Repo on branch `feat/overworld` with commits through Phase F committed.
- [ ] Editor closed. `Build.bat GAME_COREEditor Win64 Development -Project=...`
      completes clean (per CLAUDE.md 'Build & Run' — VS solution build is
      known-broken on this machine).
- [ ] Open editor with the project. Landscape imported into
      `/Game/Maps/Overworld` (Phase A2 manual click sequence completed).
- [ ] `Tools/build_overworld_biomes.py` has been run at least once and
      you can see the 5 REGION_ actor label prefixes in the outliner.
- [ ] World Partition is enabled on `/Game/Maps/Overworld`
      (World Settings → World Partition → Runtime Grid = 'MainGrid').

---

## G1 — Perf snapshot per biome (30 min)

Target on the dev machine (RTX 4050 6 GB, 1080p Medium settings):
| Metric        | Budget       |
|---------------|--------------|
| Frame time    | ≤ 22 ms  (~45 fps sustained) |
| GPU           | ≤ 14 ms      |
| CPU (game)    | ≤ 6 ms       |
| CPU (render)  | ≤ 6 ms       |
| DrawCalls     | ≤ 4,500      |

Procedure per biome (5 biomes = 5 measurements):

1. PIE, walk to biome center (castle plateau, marsh clearing, desert
   bowl, plains ridge, mountain slope).
2. Stand still 3 s to let streaming settle.
3. Type `stat unit` + `stat gpu` in the PIE console.
4. Read the four numbers, log them in a table below:

| Biome     | Frame | GPU  | CPU game | CPU rt | Draw calls |
|-----------|-------|------|----------|--------|------------|
| Castle    |       |      |          |        |            |
| Marsh     |       |      |          |        |            |
| Desert    |       |      |          |        |            |
| Plains    |       |      |          |        |            |
| Mountains |       |      |          |        |            |

**If any biome exceeds budget, dial in this order** (per NEXTSTEP.md PART 2 —
lessons carried over from the arena perf pass):

1. **Grass / ground-cover cull distance.** In Content Browser find the
   `REGION_<BIOME>_*` HISM actors (Phase D2 follow-up) or the plain
   StaticMeshActors placed by `build_overworld_biomes.py`. Reduce
   Component Cull Distance to ~15,000 UU (150 m) for grass, 40,000 UU
   for larger props.
2. **Cloud View Sample Count Scale.** Console command
   `r.VolumetricCloud.ViewSampleCountScale 0.5` (was 1.0). Big win on
   RTX 4050.
3. **Grain / fringe off.** In the biome's PostProcess volume
   (`REGION_<BIOME>_PostProcess`), zero out grain intensity and
   chromatic aberration.
4. **Optional Nanite pass on dressing** (last resort — only if the above
   don't get you under budget). Flip `DO_NANITE=True` at the top of
   `Tools/build_overworld_biomes.py` and re-run. Nanite has an overhead
   the arena had budget for; the overworld's density may not.

---

## G2 — Encounter transitions (15 min)

Walk into each of the 5 encounter volumes. For each:

- [ ] Approaching the volume: exploration camera (arm ~550, wider FOV).
- [ ] Crossing the trigger: no hitch > 1 frame; camera smoothly interps to
      combat arm (~400) + combat FOV over ~0.3 s.
- [ ] Boss reveals + collision on; combat begins.
- [ ] Log line in the Output Log:
      `NNEBossPolicy: archetype: <persona> (cos=<value>)` OR
      `archetype: <persona> (biome-preferred fallback)` OR
      `default: GameFeelSettings NNEBossModelData`.
      (Confirms Phase C wiring: the encounter fires the resolver, not
      world-begin.)
- [ ] Log line: `GameFeelSubsystem::BeginEncounter: '<EncounterID>' active`.
- [ ] Leaving the volume mid-fight (retreat): boss re-hides, exploration
      cam returns; NO save state changes (re-entering the volume works
      cleanly).
- [ ] Killing the boss: death montage plays; exploration cam returns
      about 2 s later; log line:
      `GameFeelSubsystem::EndEncounter: '<EncounterID>' released (defeated=1)`.

---

## G3 — Save / load stress (15 min)

- [ ] Fresh save: `Saved/SaveGames/` empty. Enter castle biome, defeat
      the boss. Check `Saved/SaveGames/OverworldSaveGame_guest.sav` exists.
- [ ] Quit editor, relaunch, PIE from the same map. Log line:
      `GameFeelSubsystem: overworld save loaded ('OverworldSaveGame_guest',
       1 defeated zones, 1 encounters logged)`.
- [ ] Walk into the castle biome's encounter volume — nothing happens
      (bAlreadyDefeated). Confirmed by log line:
      `BossEncounterVolume '<castle-id>': loaded from save as already
       defeated.`.
- [ ] Player position restored: pawn spawns at the same world-space
      location captured at the encounter end (log:
      `GameFeelSubsystem: restored player pos ...`).
- [ ] Defeat each of the other 4 bosses, one per PIE session; each save
      cycle increments `DefeatedBossZones.Num()` to the expected number.
- [ ] After all 5 defeated: `EncounterLog.Num()` = 5. Each entry has a
      non-empty `SelectedPersona`, a positive `DurationSeconds`, and a
      recent `EndUnixSeconds` (within the session).

---

## G4 — Regression sweep on the arena (5 min)

Prove BossArena.umap is untouched by the branch.

- [ ] Open `Content/Maps/BossArena.umap`. Log line at PIE:
      NO `GameFeelSubsystem: overworld mode` line — the volume scan
      found zero encounter volumes.
- [ ] Boss auto-installs HUD + NNE component at world begin as usual.
- [ ] Combat plays identically (same camera arm, same telegraphs, same
      damage numbers, same round reset).
- [ ] `Python/eval_archetypes.py --all` still passes (no ONNX drift from
      the branch).

---

## G5 — Ship gate

All boxes above ticked → ready for Phase H (Cook + package smoke).
Any box unticked → open a follow-up commit before Phase H.

The paper's Figure 1 (overworld wide shot) and Figure 2 (five biomes +
five telegraphs) can be captured during this pass — leave PIE up, use
`HighResShot 4` in the console at each biome vantage.

---

## H — Cook + package smoke (30 min)

Cook config is already committed:
- `[/Script/UnrealEd.ProjectPackagingSettings]` gains
  `+DirectoriesToAlwaysCook=(Path="/Game/Overworld")` and
  `+DirectoriesToAlwaysCook=(Path="/Game/Maps")`. `/Game/Arena/Models`
  (NNE brains) stays untouched.

Procedure:

1. **Editor closed.** Run:
   ```
   "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\RunUAT.bat"
   BuildCookRun -project="D:\GAME_CORE 5.8\GAME_CORE.uproject"
   -noP4 -platform=Win64 -clientconfig=Development
   -cook -pak -stage -archive
   -archivedirectory="D:\GAME_CORE 5.8\Saved\StagedBuilds"
   -map=BossArena+Overworld
   ```
2. **Watch the cook log** (`Saved/Logs/Cook-*.log`) for red 'MissingAsset'
   entries. Expected clean; if a Fab pack asset warns, the mesh path is
   wrong in `Tools/build_overworld_biomes.py` PALETTE — fix + re-run
   Phase D.
3. **Boot the packaged build:** launch
   `Saved/StagedBuilds/Windows/GAME_CORE.exe`.
4. **Parity check across all 5 biomes:** same steps as G2/G3 above but
   in the packaged build.
   - [ ] Overworld level loads. Landscape + biome dressing visible.
   - [ ] Encounter volume triggers each of the 5 archetype-matched brains.
   - [ ] `Saved/SaveGames/OverworldSaveGame_*.sav` writes on defeat.
   - [ ] BossArena.umap parity: launch from main-menu (or `-Map=BossArena`
         command-line) and combat plays identically to the Development
         editor build.

If all H boxes ticked → merge `feat/overworld` → main. Paper submission
timeline resumes from `paper.md` §10 (ablation runs / human study).
