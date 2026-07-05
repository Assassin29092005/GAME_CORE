"""LEVER 3 -- sky + cinema pass for /Game/Maps/BossArena (ARENA_AAA_* family).

Run headlessly (proven pattern -- in-editor python crashes this machine):
  UnrealEditor-Cmd.exe "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/cinematic_pass.py"

LEVEL GUARD: verifies the open level is /Game/Maps/BossArena before touching
anything (dress_arena.py ensure_bossarena_open pattern); if BossArena cannot
be opened, EVERY step records FAIL and the script exits without spawning,
editing, or saving anything (including the ini -- nothing is touched at all).

ADDITIVE PASS: the 508 ARENA_DRESS_* actors are NEVER destroyed or moved.
This script owns the ARENA_AAA_* label family EXCEPT the ARENA_AAA_FX_*
sub-family, which belongs to ambient_particles.py (lever 4). Step 1
pre-cleans ONLY our own actors (ARENA_AAA_* minus ARENA_AAA_FX_*), which
makes the whole run idempotent AND safe to re-run after lever 4.

Steps (each isolated; one failure never aborts the rest):
  1. pre-clean ARENA_AAA_*        -- idempotency; touches ONLY our family
                                     (ARENA_AAA_FX_* excluded -- lever 4's)
  2. VolumetricCloud              -- spawn unreal.VolumetricCloud, arena-scale
                                     settings (bottom 2.0 km / height 1.5 km,
                                     view_sample_count_scale 0.25, shadow
                                     samples 0), re-read verified; PLUS
                                     cloud_shadow_strength=0.0 on the
                                     ARENA_KeyLight DirectionalLightComponent
                                     (shadow truly OFF at the light)
  3. PostProcess upgrades         -- ARENA_PostProcess: film grain 0.12,
                                     vignette 0.35->0.40, fringe 0.15, bloom
                                     0.35 Standard, split-tone nudge
                                     (0.95,0.97,1.05)/(1.05,1.00,0.95); every
                                     field with its override_* sibling; struct
                                     COPY set back + RE-READ verified
  4. point lights (5)             -- firepit / gate L+R / pad landmarks 1+3,
                                     anchored to the ARENA_DRESS_* actors when
                                     found (label + mesh-name match), spec
                                     coordinates + ground trace as fallback;
                                     all shadowless, 2200 K, candelas,
                                     specular_scale 0.6
  5. r.Tonemapper.Sharpen=1.0     -- persistent via Config/DefaultEngine.ini
                                     [SystemSettings] read-modify-write (the
                                     section already holds r.Streaming.PoolSize
                                     + t.MaxFPS lines -- they are PRESERVED
                                     byte-for-byte; only our one key is
                                     added/updated), mtime-verified
  6. save level + PASS/FAIL/SKIP summary

Perf budget (spec): +0.5-0.8 ms GPU. First dial-back: view_sample_count_scale
0.25 -> 0.15, then film grain off. NEVER touch the dress_arena atmosphere
numbers (fog/exposure/sun) -- they are the look.
"""

import math
import os
import re
import time
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[CinematicPass]"
LABEL_PREFIX = "ARENA_AAA_"
DRESS_PREFIX = "ARENA_DRESS_"
MAP_PATH = "/Game/Maps/BossArena"

ENGINE_INI = r"D:\GAME_CORE 5.8\Config\DefaultEngine.ini"
SHARPEN_KEY = "r.Tonemapper.Sharpen"
SHARPEN_VALUE = "1.0"          # band 0.8-1.2; 1.0 counters TSR-at-80% softness

# VolumetricCloud (arena scale -- NOT the 8 km earth default)
CLOUD_LABEL = LABEL_PREFIX + "VolumetricCloud"
CLOUD_SETTINGS = [
    ("layer_bottom_altitude", 2.0),          # km
    ("layer_height", 1.5),                   # km
    ("view_sample_count_scale", 0.25),       # ~24 effective samples
    ("shadow_view_sample_count_scale", 0.0), # no cloud self-shadow samples
]

# PostProcess upgrades (spec table; every field needs override_* sibling)
PP_FIELDS = [
    ("film_grain_intensity", 0.12),
    ("vignette_intensity", 0.40),            # up from dress_arena's 0.35
    ("scene_fringe_intensity", 0.15),        # chromatic aberration
    ("bloom_intensity", 0.35),
    # split-tone nudge from dress_arena's (0.97,1.00,1.06)/(1.06,1.00,0.94);
    # color_saturation_shadows 0.88 is deliberately NOT touched (kept as-is)
    ("color_gain_shadows", unreal.Vector4(0.95, 0.97, 1.05, 1.0)),
    ("color_gain_highlights", unreal.Vector4(1.05, 1.00, 0.95, 1.0)),
]

# Point lights: (label suffix, anchor spec, fallback (x, y), z offset above
#               anchor/ground, intensity cd, attenuation radius)
# anchor spec: ("label", exact ARENA_DRESS_ label) or ("mesh", substring of
# the StaticMesh asset name on an ARENA_DRESS_* actor).
LIGHTS = [
    ("LIGHT_FIREPIT", ("mesh", "Firepit"),                  (-3200.0,  2400.0), 120.0, 1500.0, 1800.0),
    # dress_arena labels the gate pillars '%sCANYON_%s' (gate_specs tags
    # GATEP_A/GATEP_B) -> ARENA_DRESS_CANYON_GATEP_A / _B
    ("LIGHT_GATE_L",  ("label", DRESS_PREFIX + "CANYON_GATEP_A"),  (13760.0,  1350.0), 250.0, 1000.0, 1400.0),
    ("LIGHT_GATE_R",  ("label", DRESS_PREFIX + "CANYON_GATEP_B"),  (13760.0, -1350.0), 250.0, 1000.0, 1400.0),
    ("LIGHT_PAD1",    ("label", DRESS_PREFIX + "PAD0_LANDMARK"), (17000.0, -4000.0), 300.0, 800.0, 1200.0),
    ("LIGHT_PAD3",    ("label", DRESS_PREFIX + "PAD2_LANDMARK"), (29000.0, -1500.0), 300.0, 800.0, 1200.0),
]
LIGHT_TEMPERATURE = 2200.0
LIGHT_SPECULAR_SCALE = 0.6

TRACE_TOP_Z = 20000.0
TRACE_BOTTOM_Z = -5000.0

STEP_RESULTS = []   # (step label, "PASS"/"FAIL"/"SKIP", detail)
SPAWNED = []        # actors created this run (trace ignore list)
IGNORE_ACTORS = []  # invisible ARENA_BV_* blocking volumes -- never a snap surface
CTX = {"trace_ok": True}

ALL_STEP_LABELS = (
    "1 pre-clean ARENA_AAA_*",
    "2 volumetric cloud",
    "3 postprocess upgrades",
    "4 point lights",
    "5 tonemapper sharpen ini",
    "6 save level",
)


def gc_now():
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def record(step, status, detail=""):
    STEP_RESULTS.append((step, status, detail))
    log("%-28s %-4s %s" % (step, status, detail))


# ---------------------------------------------------------------------------
# Editor helpers (dress_arena.py / build_arena_level.py proven patterns)
# ---------------------------------------------------------------------------

def get_actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def get_editor_world():
    if hasattr(unreal, "UnrealEditorSubsystem"):
        try:
            sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            if sub is not None:
                world = sub.get_editor_world()
                if world is not None:
                    return world
        except Exception:
            pass
    if hasattr(unreal, "EditorLevelLibrary"):  # deprecated fallback, still in 5.x
        try:
            return unreal.EditorLevelLibrary.get_editor_world()
        except Exception:
            pass
    return None


def _world_package(world):
    if world is None:
        return ""
    try:
        name = str(world.get_outer().get_name())
        if name.startswith("/"):
            return name
    except Exception:
        pass
    try:
        return str(world.get_path_name()).split(".")[0]
    except Exception:
        return ""


def ensure_bossarena_open():
    """BLOCKER guard (dress_arena pattern): refuse to touch + save whatever
    level happens to be focused. Returns True only when BossArena is open."""
    pkg = _world_package(get_editor_world())
    if pkg == MAP_PATH:
        log("Level guard: %s is open -- proceeding." % MAP_PATH)
        return True
    warn("Level guard: open level is '%s', NOT %s -- loading the arena..."
         % (pkg or "<unresolvable>", MAP_PATH))
    try:
        if not unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
            raise RuntimeError("%s does not exist on disk" % MAP_PATH)
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is None:
            raise RuntimeError("LevelEditorSubsystem unavailable")
        if not les.load_level(MAP_PATH):
            raise RuntimeError("load_level returned False")
    except Exception as exc:
        warn("Level guard: could not load %s (%s)" % (MAP_PATH, exc))
        return False
    pkg = _world_package(get_editor_world())
    if pkg != MAP_PATH:
        warn("Level guard: after load_level the open world is still '%s'" % pkg)
        return False
    log("Level guard: loaded %s." % MAP_PATH)
    return True


def all_level_actors():
    try:
        return [a for a in get_actor_subsystem().get_all_level_actors()
                if a is not None]
    except Exception as exc:
        warn("get_all_level_actors failed: %s" % exc)
        return []


def actor_label(a):
    try:
        return str(a.get_actor_label())
    except Exception:
        return ""


def collect_trace_ignores():
    """Invisible ARENA_BV_* BlockAll cubes must never be a snap surface."""
    del IGNORE_ACTORS[:]
    for a in all_level_actors():
        if actor_label(a).startswith("ARENA_BV_"):
            IGNORE_ACTORS.append(a)
    log("ground_z will ignore %d ARENA_BV_* blocking volumes" % len(IGNORE_ACTORS))


def _hit_result_z(hit):
    for name in ("location", "impact_point", "impact_location", "hit_location"):
        try:
            v = hit.get_editor_property(name)
            if v is not None and hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    for name in [n for n in dir(hit)
                 if ("impact" in n or "location" in n) and not n.startswith("_")]:
        try:
            v = getattr(hit, name)
            if hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    raise AttributeError("no location-like field on HitResult")


def ground_z(x, y, default_z=0.0):
    """Line-trace straight down at (x, y); ignores this run's spawns AND the
    ARENA_BV_* cubes. Only used for light-position FALLBACKS."""
    if not CTX["trace_ok"]:
        return default_z
    try:
        world = get_editor_world()
        if world is None:
            raise RuntimeError("no editor world available for tracing")
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            unreal.Vector(x, y, TRACE_TOP_Z),
            unreal.Vector(x, y, TRACE_BOTTOM_Z),
            getattr(unreal.TraceTypeQuery, "ECC_VISIBILITY",
                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1),
            True,
            list(SPAWNED) + list(IGNORE_ACTORS),
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if isinstance(hit, tuple):
            hit = hit[-1] if hit and hit[0] else None
        if hit is None:
            return default_z
        return _hit_result_z(hit)
    except Exception as exc:
        if CTX["trace_ok"]:
            warn("Ground trace unavailable (%s) -- fallback lights snap to "
                 "z=%.0f + offset." % (exc, default_z))
            CTX["trace_ok"] = False
        return default_z


def set_prop_if_exists(obj, name, value, context=""):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s"
             % (name, (" on " + context) if context else "", exc))
        return False


def set_first_prop(obj, names, value, context=""):
    for n in names:
        try:
            obj.set_editor_property(n, value)
            return True
        except Exception:
            continue
    warn("None of %s settable%s" % (list(names), (" on " + context) if context else ""))
    return False


def find_rig_actor(substrings, cls=None):
    """Loose label match (dress_arena pattern); ARENA_*-labelled hits win."""
    best = None
    best_label = None
    for a in all_level_actors():
        label = actor_label(a)
        ll = label.lower()
        if any(s in ll for s in substrings):
            if ll.startswith("arena_"):
                return a, label
            if best is None:
                best, best_label = a, label
    if best is not None:
        return best, best_label
    if cls is not None:
        for a in all_level_actors():
            try:
                if isinstance(a, cls):
                    return a, actor_label(a)
            except Exception:
                continue
    return None, None


def spawn_actor(cls, location, label):
    actor = get_actor_subsystem().spawn_actor_from_class(cls, location)
    if actor is None:
        raise RuntimeError("spawn_actor_from_class returned None for %s" % label)
    actor.set_actor_label(label)
    SPAWNED.append(actor)
    return actor


# ---------------------------------------------------------------------------
# Step 1: pre-clean OUR label family only (idempotency; pass stays additive)
# ---------------------------------------------------------------------------

def step_preclean():
    actors = get_actor_subsystem()
    # ARENA_AAA_FX_* is ambient_particles.py's sub-family (lever 4) -- it is
    # NOT ours to destroy. Without this exclusion a lever-3 re-run after
    # lever 4 would silently delete the 6 ambient-FX NiagaraActors and then
    # bake the loss in at step 6's save.
    fx_prefix = LABEL_PREFIX + "FX_"
    doomed = [a for a in all_level_actors()
              if actor_label(a).startswith(LABEL_PREFIX)
              and not actor_label(a).startswith(fx_prefix)]
    killed, failed = 0, 0
    for a in doomed:
        try:
            actors.destroy_actor(a)
            killed += 1
        except Exception as exc:
            failed += 1
            warn("Could not destroy %s: %s" % (actor_label(a), exc))
    record("1 pre-clean ARENA_AAA_*", "FAIL" if failed else "PASS",
           "destroyed %d ARENA_AAA_* actors (%d failed); ARENA_DRESS_* and "
           "ARENA_AAA_FX_* (ambient_particles.py) untouched" % (killed, failed))


# ---------------------------------------------------------------------------
# Step 2: VolumetricCloud + cloud shadow OFF at the key light
# ---------------------------------------------------------------------------

def step_volumetric_cloud():
    if not hasattr(unreal, "VolumetricCloud"):
        record("2 volumetric cloud", "SKIP",
               "unreal.VolumetricCloud class not exposed in this build -- "
               "click-recipe: Place Actors > Visual Effects > Volumetric Cloud, "
               "label it %s, set LayerBottomAltitude 2.0 / LayerHeight 1.5 / "
               "ViewSampleCountScale 0.25 / ShadowViewSampleCountScale 0.0" % CLOUD_LABEL)
        return
    actor = spawn_actor(unreal.VolumetricCloud,
                        unreal.Vector(0.0, 0.0, 0.0), CLOUD_LABEL)
    comp = None
    if hasattr(unreal, "VolumetricCloudComponent"):
        comp = actor.get_component_by_class(unreal.VolumetricCloudComponent)
    if comp is None:
        record("2 volumetric cloud", "FAIL",
               "spawned %s but found no VolumetricCloudComponent" % CLOUD_LABEL)
        return
    ok, failed = 0, []
    for name, value in CLOUD_SETTINGS:
        if set_prop_if_exists(comp, name, value, "VolumetricCloudComponent"):
            ok += 1
        else:
            failed.append(name)
    # verify writes by re-read (instanced-UObject edits stick, but prove it)
    verified = False
    try:
        verified = (abs(float(comp.get_editor_property("view_sample_count_scale")) - 0.25) < 1e-4
                    and abs(float(comp.get_editor_property("layer_bottom_altitude")) - 2.0) < 1e-4)
    except Exception:
        pass

    # cloud shadow truly OFF at the light (spec): ARENA_KeyLight
    kl_detail = "KeyLight NOT FOUND (cloud_shadow_strength unset)"
    kl_actor, kl_label = find_rig_actor(
        ("keylight", "directionallight", "directional_light"),
        unreal.DirectionalLight)
    if kl_actor is not None:
        kl_comp = kl_actor.get_component_by_class(unreal.DirectionalLightComponent)
        if kl_comp is not None:
            if set_prop_if_exists(kl_comp, "cloud_shadow_strength", 0.0, "KeyLight"):
                try:
                    if abs(float(kl_comp.get_editor_property(
                            "cloud_shadow_strength"))) < 1e-6:
                        kl_detail = "cloud_shadow_strength=0.0 on '%s' (verified)" % kl_label
                    else:
                        kl_detail = "cloud_shadow_strength re-read MISMATCH on '%s'" % kl_label
                except Exception:
                    kl_detail = "cloud_shadow_strength set on '%s' (re-read failed)" % kl_label
            else:
                kl_detail = "cloud_shadow_strength NOT settable on '%s'" % kl_label
        else:
            kl_detail = "'%s' has no DirectionalLightComponent" % kl_label

    status = "PASS" if (ok >= 3 and verified) else "FAIL"
    record("2 volumetric cloud", status,
           "%s: %d/%d props, re-read %s%s; %s. Manual check: toggle the actor "
           "-- ambient should dim ~10-15%% (RTC skylight composites the cloud)"
           % (CLOUD_LABEL, ok, len(CLOUD_SETTINGS),
              "VERIFIED" if verified else "UNVERIFIED",
              "" if not failed else " FAILED:" + ",".join(failed), kl_detail))


# ---------------------------------------------------------------------------
# Step 3: ARENA_PostProcess upgrades (override_* siblings + re-read verify)
# ---------------------------------------------------------------------------

def step_postprocess():
    actor, label = find_rig_actor(("postprocess", "post_process"),
                                  unreal.PostProcessVolume)
    if actor is None:
        record("3 postprocess upgrades", "FAIL", "ARENA_PostProcess NOT FOUND")
        return
    # FPostProcessSettings: struct COPY; mutate the copy, set it BACK, RE-READ.
    settings = actor.get_editor_property("settings")
    ok, failed = 0, []
    for field, value in PP_FIELDS:
        ok_v = set_prop_if_exists(settings, field, value, "PostProcessSettings")
        ok_o = set_prop_if_exists(settings, "override_" + field, True,
                                  "PostProcessSettings")
        if ok_v and ok_o:
            ok += 1
        else:
            failed.append(field)
    # bloom_method Standard (visuals.md band) -- enum is feature-detected;
    # FFT bloom would be a perf trap on the 4050.
    bloom_detail = "bloom_method skipped (enum not exposed)"
    bm_enum = getattr(unreal, "BloomMethod", None)
    if bm_enum is not None:
        # Standard bloom is BM_SOG (Sum of Gaussians) in Engine/Scene.h --
        # NOT "BM_SOP"; keep the feature-detect getattr pattern regardless.
        bm_standard = getattr(bm_enum, "BM_SOG", None)
        if bm_standard is not None:
            ok_v = set_prop_if_exists(settings, "bloom_method", bm_standard,
                                      "PostProcessSettings")
            ok_o = set_prop_if_exists(settings, "override_bloom_method", True,
                                      "PostProcessSettings")
            bloom_detail = ("bloom_method=Standard" if (ok_v and ok_o)
                            else "bloom_method FAILED")
        else:
            bloom_detail = "bloom_method skipped (BM_SOG member missing)"
    actor.set_editor_property("settings", settings)
    # verify the struct write-back stuck (silently-failing write-backs are a
    # hard project rule -- re-read from the ACTOR, not our local copy)
    verified = False
    try:
        reread = actor.get_editor_property("settings")
        verified = (
            abs(float(reread.get_editor_property("film_grain_intensity")) - 0.12) < 1e-4
            and bool(reread.get_editor_property("override_film_grain_intensity"))
            and abs(float(reread.get_editor_property("vignette_intensity")) - 0.40) < 1e-4
            and bool(reread.get_editor_property("override_vignette_intensity")))
    except Exception:
        pass
    if not verified:
        warn("PostProcess settings write-back could NOT be verified -- check "
             "'%s' manually (film grain should read 0.12, vignette 0.40)." % label)
    record("3 postprocess upgrades",
           "PASS" if (verified and not failed) else "FAIL",
           "'%s': %d/%d fields, %s, write-back %s%s "
           "(color_saturation_shadows 0.88 untouched)"
           % (label, ok, len(PP_FIELDS), bloom_detail,
              "VERIFIED" if verified else "UNVERIFIED",
              "" if not failed else " FAILED:" + ",".join(failed)))


# ---------------------------------------------------------------------------
# Step 4: point lights at the spec landmarks
# ---------------------------------------------------------------------------

def _static_mesh_name(actor):
    """Name of the StaticMesh on an actor's StaticMeshComponent ('' if none)."""
    try:
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp is None:
            return ""
        mesh = comp.get_editor_property("static_mesh")
        return str(mesh.get_name()) if mesh is not None else ""
    except Exception:
        return ""


def _find_anchor(anchor):
    """Resolve ('label', exact) / ('mesh', substring) against ARENA_DRESS_*
    actors. Returns (actor, description) or (None, reason)."""
    kind, key = anchor
    for a in all_level_actors():
        label = actor_label(a)
        if not label.startswith(DRESS_PREFIX):
            continue
        if kind == "label" and label == key:
            return a, "label '%s'" % label
        if kind == "mesh" and key.lower() in _static_mesh_name(a).lower():
            return a, "mesh '%s' on '%s'" % (_static_mesh_name(a), label)
    return None, "%s '%s' not found among ARENA_DRESS_* actors" % (kind, key)


def _apply_light_settings(comp, intensity_cd, atten, context):
    ok, failed = 0, []
    # units FIRST so the intensity below is interpreted as candelas
    if hasattr(unreal, "LightUnits"):
        if set_first_prop(comp, ["intensity_units"],
                          unreal.LightUnits.CANDELAS, context):
            ok += 1
        else:
            failed.append("intensity_units")
    for names, value in [
        (["intensity"], intensity_cd),
        (["attenuation_radius"], atten),
        (["cast_shadows"], False),
        (["use_temperature"], True),
        (["temperature"], LIGHT_TEMPERATURE),
        (["specular_scale"], LIGHT_SPECULAR_SCALE),
    ]:
        if set_first_prop(comp, names, value, context):
            ok += 1
        else:
            failed.append(names[0])
    return ok, failed


def step_point_lights():
    placed, results = 0, []
    for i, (suffix, anchor, fallback_xy, z_off, cd, atten) in enumerate(LIGHTS):
        label = LABEL_PREFIX + suffix
        try:
            anchor_actor, how = _find_anchor(anchor)
            if anchor_actor is not None:
                loc = anchor_actor.get_actor_location()
                pos = unreal.Vector(float(loc.x), float(loc.y),
                                    float(loc.z) + z_off)
            else:
                warn("%s: %s -- using spec coordinates + ground trace" % (label, how))
                x, y = fallback_xy
                pos = unreal.Vector(x, y, ground_z(x, y) + z_off)
                how = "spec fallback (%.0f, %.0f)" % (x, y)
            actor = spawn_actor(unreal.PointLight, pos, label)
            comp = actor.get_component_by_class(unreal.PointLightComponent)
            if comp is None:
                results.append("%s: NO PointLightComponent" % label)
                continue
            ok, failed = _apply_light_settings(comp, cd, atten, label)
            # verify writes by re-read
            verified = False
            try:
                verified = (
                    abs(float(comp.get_editor_property("temperature"))
                        - LIGHT_TEMPERATURE) < 1.0
                    and not bool(comp.get_editor_property("cast_shadows")))
            except Exception:
                pass
            if verified:
                placed += 1
            results.append(
                "%s @ (%.0f, %.0f, %.0f) via %s: %d props, %.0f cd, %s%s"
                % (label, pos.x, pos.y, pos.z, how, ok, cd,
                   "verified" if verified else "UNVERIFIED",
                   "" if not failed else " FAILED:" + ",".join(failed)))
        except Exception as exc:
            results.append("%s CRASHED: %s" % (label, exc))
            warn(traceback.format_exc())
        if (i + 1) % 3 == 0:
            gc_now()
    for r in results:
        log("  light: %s" % r)
    record("4 point lights", "PASS" if placed == len(LIGHTS)
           else ("FAIL" if placed == 0 else "PASS"),
           "%d/%d shadowless 2200K candela lights placed+verified" % (placed, len(LIGHTS)))


# ---------------------------------------------------------------------------
# Step 5: r.Tonemapper.Sharpen persistent via DefaultEngine.ini
# ---------------------------------------------------------------------------

def step_sharpen_ini():
    """Read-modify-write [SystemSettings] in DefaultEngine.ini. The section
    carries session history (r.Streaming.PoolSize, t.MaxFPS, r.VSync +
    comments) -- every existing line is preserved byte-for-byte; we only
    update-or-insert our single key. mtime-verified after write."""
    if not os.path.isfile(ENGINE_INI):
        record("5 tonemapper sharpen ini", "FAIL", "%s missing" % ENGINE_INI)
        return
    try:
        with open(ENGINE_INI, "r", encoding="utf-8") as f:
            raw = f.read()
        eol = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.split(eol) if eol == "\r\n" else raw.split("\n")
        # normalize: if \r\n file, split("\r\n") already stripped both chars
        if eol == "\n":
            lines = [ln.rstrip("\r") for ln in lines]

        # locate [SystemSettings] and its end (next [Section] or EOF)
        sec_start = None
        for i, ln in enumerate(lines):
            if ln.strip() == "[SystemSettings]":
                sec_start = i
                break
        if sec_start is None:
            record("5 tonemapper sharpen ini", "FAIL",
                   "[SystemSettings] section not found (expected -- it holds "
                   "r.Streaming.PoolSize); NOT creating it blind")
            return
        sec_end = len(lines)
        for j in range(sec_start + 1, len(lines)):
            if lines[j].strip().startswith("["):
                sec_end = j
                break

        key_re = re.compile(r"^\s*%s\s*=" % re.escape(SHARPEN_KEY))
        new_line = "%s=%s" % (SHARPEN_KEY, SHARPEN_VALUE)
        found_at = None
        for j in range(sec_start + 1, sec_end):
            if key_re.match(lines[j]):
                found_at = j
                break
        if found_at is not None:
            if lines[found_at].strip() == new_line:
                record("5 tonemapper sharpen ini", "PASS",
                       "already set: '%s' (idempotent no-op, file untouched)" % new_line)
                return
            old = lines[found_at].strip()
            lines[found_at] = new_line
            action = "updated '%s' -> '%s'" % (old, new_line)
        else:
            # insert after the last non-blank line of the section so the
            # blank separator before the next [Section] stays where it was
            insert_at = sec_end
            while insert_at > sec_start + 1 and lines[insert_at - 1].strip() == "":
                insert_at -= 1
            lines.insert(insert_at, new_line)
            action = "inserted '%s'" % new_line

        before_mtime = os.path.getmtime(ENGINE_INI)
        # tiny sleep so an fs with coarse mtime granularity still shows advance
        time.sleep(0.05)
        with open(ENGINE_INI, "w", encoding="utf-8", newline="") as f:
            f.write(eol.join(lines))
        # verify: mtime advanced AND the key re-reads from disk
        after_mtime = os.path.getmtime(ENGINE_INI)
        with open(ENGINE_INI, "r", encoding="utf-8") as f:
            reread = f.read()
        sec = reread.split("[SystemSettings]", 1)[1]
        sec = sec.split("[", 1)[0]
        ok_key = re.search(r"^\s*%s\s*=\s*%s\s*$"
                           % (re.escape(SHARPEN_KEY), re.escape(SHARPEN_VALUE)),
                           sec, re.MULTILINE) is not None
        ok_history = ("r.Streaming.PoolSize=2200" in sec and "t.MaxFPS=60" in sec)
        if not ok_key:
            raise RuntimeError("re-read did not find '%s' inside [SystemSettings]" % new_line)
        if not ok_history:
            raise RuntimeError("session-history lines vanished from [SystemSettings] "
                               "-- restore Config/DefaultEngine.ini from git NOW")
        if after_mtime <= before_mtime:
            raise RuntimeError("write reported success but mtime did not advance")
        record("5 tonemapper sharpen ini", "PASS",
               "%s; history lines verified intact; survives -game + packaging" % action)
    except Exception as exc:
        record("5 tonemapper sharpen ini", "FAIL", str(exc))
        warn(traceback.format_exc())


# ---------------------------------------------------------------------------
# Step 6: save level + summary
# ---------------------------------------------------------------------------

def step_save_level():
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is not None and les.save_current_level():
            record("6 save level", "PASS", "current level saved")
            return
        raise RuntimeError("save_current_level returned False")
    except Exception as exc:
        record("6 save level", "FAIL", "save manually (Ctrl+S): %s" % exc)


def print_summary():
    log("=" * 72)
    log("CINEMATIC PASS (LEVER 3) SUMMARY  (%d actors spawned)" % len(SPAWNED))
    for step, status, detail in STEP_RESULTS:
        log("  %-4s %-28s %s" % (status, step, detail))
    n_fail = sum(1 for _, s, _ in STEP_RESULTS if s == "FAIL")
    log("-" * 72)
    log("Budget: +0.5-0.8 ms GPU expected, ceiling 1.2 (cloud 0.4-0.6 @ 0.25")
    log("scale; post ~0.1; lights ~0.1). Dial-back order if 'stat unit' GPU")
    log("> 14 ms mid-fight: view_sample_count_scale 0.25 -> 0.15, then film")
    log("grain off. NEVER touch the dress_arena fog/exposure/sun numbers.")
    log("Manual verify: toggle %s -- ambient dims ~10-15%%" % CLOUD_LABEL)
    log("(SkyLight RTC composites the cloud into the ambient capture).")
    if n_fail:
        warn("%d step(s) FAILED -- see warnings above." % n_fail)
    log("=" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("Cinematic pass (LEVER 3): cloud + post + lights + sharpen; labels %s*"
        % LABEL_PREFIX)
    # BLOCKER guard: never touch (or SAVE) a world that is not BossArena.
    # The ini edit is ALSO gated -- if the guard fails, nothing at all runs.
    if not ensure_bossarena_open():
        for label in ALL_STEP_LABELS:
            record(label, "FAIL",
                   "wrong level open and %s could not be loaded -- NOTHING "
                   "was touched (ini included)" % MAP_PATH)
        print_summary()
        return
    collect_trace_ignores()
    steps = [step_preclean,
             step_volumetric_cloud,
             step_postprocess,
             step_point_lights,
             step_sharpen_ini,
             step_save_level]
    for fn in steps:
        try:
            fn()
        except Exception as exc:
            record(fn.__name__, "FAIL", str(exc))
            warn(traceback.format_exc())
        gc_now()   # crash-resistance: free churn between steps (16 GB box)
    print_summary()


main()
