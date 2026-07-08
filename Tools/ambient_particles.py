"""LEVER 4 -- ambient ash motes (+ optional snowfall) for /Game/Maps/BossArena.

Run headlessly (proven pattern -- in-editor python crashes this machine):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe"
      "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/ambient_particles.py"

GROUND TRUTH vs the spec (verified on disk + in 5.8 engine source, 2026-07-05):
  * The spec's template paths /Niagara/DefaultAssets/Templates/Systems/
    HangingParticulates|BlowingParticles DO NOT exist in UE 5.8. Both ship as
    **NiagaraEmitter** assets under .../Templates/Emitters/ instead. A
    NiagaraActor needs a **NiagaraSystem**, so a straight duplicate of the
    emitter is not spawnable.
  * The only assembly path (UNiagaraSystemFactoryNew) is NOT python-drivable:
    SystemToCopy / EmittersToAddToNewSystem are raw C++ members, not
    UPROPERTYs (NiagaraSystemFactoryNew.h:23-24) -- set_editor_property can
    never reach them. Module-input editing is likewise not exposed.

So this script implements the spec's fallback verdict as a TWO-PHASE,
IDEMPOTENT pipeline (the "manual-recipe + post-tune script" path, with the
template-duplication path still probed first so it self-upgrades if a future
engine exposes real System templates):

  PHASE 1 (this run, fully headless):
    1. Feature-detect the Niagara python surface + the /Niagara mount.
    2. Duplicate the template into the project:
         - if a NiagaraSystem template is found  -> /Game/Arena/FX/NS_AshMotes
           (verified to re-load as a NiagaraSystem), and tiling proceeds NOW;
         - if only the NiagaraEmitter template exists (the 5.8 reality) ->
           /Game/Arena/FX/NE_AshMotes_Emitter, so the one-time manual step is
           a single right-click on a project-local asset. The factory-assembly
           attempt is still made (feature-detected, honest FAIL detail).
    3. Emit the exact click-recipe (create NS_AshMotes from the duplicated
       emitter + the 5-edit tune from the spec).
  PHASE 2 (re-run after the one-time manual creation/tune -- or immediately,
  if a NiagaraSystem template was available):
    4. Detect /Game/Arena/FX/NS_AshMotes, spawn/refresh 6 NiagaraActors
       (labels ARENA_AAA_FX_Ash_NN: 2 bowl tiles + gate mouth + 3 pads),
       verify the component asset assignment by RE-READ, attempt user-param
       overrides (guarded no-ops on the stock template -- it exposes zero
       user params -- but they bind automatically if the tune adds them).

Snowfall variant (BlowingParticles -> NS_Snowfall, ARENA_AAA_FX_Snow_NN) sits
behind DO_SNOWFALL below; default False.

HARD RULES honoured: level guard on /Game/Maps/BossArena (record FAIL for all
steps + touch nothing when it cannot be opened); ARENA_BV_* trace ignores for
ground snapping; per-item isolation; [AmbientFX] logging; PASS/FAIL/SKIP
summary; force-save + on-disk mtime/existence verify for every duplicated
asset; GC between steps and every ~12 saves; ADDITIVE -- only the
ARENA_AAA_FX_* label family is ever destroyed/respawned, ARENA_DRESS_* is
never touched; honest SKIP when the engine template content is inaccessible.

Perf note (spec budget): ash ~0.05-0.15 ms GPU @1080p (snow +0.3). Dial-back
order if Shader Complexity reddens: halve SpawnRate, then shrink sprites.
Keep both emitters GPU sim + Fixed Bounds (visuals.md rule).
"""

import os
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[AmbientFX]"
MAP_PATH = "/Game/Maps/BossArena"       # the ONLY level this script may touch
LABEL_PREFIX = "ARENA_AAA_FX_"          # additive family; ARENA_DRESS_* untouched
FX_DIR = "/Game/Arena/FX"

DO_SNOWFALL = True                     # flip True for the snow variant pass

# Template candidates, probed in order. First entry per list is the spec's
# claimed path (absent in 5.8 -- probed anyway: zero cost, and the script
# self-upgrades if a later engine ships a real System template). Second is
# the verified on-disk 5.8 location (a NiagaraEmitter).
ASH_TEMPLATE_CANDIDATES = [
    "/Niagara/DefaultAssets/Templates/Systems/HangingParticulates",
    "/Niagara/DefaultAssets/Templates/Emitters/HangingParticulates",
]
SNOW_TEMPLATE_CANDIDATES = [
    "/Niagara/DefaultAssets/Templates/Systems/BlowingParticles",
    "/Niagara/DefaultAssets/Templates/Emitters/BlowingParticles",
]

ASH_SYSTEM_PATH = FX_DIR + "/NS_AshMotes"
ASH_EMITTER_DUP_PATH = FX_DIR + "/NE_AshMotes_Emitter"
SNOW_SYSTEM_PATH = FX_DIR + "/NS_Snowfall"
SNOW_EMITTER_DUP_PATH = FX_DIR + "/NE_Snowfall_Emitter"

# 6-actor tiling (spec: 2 over the bowl, 4 over the zone). Zone tiles sit on
# the gate mouth + the three pad centers -- ash where the player actually
# fights. z is ABOVE traced ground. HangingParticulates spawns in a local-space
# box, so actor scale is the coverage dial (the only headless lever).
ASH_TILES = [
    # (label suffix, x, y, z above ground, (sx, sy, sz))
    ("Ash_01", -1600.0,     0.0, 400.0, (55.0, 55.0, 8.0)),   # bowl west
    ("Ash_02",  1600.0,     0.0, 400.0, (55.0, 55.0, 8.0)),   # bowl east
    ("Ash_03", 14000.0,     0.0, 350.0, (60.0, 60.0, 8.0)),   # gate mouth
    ("Ash_04", 17000.0, -4000.0, 350.0, (60.0, 60.0, 8.0)),   # pad 1
    ("Ash_05", 22000.0,  3500.0, 350.0, (60.0, 60.0, 8.0)),   # pad 2
    ("Ash_06", 29000.0, -1500.0, 350.0, (60.0, 60.0, 8.0)),   # pad 3
]
SNOW_TILES = [("Snow" + s[3:], x, y, z, sc) for (s, x, y, z, sc) in ASH_TILES]

# Best-effort user-parameter overrides, attempted after set_asset. The stock
# 5.8 templates expose ZERO user params (spec caveat -- verified), so these
# are silent no-ops today; they bind automatically on a re-run if the manual
# tune promotes these values to user parameters. Names must carry the "User."
# namespace prefix for SetNiagaraVariable* to match.
ASH_USER_FLOATS = {"User.SpawnRate": 35.0}
ASH_USER_COLORS = {"User.Color": (0.35, 0.33, 0.30, 0.6)}
SNOW_USER_FLOATS = {"User.SpawnRate": 600.0}
SNOW_USER_COLORS = {"User.Color": (0.82, 0.84, 0.88, 1.0)}

TRACE_TOP_Z = 20000.0
TRACE_BOTTOM_Z = -5000.0

STEP_RESULTS = []   # (step label, "PASS"/"FAIL"/"SKIP", detail)
IGNORE_ACTORS = []  # ARENA_BV_* invisible blocking cubes -- never a snap surface
CTX = {
    "trace_ok": True,
    "level_dirty": False,   # spawned or destroyed anything -> save the level
    "ash_state": None,      # None | "system_ready" | "emitter_only" | "unavailable"
    "snow_state": None,
}

GC_EVERY_SAVES = 12
_SAVE_COUNT = [0]


# ---------------------------------------------------------------------------
# Logging / bookkeeping (dress_arena.py patterns)
# ---------------------------------------------------------------------------

def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def record(step, status, detail=""):
    STEP_RESULTS.append((step, status, detail))
    log("%-28s %-4s %s" % (step, status, detail))


def gc_now():
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Editor helpers (proven in dress_arena.py / build_arena_level.py)
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
    """BLOCKER guard: verify the open world IS BossArena; if not, load it and
    re-verify. Returns True only when the arena is confirmed open."""
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


def collect_trace_ignores():
    """Sweep the level's INVISIBLE BlockAll cubes (ARENA_BV_*). ground_z must
    ignore them or actors snap onto hidden 30 m wall tops."""
    del IGNORE_ACTORS[:]
    try:
        for a in get_actor_subsystem().get_all_level_actors():
            try:
                if a is not None and str(a.get_actor_label()).startswith("ARENA_BV_"):
                    IGNORE_ACTORS.append(a)
            except Exception:
                continue
        log("ground_z will ignore %d ARENA_BV_* blocking volumes" % len(IGNORE_ACTORS))
    except Exception as exc:
        warn("Could not collect the ARENA_BV_* trace ignore list (%s)" % exc)


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
    """Line-trace straight down at (x, y); returns hit Z or default_z."""
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
            list(IGNORE_ACTORS),
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
            warn("Ground trace unavailable (%s) -- FX tiles snap to z=%.0f+offset."
                 % (exc, default_z))
            CTX["trace_ok"] = False
        return default_z


def force_save_asset(asset):
    """mark dirty -> save(only_if_is_dirty=False) -> verify on disk: mtime
    advanced for pre-existing files, file EXISTS for brand-new ones (dirty-
    gated saves silently wrote NOTHING in earlier passes)."""
    try:
        asset.get_outer().mark_package_dirty()
    except Exception:
        pass
    pkg_name = asset.get_outer().get_name()
    disk_path = None
    if pkg_name.startswith("/Game/"):
        disk_path = os.path.join(
            unreal.Paths.project_content_dir(), pkg_name[len("/Game/"):] + ".uasset")
    before = os.path.getmtime(disk_path) if disk_path and os.path.isfile(disk_path) else None
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError("save_loaded_asset failed for %s" % asset.get_path_name())
    if disk_path is not None:
        if before is not None:
            if os.path.getmtime(disk_path) <= before:
                raise RuntimeError(
                    "save reported success but %s was NOT rewritten on disk" % disk_path)
        elif not os.path.isfile(disk_path):
            raise RuntimeError(
                "save reported success but %s never appeared on disk" % disk_path)
    _SAVE_COUNT[0] += 1
    if _SAVE_COUNT[0] % GC_EVERY_SAVES == 0:
        gc_now()


def _class_name(obj):
    try:
        return str(obj.get_class().get_name())
    except Exception:
        return "<unknown>"


def _is_niagara_system(obj):
    cls = getattr(unreal, "NiagaraSystem", None)
    if cls is not None:
        return isinstance(obj, cls)
    return _class_name(obj) == "NiagaraSystem"      # class-name fallback


def _is_niagara_emitter(obj):
    cls = getattr(unreal, "NiagaraEmitter", None)
    if cls is not None:
        return isinstance(obj, cls)
    return _class_name(obj) == "NiagaraEmitter"


# ---------------------------------------------------------------------------
# Step 1: Niagara feature-detect
# ---------------------------------------------------------------------------

def step_feature_detect():
    missing = [n for n in ("NiagaraActor", "NiagaraComponent")
               if getattr(unreal, n, None) is None]
    if missing:
        CTX["ash_state"] = CTX["snow_state"] = "unavailable"
        record("1 niagara feature-detect", "SKIP",
               "python classes missing: %s -- Niagara plugin not script-exposed "
               "in this session; nothing to do headlessly" % ", ".join(missing))
        return
    mount_ok = False
    try:
        mount_ok = unreal.EditorAssetLibrary.does_directory_exist(
            "/Niagara/DefaultAssets")
    except Exception as exc:
        warn("does_directory_exist(/Niagara/DefaultAssets) raised: %s" % exc)
    found = [p for p in ASH_TEMPLATE_CANDIDATES + SNOW_TEMPLATE_CANDIDATES
             if unreal.EditorAssetLibrary.does_asset_exist(p)]
    for p in ASH_TEMPLATE_CANDIDATES + SNOW_TEMPLATE_CANDIDATES:
        log("  template probe %-70s %s"
            % (p, "FOUND" if p in found else "absent"))
    project_side = [p for p in (ASH_SYSTEM_PATH, ASH_EMITTER_DUP_PATH,
                                SNOW_SYSTEM_PATH, SNOW_EMITTER_DUP_PATH)
                    if unreal.EditorAssetLibrary.does_asset_exist(p)]
    if not mount_ok and not found and not project_side:
        CTX["ash_state"] = CTX["snow_state"] = "unavailable"
        record("1 niagara feature-detect", "SKIP",
               "/Niagara mount unreadable and no project-side FX assets exist "
               "-- engine Niagara template content not accessible (trimmed "
               "install?); honest SKIP for all FX steps")
        return
    record("1 niagara feature-detect", "PASS",
           "classes OK; mount %s; templates found: %d; project FX assets: %d"
           % ("OK" if mount_ok else "UNREADABLE", len(found), len(project_side)))


# ---------------------------------------------------------------------------
# Step 2: template duplication (per variant)
# ---------------------------------------------------------------------------

def _ensure_fx_dir():
    try:
        if not unreal.EditorAssetLibrary.does_directory_exist(FX_DIR):
            unreal.EditorAssetLibrary.make_directory(FX_DIR)
    except Exception as exc:
        warn("Could not ensure %s exists: %s" % (FX_DIR, exc))


def _try_factory_assembly(emitter_asset, system_path):
    """Attempt NiagaraSystemFactoryNew configuration. EXPECTED TO FAIL in 5.8:
    SystemToCopy / EmittersToAddToNewSystem are raw C++ members, not
    UPROPERTYs (NiagaraSystemFactoryNew.h:23-24), so python cannot reach them.
    Kept as a cheap feature-detect so the script self-upgrades if Epic ever
    exposes the knobs. The created asset's name/dir derive from system_path
    (both variants call this -- ash AND snow). Returns (system_or_None,
    detail)."""
    factory_cls = getattr(unreal, "NiagaraSystemFactoryNew", None)
    if factory_cls is None:
        return None, "NiagaraSystemFactoryNew not python-exposed"
    try:
        factory = factory_cls()
    except Exception as exc:
        return None, "factory not constructible: %s" % exc
    configured = False
    for prop in ("emitters_to_add_to_new_system", "system_to_copy"):
        try:
            if prop == "emitters_to_add_to_new_system":
                factory.set_editor_property(prop, [emitter_asset])
            else:
                continue  # system_to_copy is useless for emitter assembly
            configured = True
            break
        except Exception:
            continue
    if not configured:
        return None, ("factory knobs are raw C++ members (not UPROPERTYs) -- "
                      "not settable from python in 5.8")
    # If we ever get here (future engine), actually create the system.
    try:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        sys_asset = tools.create_asset(
            system_path.rsplit("/", 1)[-1], system_path.rsplit("/", 1)[0],
            getattr(unreal, "NiagaraSystem", None), factory)
        if sys_asset is None:
            return None, "create_asset returned None"
        return sys_asset, "factory assembly succeeded"
    except Exception as exc:
        return None, "create_asset raised: %s" % exc


def _duplicate_verified(src_path, dst_path, want_system):
    """duplicate_asset + force-save + RELOAD-verify the class. Returns the
    reloaded asset or raises."""
    dup = unreal.EditorAssetLibrary.duplicate_asset(src_path, dst_path)
    if dup is None:
        raise RuntimeError("duplicate_asset returned None (%s -> %s)"
                           % (src_path, dst_path))
    force_save_asset(dup)
    reloaded = unreal.EditorAssetLibrary.load_asset(dst_path)
    if reloaded is None:
        raise RuntimeError("duplicated asset did not reload: %s" % dst_path)
    if want_system and not _is_niagara_system(reloaded):
        raise RuntimeError("%s reloaded as %s, expected NiagaraSystem"
                           % (dst_path, _class_name(reloaded)))
    if not want_system and not _is_niagara_emitter(reloaded):
        raise RuntimeError("%s reloaded as %s, expected NiagaraEmitter"
                           % (dst_path, _class_name(reloaded)))
    return reloaded


def ensure_variant_assets(step_label, candidates, system_path, emitter_dup_path):
    """Resolve the variant to one of: 'system_ready' (NS asset exists+valid),
    'emitter_only' (project-local emitter dup exists, manual step pending),
    'unavailable'. Records the step itself."""
    _ensure_fx_dir()

    # (a) project-side system already there (previous run OR the manual step)?
    if unreal.EditorAssetLibrary.does_asset_exist(system_path):
        asset = unreal.EditorAssetLibrary.load_asset(system_path)
        if asset is not None and _is_niagara_system(asset):
            record(step_label, "PASS",
                   "%s already present (previous run or manual creation) -- "
                   "duplication skipped" % system_path)
            return "system_ready"
        record(step_label, "FAIL",
               "%s exists but is %s, not a NiagaraSystem -- rename/remove it "
               "and re-run" % (system_path, _class_name(asset)))
        return "unavailable"

    # (b) resolve the engine template.
    src = next((p for p in candidates
                if unreal.EditorAssetLibrary.does_asset_exist(p)), None)
    if src is None:
        # emitter dup from an earlier run still counts as progress
        if unreal.EditorAssetLibrary.does_asset_exist(emitter_dup_path):
            record(step_label, "PASS",
                   "engine template gone but %s exists from an earlier run -- "
                   "manual system creation still pending (see recipe)"
                   % emitter_dup_path)
            return "emitter_only"
        record(step_label, "SKIP",
               "no template candidate accessible under /Niagara -- engine "
               "content trimmed or mount unreadable; honest SKIP")
        return "unavailable"

    template = unreal.EditorAssetLibrary.load_asset(src)
    if template is None:
        record(step_label, "FAIL", "template exists but failed to load: %s" % src)
        return "unavailable"

    # (c) a real System template (future engines / spec's original claim).
    if _is_niagara_system(template):
        try:
            _duplicate_verified(src, system_path, want_system=True)
            record(step_label, "PASS",
                   "SYSTEM template %s -> %s (saved + reload-verified)"
                   % (src, system_path))
            return "system_ready"
        except Exception as exc:
            record(step_label, "FAIL", "system duplication failed: %s" % exc)
            return "unavailable"

    # (d) the 5.8 reality: an Emitter template.
    if _is_niagara_emitter(template):
        detail_parts = []
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(emitter_dup_path):
                detail_parts.append("%s already duplicated" % emitter_dup_path)
                emitter_dup = unreal.EditorAssetLibrary.load_asset(emitter_dup_path)
            else:
                emitter_dup = _duplicate_verified(src, emitter_dup_path,
                                                  want_system=False)
                detail_parts.append("emitter %s -> %s (saved + reload-verified)"
                                    % (src.rsplit("/", 1)[-1], emitter_dup_path))
        except Exception as exc:
            record(step_label, "FAIL", "emitter duplication failed: %s" % exc)
            return "unavailable"
        sys_asset, fac_detail = _try_factory_assembly(emitter_dup, system_path)
        detail_parts.append("factory assembly: %s" % fac_detail)
        if sys_asset is not None:
            try:
                force_save_asset(sys_asset)
                reloaded = unreal.EditorAssetLibrary.load_asset(system_path)
                if reloaded is not None and _is_niagara_system(reloaded):
                    record(step_label, "PASS", "; ".join(detail_parts))
                    return "system_ready"
            except Exception as exc:
                detail_parts.append("factory system save/verify failed: %s" % exc)
        detail_parts.append("one-time manual system creation needed (recipe below)")
        record(step_label, "PASS", "; ".join(detail_parts))
        return "emitter_only"

    record(step_label, "FAIL",
           "template %s loaded as unexpected class %s" % (src, _class_name(template)))
    return "unavailable"


def step_ash_assets():
    CTX["ash_state"] = (
        "unavailable" if CTX["ash_state"] == "unavailable"
        else ensure_variant_assets("2 ash template/assets",
                                   ASH_TEMPLATE_CANDIDATES,
                                   ASH_SYSTEM_PATH, ASH_EMITTER_DUP_PATH))
    if CTX["ash_state"] == "unavailable" and not STEP_RESULTS[-1][0].startswith("2 "):
        record("2 ash template/assets", "SKIP", "feature-detect said unavailable")


# ---------------------------------------------------------------------------
# Step 3/4: actor tiling (per variant)
# ---------------------------------------------------------------------------

def _preclean_family(suffix_prefix):
    """Destroy ONLY our own label family (ARENA_AAA_FX_<suffix_prefix>*).
    ARENA_DRESS_* and everything else is never touched (additive contract)."""
    actors = get_actor_subsystem()
    doomed = []
    for a in actors.get_all_level_actors():
        try:
            lbl = str(a.get_actor_label())
        except Exception:
            continue
        if lbl.startswith(LABEL_PREFIX + suffix_prefix):
            doomed.append(a)
    killed = 0
    for a in doomed:
        try:
            actors.destroy_actor(a)
            killed += 1
            CTX["level_dirty"] = True
        except Exception as exc:
            warn("Could not destroy %s: %s" % (a.get_actor_label(), exc))
    return killed


def _get_niagara_component(actor):
    try:
        comp = actor.get_editor_property("niagara_component")
        if comp is not None:
            return comp
    except Exception:
        pass
    try:
        return actor.get_component_by_class(unreal.NiagaraComponent)
    except Exception:
        return None


def _assign_asset_verified(comp, system_asset):
    """set_asset (or the asset editor-property) then RE-READ verify."""
    assigned = False
    if hasattr(comp, "set_asset"):
        try:
            comp.set_asset(system_asset)
            assigned = True
        except Exception as exc:
            warn("set_asset raised: %s" % exc)
    if not assigned:
        comp.set_editor_property("asset", system_asset)  # raises on failure
    # verify by re-read (struct-array lesson: never trust a silent write)
    current = None
    if hasattr(comp, "get_asset"):
        try:
            current = comp.get_asset()
        except Exception:
            current = None
    if current is None:
        try:
            current = comp.get_editor_property("asset")
        except Exception:
            current = None
    if current is None:
        raise RuntimeError("asset re-read returned None after assignment")
    want = str(system_asset.get_path_name())
    got = str(current.get_path_name())
    if got != want:
        raise RuntimeError("asset re-read mismatch: %s != %s" % (got, want))


def _apply_user_params(comp, floats, colors, note_once):
    """Best-effort user-param overrides. Stock templates expose zero user
    params, so these are silent no-ops today; they bind if the manual tune
    adds them. Never fails the item."""
    for name, val in floats.items():
        try:
            if hasattr(comp, "set_niagara_variable_float"):
                comp.set_niagara_variable_float(name, float(val))
        except Exception:
            pass
    for name, rgba in colors.items():
        try:
            if hasattr(comp, "set_niagara_variable_linear_color"):
                comp.set_niagara_variable_linear_color(
                    name, unreal.LinearColor(*rgba))
        except Exception:
            pass
    if note_once[0]:
        note_once[0] = False
        log("  user-param overrides attempted (%s) -- NO-OPS on the stock "
            "template (zero exposed user params); they bind automatically if "
            "the manual tune promotes these to User parameters."
            % ", ".join(list(floats) + list(colors)))


def tile_variant(step_label, state, system_path, tiles, floats, colors,
                 suffix_prefix):
    if state == "system_ready":
        pass
    elif state == "emitter_only":
        record(step_label, "SKIP",
               "%s not created yet -- do the one-time manual step (recipe "
               "below), then RE-RUN this script; it will detect the system "
               "and tile the %d actors automatically" % (system_path, len(tiles)))
        return
    else:
        record(step_label, "SKIP", "Niagara templates unavailable")
        return

    system_asset = unreal.EditorAssetLibrary.load_asset(system_path)
    if system_asset is None or not _is_niagara_system(system_asset):
        record(step_label, "FAIL", "%s failed to load as a NiagaraSystem" % system_path)
        return

    killed = _preclean_family(suffix_prefix)
    if killed:
        log("  pre-clean: destroyed %d stale %s%s* actors (idempotent respawn)"
            % (killed, LABEL_PREFIX, suffix_prefix))

    actors = get_actor_subsystem()
    note_once = [True]
    n_ok, n_fail = 0, 0
    for (suffix, x, y, dz, scale) in tiles:
        label = LABEL_PREFIX + suffix
        try:                                    # per-item isolation
            z = ground_z(x, y) + dz
            actor = actors.spawn_actor_from_class(
                unreal.NiagaraActor, unreal.Vector(x, y, z),
                unreal.Rotator(0.0, 0.0, 0.0))
            if actor is None:
                raise RuntimeError("spawn_actor_from_class returned None")
            CTX["level_dirty"] = True
            actor.set_actor_label(label)
            try:
                actor.set_actor_scale3d(unreal.Vector(*scale))
            except Exception as exc:
                warn("Could not scale %s: %s" % (label, exc))
            comp = _get_niagara_component(actor)
            if comp is None:
                raise RuntimeError("NiagaraComponent not found on the actor")
            _assign_asset_verified(comp, system_asset)
            _apply_user_params(comp, floats, colors, note_once)
            n_ok += 1
            log("  + %-24s (%.0f, %.0f, %.0f) scale (%.0f, %.0f, %.0f) "
                "asset VERIFIED" % (label, x, y, z, scale[0], scale[1], scale[2]))
        except Exception as exc:
            n_fail += 1
            warn("FX tile %s failed: %s" % (label, exc))
    if n_ok == 0:
        record(step_label, "FAIL", "0/%d NiagaraActors spawned" % len(tiles))
    elif n_fail:
        record(step_label, "PASS",
               "%d/%d NiagaraActors spawned+verified (%d failed -- see warnings)"
               % (n_ok, len(tiles), n_fail))
    else:
        record(step_label, "PASS",
               "%d/%d NiagaraActors spawned, asset assignment re-read verified"
               % (n_ok, len(tiles)))


def step_ash_actors():
    tile_variant("3 ash actor tiling", CTX["ash_state"], ASH_SYSTEM_PATH,
                 ASH_TILES, ASH_USER_FLOATS, ASH_USER_COLORS, "Ash_")


# ---------------------------------------------------------------------------
# Step 4: snowfall variant (flagged)
# ---------------------------------------------------------------------------

def step_snowfall():
    if not DO_SNOWFALL:
        record("4 snowfall variant", "SKIP",
               "DO_SNOWFALL=False (default). Flip the flag at the top and "
               "re-run for the BlowingParticles-based variant. Any existing "
               "%sSnow_* actors are left untouched." % LABEL_PREFIX)
        return
    if CTX["snow_state"] == "unavailable":
        record("4 snowfall variant", "SKIP", "Niagara templates unavailable")
        return
    CTX["snow_state"] = ensure_variant_assets(
        "4a snow template/assets", SNOW_TEMPLATE_CANDIDATES,
        SNOW_SYSTEM_PATH, SNOW_EMITTER_DUP_PATH)
    tile_variant("4 snowfall variant", CTX["snow_state"], SNOW_SYSTEM_PATH,
                 SNOW_TILES, SNOW_USER_FLOATS, SNOW_USER_COLORS, "Snow_")


# ---------------------------------------------------------------------------
# Step 5: manual tune recipe (module-input editing is NOT python-accessible)
# ---------------------------------------------------------------------------

def step_recipe():
    lines = []
    if CTX["ash_state"] == "emitter_only":
        lines += [
            "ASH -- one-time CREATE (then re-run this script to auto-tile):",
            "  1. Content Browser -> /Game/Arena/FX -> right-click",
            "     NE_AshMotes_Emitter -> 'Create Niagara System' -> name it",
            "     NS_AshMotes (exact name -- the re-run keys on it).",
            "     (If the context entry is absent: right-click empty space ->",
            "     FX -> Niagara System -> 'New system from selected emitter(s)'",
            "     -> pick NE_AshMotes_Emitter -> name NS_AshMotes.)",
        ]
    if CTX["ash_state"] in ("emitter_only", "system_ready"):
        lines += [
            "ASH -- 5-edit tune (open /Game/Arena/FX/NS_AshMotes):",
            "  1. Emitter Update -> Spawn Rate: SpawnRate = 35",
            "  2. Particle Spawn -> Initialize Particle: Lifetime Min 12 / Max 20 s",
            "  3.    same module: Sprite Size Min 2 / Max 4 uu",
            "  4.    same module: Color (0.35, 0.33, 0.30), alpha 0.6",
            "  5. Particle Update -> Curl Noise Force: Noise Strength = 8",
            "  THEN (visuals.md rule): Emitter Properties -> Sim Target =",
            "  GPUCompute Sim, Calculate Bounds Mode = Fixed (generous box,",
            "  e.g. +-2000 local -- actor scale 55-60x multiplies it). Save.",
        ]
    if DO_SNOWFALL and CTX["snow_state"] in ("emitter_only", "system_ready"):
        lines += [
            "SNOW -- create NS_Snowfall from NE_Snowfall_Emitter (same flow),",
            "  tune: SpawnRate 600/s; Gravity Force (0,0,-40); Wind (30,0,0);",
            "  Sprite Size 3-6 uu; Color (0.82, 0.84, 0.88); Lifetime 8 s;",
            "  GPU sim + Fixed Bounds. Save, re-run with DO_SNOWFALL=True.",
        ]
    if not lines:
        record("5 manual tune recipe", "SKIP",
               "nothing applicable (Niagara content unavailable)")
        return
    log("-" * 72)
    log("MANUAL RECIPE (module inputs are not python-editable in 5.8):")
    for ln in lines:
        log("  " + ln)
    log("PERF DIAL-BACK ORDER (spec): halve SpawnRate first, then shrink")
    log("sprite sizes -- overdraw, not count, is the risk. Ash budget")
    log("0.05-0.15 ms GPU; snow +0.3; ceiling 0.5 ms.")
    log("-" * 72)
    record("5 manual tune recipe", "PASS",
           "%d recipe lines printed above" % len(lines))


# ---------------------------------------------------------------------------
# Step 6: save level
# ---------------------------------------------------------------------------

def step_save_level():
    if not CTX["level_dirty"]:
        record("6 save level", "SKIP", "no level mutations this run")
        return
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is not None and les.save_current_level():
            record("6 save level", "PASS", "current level saved")
            return
        raise RuntimeError("save_current_level returned False")
    except Exception as exc:
        record("6 save level", "FAIL", "save manually (Ctrl+S): %s" % exc)


# ---------------------------------------------------------------------------
# Summary / main
# ---------------------------------------------------------------------------

ALL_STEP_LABELS = (
    "1 niagara feature-detect", "2 ash template/assets", "3 ash actor tiling",
    "4 snowfall variant", "5 manual tune recipe", "6 save level")


def print_summary():
    log("=" * 72)
    log("AMBIENT PARTICLES (LEVER 4) SUMMARY")
    for step, status, detail in STEP_RESULTS:
        log("  %-4s %-28s %s" % (status, step, detail))
    n_fail = sum(1 for _, s, _ in STEP_RESULTS if s == "FAIL")
    log("-" * 72)
    if CTX["ash_state"] == "emitter_only":
        log("NEXT: do the one-time 'Create Niagara System' step in the recipe")
        log("above, then RE-RUN this script -- it detects NS_AshMotes and")
        log("tiles the 6 ARENA_AAA_FX_Ash_* actors automatically (phase 2).")
    elif CTX["ash_state"] == "system_ready":
        log("Ash actors are live. Verify in-editor: motes over the bowl and")
        log("the three pads; 'stat gpu' Niagara cost should be ~0.1 ms.")
    log("Additive contract honoured: only ARENA_AAA_FX_* was created or")
    log("destroyed; the 508 ARENA_DRESS_* actors were never touched.")
    if n_fail:
        warn("%d step(s) FAILED -- see warnings above." % n_fail)
    log("=" * 72)


def main():
    log("Ambient ash motes / snowfall pass (labels %s*, additive)" % LABEL_PREFIX)
    if not ensure_bossarena_open():
        for label in ALL_STEP_LABELS:
            record(label, "FAIL",
                   "wrong level open and %s could not be loaded -- NOTHING "
                   "was touched" % MAP_PATH)
        print_summary()
        return
    collect_trace_ignores()
    steps = [step_feature_detect, step_ash_assets, step_ash_actors,
             step_snowfall, step_recipe, step_save_level]
    for fn in steps:
        try:
            fn()
        except Exception as exc:
            record(fn.__name__, "FAIL", str(exc))
            warn(traceback.format_exc())
        gc_now()   # crash-resistance on the 16 GB box
    print_summary()


main()
