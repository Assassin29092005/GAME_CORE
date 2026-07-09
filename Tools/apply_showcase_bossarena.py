"""Apply the BOSSARENA SHOWCASE pass — minimalist arena + RL-visibility palette.

Goal: turn the shipping BossArena into a stripped-down "showcase" surface that
frames the fight and makes the RL brain the visual subject. Reversible in one
env-flag flip; never destroys the 508 ARENA_DRESS_* actors that dress_arena.py
placed.

Run headlessly (the same proven pattern the other arena scripts use — editor
Python crashes this machine mid-batch):
  UnrealEditor-Cmd.exe "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/apply_showcase_bossarena.py"

Env flags:
  SHOWCASE_MODE = on  (default) — apply the pass (hide dress, spawn monoliths,
                      swap post-process to the crushed-blacks / gold-rim look).
                = off           — revert: unhide dress actors, destroy showcase
                      landmarks, restore post-process, save. Ships-clean arena.

Level guard: refuses to touch anything unless the open level is
/Game/Maps/BossArena. Same guard the other tools use.

Design (why it's non-destructive):
  * The 508 dress actors REPRESENT weeks of tuning. Destroying them would make
    the pass a one-way door. Instead we flip bIsHiddenInGame + the editor
    "temporary hidden" flag — one bool round-trip to restore.
  * Post-process settings are captured on first apply into a JSON sidecar
    (Saved/ShowcaseBackup/*.json) — SHOWCASE_MODE=off reads that and restores.
    Missing sidecar → we log LOAD SKIP and leave PP untouched (safer than
    guessing at the shipping numbers).
  * Showcase landmarks (4 obsidian monoliths at N/E/S/W) are labeled
    ARENA_SHOWCASE_* — a family only this script ever writes, so a re-run or
    revert can clean them independently of everything else.

Perf: the pass REMOVES draw calls (hides ~500 static-mesh actors) and adds
~4 large Nanite-friendly meshes. Net GPU cost is strictly negative on the 4050.

What it does NOT touch (leave alone; other tools own them):
  * ARENA_KeyLight / ARENA_SkyAtmosphere / ARENA_SkyLight / ARENA_HeightFog —
    dress_arena.py owns the atmosphere numbers.
  * ARENA_AAA_* volumetric-cloud + point-light rig — cinematic_pass.py owns.
  * ARENA_AAA_FX_* particles — ambient_particles.py owns.
  * The floor ring, backdrop, gate assembly — required for combat / motion
    warping / boss faux-arena silhouette.
"""

import json
import math
import os
import time
import traceback

import unreal


TAG = "[Showcase]"
LABEL_PREFIX = "ARENA_SHOWCASE_"
DRESS_PREFIX = "ARENA_DRESS_"
MAP_PATH = "/Game/Maps/BossArena"

# Dress actors that must stay visible in showcase mode: hiding them turns the
# arena into a void. These labels come from dress_arena.py step 3
# (_place_blender_mesh with LABEL_PREFIX + suffix — the FLOORRING is a root-
# motion contract; the BACKDROP is the horizon silhouette).
DRESS_WHITELIST_SUFFIXES = ("FLOORRING", "BACKDROP")

BACKUP_DIR = r"D:\GAME_CORE 5.8\Saved\ShowcaseBackup"
BACKUP_FILE = os.path.join(BACKUP_DIR, "postprocess_baseline.json")

# Monolith placements — cardinal N/E/S/W at rim radius, tall enough to read as
# spatial anchors from the arena floor. Rotation aims each away from center.
MONOLITH_R = 6400.0
MONOLITH_Z = 20.0                     # sunk slightly so base kisses ground
MONOLITH_SCALE = 3.5                  # 3.5× stock spire; still under RIM_R walls
MONOLITH_MESHES = [
    # Any one of these works; picked in order of preference. Missing → next.
    # Pillar meshes FIRST — Dusk_Spire_Back is a building-scale backdrop panel
    # whose collision hull at 3.5x covered the whole fight floor; both pawns
    # spawned inside it and depenetration pushed them through the ground (the
    # "endless falling" bug). It stays only as a last-resort visual.
    "/Game/ParagonProps/Monolith/Dusk/Meshes/Dusk_Spire_Gate_Pillar_A",
    "/Game/ParagonProps/Monolith/Dusk/Meshes/Dusk_Spire_Gate_Pillar_B",
    "/Game/ParagonProps/Monolith/Dusk/Meshes/Evil_Stair_Pillar",
    "/Game/ParagonProps/Monolith/Dusk/Meshes/Dusk_Spire_Back",
]
MONOLITH_CARDINALS = [
    ("N", 0.0,             +MONOLITH_R, 180.0),
    ("E", +MONOLITH_R,      0.0,        270.0),
    ("S", 0.0,             -MONOLITH_R,   0.0),
    ("W", -MONOLITH_R,      0.0,         90.0),
]

# Post-process showcase settings (applied to ARENA_PostProcess actor).
# All values in linear space unless noted; every field is set alongside its
# override_* sibling per the FPostProcessSettings struct contract.
#
# Design goal: crushed blacks, cool blue-black shadows, warm gold key highlight
# (the boss under key light reads as the focal point), tighter vignette,
# stronger sharpening — all no-cost look changes, no new render features.
SHOWCASE_PP = {
    # Exposure: KEEP auto exposure — the shipping arena runs under the ashen
    # dusk key light, and any manual override starves the scene. The bias
    # nudges the metered target slightly darker so the palette shift below has
    # room to work. The min/max targets keep auto exposure from either
    # crushing dark corners to void (0.35 shipping default) or blowing out
    # highlights (0.85 shipping default) — same numbers, restated explicitly
    # so a stale prior-run manual-exposure lock is overwritten.
    "auto_exposure_method": unreal.AutoExposureMethod.AEM_HISTOGRAM,
    "auto_exposure_min_brightness": 0.35,
    "auto_exposure_max_brightness": 0.85,
    "auto_exposure_bias": -0.25,               # subtle duskier baseline
    # Bloom (subtle, keeps the key light glow but doesn't wash)
    "bloom_intensity": 0.55,
    # Vignette (moderate — pulls eye to center without going tunnel-vision)
    "vignette_intensity": 0.45,
    # Chromatic fringe (very subtle, cinematic feel)
    "scene_fringe_intensity": 0.25,
    # Film grain (light, adds motion texture)
    "film_grain_intensity": 0.10,
    # Global saturation (slight desat, everything reads cinematic)
    "color_saturation": unreal.Vector4(0.92, 0.92, 0.92, 1.0),
    # Gamma (moderate lift on midtones; NOT the crushed >1 that killed the frame)
    "color_gamma": unreal.Vector4(0.98, 0.98, 1.00, 1.0),
    # Gain (cool highlights, warm midtones = "gold on cold" look)
    "color_gain": unreal.Vector4(0.98, 1.00, 1.05, 1.0),
    # Offset (nudges shadows toward cool blue)
    "color_offset": unreal.Vector4(-0.003, -0.001, +0.006, 0.0),
    # Contrast (punchy but not clip-hostile)
    "color_contrast": unreal.Vector4(1.06, 1.06, 1.06, 1.0),
}

# Fields we serialize/backup so revert is faithful.
BACKUP_FIELDS = list(SHOWCASE_PP.keys())


# ---------------------------------------------------------------------------
# Step framework (matches dress_arena.py / cinematic_pass.py conventions)
# ---------------------------------------------------------------------------

CTX = {"results": [], "changes": 0}


def _record(step, status, msg=""):
    CTX["results"].append((step, status, msg))
    tag = {"PASS": "+", "SKIP": "~", "FAIL": "!"}.get(status, "?")
    unreal.log("%s %s %s: %s" % (TAG, tag, step, msg or status))


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
                unreal.log_warning("%s %s failed:\n%s" % (TAG, name, traceback.format_exc()))
                _record(name, "FAIL", str(e))
        return _inner
    return _wrap


def _get_world():
    subsys = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    if subsys is not None:
        w = subsys.get_editor_world()
        if w is not None:
            return w
    return unreal.EditorLevelLibrary.get_editor_world()


def _actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _ensure_bossarena_open():
    world = _get_world()
    if world is None:
        raise StepSkip("no editor world open")
    path = world.get_path_name().split(":")[0]
    if not (path.endswith("BossArena") or path.endswith("BossArena.BossArena")):
        # Try loading it
        try:
            unreal.EditorLoadingAndSavingUtils.load_map(MAP_PATH)
        except Exception:
            pass
        world = _get_world()
        path = world.get_path_name().split(":")[0]
        if not (path.endswith("BossArena") or path.endswith("BossArena.BossArena")):
            raise StepSkip("current map is '%s'; expected /Game/Maps/BossArena" % path)


def _mode():
    return os.environ.get("SHOWCASE_MODE", "off").lower().strip()


# ---------------------------------------------------------------------------
# Step 1 — hide (or unhide) every ARENA_DRESS_* actor
# ---------------------------------------------------------------------------

@_step("1. Toggle ARENA_DRESS_* visibility")
def step_1_toggle_dress():
    _ensure_bossarena_open()
    world = _get_world()

    hide = _mode() == "on"
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    n_matched = 0
    n_flipped = 0
    n_whitelisted = 0
    # UE 5.8 dropped the reflected `actor_hidden_in_game` python property on
    # StaticMeshActor — reading it raises AttributeError. Setters still work.
    # Read via get_editor_property (works for bHidden across 5.7/5.8), fall
    # back to unconditional set when even that fails; being idempotent means
    # over-writing an already-hidden actor with hide=True is a no-op anyway.
    def _is_hidden(actor):
        try:
            return bool(actor.get_editor_property("hidden"))
        except Exception:
            try:
                return bool(actor.get_editor_property("bHidden"))
            except Exception:
                return None  # unknown — assume flip is needed
    for a in actors:
        if not a:
            continue
        label = a.get_actor_label()
        if not label.startswith(DRESS_PREFIX):
            continue
        # Never hide the floor ring or backdrop — the arena would go void black
        # without a floor to stand on (root-motion contract) or a horizon to
        # frame against. These are structural, not "dressing" in the visual
        # sense.
        suffix = label[len(DRESS_PREFIX):]
        if any(suffix.startswith(w) for w in DRESS_WHITELIST_SUFFIXES):
            # Force these BACK visible in case a prior stale run hid them.
            a.set_actor_hidden_in_game(False)
            try:
                a.set_is_temporarily_hidden_in_editor(False)  # restore only
            except Exception:
                pass
            n_whitelisted += 1
            continue
        n_matched += 1
        current = _is_hidden(a)
        if current is None or current != hide:
            a.set_actor_hidden_in_game(hide)
            n_flipped += 1
        # NOTE: intentionally NOT calling set_is_temporarily_hidden_in_editor —
        # on UE 5.8 with World Partition, that flag can strip PhysX cooking on
        # save, and when the level reloads the physics-owning static-mesh
        # actors no longer contribute collision. bIsHiddenInGame alone hides
        # render in PIE without touching physics, which is exactly what the
        # showcase needs.
    return "%s %d of %d ARENA_DRESS_* actors (whitelisted %d: %s; %s)" % (
        "hid" if hide else "unhid", n_flipped, n_matched, n_whitelisted,
        ", ".join(DRESS_WHITELIST_SUFFIXES), _mode())


# ---------------------------------------------------------------------------
# Step 2 — spawn (or destroy) the 4 cardinal monoliths
# ---------------------------------------------------------------------------

def _pick_monolith_mesh():
    for path in MONOLITH_MESHES:
        m = unreal.EditorAssetLibrary.load_asset(path)
        if m is not None:
            return m, path
    return None, None


@_step("2. Cardinal obsidian monoliths (N/E/S/W)")
def step_2_monoliths():
    _ensure_bossarena_open()
    world = _get_world()
    subsys = _actor_subsystem()

    # Always sweep our own family first — idempotent regardless of mode.
    existing = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
    swept = 0
    for a in existing:
        if a and a.get_actor_label().startswith(LABEL_PREFIX):
            subsys.destroy_actor(a)
            swept += 1

    if _mode() != "on":
        return "swept %d prior showcase monoliths (revert mode, none respawned)" % swept

    mesh, mesh_path = _pick_monolith_mesh()
    if mesh is None:
        raise StepSkip("no monolith mesh available (checked %d fallbacks)" % len(MONOLITH_MESHES))

    spawned = 0
    for label_suffix, x, y, yaw in MONOLITH_CARDINALS:
        loc = unreal.Vector(x, y, MONOLITH_Z)
        rot = unreal.Rotator(0.0, 0.0, yaw)
        actor = subsys.spawn_actor_from_class(unreal.StaticMeshActor, loc, rot)
        if actor is None:
            continue
        actor.set_actor_label("%s%s_Monolith" % (LABEL_PREFIX, label_suffix))
        smc = actor.static_mesh_component
        smc.set_static_mesh(mesh)
        actor.set_actor_scale3d(unreal.Vector(MONOLITH_SCALE, MONOLITH_SCALE, MONOLITH_SCALE * 1.4))
        # NO COLLISION — same contract as the floor ring and backdrop
        # (dress_arena._no_collision): the monoliths are visual landmarks, and
        # the ARENA_BV_* blocking ring already fences the play space. A large
        # mesh's collision hull overlapping a spawn point ejects pawns through
        # the floor (the endless-falling bug this line fixes).
        try:
            smc.set_collision_profile_name("NoCollision")
        except Exception:
            pass
        smc.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        spawned += 1
    return "swept %d prior, spawned %d monoliths using %s" % (swept, spawned, mesh_path)


# ---------------------------------------------------------------------------
# Step 3 — post-process showcase palette (with backup for faithful revert)
# ---------------------------------------------------------------------------

def _find_actor_by_label(world, label):
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    for a in actors:
        if a and a.get_actor_label() == label:
            return a
    return None


def _find_post_process_actor(world):
    # Preferred: the ARENA_PostProcess actor named by build_arena_level.py.
    a = _find_actor_by_label(world, "ARENA_PostProcess")
    if a is not None:
        return a
    # Fallback: any PostProcessVolume in the level.
    volumes = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PostProcessVolume)
    return volumes[0] if volumes else None


def _serialize_field(settings, name):
    """Pull the current value of an FPostProcessSettings field for backup.
    Returns a JSON-friendly representation (float / [x,y,z,w] / enum-name)."""
    v = getattr(settings, name)
    # Vector4-like
    if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z") and hasattr(v, "w"):
        return {"__type__": "Vector4", "x": v.x, "y": v.y, "z": v.z, "w": v.w}
    # Enum
    if hasattr(v, "name"):
        return {"__type__": "Enum", "name": v.name}
    # Scalar
    return float(v)


def _deserialize_field(dumped):
    if isinstance(dumped, dict) and dumped.get("__type__") == "Vector4":
        return unreal.Vector4(dumped["x"], dumped["y"], dumped["z"], dumped["w"])
    if isinstance(dumped, dict) and dumped.get("__type__") == "Enum":
        return getattr(unreal.AutoExposureMethod, dumped["name"])
    return float(dumped)


def _override_name(field):
    # Field 'auto_exposure_min_brightness' maps to override 'override_auto_exposure_min_brightness'
    return "override_" + field


@_step("3. Post-process showcase palette")
def step_3_postprocess():
    _ensure_bossarena_open()
    world = _get_world()
    ppa = _find_post_process_actor(world)
    if ppa is None:
        raise StepSkip("no PostProcessVolume in level")

    # Grab the FPostProcessSettings struct (property named 'settings' on
    # UPostProcessComponent; on APostProcessVolume it's 'settings' too).
    ppc = ppa.get_component_by_class(unreal.PostProcessComponent) if hasattr(ppa, "get_component_by_class") else None
    if ppc is None:
        # APostProcessVolume path
        settings = ppa.get_editor_property("settings")
    else:
        settings = ppc.get_editor_property("settings")

    if _mode() == "on":
        # Back up first (only if backup doesn't exist yet — first-run baseline)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        if not os.path.exists(BACKUP_FILE):
            baseline = {}
            for name in BACKUP_FIELDS:
                try:
                    baseline[name] = _serialize_field(settings, name)
                    baseline[_override_name(name)] = bool(getattr(settings, _override_name(name)))
                except Exception as e:
                    unreal.log_warning("%s backup miss for '%s': %s" % (TAG, name, e))
            with open(BACKUP_FILE, "w") as fh:
                json.dump(baseline, fh, indent=2)

        # Apply showcase palette
        applied = 0
        for name, value in SHOWCASE_PP.items():
            try:
                setattr(settings, _override_name(name), True)
                setattr(settings, name, value)
                applied += 1
            except Exception as e:
                unreal.log_warning("%s apply miss for '%s': %s" % (TAG, name, e))
        # Struct write-back (Unreal's Python API takes struct-by-value)
        if ppc is not None:
            ppc.set_editor_property("settings", settings)
        else:
            ppa.set_editor_property("settings", settings)
        return "applied %d/%d fields; baseline stashed at %s" % (
            applied, len(SHOWCASE_PP), BACKUP_FILE if os.path.exists(BACKUP_FILE) else "<none>")

    # revert
    if not os.path.exists(BACKUP_FILE):
        raise StepSkip("no baseline at %s — PP left untouched" % BACKUP_FILE)
    with open(BACKUP_FILE) as fh:
        baseline = json.load(fh)
    restored = 0
    for name in BACKUP_FIELDS:
        if name not in baseline:
            continue
        try:
            setattr(settings, name, _deserialize_field(baseline[name]))
            override_key = _override_name(name)
            if override_key in baseline:
                setattr(settings, override_key, bool(baseline[override_key]))
            restored += 1
        except Exception as e:
            unreal.log_warning("%s revert miss for '%s': %s" % (TAG, name, e))
    if ppc is not None:
        ppc.set_editor_property("settings", settings)
    else:
        ppa.set_editor_property("settings", settings)
    return "restored %d/%d fields from baseline" % (restored, len(BACKUP_FIELDS))


# ---------------------------------------------------------------------------
# Step 4 — save
# ---------------------------------------------------------------------------

@_step("4. Save BossArena")
def step_4_save():
    _ensure_bossarena_open()
    try:
        # Save the level's world asset (level-editor save path)
        world = _get_world()
        wpath = world.get_outermost().get_name()  # /Game/Maps/BossArena
        ok = unreal.EditorAssetLibrary.save_asset(wpath)
        if not ok:
            raise StepSkip("save_asset returned False")
    except Exception as e:
        raise StepSkip("save failed: %s" % e)
    return "saved"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    unreal.log("%s starting apply (SHOWCASE_MODE=%s)..." % (TAG, _mode()))

    step_1_toggle_dress()
    step_2_monoliths()
    step_3_postprocess()
    step_4_save()

    unreal.log("%s ===== SUMMARY (%.1fs) =====" % (TAG, time.time() - t0))
    for step, status, msg in CTX["results"]:
        unreal.log("%s  %-6s  %s  --  %s" % (TAG, status, step, msg))


if __name__ == "__main__":
    main()
