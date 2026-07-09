# BossArena — Showcase Mode

Cinematic + minimalist BossArena variant that keeps the ship-quality shipping
arena intact while producing a stripped, RL-focused presentation surface.

Two pieces:

1. **Headless dressing/PP script**: `Tools/apply_showcase_bossarena.py` hides
   the 508 `ARENA_DRESS_*` clutter, spawns four obsidian monolith landmarks at
   the cardinal directions, and swaps the ARENA_PostProcess volume to a
   crushed-blacks / gold-rim / tighter-vignette palette. Fully reversible.
2. **RL-visibility HUD**: `UGameFeelSettings::bEnableRLShowcase = true` turns
   on four Slate panels layered over the existing boss HUD:
   - top-left: brain badge (NNE persona + cosine confidence),
   - top-right: 5-cell action-mask row (dimmed = masked, gold = chosen),
   - bottom-left: 8-dim player-profile radar (live from `PlayerProfileComponent`),
   - center-right: taunt fade fed by `OnBossInsightGenerated`.

Both pieces are independent — you can run the visual pass without the RL HUD,
or the RL HUD in the ship-quality arena, or both together.

Neither piece touches combat: the RL HUD is a read-only mirror of live
components (never mutates), and the dressing pass hides actors via
`bIsHiddenInGame` instead of destroying them.

## Apply — one-shot headless pass

Editor closed. From a PowerShell prompt:

```powershell
# Apply the showcase pass (default when SHOWCASE_MODE is unset).
& 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe' `
    'D:\GAME_CORE 5.8\GAME_CORE.uproject' `
    -ExecutePythonScript='D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py'
```

Or, in the editor Output Log's Cmd console:

```
py "D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py"
```

To revert (unhide all dress actors, destroy monoliths, restore PP baseline):

```powershell
$env:SHOWCASE_MODE = 'off'
& 'C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe' `
    'D:\GAME_CORE 5.8\GAME_CORE.uproject' `
    -ExecutePythonScript='D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py'
```

## Enable the RL-visibility HUD

Three ways, all equivalent in effect — pick whichever fits the moment:

- **Project Settings** → Game → Game Feel → **Enable RL Showcase**. Persists
  to `Config/DefaultGame.ini`. Takes effect on the next play.
- **Runtime console** (backtick `~`): `arena.Showcase 1` (or `0`). The HUD
  component reads the setting every tick, so panels appear on the very next
  paint. The command also `SaveConfig()`s so the setting survives sessions.
- **INI edit**: `Config/DefaultGame.ini` under
  `[/Script/GAME_CORE.GameFeelSettings]`, add `bEnableRLShowcase=True`.

Requires `bEnableBossStatusHUD=True` (the RL panels layer over the boss HUD).

## PIE verification

- **Brain badge (top-left)** shows the resolved persona and cosine confidence
  once the NNE component picks (log line `NNEBossPolicy: archetype: <persona>
  (cos=…)` or the fallback message).
- **Mask row (top-right)** — every action cell should light up (dark gray) when
  legal and fade out when masked. The one gold-outlined cell is the last
  chosen action (from NNE argmax, or the committed `BossActionComponent`
  action when NNE isn't driving).
- **Profile radar (bottom-left)** — polygon starts as a regular octagon (all
  0.5, neutral player) and morphs as the hero fights: heavier attack cadence
  bulges "Agg", frequent dodges bulge "Dge", etc.
- **Taunt (center-right)** — fades in on `OnBossInsightGenerated`; the boss's
  `UBossExplainabilityComponent` broadcasts these when a profile trait crosses
  its threshold.

If a panel stays blank, the corresponding component isn't on the boss/hero.
Check `FindComponentByClass` logs; the RL HUD tolerates missing peers.

## Perf

The showcase pass **reduces** draw calls (hides ~500 static-mesh actors, adds
4). GPU cost is strictly negative on the RTX 4050. The Slate panels are 4
constant-cost paint calls (~0.02 ms in aggregate on the target GPU).

## Backup / revert

`SHOWCASE_MODE=on` writes `Saved/ShowcaseBackup/postprocess_baseline.json` on
first apply, snapshotting the shipping post-process values. `SHOWCASE_MODE=off`
reads that file and restores them. **Keep the file** — regenerating from
"clean" would require finding the original numbers in `dress_arena.py` /
`cinematic_pass.py`, which is tedious.

## Related

- `Tools/dress_arena.py` owns the 508 dress actors we hide.
- `Tools/cinematic_pass.py` owns the volumetric clouds + shipping PP defaults.
- `Source/GAME_CORE/Public/BossStatusHUD.h` — extended widget + component.
- `Source/GAME_CORE/Public/GameFeelSettings.h` — `bEnableRLShowcase` flag.
