# Plan — What to do with the RPG overworld map

## Context

You showed a hand-drawn D&D-style overworld: castle at center, marsh/lakes to
the west, desert to the north, plains + villages to the east/south-east,
mountains + forests to the south. 2 km scale bar. You asked what I think about
building it for the game.

The map is beautiful, but there's a scope mismatch to name up front so we can
decide against the right target rather than the wrong one:

- **The game is a single-arena adaptive-boss combat title.** M0–M4 done,
  M5 shipped (turtle default + rusher banked), M6 game-side done,
  M8 cook smoke PASS. You are close to release.
- **The paper's core research pitch is "profile-matched archetype selection"**
  (`paper.md` §4 point 5) — the *system* picks the boss archetype from the
  player's decayed cross-encounter dossier, automatically, at world load.
  The website's "One Boss" pitch explicitly says *"One mind · many fighters"*.
- **The current arena tool suite is a monolithic single-map builder**
  (verified — every `Tools/*.py` script hard-codes `MAP_PATH="/Game/Maps/BossArena"`
  and welds the ashen palette / KiteDemo asset paths into ~50-category
  PALETTE dicts and geometry-specific label taxonomies). Only
  `ambient_particles.py` has any variant support (ash↔snow flag). Content:
  `BossArena.umap` is the only level; no biome source packs in `SourceArt/`.

A playable open-world map on top of this would require: new source asset
packs per biome, a theme-descriptor abstraction refactored across all 7
scripts, a level-transition manager, world-streaming or gated seams,
outside-combat locomotion + camera + save state, and a player-driven
selection mechanic that **directly replaces** the paper's contribution.
It is at least 2–3 months of scope creep and it dilutes the thesis.

**So the useful question isn't "should we build it" — it's "how do we use it
in service of the game and the paper without breaking either."**

## Recommendation

Use the map as **worldbuilding art, not playable geography.** Three tiers of
increasing effort. Pick one or stack them.

### Tier 1 — Menu / UI backdrop (recommended default; ~2 h)

Use the map as a static graphic in three places on the site + game UI:

- **`Website/src/pages/Login.jsx`** — full-bleed backdrop behind the login
  form, dimmed to ~35% opacity, subtle vignette. Sets tone before the player
  ever sees combat.
- **`Website/src/pages/World.jsx`** — inline card above the "One mind ·
  many fighters" paragraph. Frame as *"The world the boss watches over"* —
  reinforces the singular-boss pitch rather than fragmenting it.
- **`Source/GAME_CORE/Public/LoginScreen.h` + `Private/LoginScreen.cpp`**
  (the in-game `SLoginScreen` Slate widget) — same graphic as an
  `FSlateBrush` background image, dimmed. One asset added to
  `Content/UI/Textures/T_WorldMap.png`, one brush wired.

Zero engine risk. No level work. Adds significant worldbuilding polish for
low cost. Doubles as **Figure 0 in the paper** (world lore establishing
shot before the system diagram takes over).

### Tier 2 — Community "atlas" on the World page (~1 day, web-only)

On `Website/src/pages/World.jsx`, overlay dots on the map corresponding to
aggregated player fights — one per region, sized by fight count, colored by
which archetype (rusher/turtle/kiter/…) matched most often for players in
that Firebase-region bucket. Feed from the existing `meta/global` Firestore
doc (`CommunityDifficultySubsystem` already writes it). No new backend, no
new game code, no engine touch. Turns the map into a live artifact of the
"One Boss" community loop — the strongest supporting figure for
`paper.md` §4 point 9.

Requires: (a) either add a `region` field to the round-JSON schema in
`Website/README.md` (the contract) and to `TelemetryUploadSubsystem::Upload`,
or approximate via IP-geo on the client at upload time — either is a small
diff. Recommended if you want the paper to include a longitudinal
community read (§10 point 6).

### Tier 3 — Biome-themed arena *skins* driven by archetype match (2–3 weeks; DEFER)

If, post-release, you want the biome flavor to reach into the arena itself
without breaking the research pitch, do it *system-driven*, not
player-picked:

- Refactor `Tools/build_arena_level.py`, `upgrade_terrain_material.py`,
  `scatter_ground_cover.py`, `cinematic_pass.py`, `dress_arena.py`,
  `ambient_particles.py`, `build_beauty_meshes.py` to accept a
  `THEME` env var (`ashen` / `desert` / `marsh` / `castle` / `grassland`)
  with per-theme palette + asset-pack constants.
- Build 3 additional themed skins (castle for turtle, desert for rusher,
  marsh for kiter) as separate `.umap`s: `BossArena_Castle.umap`,
  `BossArena_Desert.umap`, `BossArena_Marsh.umap`.
- `UGameFeelSubsystem::TryInstall` — after archetype resolution but before
  `UNNEBossPolicyComponent` injection, look up the picked persona's
  associated biome (new `+NNEArchetypeBank=(...,BiomeSkin="Desert")` field
  in `Config/DefaultGame.ini`) and `OpenLevel(BossArena_<Biome>)`.

Preserves the paper's automatic-selection contribution *and* gives players
the visual differentiation the map hints at. But this needs asset packs
per biome (per `visuals.md` budgeting on RTX 4050) and is real work.
**Explicitly not for pre-release.** Adds a compelling extension section
for the paper (§10 or Future Work).

## Anti-recommendation (do not build)

- **A playable overworld you walk / ride across.** Camera, save state,
  outside-combat locomotion, streaming, NPC dialogue, quest scaffolding —
  all of these are new subsystems. It is a different game.
- **A player-driven biome / boss picker.** It replaces the paper's
  §4 point 5 mechanism with a menu. If you want the picker, that's a
  legitimate design choice, but then the paper's framing has to change
  and the "One mind · many fighters" tagline has to go.

## Files that would change (Tier 1 only)

- `Website/public/world-map.jpg` (or `.webp`) — asset (from the image you
  pasted; compress to ~500 KB).
- `Website/src/pages/Login.jsx` — background style / one image import.
- `Website/src/pages/World.jsx` — inline card.
- `Website/src/styles.css` — one class for the dimmed backdrop.
- `Content/UI/Textures/T_WorldMap.uasset` — imported texture.
- `Source/GAME_CORE/Private/LoginScreen.cpp` — one `FSlateBrush` field
  wired into the widget's background slot.

Nothing else — no editor tools, no `Config/` changes, no Python.

## Verification

- Tier 1: `cd Website && npm run dev` → Login and World pages render map
  backdrop at intended opacity; light and dark theme both readable;
  no CLS on load. In-editor: PIE → login screen shows map behind form.
- Tier 2: Firestore `meta/global` doc has the new aggregate field; a real
  overnight run produces at least one dot on the map after upload.
- Tier 3 (deferred): PIE → new player profile forces rusher match →
  desert-skin arena loads. Round reset preserves skin. Cook smoke on all
  four `.umap`s pass.

## Corrections after user pushback

The user challenged the recommendation on four points. Honest revisions:

1. **AAA tile streaming (10×10 grid).** True. UE5 **World Partition** (built
   in since 5.0) does exactly this — grid partition + HLOD + async cell
   streaming around the player. Setup is a project-setting flip and a
   landscape conversion, not custom engineering. My original "streaming
   / gated seams" phrasing overstated the cost. Retracted.

2. **RL compatibility.** The 17-dim obs is combat-local
   (distance/angle/HP/velocity/profile). The world map does not touch it.
   What changes is the *trigger moment*: `UGameFeelSubsystem::TryInstall`
   runs on entering a boss zone (trigger volume), not on `BeginPlay`.
   Archetype resolution runs from the same stored profile at the deferred
   moment. **This actually strengthens the paper** — multiple encounters
   per session multiplies match evidence, aligns with the longitudinal
   community-read study in §10 point 6, and lets "One mind · many fighters"
   become "one mind that finds you wherever you are." Reframe, don't
   discard.

3. **Available tooling was underused.** Blender MCP (terrain heightmap
   bake + erosion sim + asset scripts), UE MCP (level-ops when editor
   running), and the Fab library (MedCastle, KiteDemo, Nordic, Paragon
   Dusk, ForestOfSpikes packs) are all already wired. Retargeting pipeline
   (`setup_retargeters.py`, `batch_retarget_anims.py`) exists.
   `Tools/build_arena_level.py` + `dress_arena.py` are forkable per biome,
   not a monolith to rewrite.

4. **Realistic timeline is ~3 weeks focused solo work, not 2–3 months.**

## Tier 4 — Streamed open world with encounter-triggered boss (added)

### Approach

- **Terrain.** Bake heightmap from the map image via Blender MCP
  (displacement + hydraulic erosion). Import as UE landscape. Convert
  landscape to World Partition (built-in one-click since 5.0).
- **World Partition.** Enable in project settings. Runtime grid ~1 km cells
  with HLOD1 at 5 km cull. Landscape auto-partitions.
- **Biome dressing.** Fork `Tools/dress_arena.py` five times:
  `dress_castle.py`, `dress_marsh.py`, `dress_desert.py`, `dress_plains.py`,
  `dress_mountains.py`. Each takes its region's world-bounds rectangle,
  swaps the PALETTE dict to that biome's Fab assets, keeps the actor-label
  taxonomy (`REGION_CASTLE_*` etc.). Idempotent, re-runnable, guarded to
  the overworld map only.
- **Player traversal.** Existing Mover-based hero already walks. Combat
  camera arm (`UCombatCameraComponent`) already auto-injected; add a
  looser "exploration" arm swap outside combat via a trigger volume.
- **Encounter triggers.** One `ATriggerVolume` per biome center gated by
  archetype: enter the desert bowl → `TryInstall` picks rusher (or the
  archetype-matched brain from the stored profile) → boss spawns → combat
  camera swaps in → round runs as it does today → death/exit removes the
  boss and resets exploration camera.
- **Persistence.** `USaveGame` for player position + defeated-boss
  bitfield. Already halfway there — `PlayerMemoryComponent` handles the
  hard part (profile persistence).
- **Minion patrols.** Existing `AMinionEncounterSpawner` scattered per
  biome — 2–3 spawner actors per zone.

### Timeline

| Phase | Days | Confidence |
|---|---|---|
| World Partition + landscape from heightmap (Blender MCP bake) | 2–3 | high |
| Player traversal outside combat (Mover + camera arm swap) | 1–2 | high |
| 5 biome dressing forks + Fab pack integration | 5–7 | medium |
| Encounter trigger volumes + deferred `TryInstall` + save/load | 2 | high |
| NavMesh + minion patrols per biome | 2 | medium |
| Paper reframe (§4 point 5, §4 point 9, website "One Boss" copy) | 1 | high |
| Playtest + performance pass on RTX 4050 (GPU ~14 ms budget) | 3–5 | low |
| Cook + package smoke on the bigger map | 1 | medium |

**Realistic total: ~3 weeks focused solo work.**

### Risks that remain real (do not sugar-coat)

- **RTX 4050 6 GB is tight for a 2 km world** even with WP. Foliage
  scatter + HLOD tuning eats days. `visuals.md` was written for a single
  arena.
- **Fab pack quality varies.** Some retargets have LOD gaps, missing
  collision, or Nanite non-compat. Per-pack fixes are the death-by-a-thousand-
  cuts hours; hard to estimate.
- **Paper timeline cost.** Every week on the world is a week not on
  ablation runs / human study / the "results to run" items in
  `paper.md` §10.

### Paper reframe (required if Tier 4 ships)

- **§4 point 5** — "Archetype-matched policy selection" wording moves from
  "at world load" to "on encounter". Same mechanism, deferred moment.
- **§4 point 9 / §11.3** — "One Boss" wording becomes "one mind, many
  encounters." Website copy on `World.jsx` gets one paragraph rewrite.
- **§10 point 6** — longitudinal community read becomes stronger (more
  encounters per player = more data points per unit time).
- **§11.2** — screenshot slate grows: overworld shot, five biome shots,
  five telegraphs from five brains. Richer figure budget.
- **§13** — new limitation to declare: single-machine world budget on
  RTX 4050, cross-hardware generalisation TBD.

## Anti-recommendation (still stands)

- **Player-driven biome / boss picker.** Explicitly not the mechanism.
  Selection stays automatic, driven by the profile-matched centroid at
  encounter time. If you want a picker, the paper's contribution
  argument changes and needs different framing.

## User decision — build Tier 4

Ship-schedule paused ~3 weeks. Below is the execution plan.

---

# Tier 4 execution plan

## Phase ordering + critical files

### Phase A — Terrain from heightmap (2–3 days)

**Goal:** UE landscape with the map's geography (marsh/desert/plains/mountains
around a central castle plateau), World Partition enabled, playable to walk.

- **A1. Reference bake (Blender MCP).** Take the pasted map image; in
  Blender: displace a subdivided plane by luminance-derived heightmap
  (rivers = low, mountains = high), run a hydraulic-erosion sim
  (Blender's built-in `A.N.T. Landscape` or manual erode via geometry
  nodes), export a 2049×2049 16-bit PNG heightmap. Also export a
  weightmap PNG per biome (marsh/desert/plains/mountains/castle-plateau)
  by manual selection or color-key.
- **A2. UE landscape import.** New level `Content/Maps/Overworld.umap`.
  Landscape Mode → import heightmap. Size ~2 km × 2 km, 63 quads/component.
  Import weightmaps as layer infos on a new `M_OverworldLandscape`
  material (fork `M_Terrain` from `upgrade_terrain_material.py`).
- **A3. World Partition conversion.** Project Settings →
  Enable World Partition. Landscape → convert to World Partition (built-in
  wizard). Runtime grid 1024 m cells; HLOD1 at 5 km cull. Loading Range
  enabled.
- **A4. Nav bounds.** `AArenaEditorTools::SpawnNavMeshBoundsVolume`
  (already exists — `Source/GAME_CORE/Public/ArenaEditorTools.h`)
  encompassing the walkable regions. Multiple volumes per biome cheaper
  than one giant one.

**New tool file:** `Tools/build_overworld_level.py` — forks
`Tools/build_arena_level.py`; env-parameterized (`OVERWORLD_HEIGHTMAP`,
`OVERWORLD_WEIGHTMAP_DIR`). Headless via `-ExecutePythonScript`.

**Reuse:**
- `Tools/build_arena_level.py` (level-op patterns, nav-mesh spawn)
- `ArenaEditorTools::SpawnNavMeshBoundsVolume`
  (`Source/GAME_CORE/Public/ArenaEditorTools.h`) — nav volume with real
  brush geometry (the scripting-can't-do-it fix already exists).

**Verify A:** PIE → hero spawns on castle plateau → walks in every
direction, doesn't fall through terrain, framerate ≥ 45 fps at
1080p Medium.

### Phase B — Exploration camera + traversal (1–2 days)

**Goal:** hero moves outside combat with a looser third-person camera;
snaps to combat cam on encounter start.

- **B1. Exploration camera mode on `UCombatCameraComponent`.** Add
  `ECameraMode { Combat, Exploration }` and per-mode arm/FOV/lag settings
  read from `GameFeelSettings` (`ExplorationArmLength`,
  `ExplorationFOV`, `ExplorationLag`).
- **B2. Mode swap trigger.** `UGameFeelSubsystem::SetCameraMode(EnumVal)`.
  Default `Exploration` on world load; encounter volume flips to
  `Combat` on begin overlap, back to `Exploration` on boss death /
  volume exit.
- **B3. Lock-on gate.** `LockOnComponent::SetActive(false)` outside
  combat (`ULockOnComponent` already exists).

**Critical files:**
- `Source/GAME_CORE/Public/CombatCameraComponent.h` +
  `Private/CombatCameraComponent.cpp`
- `Source/GAME_CORE/Public/GameFeelSettings.h` +
  `Private/GameFeelSettings.cpp` (add 3 UPROPERTYs)
- `Source/GAME_CORE/Public/GameFeelSubsystem.h` +
  `Private/GameFeelSubsystem.cpp` (add `SetCameraMode`)

**Reuse:** `UCombatCameraComponent` already auto-injected by
`UGameFeelSubsystem` — extend, don't add a second component.

**Verify B:** PIE → walk exploration cam → enter test trigger → combat
cam snaps in over 0.3 s interp → walk out → exploration cam returns.

### Phase C — Encounter triggers + deferred archetype install (2 days)

**Goal:** entering a boss zone triggers the current archetype match
+ boss spawn + combat; leaving / boss-death ends the encounter cleanly.

- **C1. New actor `ABossEncounterVolume`.**
  `Source/GAME_CORE/Public/BossEncounterVolume.h` (new). ATriggerVolume
  subclass with:
  - `TSoftObjectPtr<AActor> BossBP` (BP_Boss reference)
  - `FVector BossSpawnOffset`
  - `FRotator BossSpawnRotation`
  - overlap logic → `UGameFeelSubsystem::BeginEncounter(this)`.
- **C2. Refactor `UGameFeelSubsystem::TryInstall`.** Split into
  `LoadMemoryAndProfile()` (still on `BeginPlay`) and
  `BeginEncounter(EncounterVolume)` (called from C1). NNE injection +
  camera swap + boss spawn move to `BeginEncounter`. Existing archetype
  resolution stays exactly where it is — just deferred.
- **C3. Encounter end.** `EndEncounter()` on boss death
  (`OnBossDied` broadcast, already exists) OR on player exiting a wider
  disengage volume. Despawns boss actor, restores exploration camera,
  fires `TelemetryUploadSubsystem::QueueRoundUpload` (already exists).
- **C4. Level placement.** One `ABossEncounterVolume` per biome center
  (castle courtyard, desert bowl, marsh clearing, plains plateau,
  mountain valley). Placed via `Tools/build_overworld_level.py`
  (idempotent). Each hardcodes `PreferredPersona` (rusher/turtle/kiter/…)
  as a FALLBACK — the profile match still runs first; if the player's
  profile matches nothing in the bank, the biome's preferred persona is
  used instead of the global default.

**Critical files:**
- `Source/GAME_CORE/Public/BossEncounterVolume.h` +
  `Private/BossEncounterVolume.cpp` (new, ~150 lines total)
- `Source/GAME_CORE/Public/GameFeelSubsystem.h` +
  `Private/GameFeelSubsystem.cpp` (refactor `TryInstall`;
  add `BeginEncounter`/`EndEncounter`)
- `Source/GAME_CORE/Public/NNEBossPolicyComponent.h` — add
  `PreferredPersonaOverride` parameter to the archetype resolver
- `Config/DefaultGame.ini` — `+NNEArchetypeBank` rows gain optional
  `BiomeSpawnZone` hint (documentation only)

**Reuse:**
- Archetype resolution + mean-centered cosine
  (`UNNEBossPolicyComponent::ResolveArchetype`) — unchanged, called at
  new moment.
- `UPlayerMemoryComponent::LoadMemory` / `RecordEncounterEnd` /
  `SaveMemory` — reused wholesale (now called once per encounter, not
  once per level load).
- `UTelemetryUploadSubsystem::QueueRoundUpload` — reused as-is.
- `AutoResetRoundOnDeath` behavior on `CombatComponent` — reused
  (encounter end == round end).

**Verify C:** PIE → walk into each of the 5 encounter volumes → correct
biome-preferred brain loads unless profile match overrides → fight →
win/loss → boss despawns → walk to next biome → different brain loads.

### Phase D — Biome dressing (5–7 days, the bulk)

**Goal:** each biome region looks distinctly like its map region.

For each biome (5 total: castle, marsh, desert, plains, mountains):

- **D1. Fork `Tools/dress_arena.py` → `Tools/dress_<biome>.py`.**
  Swap PALETTE dict to the biome's Fab-pack assets (MedCastle for castle,
  Nordic swamps or ForestOfSpikes-water for marsh, Paragon Dusk rocks
  for desert dunes, Nordic grass for plains, Nordic mountain rocks for
  mountains). Region bounds = rectangle in overworld coords. Actor label
  prefix per biome (`REGION_CASTLE_*` etc.).
- **D2. Fork `Tools/scatter_ground_cover.py` → per-biome tint + mesh
  swap.** Grass tint from ~(0.30,0.26,0.17) ashen to per-biome palette.
  Regions gated by biome bounds. Reuse the HISM cover approach —
  proven at 24.5k instances on RTX 4050.
- **D3. `Tools/upgrade_overworld_material.py` — fork of
  `upgrade_terrain_material.py`.** Multi-layer landscape material using
  the weightmaps from A1. One texture set per biome
  (`SourceArt/Overworld/Textures/<biome>/`).
- **D4. `Tools/cinematic_pass_overworld.py`.** Two sky variants: day for
  overworld traversal, biome-specific atmosphere per encounter volume
  (cold blue for castle, dusty orange for desert, misty green for
  marsh). PostProcessVolume per biome.
- **D5. `Tools/ambient_particles_overworld.py`.** Extend the existing
  ash/snow variants — add pollen (plains), sand (desert), pond flies
  (marsh).

**Critical files:** all under `Tools/`. All idempotent, guarded to
`/Game/Maps/Overworld` only.

**Reuse:**
- `Tools/dress_arena.py` (~500-line PALETTE + region-scatter pattern) —
  fork per biome. Do not try to unify into one theme-swappable script;
  the punch-list shows every script is deeply coupled, and 5 forks are
  faster than one abstraction refactor with 5 configs.
- `Tools/scatter_ground_cover.py` (HISM budget already tuned).
- `Tools/cinematic_pass.py` (PP + volumetric cloud settings).
- `Tools/ambient_particles.py` (already has `DO_SNOWFALL` variant flag —
  the least refactor-hostile).
- `Tools/build_beauty_meshes.py` (Blender floor-ring / backdrop scripts) —
  fork per biome for distinctive silhouettes (castle keep, mountain
  peaks).

**Verify D:** headless `-ExecutePythonScript` runs each script clean;
PIE walk-through — each biome looks visually distinct at 15 m
draw distance; `stat unit` GPU ≤ 14 ms in each biome; HLOD1 at 5 km
kicks in without pop.

### Phase E — Save/load + minion patrols (2 days)

- **E1. `UOverworldSaveGame` (new).** Fields: `PlayerLocation`,
  `PlayerRotation`, `TSet<FName> DefeatedBossZones`,
  `TArray<FEncounterRecord> EncounterLog`. Written on encounter end,
  loaded on level open.
- **E2. `AMinionEncounterSpawner` placements per biome.** 2–3 spawners
  per biome, tied to nav volumes. `AMinionEncounterSpawner` already
  exists — placement only.

**Critical files:**
- `Source/GAME_CORE/Public/OverworldSaveGame.h` +
  `Private/OverworldSaveGame.cpp` (new, thin)
- `Source/GAME_CORE/Private/GameFeelSubsystem.cpp` — hook save/load into
  world begin / encounter end
- `Tools/build_overworld_level.py` — place spawner actors during headless
  build

**Reuse:** `AMinionEncounterSpawner`
(`Source/GAME_CORE/Public/MinionEncounterSpawner.h`), full BT stack
(`BTService_MinionCombatState`, `BTTask_MinionAttack`,
`BTDecorator_MinionCanAct`), faction rules (Enemy tag) — all reused.

**Verify E:** PIE → defeat castle boss → quit → relaunch → boss zone
marked defeated (no re-encounter); patrol minions on the way to
each biome — killable, don't friendly-fire.

### Phase F — Paper reframe (1 day, parallel with F)

- Rewrite `paper.md` §4 point 5 wording: world load → encounter.
- Rewrite `paper.md` §4 point 9 wording: "One Boss" → "one mind, many
  encounters."
- Add new figures list to §11.2 (overworld shot, 5 biomes, 5 telegraphs).
- Add limitation to §13: single-machine world-perf budget.
- Rewrite `Website/src/pages/World.jsx` hero copy to match.

**Critical files:** `paper.md`, `Website/src/pages/World.jsx`.

### Phase G — Playtest + perf pass (3–5 days)

- **G1. `stat unit` + `stat gpu` per biome.** Target ≤ 14 ms at 1080p
  Medium on RTX 4050. Dial in this order per `NEXTSTEP.md` PART 2:
  grass cull distances (HISM), cloud View Sample Count Scale, grain +
  fringe off. Optional Nanite pass on dressing.
- **G2. Encounter transitions.** No hitch on volume overlap. Async load
  boss BP early via `TSoftObjectPtr::LoadAsync` on approach (< 20 m).
- **G3. Save/load stress.** Quit/relaunch 20× across biomes; state
  restored every time.

### Phase H — Cook + package smoke (1 day)

- `Config/DefaultGame.ini` `DirectoriesToAlwaysCook` — add
  `/Game/Maps/Overworld` and all biome-specific asset folders.
- Full cook + package Windows dev build.
- Boot the packaged build; PIE-parity check across all 5 biomes.

---

## Verification checklist (end-to-end)

- [ ] PIE — hero spawns on castle plateau, walks in all 4 cardinal
      directions across biomes without terrain gaps.
- [ ] Enter each of the 5 encounter volumes — correct persona-matched
      brain resolves in the log (`NNEBossPolicy: ready — model 'NNM_Boss<X>'`);
      profile match still overrides the biome preference when the player
      has enough encounter history.
- [ ] Combat plays identically to today's `BossArena.umap` — same
      camera arm, same HUD, same damage numbers.
- [ ] Boss death → boss despawns → exploration cam returns → biome
      marked defeated in save → subsequent visits do not re-spawn the boss.
- [ ] `stat unit` GPU ≤ 14 ms in every biome at 1080p Medium.
- [ ] Cook + package succeeds; packaged build parity-check clean.
- [ ] `paper.md` §4/§9/§11/§13 updated to match new "encounter-triggered
      archetype match" framing.

---

## Risks (final call-out)

- RTX 4050 GPU budget in the plains + mountains biomes (open sightlines,
  lots of grass) is the single biggest risk. Escape hatch: shorten
  draw distances aggressively, add fog-culled horizon meshes.
- Fab pack quality — allocate ~1 day of the D phase to per-pack material
  / collision / LOD fixes and be honest if it grows.
- Paper timeline — ~3 weeks displaced from the ablation-runs / human-study
  plan. Acceptable trade-off IF Tier 4 becomes the paper's Figure 1 and
  the "encounter-triggered" reframe replaces the shipped-arena framing
  everywhere consistently.