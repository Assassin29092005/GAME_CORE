# GAME_CORE — Visuals Guide (indie bar, RTX 4050)

Companion to **guide.md**. That file owns how the game *feels*; this one owns how it
*looks* — and both spend the same frame budget, so every choice below is sized against the
dev machine: **RTX 4050 laptop GPU (6 GB VRAM), 16 GB RAM, 1080p / 60 fps, with the Python
RL process running alongside.**

The bar is deliberate: **cohesive indie, not AAA.** A consistent, readable look that never
costs a frame beats an ambitious one that hitches — guide.md Phase 0 already established
that smoothness dies at the frame level first. The fight must read instantly; everything
else is negotiable.

Contents: renderer setup and the VRAM/RAM budget, a five-actor lighting rig for the arena,
art direction that reads at this budget, combat VFX, scalability defaults — then the full
**Blender -> UE 5.7 terrain pipeline** (two routes, with a recommendation), set dressing,
and Blender-on-this-laptop limits.

---

## Renderer setup for the RTX 4050

The whole visual stack below is chosen around one constraint: 6 GB of VRAM shared with a Python process, at 1080p/60. Lumen + VSM + Nanite + TSR is the modern UE5 look, and a 4050 runs it fine at indie scene complexity — *if* you keep hardware ray tracing off and manage the texture pool. Everything in this section lives in **Edit -> Project Settings -> Engine -> Rendering** unless noted.

**Global illumination and reflections:**

- **Edit -> Project Settings -> Engine -> Rendering -> Global Illumination -> Dynamic Global Illumination Method = Lumen.** Applies live (expect a shader recompile in the background), no restart.
- **Edit -> Project Settings -> Engine -> Rendering -> Reflections -> Reflection Method = Lumen.** Same — no restart.
- **Edit -> Project Settings -> Engine -> Rendering -> Lumen -> Use Hardware Ray Tracing when Available = unchecked.** This is the load-bearing decision. The 4050 *supports* HWRT, but enabling it builds ray-tracing acceleration structures (BLAS) for every mesh resident in memory — typically several hundred MB to over 1 GB of VRAM you don't have, before any quality gain shows up. Software Lumen traces against mesh distance fields instead, costs near-zero extra VRAM, and at one-arena/two-characters scale the visual difference is marginal. Leave **Engine -> Rendering -> Hardware Ray Tracing -> Support Hardware Ray Tracing** unchecked too (it requires an editor restart to change), so the structures are never built at all.
- One honesty note: in 5.7 Epic is steering Lumen toward the hardware path long-term and has deprecated the software "detail traces" mode (see [Tom Looman's 5.7 highlights](https://tomlooman.com/unreal-engine-5-7-performance-highlights/) and the [Lumen technical docs](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-technical-details-in-unreal-engine)). Software Lumen still works in 5.7; set **Engine -> Rendering -> Lumen -> Software Ray Tracing Mode = Global Tracing** (the cheaper mode, and the one that survives the deprecation — verify exact options in your 5.7 build). Revisit HWRT only if you move to an 8+ GB card.
- Software Lumen requires distance fields: confirm **Engine -> Rendering -> Software Ray Tracing -> Generate Mesh Distance Fields = checked**. Changing this prompts an editor restart and rebuilds meshes.

**Shadows:**

- **Edit -> Project Settings -> Engine -> Rendering -> Shadows -> Shadow Map Method = Virtual Shadow Maps.** No restart. VSM gives you crisp character contact shadows, which matter for read-the-boss gameplay.
- Two constantly-moving skeletal meshes invalidate VSM pages every frame, so watch the cost: if `stat gpu` shows Shadow Depths over ~2.5 ms during a fight, fall back to **Shadow Map Method = Shadow Maps** (the classic CSM path) — it looks softer but is reliably cheap. Runtime equivalent for A/B testing: `r.Shadow.Virtual.Enable 0/1` in the console.

**Nanite:**

- New 5.x projects ship with Nanite enabled; confirm at **Edit -> Project Settings -> Engine -> Rendering -> Nanite -> Nanite Support = checked** (expect a shader recompile; restart if prompted — verify exact label in your 5.7 build). Nanite has a fixed base cost (~1–2 ms at 1080p) but it is what makes Megascans-density arena meshes affordable, and software Lumen traces work fine against it.
- Per-mesh: open the static mesh asset, **Static Mesh editor -> Details panel -> Nanite Settings -> Enable Nanite Support = checked**, then Apply Changes. Use it for all arena architecture; skeletal meshes (both pawns) are not Nanite and don't need to be.

**Anti-aliasing and upscaling:**

- **Edit -> Project Settings -> Engine -> Rendering -> Default Settings -> Anti-Aliasing Method = Temporal Super Resolution (TSR).** No restart. TSR doubles as your upscaler: render below 1080p, output at 1080p.
- Screen percentage: start at `r.ScreenPercentage 80`. If the GPU line in `stat unit` sits above ~14 ms during a full boss fight (you want headroom, not exactly 16.6 — see the frame-pacing rules in guide.md Phase 0), step down toward 66. Bake the value into `Config/DefaultEngine.ini`:

  ```ini
  [SystemSettings]
  r.ScreenPercentage=80
  ```

- **Optional DLSS route (recommended on this GPU):** install the [NVIDIA DLSS plugin](https://forums.developer.nvidia.com/t/ue-5-7-dlss-4-unreal-engine-plugin-status-update/351358) — get it from Fab (Epic Games Launcher -> Fab, search "NVIDIA DLSS") or NVIDIA's developer site, which ships a 5.7-specific build. Drop it in `D:\GAME_CORE\Plugins\` if installing per-project, then **Edit -> Plugins -> search "DLSS" -> Enabled**, and restart the editor (all plugin toggles require a restart). Configure under **Edit -> Project Settings -> Plugins -> NVIDIA DLSS** (verify the exact page name in your build). At runtime, `r.NGX.DLSS.Enable 1` turns it on, and quality mode follows screen percentage: `r.ScreenPercentage 66` ≈ DLSS Quality, `50` ≈ Performance. DLSS Quality at 1080p generally beats TSR at the same input resolution on a 40-series card, at lower GPU cost. Keep TSR as the project default so the game still works on non-NVIDIA hardware.

**Restart summary:** plugin enable/disable, Support Hardware Ray Tracing, and Generate Mesh Distance Fields need an editor restart. The GI / Reflection / Shadow / AA method dropdowns apply live.

## VRAM and RAM budget

6 GB disappears fast. Windows itself plus the UE process baseline eat roughly 1–1.5 GB of VRAM before your content loads. A working budget at 1080p:

| Pool | Budget | Notes |
|---|---|---|
| OS + engine baseline | ~1.0–1.5 GB | Not negotiable; worse with browser/OBS open |
| Render targets (GBuffer, Lumen, VSM, TSR history) | ~1.2–1.5 GB | Scales with screen percentage — another reason for 80% |
| Texture streaming pool | 2.0–2.5 GB | The one knob you control directly (below) |
| Meshes / Nanite streaming | ~0.5–0.75 GB | One arena + two characters fits easily |
| Niagara, UI, misc | ~0.25 GB | |
| RT acceleration structures | **0 GB** | Because HWRT is off — this row is why it's off |
| Headroom | ~0.5 GB | For spikes; if this is gone, you'll hitch |

**Set the streaming pool explicitly** in `Config/DefaultEngine.ini`:

```ini
[SystemSettings]
r.Streaming.PoolSize=2200
```

2000–2500 is the right range on 6 GB. Too high and the engine happily fills it until something else (render targets) starves; too low and textures visibly pop. 2200 is a good starting point.

**Texture rules:**

- **2K maximum for almost everything.** Open each texture asset, **Texture editor -> Details -> Compression -> Maximum Texture Size = 2048**. Source files can stay 4K; this caps what gets cooked and streamed.
- **4K only for the arena hero surface** — the floor the camera stares at all fight. One 4K set (BaseColor/Normal/ORM), nothing else.
- Compression settings (same Details panel): `Default (DXT1/5, BC1/3)` for color, `Normalmap (DXT5, BC5)` for normals, `Masks (no sRGB)` for packed roughness/metallic/AO. Reach for `BC7` only when you can see banding — it's twice the memory of BC1.

**Watching usage:**

- `stat streaming` (console, backtick) — shows pool usage vs. budget; "Over Budget" here means pop-in is coming.
- `stat rhi` — total texture/buffer memory the RHI thinks it has allocated.
- `MemReport -full` (console) — writes a full breakdown to `Saved/Profiling/MemReports/`; the texture list sorted by size is where you find the one 4K texture you forgot about.
- Ground truth: **Task Manager -> Performance -> GPU -> Dedicated GPU memory**. When this pins at 5.9/6.0 GB, you're already paging and frame times go bimodal.

**16 GB RAM workflow tips:**

- **Run the game standalone when training, not PIE.** PIE keeps the entire editor resident next to the game (~6–9 GB combined), plus Python/torch on top. Close the editor and launch the game directly:

  ```
  "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "D:\GAME_CORE\GAME_CORE.uproject" -game -windowed -ResX=1920 -ResY=1080
  ```

  `RLBridgeComponent` hosts the TCP server in-game, so `train.py` connects to a standalone process the same as it does to PIE.
- **Keep torch off the GPU.** If SB3 grabs CUDA, the training process competes for the same 6 GB as the renderer. The policy is a small MLP over a 17–29-dim observation — CPU is as fast or faster. Force `device='cpu'` when constructing the PPO model in `Python/train.py`.
- **Expect shader-compile memory spikes.** First launch after material or rendering-setting changes spawns ShaderCompileWorker processes that can transiently add 3–5 GB. Let compilation finish (progress toast, bottom-right of the editor) before starting a training run.
- **Do not run Blender + UE + training simultaneously.** Pick two. Blender with a production scene open is multiple GB; the OS will start paging UE and the hitches will look like a gameplay bug (you will waste an evening profiling it — see guide.md Phase 0 on measuring honestly).
- **DDC note:** the Derived Data Cache defaults to `%LOCALAPPDATA%\UnrealEngine\Common\DerivedDataCache`. Keep it on the SSD and never delete it mid-project — rebuilding it means hours of shader and distance-field recompiles.

## Lighting recipe for a boss arena

One arena, one fight, no time of day — so the lighting rig is five actors, all dynamic (no baking, no lightmap UV pain). Fast path: **Window -> Env. Light Mixer**, which has one-click Create buttons for most of the list. Otherwise drag each from the **Place Actors panel (Window -> Place Actors), Lights / Visual Effects / Volumes categories**.

1. **Directional Light** (Env. Light Mixer -> Create Atmospheric Light). Set **Mobility = Movable** (Details -> Transform). Start at **Intensity 5 lux**, check **Details -> Light -> Use Temperature**, set **Temperature 5500 K** (neutral-warm key). Pitch it around −40° so characters get a clear lit side and shadow side — flat top-down light kills silhouette readability.
2. **Sky Atmosphere** (Env. Light Mixer -> Create Sky Atmosphere). Defaults are fine; it exists to give the sky light and reflections something physically plausible to sample.
3. **Sky Light** (Env. Light Mixer -> Create Sky Light). **Mobility = Movable**, then check **Details -> Light -> Real Time Capture**. This keeps ambient light and the directional light in agreement automatically, for a fraction of a millisecond of GPU.
4. **Exponential Height Fog** (Env. Light Mixer -> Create Height Fog). Set **Fog Density 0.01–0.02** for depth separation between the boss and the arena walls. The **Details -> Volumetric Fog -> Volumetric Fog checkbox** is optional atmosphere on a 6 GB card: it costs roughly 0.5–1 ms at 1080p with defaults. If you enable it, keep density at the low end and do not add volumetric local lights. If `stat gpu` says you can't afford it, plain (non-volumetric) height fog still does 80% of the depth-cueing job.
5. **PostProcessVolume** (Place Actors -> Volumes -> PostProcessVolume). Check **Details -> Post Process Volume Settings -> Infinite Extent (Unbound)** so it applies everywhere. Then:
   - **Exposure — clamp it.** **Details -> Lens -> Exposure -> Metering Mode = Auto Exposure Histogram**, then set **Min EV100** and **Max EV100** to a narrow band. To find the band: open **viewport Show -> Visualize -> HDR (Eye Adaptation)**, stand in the arena, note the settled EV100 value, and set Min/Max to that value ±0.5 (e.g., settled at 1.0 -> Min 0.5, Max 1.5). Tighten to ±0.25 once the lighting is final.
   - **Why this matters for combat:** guide.md Phase 4.4 makes telegraphs the fairness contract — a wind-up pose held 0.3–0.6 s that the player must read instantly. Unclamped auto-exposure re-meters whenever the camera swings past the sky or into shadow, so for half a second after a dodge the boss is crushed black or blown out — exactly when you need to read the next attack. A clamped band keeps scene values stable through every camera move; readability never depends on where the camera just came from.
   - **Bloom:** **Details -> Lens -> Bloom -> Intensity 0.3–0.4** (down from the 0.675 default), **Method = Standard** (Convolution bloom is a cost you don't need). Bloom should kiss highlights, not haze the silhouettes.
   - **Color grading:** leave a slot wired now so the look is one asset swap later — either a LUT in **Details -> Color Grading -> Misc -> Color Grading LUT**, or skip LUTs and use the global controls directly: **Color Grading -> Global -> Saturation ~0.95, Contrast ~1.05** is a safe "graded, not filtered" starting point.

## Indie art direction that reads well

The bar is cohesive, not lavish. A small consistent kit beats a large inconsistent one, and every choice defers to the same rule guide.md uses for animation: the fight must read instantly. The 60-seconds-muted test at the end of guide.md applies to art too — if a grayscale screenshot of the fight doesn't show two clear silhouettes on a calmer background, the art direction is failing at its one job.

**The style: stylized-realistic hybrid.** Realistic forms and lighting (Lumen does the heavy lifting), simplified materials — broader roughness zones, restrained albedo detail, no photo-noise. This style survives mixed asset sources (scans next to hand-made props) far better than pure realism does, which is exactly the situation an indie kit-bash is in.

- **Limited palette.** Three to four hue families total. Arena: desaturated neutrals (stone grey, cold brown). Hero: one accent hue. Boss: the contrasting accent — warm orange-red against a hero teal/cyan is the classic pairing for a reason. The boss's accent should also be the color of its telegraph VFX, so "danger" has one consistent hue.
- **Value contrast is the actual readability mechanism.** Keep the arena floor and walls in the mid-value range and push both characters lighter or darker than their backdrop. Check it: screenshot a fight, desaturate it, squint. Characters should pop with zero color information.
- **Trim sheets and tiling materials over unique textures.** One 2K trim sheet (edges, moldings, metal bands) plus two or three 2K tiling materials (floor, wall, dirt) can texture the entire arena inside the VRAM budget from the section above. Unique-texturing arena geometry is how 6 GB dies.
- **Decals for wear.** Place Actors -> drag a **Decal Actor** onto the floor: cracks, scorch marks, scuffed circles where the fight happens. Deferred decals are cheap, they break up tiling, and they let you art-direct the camera's most-stared-at surface (the floor) without touching the tiling material.

**Where to get assets:**

- **[Quixel Megascans on Fab](https://quixel.com/en-US/news/quixel-on-fab-new-megascans-and-megaplants)** (Epic Games Launcher -> Fab tab, or fab.com). Licensing changed: the free-for-Unreal era ended after 2024. Anything you claimed back then stays in your library; new Megascans are now individually priced or in Fab subscription tiers, with a rotating selection of free assets under the Fab Standard License — check the license line on each asset page before depending on it.
- **[Poly Haven](https://polyhaven.com)** — CC0, no strings. Excellent tiling textures and HDRIs.
- **[Kenney](https://kenney.nl)** — CC0. More stylized; good for UI and placeholder props.
- **Sketchfab** — filter by license explicitly (the downloadable filter + CC license facet). CC-BY requires visible credit; track it in a CREDITS file from day one, not at ship.

**Do / do not:**

- Do run every new asset through the palette: tint albedo toward your hue families in the material instance rather than using assets as-shipped.
- Do build one master material with instances (tint, roughness scale, detail normal) instead of unique materials per asset — consistency and shader-compile time both win.
- Do cap imported textures to 2K immediately (section above) before they bloat the DDC and the pool.
- Do not mix realism levels on the two characters — the hero and boss must look like the same game even if the arena is scrappier.
- Do not buy environment packs before blocking the arena in greybox and fighting in it; readability problems found after art is placed cost ten times more to fix.
- Do not use noisy detail normals everywhere — they shimmer under TSR at 80% screen percentage.

## Combat VFX on a budget

Niagara from templates gets you to "every hit visibly lands" in an afternoon. Create systems via **Content Browser right-click -> FX -> Niagara System**, then pick **New system from a template or behavior example** in the wizard (template names below are the 5.x set — the picker shows them with thumbnails).

**Template-to-effect map:**

- **Omnidirectional Burst** -> hit impacts. Sparks/chips bursting from the hit point. Cut spawn count to ~20–40; one short-lived burst reads better than a firework.
- **Directional Burst** -> directional impacts — parry sparks, block impacts, anything that should fly *away* from the contact normal.
- **Hanging Particulates** -> ambient arena dust motes in the light shafts. Set it and forget it; this is the single cheapest "the air has atmosphere" effect.
- **Fountain** -> the learning template, and a decent base for dust kicked up by the boss's heavy landings (gravity up, sprite size up, velocity down).
- **Slash trails** have no direct template: make an empty system, add an emitter with a **Ribbon Renderer**, and drive its position from the weapon. The simplest robust setup is attaching the system to the weapon socket and letting a **Timed Niagara Effect** notify state (below) own its lifetime across the swing.

**Spawning from montages** — this is the workflow that keeps VFX in sync with the existing combat timing:

- One-shot effects (whoosh dust at swing start): open the attack montage, right-click the **Notifies track -> Add Notify -> Play Niagara Particle Effect**, select the notify, and set the system, socket name, and offset in the **Details panel**.
- Duration effects (slash trail across the active window): right-click the **Notifies track -> Add Notify State -> Timed Niagara Effect** and stretch it over the swing frames — conveniently, roughly the same span as your `ANS_DealDamage` window.
- Hit impacts should not come from the montage at all: spawn them from the same code path that applies damage (`ANS_DealDamage` -> the target's `HitFeedbackComponent`), at the actual hit location, so the impact VFX inherits the one-hit-per-swing guard and never fires on a whiff.

**The translucency overdraw warning.** Particle sprites are translucent, and translucency cost scales with screen coverage times layer count. Ten large overlapping soft sprites can cost more than the entire Lumen pass. Check with **viewport View Mode dropdown (top-left, where it says "Lit") -> Optimization Viewmodes -> Shader Complexity**: green is fine, red means stacked overdraw. Fixes, in order: fewer particles, smaller particles, shorter lifetimes, and erosion-style opacity masks instead of big soft alpha fades. Keep impact effects under ~0.2 s — guide.md Phase 3.4 gets hit weight from hit stop and shake; VFX is garnish, not the meal.

**GPU vs CPU sim:** set per emitter in the **Emitter node -> Properties -> Sim Target**. Rule of thumb: CPU sim for the small combat one-shots (tens of particles, spawn-and-die, no readback issues), GPU sim for anything in the hundreds-to-thousands (ambient dust, debris showers). GPU emitters need **Fixed Bounds** set in the emitter properties (Calculate Bounds Mode = Fixed) or they can vanish when the camera moves. With two combatants and a handful of bursts per second, this project's VFX load is trivial — overdraw, not particle count, is the only way you'll hurt the frame.

## Scalability defaults to ship

Scalability is your coarse performance dial, and on this hardware the right answer is a custom mix, not a preset. Set it in-editor via the **Settings button at the top-right of the level editor toolbar -> Engine Scalability Settings**, verify frame times in a real fight (`stat unit`, per guide.md Phase 0 — GPU under ~14 ms with headroom), then bake the values into config so packaged builds and `-game` launches match what you tuned.

**Recommended mix for the 4050 at 1080p/60:**

| Group | Setting | Why |
|---|---|---|
| Resolution Scale | 80% | TSR upscales to 1080p; see renderer section |
| View Distance | High | One arena — this is nearly free |
| Anti-Aliasing | High | TSR quality tier |
| Post Processing | Medium–High | Epic adds DOF/motion-blur cost you won't see in combat |
| Shadows | **High, not Epic** | Epic raises VSM page counts/ray counts sharply; High is the knee of the curve |
| Global Illumination | High | Lumen at sensible internal resolution; Epic is the expensive step |
| Reflections | High | Lumen reflections, ditto |
| Textures | High | Actual memory is governed by `r.Streaming.PoolSize`, already set |
| Effects | Medium–High | Niagara/translucency quality |
| Foliage | Medium | Arena has little; don't pay for it |
| Shading | High | |

**Bake it in.** The scalability groups are `sg.` console variables (0 = Low, 1 = Medium, 2 = High, 3 = Epic, 4 = Cinematic; Resolution is a percentage). Put them in `Config/DefaultGameUserSettings.ini` so shipped builds start there but a future settings menu can still override per-user:

```ini
[ScalabilityGroups]
sg.ResolutionQuality=80
sg.ViewDistanceQuality=2
sg.AntiAliasingQuality=2
sg.PostProcessQuality=2
sg.ShadowQuality=2
sg.GlobalIlluminationQuality=2
sg.ReflectionQuality=2
sg.TextureQuality=2
sg.EffectsQuality=2
sg.FoliageQuality=1
sg.ShadingQuality=2
```

Two cautions: don't set `r.ScreenPercentage` in `[SystemSettings]` *and* `sg.ResolutionQuality` here — pick one owner for resolution (this file is the better one, since users can change it). And note that `Saved/Config/.../GameUserSettings.ini` on a machine that has already run the game overrides these defaults — delete the saved file when testing whether your baked values actually apply.

When a fight drops frames, change scalability groups one at a time and re-fight — same one-variable discipline as the guide.md Phase 8 tuning loop. Shadows and GI are the two groups that buy back the most milliseconds on this GPU; Resolution Scale is the third lever, and with TSR (or DLSS) in the chain it degrades the image far more gracefully than dropping either of the other two to Medium.

---

## Terrain: pick your pipeline

Yes — Blender is a perfectly good terrain tool for this project, and the whole pipeline is
below. Two routes exist, and the choice shapes everything after it:

| | **Pipeline A: heightmap -> UE Landscape** | **Pipeline B: sculpted mesh -> Nanite static mesh** |
|---|---|---|
| Authoring | sculpt in Blender, bake a heightmap, import | sculpt in Blender, export the mesh itself |
| Shape freedom | no overhangs (one height per XY point) | anything — cliffs, overhangs, broken edges |
| Texturing | UE landscape layer painting (grass/rock/dirt brushes) | triplanar material, optional vertex paint |
| Foliage / paint tools | full Landscape + Foliage tool support | Foliage mode still works on meshes |
| Collision | automatic | one setting (complex-as-simple) |
| Extra steps | the bake (camera, mist pass, compositor) | none — your sculpt is the asset |
| Best for | rolling open terrain, iterating in other tools | a contained, art-directed arena |

**Recommendation for this project: Pipeline B.** The game is one boss arena (~150–250 m of
playable space, not open world), you explicitly want to build it in Blender, and a mesh
keeps the entire authoring loop there — no heightmap bake, full freedom for the raised
border/cliff walls an arena wants, and Nanite eats the polygon cost on the 4050. Pipeline A
is documented in full anyway: it's the better route if the project ever grows rolling
terrain beyond the arena, and the bake technique is worth knowing.

Both pipelines assume Blender 4.x and start from the same sculpt, so read Pipeline B's
sculpting steps even if you choose A.

## Pipeline B (recommended): sculpted mesh arena -> Nanite

**Blender side:**

1. **Scale sanity first.** Keep Blender's default units (1 unit = 1 m) and model true to
   size — a 200 m arena is a 200 m mesh. Before anything else, export a default 2 m cube to
   FBX and import it into UE: it should measure 200 Unreal units against a pawn. If that
   round-trips correctly, all the scale questions are settled for the rest of the pipeline.
2. **Base mesh.** Shift+A -> Mesh -> Plane. Open the sidebar (N), set Dimensions to
   200 × 200 m. **Ctrl+A -> All Transforms** (never sculpt on an unapplied scale — brush
   behavior and the export both go wrong). Tab into Edit Mode, select all (A), right-click
   -> Subdivide, and repeat (or set Number of Cuts ~100) until the plane has a few tens of
   thousands of faces.
3. **Block the big shapes in Edit Mode before sculpting.** Turn on proportional editing (O),
   grab (G, then Z) regions to rough in the bowl, the raised rim, an entrance notch.
   Big-shape blocking with proportional edit is faster and cleaner than sculpting up from
   flat.
4. **Multiresolution modifier for sculpt detail.** Properties -> Modifiers (wrench icon) ->
   Add Modifier -> Generate -> **Multiresolution**, click Subdivide 3–4 times. Watch the
   vertex count in the viewport stats overlay — stay at or under ~5 M on 16 GB RAM (see the
   laptop section below). Multires lets you step levels down at any time, which Dyntopo
   doesn't.
5. **Sculpt.** Top-bar **Sculpting** workspace. The brushes that matter for terrain:
   **Draw** (raise; hold Ctrl to carve), **Clay Strips** (rocky buildup), **Flatten**
   (fight floors), **Crease** (gullies and cracks), **Smooth** (hold Shift with any brush).
   F = brush size, Shift+F = strength. Turn symmetry OFF for natural terrain (the butterfly
   icon / Symmetry panel in the header — X is on by default and mirrored terrain reads
   instantly fake).
6. **Sculpt to the gameplay contract, not just the look:**
   - The central fight floor (~30–40 m across) stays **near-flat** — root-motion combat and
     motion warping snag on bumpy ground, and Phase 2.3 of guide.md will blame the collision.
   - Border features read as walls: 45°+ slopes, height the camera can't accidentally look
     over from fight distance.
   - No thin floating shells or deep undercuts at the playable edge — they're collision pain
     for zero gameplay.
7. **Polygon budget.** With Nanite the mesh does NOT need decimating for runtime — keep
   1–2 M triangles and let Nanite handle it (fine on the 4050). Cap it there mostly for FBX
   export time and file size. If you want a lighter file anyway: Add Modifier -> Generate ->
   **Decimate** (Collapse), ratio until ~100–300k tris. Either way, apply the Multires at
   your chosen level before export (modifier dropdown -> Apply) or check "Apply Modifiers"
   in the exporter.
8. **Skip UVs.** Plan to use a world-aligned (triplanar) material in UE (step 13) and the
   terrain needs no UV unwrap at all — no seams, no stretching on slopes. Only if you insist
   on UV-mapped texturing: Edit Mode -> A -> UV menu -> Smart UV Project (Island Margin 0.02).
9. **Export.** Select the terrain object -> File -> Export -> FBX: check **Limit to
   Selected Objects**, check **Apply Modifiers** (Geometry tab), leave the Transform section
   at defaults — with transforms applied in step 2, the default Blender->FBX->UE unit
   handling imports at the correct size (your step-1 cube already proved it). If the mesh
   ever arrives rotated, fix rotation in Blender (Ctrl+A again) rather than fighting
   exporter axis settings.

**UE side:**

10. **Import.** Drag the FBX into the Content Browser. In the import dialog: this is a
    static mesh (no skeleton), check **Build Nanite**, uncheck **Generate Lightmap UVs**
    (the lighting rig above is all-dynamic), Import Uniform Scale 1.0. Drop it in the level
    and stand a pawn on it immediately — size check before anything else.
11. **Collision in one setting.** Double-click the mesh -> Static Mesh editor -> Details ->
    Collision -> **Collision Complexity = Use Complex Collision As Simple**. Why this is
    fine here: the arena is static scenery queried by character movement and traces — no
    dynamic rigid bodies need a convex hull, and Chaos handles complex-mesh queries for two
    pawns at this scale without measurable cost. (Never do this on movable or
    physics-simulated meshes.)
12. **Verify Nanite took.** Viewport View Mode dropdown -> Nanite Visualization ->
    Triangles — the arena should show Nanite's cluster coloring. Then `stat unit` while
    walking it; the Nanite base cost is already inside the renderer-section budget.
13. **Triplanar material — no UVs, no seams.** New Material `M_Terrain`: in the graph, use
    the **WorldAlignedTexture** material function for each texture (search the palette;
    pair with **WorldAlignedNormal** for normal maps), TextureSize around 200–500 (= one
    texture repeat per 2–5 m). Blend two sets — ground and rock — by slope: take
    **VertexNormalWS**, mask its Z (B channel) through a Power/Clamp, and **Lerp** ground
    over rock where the surface is flat. Steep slopes read as rock automatically, which is
    exactly what a sculpted arena wants. Optional third layer: Mesh Paint mode (Mode
    dropdown -> Mesh Paint) -> paint the Red vertex channel where the fight wears the
    ground, and Lerp a dirt set in with a **Vertex Color** node. All textures 2K per the
    VRAM budget above.

## Pipeline A: heightmap -> UE Landscape

Sculpt exactly as in Pipeline B steps 1–6, with one extra constraint: stay
**heightmap-legal** — no overhangs, since a heightmap stores one height per XY point.

**Baking the heightmap in Blender (top-down mist render):**

1. **Camera.** Shift+A -> Camera. Clear its rotation (Alt+R) — a zero-rotation Blender
   camera looks straight down −Z, which is exactly top-down. Center it over the terrain
   (match the plane's X/Y; Z comfortably above the highest peak, e.g. 100 m). In the camera
   data properties (green camera icon): **Lens -> Type = Orthographic**, **Orthographic
   Scale = 200** (the terrain's width in meters — the ortho scale is the visible extent).
2. **Mist pass.** View Layer Properties (stacked-images icon) -> Passes -> Data -> check
   **Mist**. Then World Properties (globe icon) -> **Mist Pass**: Start = camera height
   minus the terrain's highest point, Depth = the terrain's height range, Falloff =
   **Linear**. Worked example: camera at Z = 100, terrain spans 0–40 m -> Start = 60,
   Depth = 40. Mist now ramps 0 -> 1 across exactly your height range.
3. **Invert it in the compositor.** Mist measures distance *from the camera*, so peaks
   (near) come out dark and valleys (far) bright — backwards for a heightmap. Open the
   **Compositing** workspace, check **Use Nodes**, and wire: Render Layers (**Mist**
   output) -> **Invert Color** node (Shift+A -> Color) -> Composite (Image input).
4. **The silent killer: color management.** Render Properties -> Color Management ->
   **View Transform = Standard** (or Raw). The default AgX/Filmic transform tone-maps your
   data into mush and the terraced result looks fine in Blender but imports wrong. This one
   setting ruins more heightmap bakes than everything else combined.
5. **Render settings.** Eevee is fine for a mist pass (fast). Output Properties:
   **Resolution X = Y = 1009** (or 505 / 2017 — these are UE's recommended landscape sizes;
   they're (components × 63 quads) + 1 vertex grids, so the landscape divides into whole
   components). Render (F12), then in the render window: Image -> Save As -> **PNG, Color =
   BW, Color Depth = 16-bit**. 8-bit gives only 256 height steps — visible terracing; the
   16 bits are the entire point of the format.

**Importing in UE:**

6. **Landscape mode.** Viewport top-left mode dropdown (where it says "Select") ->
   **Landscape** (or Shift+2). In the Landscape panel: Manage tab -> New -> **Import from
   File** -> Heightmap File = your PNG. If it warns about the resolution, the render wasn't
   exactly 505/1009/2017 — re-render; don't let it resample.
7. **Layout.** Section Size = 63×63 quads, Sections Per Component = 1×1. A 1009 map becomes
   16×16 components (505 -> 8×8) — the right shape at this scale.
8. **Scale — the part everyone gets wrong.** X/Y Scale 100 means 1 m per quad, so a 1009
   map at scale 100 is ~1008 m across. For a ~250 m arena: render at 505 and set X/Y scale
   = 50 (≈ 252 m), or 1009 at scale 25. **Z Scale:** UE maps the full 16-bit range to 512 m
   of height at Z = 100 — i.e. *total height range in meters = 5.12 × ZScale*, so
   **ZScale = your range / 5.12**. The mist bake uses the full 16-bit range by construction
   (Depth = your range), so the worked example lands at: 40 m of relief -> Z = 40 / 5.12 ≈
   **7.8**. Import, then move the landscape's Z so the fight floor sits at world 0.
9. **Landscape material.** New Material `M_Landscape`: add a **LandscapeLayerBlend** node,
   add 3 layers (Grass / Rock / Dirt), Blend Type = **LB Weight Blend** on each; feed each
   from a 2K tiling texture set (Poly Haven / Megascans per the asset-sources section) with
   a **LandscapeLayerCoords** node controlling tiling. Duplicate the LayerBlend for the
   Normal output (same layer names). Assign: select the landscape -> Details -> Landscape ->
   Landscape Material.
10. **Layer Info objects, then paint.** Landscape mode -> **Paint** tab: each layer shows a
    warning icon -> click the **+** beside it -> **Weight-Blended Layer (Normal)** -> save
    the LayerInfo asset. The first layer floods as the base; then select Rock, set brush
    strength ~0.3, and paint slopes and rim; Dirt where the fight traffic flows. Low
    strength, multiple passes — heightmap painting rewards patience.
11. **Skip Runtime Virtual Textures** at this scope — RVT solves open-world landscape/object
    blending problems a single arena doesn't have, and it costs VRAM you do not have spare.

## Set dressing and bounds

1. **A small rock kit beats many uniques.** 5–8 rock/boulder sculpts (same Blender workflow,
   ~30 minutes each, Nanite on import) — or Megascans 3D rocks (mind the licensing note in
   the asset-sources section). Scatter them rotated and scaled; shared textures keep the
   VRAM bill flat no matter how many instances you place.
2. **Bounds are layered:** a *visual* wall (cliff rim, rocks, broken colonnade — whatever
   the sculpt established) plus a *gameplay* net: **Window -> Place Actors -> Volumes ->
   Blocking Volume**, scaled into a perimeter ring just inside the visual wall. Players will
   try to leave; the volume is the contract. Keep the playable boundary visually obvious —
   same readability rule as the art-direction section.
3. **Foliage, restrained.** Mode dropdown -> **Foliage** (Shift+3) -> + Foliage -> add a
   Static Mesh Foliage type per plant. On this GPU: sparse tufts and scrub only, low
   density (≈ 50–100 per 10 m² max), and in each foliage type's Details set **Cast Shadow = OFF**
   for grass — wind-animated (WPO) grass invalidates Virtual Shadow Map pages every frame,
   and the cost lands mid-fight (the renderer section's VSM fallback note is about exactly
   this). Sparse and shadowless ground cover reads fine at the indie bar.
4. **One landmark.** A single big silhouette element — broken statue, dead tree, monolith —
   off-center in the arena. Fights spin the camera constantly; players orient by landmark,
   and an arena without one feels like a treadmill.

## Blender on this laptop

1. **Sculpt ceiling: ~5 M verts comfortably,** 10 M with everything else closed. 16 GB of
   RAM is the limit, not the GPU — Windows plus a browser already holds 6+ GB. The viewport
   stats overlay (Overlays dropdown -> Statistics) keeps the count honest.
2. **Multires over Dyntopo for terrain, always:** non-destructive levels you can step down
   when RAM tightens, no topology surgery on what is fundamentally a heightfield, and the
   lower levels make posing big shapes cheap.
3. **Edit -> Preferences -> System: GPU Subdivision = on** (the 4050 is genuinely good
   here). While sculpting, keep the viewport in **Solid** shading — Material Preview/
   Rendered modes burn VRAM and add nothing to a sculpt session.
4. **Undo is the hidden RAM hog.** Sculpt-mode undo snapshots are large exactly when the
   mesh is large: drop **Edit -> Preferences -> System -> Undo Steps** to ~10 for heavy
   sessions, and save incrementally instead (**File -> Save Incremental**, Ctrl+Alt+S)
   before every major pass.
5. **Close UE while sculpting** — the visuals RAM-budget rule (pick two of Blender / UE /
   training) applies hardest here. Sculpt, export, then open UE.
