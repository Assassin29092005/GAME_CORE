"""One-shot fix pass for the Overworld level (Tier 4).

Fixes three things the user hits after landscape + biomes are in place:
  1. PlayerStart is missing or at a wrong height — the hero falls off the
     edge / into the void on PIE.
  2. Dressing actors (REGION_*) spawned at a hard-coded Z=200 UU may be
     below the actual landscape surface for that XY — buries them.
  3. Diagnostic: verify a Landscape actor + its collision components exist;
     log the plateau-top and world-origin Z for sanity.

Run INSIDE the UE editor (level must be /Game/Maps/Overworld):
  py "D:/GAME_CORE 5.8/Tools/fix_overworld_playerstart.py"
"""

import os
import traceback

import unreal


MAP_PATH = "/Game/Maps/Overworld"
LABEL_PREFIX = "REGION_"
PLAYER_START_LABEL = "OVERWORLD_PlayerStart"

# Castle plateau roughly centered at world origin. Z=3500 is safe: high enough
# above plateau top (~+3000 UU) that spawn doesn't punch through collision, low
# enough that the fall onto plateau is < 1 s (fun-feel + no glitch potential).
PLAYER_START_LOCATION = unreal.Vector(0.0, 0.0, 3500.0)
PLAYER_START_ROTATION = unreal.Rotator(0.0, 0.0, 0.0)

# Line-trace start height for the snap-to-floor pass. 100 km above origin is
# safely above the tallest possible mountain peak.
TRACE_START_Z = 100000.0
# Trace goes down to this Z. Landscape bottom is around -15000; -50000 is safe.
TRACE_END_Z = -50000.0
# Vertical offset above hit point so meshes sit lightly on terrain, not sunk.
SNAP_OFFSET_Z = 5.0


CTX = {"results": []}


def _record(step, status, msg=""):
    CTX["results"].append((step, status, msg))
    tag = {"PASS": "+", "SKIP": "~", "FAIL": "!"}.get(status, "?")
    unreal.log("[fix-overworld] %s %s: %s" % (tag, step, msg or status))


class StepSkip(Exception):
    pass


def _step(name):
    def _wrap(fn):
        def _inner(*a, **k):
            try:
                r = fn(*a, **k)
                _record(name, "PASS", str(r) if r is not None else "")
                return r
            except StepSkip as e:
                _record(name, "SKIP", str(e))
            except Exception as e:
                unreal.log_warning("[fix-overworld] %s failed:\n%s" % (name, traceback.format_exc()))
                _record(name, "FAIL", str(e))
        return _inner
    return _wrap


def _get_world():
    return unreal.EditorLevelLibrary.get_editor_world()


def _require_overworld():
    world = _get_world()
    if world is None:
        raise StepSkip("no editor world open")
    current = world.get_path_name().split(":")[0]
    if not current.endswith("Overworld") and not current.endswith("Overworld.Overworld"):
        raise StepSkip("current map is '%s'; expected /Game/Maps/Overworld" % current)


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


# ---------------------------------------------------------------------------
# 1. PlayerStart — remove any existing (avoid duplicates), spawn a fresh one
#    at the safe location above castle plateau.
# ---------------------------------------------------------------------------

@_step("1. PlayerStart placed at (0, 0, 3500)")
def step_1_player_start():
    _require_overworld()
    world = _get_world()
    subsys = _actor_subsystem()

    # Sweep any existing PlayerStart. We want ONE, in a known good spot.
    existing = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PlayerStart)
    for a in existing:
        subsys.destroy_actor(a)

    actor = subsys.spawn_actor_from_class(
        unreal.PlayerStart, PLAYER_START_LOCATION, PLAYER_START_ROTATION)
    if actor is None:
        raise StepSkip("spawn_actor_from_class returned None")
    actor.set_actor_label(PLAYER_START_LABEL)
    return "removed %d prior, spawned 1 at %s" % (len(existing), PLAYER_START_LOCATION)


# ---------------------------------------------------------------------------
# 2. Snap dressing actors to landscape surface. Every REGION_* StaticMeshActor
#    was spawned at hard-coded Z=200 UU by build_overworld_biomes.py — some
#    end up buried, others floating. Line-trace down from way above and place
#    each actor at the hit point (+ small offset so meshes sit lightly).
# ---------------------------------------------------------------------------

def _trace_down(world, xy):
    """Return world Z of the landscape hit at (x, y), or None if none."""
    start = unreal.Vector(xy[0], xy[1], TRACE_START_Z)
    end = unreal.Vector(xy[0], xy[1], TRACE_END_Z)
    # Use a static-collision line trace against WorldStatic. Landscape components
    # are on that channel by default.
    hit = unreal.SystemLibrary.line_trace_single(
        world,
        start,
        end,
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,  # Visibility
        False,
        [],
        unreal.DrawDebugTrace.NONE,
        True,
        unreal.LinearColor.RED,
        unreal.LinearColor.GREEN,
        5.0,
    )
    if hit:
        return hit.impact_point.z
    return None


@_step("2. Snap REGION_* dressing actors to landscape")
def step_2_snap_to_floor():
    _require_overworld()
    world = _get_world()

    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
    targeted = [a for a in actors if a and a.get_actor_label().startswith(LABEL_PREFIX)]
    if not targeted:
        raise StepSkip("no REGION_* actors found — run build_overworld_biomes.py first")

    snapped = 0
    missed = 0
    for a in targeted:
        loc = a.get_actor_location()
        hit_z = _trace_down(world, (loc.x, loc.y))
        if hit_z is None:
            missed += 1
            continue
        a.set_actor_location(
            unreal.Vector(loc.x, loc.y, hit_z + SNAP_OFFSET_Z),
            False,  # bSweep
            False,  # bTeleport
        )
        snapped += 1

    return "snapped %d / %d actors (misses = %d — likely outside landscape XY bounds)" % (
        snapped, len(targeted), missed)


# ---------------------------------------------------------------------------
# 3. Diagnostic: confirm landscape + collision are present, log plateau Z so
#    the user can see the world height range.
# ---------------------------------------------------------------------------

@_step("3. Diagnostic — landscape + collision + plateau Z")
def step_3_diagnostic():
    _require_overworld()
    world = _get_world()

    landscapes = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Landscape)
    if not landscapes:
        # Try proxy (World Partition splits it)
        proxies = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.LandscapeProxy)
        landscapes = proxies
    if not landscapes:
        raise StepSkip("no Landscape / LandscapeProxy in this world — landscape import didn't complete")

    landscape = landscapes[0]

    # Trace at world origin (castle plateau top) so user sees the actual Z.
    plateau_z = _trace_down(world, (0.0, 0.0))
    if plateau_z is None:
        return ("landscape '%s' present (%d proxies), but trace at (0,0) missed "
                "— landscape collision may not be built. Landscape Mode -> Manage -> Rebuild."
                % (landscape.get_name(), len(landscapes)))
    return "landscape '%s' present (%d proxies), plateau Z at (0,0) = %.1f UU (%.1f m)" % (
        landscape.get_name(), len(landscapes), plateau_z, plateau_z / 100.0)


# ---------------------------------------------------------------------------
# 4. Save the level.
# ---------------------------------------------------------------------------

@_step("4. Save Overworld level")
def step_4_save():
    _require_overworld()
    try:
        unreal.EditorAssetLibrary.save_asset(MAP_PATH)
    except Exception as e:
        raise StepSkip("save_asset failed: %s" % e)
    return "saved"


def main():
    unreal.log("[fix-overworld] running fix pass...")
    step_1_player_start()
    step_2_snap_to_floor()
    step_3_diagnostic()
    step_4_save()

    unreal.log("[fix-overworld] ===== SUMMARY =====")
    for step, status, msg in CTX["results"]:
        unreal.log("[fix-overworld]  %-6s  %s  --  %s" % (status, step, msg))
    unreal.log("[fix-overworld] Now press PLAY. Hero drops onto castle plateau.")


if __name__ == "__main__":
    main()
