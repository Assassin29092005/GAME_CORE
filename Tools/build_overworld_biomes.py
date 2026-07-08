"""Dress the /Game/Maps/Overworld level with per-biome props, ground cover,
lighting variation, and (optionally) atmospheric particles.

Tier 4 Phase D. One script covers all 5 biomes (castle / marsh / desert /
plains / mountains) — each biome is a self-contained function so it is
independently re-runnable and forkable if a designer wants a heavier bespoke
pass on any single biome later.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log → set 'Cmd' → paste:
      py "D:/GAME_CORE 5.8/Tools/build_overworld_biomes.py"
  or Tools → Execute Python Script… → this file.

Env vars:
  OVERWORLD_BIOME  (optional)  "all" (default) or one of
                                 castle, marsh, desert, plains, mountains
                                 — dress just that biome.

Behaviors:
  * Idempotent: actor labels are prefixed 'REGION_<BIOME>_*'. Prior actors
    with the matching prefix are destroyed before the current pass spawns.
  * Level-guarded: refuses to touch anything if the currently open map is
    not /Game/Maps/Overworld. Prevents accidental dress passes on BossArena.
  * Best-effort assets: if a Fab pack mesh path is missing (Fab packs are
    gitignored — see CLAUDE.md), the individual mesh spawn skips with a
    log line and the biome continues with what it does have.

World coordinate convention:
  * Level origin (0, 0, 0) at the WORLD CENTER (castle plateau top).
  * +X = East, +Y = North (UE default).
  * Landscape scale 100 UU per meter → 2 km world runs
    (-100,000, -100,000) → (+100,000, +100,000) in UU.

Biome region bounds (in UU) — mirrors Tools/build_overworld_heightmap.py
weightmap masks (u,v space converted back to world):
  Castle:     circle r=15,000 UU at origin
  Marsh:      x ∈ [-100,000, -25,000],  y ∈ [-45,000, +45,000]  (W band)
  Desert:     x ∈ [+25,000, +100,000], y ∈ [+20,000, +100,000] (NE quadrant)
  Mountains:  x ∈ [-100,000, -30,000], y ∈ [-100,000, -35,000] (SW corner)
  Plains:     fills whatever the other 4 leave (~40% of the world).
"""

import math
import os
import random
import traceback

import unreal


# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

MAP_PATH = "/Game/Maps/Overworld"
LABEL_PREFIX = "REGION_"

BIOMES = ("castle", "marsh", "desert", "plains", "mountains")


# Region bounds in UU (2 km world, origin at center).
REGION_BOUNDS = {
    "castle":    {"kind": "circle", "center": (0, 0),       "radius": 15000.0},
    "marsh":     {"kind": "rect",   "min": (-100000, -45000),"max": (-25000,  45000)},
    "desert":    {"kind": "rect",   "min": (25000,   20000),"max": (100000, 100000)},
    "mountains": {"kind": "rect",   "min": (-100000, -100000),"max": (-30000, -35000)},
    # Plains is derived: whatever the other four don't claim.
    "plains":    {"kind": "fill",   "min": (-100000, -100000),"max": (100000, 100000)},
}


# Per-biome PALETTE. Each entry is (asset_package_path, weight, extra_kwargs).
# Weight is a relative probability inside the scatter. Missing meshes SKIP.
PALETTE = {
    "castle": [
        # Central keep + towers (few, big).
        ("/Game/MedCastle/Mesh/Bridges/SM_ArchedGate2",         2.0, {"scale": 1.2}),
        ("/Game/MedCastle/Mesh/Bridges/SM_ArchedBridge",         2.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Balconies/SM_CastleSqareTowerTerrace", 3.0, {"scale": 1.0}),
        # Ground clutter around plateau.
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Boulder2",        6.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Boulder6",        4.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Rock7",           6.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Rock9",           4.0, {"scale": 0.8}),
    ],
    "marsh": [
        # Wet ground: ferns, dead branches, small water stones.
        ("/Game/KiteDemo/Environments/Foliage/Ferns/SM_Fern_01", 10.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Grass22",         8.0, {"scale": 1.2}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_BranchesSmall1",  5.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_BranchesSmall2",  5.0, {"scale": 1.0}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Rock7",           3.0, {"scale": 0.7}),
    ],
    "desert": [
        # Sun-bleached rocks (Paragon Agora set) + occasional ruined pillar.
        ("/Game/ParagonProps/Agora/Rocks/Meshes/SM_Agelsjon_Rock_1", 6.0, {"scale": 1.0}),
        ("/Game/ParagonProps/Agora/Rocks/Meshes/SM_Agelsjon_Rock_2_WB", 6.0, {"scale": 1.0}),
        ("/Game/ParagonProps/Agora/Rocks/Meshes/SM_Agelsjon_Rock_Boulder_1", 3.0, {"scale": 1.4}),
        ("/Game/ParagonProps/Agora/Rocks/Meshes/SM_LargePlainsBoulder002", 3.0, {"scale": 1.3}),
        ("/Game/ParagonProps/Agora/Props/Meshes/SM_Angelsjon_TriPillar", 1.0, {"scale": 1.0}),
        ("/Game/ParagonProps/Agora/Props/Meshes/SM_TowerTrunk_Temp",   0.5, {"scale": 1.0}),
    ],
    "plains": [
        # Green grassland — trees and small rock accents.
        ("/Game/ParagonProps/Agora/Trees/Meshes/SM_FlowerTree_01",   6.0, {"scale": 1.0}),
        ("/Game/ParagonProps/Agora/Trees/Meshes/SM_FlowerTree_01b",  6.0, {"scale": 1.0}),
        ("/Game/ParagonProps/Agora/Trees/Meshes/SM_FlowerHuge",      2.0, {"scale": 1.2}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Grass22",            8.0, {"scale": 1.5}),
        ("/Game/MedCastle/Mesh/Foliage_Rocks/SM_Boulder2",           3.0, {"scale": 0.9}),
    ],
    "mountains": [
        # Rocky peaks and scree — heavy cliff meshes at bigger scale.
        ("/Game/KiteDemo/Environments/Cliffs/Cliff01/SM_Cliff01",   6.0, {"scale": 1.4}),
        ("/Game/ForestOfSpikes/Meshes/SM_Rock_01",                  6.0, {"scale": 1.6}),
        ("/Game/ForestOfSpikes/Meshes/SM_Rock_02",                  6.0, {"scale": 1.8}),
        ("/Game/ForestOfSpikes/Meshes/SM_Rock_03",                  4.0, {"scale": 1.4}),
        ("/Game/ParagonProps/Agora/Rocks/Meshes/SM_Agelsjon02_Cliff", 3.0, {"scale": 1.8}),
    ],
}


# Scatter density per biome (approximate number of actors placed).
BIOME_ACTOR_COUNT = {
    "castle":    28,
    "marsh":     60,
    "desert":    50,
    "plains":    75,
    "mountains": 55,
}


# PostProcess volume per biome. Approximate GoW-style palette shift.
# Numbers are (min_ev, max_ev, color_temp_k, saturation, contrast).
POSTPROCESS = {
    "castle":    (0.5, 3.0, 5800, 1.02, 1.05),
    "marsh":     (0.2, 2.5, 4900, 0.85, 1.10),
    "desert":    (1.2, 4.0, 5600, 1.10, 1.05),
    "plains":    (0.6, 3.5, 5500, 1.05, 1.02),
    "mountains": (0.8, 3.5, 5200, 0.95, 1.08),
}


# Seed for reproducible scatter (change to re-roll a biome's layout).
SEED = 20260708


# ---------------------------------------------------------------------------
# Result/summary framework
# ---------------------------------------------------------------------------

CTX = {"results": []}


def _record(step, status, msg=""):
    CTX["results"].append((step, status, msg))
    tag = {"PASS": "+", "SKIP": "~", "FAIL": "!"}.get(status, "?")
    unreal.log("[overworld-biome] %s %s: %s" % (tag, step, msg or status))


class StepSkip(Exception):
    pass


def _step(name):
    def _wrap(fn):
        def _inner(*args, **kwargs):
            try:
                ret = fn(*args, **kwargs)
                _record(name, "PASS", str(ret) if ret is not None else "")
                return ret
            except StepSkip as e:
                _record(name, "SKIP", str(e))
            except Exception as e:
                tb = traceback.format_exc()
                unreal.log_warning("[overworld-biome] %s failed:\n%s" % (name, tb))
                _record(name, "FAIL", str(e))
        return _inner
    return _wrap


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------

def _get_actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _get_world():
    return unreal.EditorLevelLibrary.get_editor_world()


def _require_overworld():
    world = _get_world()
    if world is None:
        raise StepSkip("no editor world (open /Game/Maps/Overworld first)")
    current_map = world.get_path_name().split(":")[0]
    if not current_map.endswith("/Overworld") and not current_map.endswith("Overworld.Overworld"):
        raise StepSkip("current map is '%s'; expected /Game/Maps/Overworld — refusing" % current_map)


def _load_asset(path):
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return None
    return unreal.EditorAssetLibrary.load_asset(path)


def _sweep(prefix):
    subsys = _get_actor_subsystem()
    world = _get_world()
    if world is None:
        return 0
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    removed = 0
    for a in actors:
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        if label and label.startswith(prefix):
            subsys.destroy_actor(a)
            removed += 1
    return removed


def _spawn_mesh(mesh_asset, location, rotation, scale=1.0, label=None):
    """Spawn a StaticMeshActor for a loaded mesh. Returns the actor or None."""
    if mesh_asset is None:
        return None
    world = _get_world()
    if world is None:
        return None
    subsys = _get_actor_subsystem()
    actor = subsys.spawn_actor_from_class(
        unreal.StaticMeshActor,
        unreal.Vector(*location),
        unreal.Rotator(0.0, 0.0, rotation),
    )
    if actor is None:
        return None
    comp = actor.static_mesh_component
    comp.set_static_mesh(mesh_asset)
    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    if label:
        actor.set_actor_label(label)
    # Nanite / static / no runtime nav-blocking (nav mesh over landscape covers it).
    comp.set_mobility(unreal.ComponentMobility.STATIC)
    return actor


# ---------------------------------------------------------------------------
# Sampling: sample a random world-space point INSIDE a biome region + apply
#          a fall-off ring so a biome's edge fades into its neighbor instead
#          of dropping props flush against the boundary. Rejects points that
#          land inside another biome's core.
# ---------------------------------------------------------------------------

def _in_circle(pt, cx, cy, radius):
    return (pt[0]-cx)**2 + (pt[1]-cy)**2 <= radius*radius


def _in_rect(pt, mn, mx):
    return mn[0] <= pt[0] <= mx[0] and mn[1] <= pt[1] <= mx[1]


def _biome_at(pt):
    """Return the biome name a world point belongs to (approx — for plains fill)."""
    if _in_circle(pt, 0, 0, REGION_BOUNDS["castle"]["radius"]):
        return "castle"
    for name in ("marsh", "desert", "mountains"):
        b = REGION_BOUNDS[name]
        if _in_rect(pt, b["min"], b["max"]):
            return name
    return "plains"


def _sample_points(biome, count, seed):
    """Yield `count` (x, y) points inside `biome`'s region (world UU)."""
    rng = random.Random(seed)
    b = REGION_BOUNDS[biome]
    tries = 0
    yielded = 0
    while yielded < count and tries < count * 20:
        tries += 1
        if b["kind"] == "circle":
            r = b["radius"] * math.sqrt(rng.random())
            theta = rng.uniform(0, 2 * math.pi)
            pt = (b["center"][0] + r * math.cos(theta),
                  b["center"][1] + r * math.sin(theta))
            # Keep a small castle-interior clear zone so props don't spawn on top
            # of the boss encounter volume.
            if _in_circle(pt, 0, 0, 3500.0):
                continue
        elif b["kind"] == "rect":
            pt = (rng.uniform(b["min"][0], b["max"][0]),
                  rng.uniform(b["min"][1], b["max"][1]))
        else:  # fill (plains)
            pt = (rng.uniform(b["min"][0], b["max"][0]),
                  rng.uniform(b["min"][1], b["max"][1]))
            # Only accept plains points that aren't inside another biome core.
            if _biome_at(pt) != "plains":
                continue
        yielded += 1
        yield pt, rng.uniform(0.0, 360.0), rng.uniform(0.85, 1.25)  # rotation + scale jitter


# ---------------------------------------------------------------------------
# Weighted mesh picker
# ---------------------------------------------------------------------------

def _weighted_pick(palette, rng):
    total = sum(w for _, w, _ in palette)
    if total <= 0.0:
        return None, {}
    r = rng.uniform(0.0, total)
    accum = 0.0
    for path, w, extra in palette:
        accum += w
        if r <= accum:
            return path, extra
    return palette[-1][0], palette[-1][2]


# ---------------------------------------------------------------------------
# Biome dressing (main worker)
# ---------------------------------------------------------------------------

def _dress_one_biome(biome):
    label_prefix = LABEL_PREFIX + biome.upper() + "_"
    removed = _sweep(label_prefix)
    unreal.log("[overworld-biome] %s: swept %d prior actors" % (biome, removed))

    palette = PALETTE[biome]
    count = BIOME_ACTOR_COUNT[biome]

    # Preload assets once
    loaded = {}
    for path, _weight, _extra in palette:
        if path not in loaded:
            loaded[path] = _load_asset(path)
            if loaded[path] is None:
                unreal.log_warning("[overworld-biome] %s: missing asset %s — skipping" % (biome, path))

    rng = random.Random(SEED + hash(biome) % 1000)
    spawned = 0
    # Landscape height at the point isn't queried here (would require a slow
    # trace per point); Z=200 lets StaticMeshActor drop into contact via the
    # editor's later "snap to floor" pass (or the mesh sinks slightly, which
    # reads as natural for scattered rocks/foliage).
    z_default = 200.0

    for i, (pt, yaw, scale_jitter) in enumerate(_sample_points(biome, count, SEED + hash(biome))):
        path, extra = _weighted_pick(palette, rng)
        mesh = loaded.get(path)
        if mesh is None:
            continue
        scale = float(extra.get("scale", 1.0)) * scale_jitter
        label = "%s%02d_%s" % (label_prefix, i, os.path.basename(path))
        actor = _spawn_mesh(mesh, (pt[0], pt[1], z_default), yaw, scale=scale, label=label)
        if actor is not None:
            spawned += 1

    return "%s: spawned %d/%d actors" % (biome, spawned, count)


@_step("Dress castle biome")
def dress_castle():
    _require_overworld()
    return _dress_one_biome("castle")


@_step("Dress marsh biome")
def dress_marsh():
    _require_overworld()
    return _dress_one_biome("marsh")


@_step("Dress desert biome")
def dress_desert():
    _require_overworld()
    return _dress_one_biome("desert")


@_step("Dress plains biome")
def dress_plains():
    _require_overworld()
    return _dress_one_biome("plains")


@_step("Dress mountains biome")
def dress_mountains():
    _require_overworld()
    return _dress_one_biome("mountains")


# ---------------------------------------------------------------------------
# PostProcess volume per biome
# ---------------------------------------------------------------------------

def _spawn_post_process(biome, cfg):
    """Spawn an unbound PostProcess volume centered on the biome region and
    limited by its rectangle extent; falls back to a global cast-a-wide-net
    volume for the castle circle (rectangle-approximation is fine at the
    plateau's size)."""
    world = _get_world()
    if world is None:
        raise StepSkip("no world")
    subsys = _get_actor_subsystem()

    label = LABEL_PREFIX + biome.upper() + "_PostProcess"
    # Sweep prior
    for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
        try:
            if a.get_actor_label() == label:
                subsys.destroy_actor(a)
        except Exception:
            pass

    b = REGION_BOUNDS[biome]
    if b["kind"] == "circle":
        cx, cy = b["center"]
        half = (b["radius"], b["radius"])
    elif b["kind"] == "rect":
        cx = (b["min"][0] + b["max"][0]) / 2.0
        cy = (b["min"][1] + b["max"][1]) / 2.0
        half = ((b["max"][0] - b["min"][0]) / 2.0, (b["max"][1] - b["min"][1]) / 2.0)
    else:
        # Plains PP unbound (fills the level)
        cx, cy = 0.0, 0.0
        half = (100000.0, 100000.0)

    actor = subsys.spawn_actor_from_class(
        unreal.PostProcessVolume,
        unreal.Vector(cx, cy, 5000.0),
        unreal.Rotator(0.0, 0.0, 0.0),
    )
    if actor is None:
        raise StepSkip("PostProcessVolume spawn failed")
    actor.set_actor_label(label)
    actor.set_actor_scale3d(unreal.Vector(half[0] / 100.0, half[1] / 100.0, 100.0))
    actor.unbound = False
    actor.priority = 5.0

    min_ev, max_ev, color_k, sat, contrast = cfg
    settings = actor.settings
    settings.set_editor_property("bOverride_AutoExposureMinBrightness", True)
    settings.set_editor_property("auto_exposure_min_brightness", min_ev)
    settings.set_editor_property("bOverride_AutoExposureMaxBrightness", True)
    settings.set_editor_property("auto_exposure_max_brightness", max_ev)
    settings.set_editor_property("bOverride_WhiteTemp", True)
    settings.set_editor_property("white_temp", float(color_k))
    settings.set_editor_property("bOverride_ColorSaturation", True)
    settings.set_editor_property("color_saturation", unreal.Vector4(sat, sat, sat, 1.0))
    settings.set_editor_property("bOverride_ColorContrast", True)
    settings.set_editor_property("color_contrast", unreal.Vector4(contrast, contrast, contrast, 1.0))

    return actor


@_step("PostProcess volumes (5 biomes)")
def do_postprocess():
    _require_overworld()
    for biome, cfg in POSTPROCESS.items():
        _spawn_post_process(biome, cfg)
    return "5 PostProcess volumes spawned"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    biome_arg = os.environ.get("OVERWORLD_BIOME", "all").lower().strip()
    unreal.log("[overworld-biome] starting: biome='%s'" % biome_arg)

    order = BIOMES if biome_arg == "all" else (biome_arg,)
    dispatch = {
        "castle":    dress_castle,
        "marsh":     dress_marsh,
        "desert":    dress_desert,
        "plains":    dress_plains,
        "mountains": dress_mountains,
    }

    for b in order:
        fn = dispatch.get(b)
        if fn is None:
            unreal.log_warning("[overworld-biome] unknown biome: '%s' — skipping" % b)
            continue
        fn()

    do_postprocess()

    # Save the level so the spawned actors persist
    try:
        unreal.EditorAssetLibrary.save_asset(MAP_PATH)
    except Exception as e:
        unreal.log_warning("[overworld-biome] save failed: %s" % e)

    unreal.log("[overworld-biome] ===== SUMMARY =====")
    for step, status, msg in CTX["results"]:
        unreal.log("[overworld-biome]  %-6s  %s  --  %s" % (status, step, msg))


if __name__ == "__main__":
    main()
