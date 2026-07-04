"""Build the BossArena level end-to-end from pre-exported source assets.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/build_arena_level.py"
  (or Tools -> Execute Python Script... and pick this file)

Inputs (see visuals.md 'Pipeline B' / 'Set dressing and bounds'):
  D:/GAME_CORE 5.8/SourceArt/Arena/SM_ArenaTerrain.fbx     (200x200 m, meters, transforms applied)
  D:/GAME_CORE 5.8/SourceArt/Arena/SM_Rock_01..06.fbx      (pivot at mesh base)
  D:/GAME_CORE 5.8/SourceArt/Arena/SM_Monolith.fbx         (pivot at mesh base)
  D:/GAME_CORE 5.8/SourceArt/Arena/SM_PatrolZone.fbx       (OPTIONAL -- world-space meters like
        the terrain, place at origin; zone x 100..350 m, y -85..85 m; not exported
        yet = the zone steps SKIP and the arena-only build is unaffected)
  D:/GAME_CORE 5.8/SourceArt/Textures/manifest.json        {"floor"|"rock"|"dirt":
        {"slug", "diff", "nor_dx", "arm"}}  -- absolute paths to 2K JPGs,
        ARM = AO/Rough/Metal packed in R/G/B, normals are DirectX (no green flip).

What it does (each step isolated; one failure never aborts the rest):
  1. Import the 8 FBXs      -> /Game/Arena/Meshes   (Nanite, no lightmap UVs, no auto collision)
  2. Complex-as-simple collision on all 8 meshes
  3. Import the 9 textures  -> /Game/Arena/Textures (diff sRGB, nor_dx TC_Normalmap, arm TC_Masks)
  4. Build M_Terrain        -> /Game/Arena/Materials (world-aligned floor/rock slope blend;
                               falls back to a simple world-XY-mapped material on ANY failure)
  5. Create (or reopen + clean) /Game/Maps/BossArena
  6. Spawn: terrain, rock ring + accents, monolith, lighting rig, blocking ring + entrance
     gate, PlayerStart (everything labelled 'ARENA_*' so re-runs can clean up)
  6f-6i. Patrol zone (M3): import + spawn SM_PatrolZone at origin, patrol
     TargetPoints + minion-spawn markers on the three encounter pads, zone
     perimeter backstop cubes, and removal of ARENA_BV_EntranceGate (the pass
     becomes a real route). Every zone step SKIPs cleanly while the FBX is absent.
  6j. NavMeshBoundsVolume over the WHOLE map via the (parallel-developed) C++
     helper unreal.ArenaEditorTools.spawn_nav_bounds_volume -- feature-detected;
     absent = SKIP + the manual drag note (python-spawned volumes get no brush).
  6k. Minion bootstrap (M3, placeholder visuals until the Stone Golem pack):
     duplicated AM_Minion_* montages + DA_MinionCombo + BP_Minion (parent
     NPCMinionCharacter) + MinionClass/PatrolPoints wiring on the three
     ARENA_MinionSpawn_P* spawners. Every sub-goal degrades to SKIP + a
     precise manual-note line in the summary; nothing here can fail the build.
  7. Save /Game/Arena and the map
  8. Print PASS/FAIL/SKIP summary + remaining manual steps
"""

import json
import math
import os
import random
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

SOURCE_ARENA_DIR = r"D:\GAME_CORE 5.8\SourceArt\Arena"
MANIFEST_PATH = r"D:\GAME_CORE 5.8\SourceArt\Textures\manifest.json"

MESH_DIR = "/Game/Arena/Meshes"
TEX_DIR = "/Game/Arena/Textures"
MAT_DIR = "/Game/Arena/Materials"
MAP_PATH = "/Game/Maps/BossArena"

TERRAIN_NAME = "SM_ArenaTerrain"
MESH_NAMES = [TERRAIN_NAME] + ["SM_Rock_%02d" % i for i in range(1, 7)] + ["SM_Monolith"]

# manifest role -> imported asset base name T_<role>_<kind>
TEX_ROLES = ("floor", "rock", "dirt")
TEX_KINDS = ("diff", "nor_dx", "arm")

WORLD_ALIGNED_TEXTURE_FN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedTexture"
WORLD_ALIGNED_NORMAL_FN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedNormal"
CUBE_MESH = "/Engine/BasicShapes/Cube"

TEXTURE_SIZE_UU = 350.0  # one repeat per 3.5 m

# Expected terrain footprint: 200 m -> 20000 UU, +-5 %
TERRAIN_EXPECTED_UU = 20000.0
TERRAIN_TOLERANCE = 0.05

# Rock ring
ENTRANCE_HALF_ANGLE_DEG = 18.0  # entrance pass centered on +X
RING_R_MIN, RING_R_MAX = 4500.0, 6800.0
ACCENT_R_MIN, ACCENT_R_MAX = 2800.0, 3800.0
WALL_RADIUS = 7800.0
WALL_COUNT = 16

# Patrol zone (M3). SM_PatrolZone.fbx is authored in WORLD-space meters exactly
# like the terrain, so it spawns at origin with no offset. Geometry contract:
# zone rectangle x 100..350 m, y -85..85 m (UU: x 10000..35000, y -8500..8500),
# connected through the existing +X entrance canyon (corridor x 100..135 m,
# |y| < 12 m); three flattened encounter pads (radius ~1800 UU) at the centers
# below; perimeter walls on the north/south/east edges are IN the mesh -- the
# BV cubes in step 6i are a fall-out-of-world backstop just inside them.
ZONE_NAME = "SM_PatrolZone"
ZONE_EXPECTED_UU = (25000.0, 17000.0)  # footprint sanity check, +-5 %
ZONE_PAD_CENTERS = [(17000.0, -4000.0), (22000.0, 3500.0), (29000.0, -1500.0)]
ZONE_PATROL_RADIUS = 1200.0  # TargetPoint ring inside each ~1800 UU pad
MINION_SPAWNER_CLASS_PATH = "/Script/GAME_CORE.MinionEncounterSpawner"

# Nav bounds (6j): one volume over the WHOLE map (arena bowl + patrol zone).
NAV_BOUNDS_LABEL = "ARENA_NavBounds"
NAV_BOUNDS_CENTER = (12500.0, 0.0, 1000.0)
NAV_BOUNDS_EXTENT = (26000.0, 11000.0, 3000.0)  # half-sizes, UU

# Minion bootstrap (6k). Placeholder visuals: UEFN mannequin + hero AnimBP
# until the user drops in their Stone Golem pack.
MINION_DIR = "/Game/Arena/Minions"
MINION_CLASS_PATH = "/Script/GAME_CORE.NPCMinionCharacter"
COMBAT_COMPONENT_CLASS_PATH = "/Script/GAME_CORE.CombatComponent"
COMBAT_ANIM_CONFIG_CLASS_PATH = "/Script/GAME_CORE.CombatAnimConfig"
SK_MANNEQUIN_PATH = "/Game/Characters/UEFN_Mannequin/Meshes/SK_UEFN_Mannequin"
SKM_MANNEQUIN_PATH = "/Game/Characters/UEFN_Mannequin/Meshes/SKM_UEFN_Mannequin"
COMBO01_DIR = "/Game/Retargeted_Animations/Combo_01"
ATTACK_MONTAGE_FALLBACK = COMBO01_DIR + "/AM_Combo_01_Hit1"
DEATH_MONTAGE_CANDIDATES = [
    "/Game/Retargeted_Animations/Knock_Down_Death_Seq_Montage",
    "/Game/Retargeted_Animations/Hit_Death_Seq_Montage",
]
RETARGETED_ANIM_DIR = "/Game/Retargeted_Animations"
HERO_BP_GEN_CLASS = "/Game/Blueprints/BP_NeuralHero.BP_NeuralHero_C"
# Standard mannequin alignment inside a Character capsule; overridden by
# BP_NeuralHero's own mesh offsets when those are readable at run time.
MINION_MESH_REL_Z = -88.0
MINION_MESH_REL_YAW = -90.0

STEP_RESULTS = []  # (step label, "PASS"/"FAIL"/"SKIP", detail)

# Shared state between steps
CTX = {
    "textures": {},   # "floor_diff" -> unreal.Texture2D
    "material": None, # M_Terrain
    "material_mode": "none",  # "rich" | "fallback" | "failed" | "none"
    "trace_ok": True, # flips false after first ground-trace failure (log once)
    "level_ready": False,  # set by step5; gates every step that spawns/saves the level
    "zone_available": False,  # set by step6f; zone mesh imported (or pre-existing)
    "zone_actor": None,       # set by step6g; gates steps 6h/6i + the navmesh note
    "extra_manual": [],       # 6j manual follow-ups (nav bounds drag)
    "minion_manual": [],      # 6k per-sub-goal manual follow-ups
    "minion_bp_class": None,  # BP_Minion generated class (or C++ fallback), for 6k.5
}


def log(msg):
    unreal.log("[ArenaBuilder] " + str(msg))


def warn(msg):
    unreal.log_warning("[ArenaBuilder] " + str(msg))


class StepSkip(Exception):
    """Raised inside a step to mark it SKIP -- a deliberate no-op (missing
    optional input), not a failure. run_step records it without a traceback."""


def record(label, ok, detail=""):
    STEP_RESULTS.append((label, "PASS" if ok else "FAIL", detail))


def record_skip(label, detail=""):
    STEP_RESULTS.append((label, "SKIP", detail))


def run_step(label, fn):
    """Run one numbered step; never let its exception escape."""
    try:
        detail = fn()
        record(label, True, detail or "")
        log("STEP OK   : %s%s" % (label, (" -- " + detail) if detail else ""))
    except StepSkip as why:
        record_skip(label, str(why))
        log("STEP SKIP : %s -- %s" % (label, why))
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all per step
        record(label, False, str(exc))
        warn("STEP FAIL : %s -- %s" % (label, exc))
        warn(traceback.format_exc())


# ---------------------------------------------------------------------------
# Small editor helpers (feature-detected for 5.8)
# ---------------------------------------------------------------------------

def get_actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def get_level_subsystem():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def get_editor_world():
    """Editor world for traces. Prefer UnrealEditorSubsystem; fall back to the
    deprecated EditorLevelLibrary only if the subsystem is missing/renamed."""
    if hasattr(unreal, "UnrealEditorSubsystem"):
        try:
            sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            if sub is not None:
                world = sub.get_editor_world()
                if world is not None:
                    return world
        except Exception:
            pass
    # Deprecated fallback (still shipped in 5.x); comment per project API rules.
    if hasattr(unreal, "EditorLevelLibrary"):
        try:
            return unreal.EditorLevelLibrary.get_editor_world()
        except Exception:
            pass
    return None


def _hit_result_z(hit):
    """Z of a HitResult's hit point, tolerant of 5.x python field renames
    (5.8 dropped both `location` and `impact_point`)."""
    for name in ("location", "impact_point", "impact_location", "hit_location"):
        try:
            v = hit.get_editor_property(name)
            if v is not None and hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    # discovery fallback: any location-ish vector field on the struct
    for name in [n for n in dir(hit)
                 if ("impact" in n or "location" in n) and not n.startswith("_")]:
        try:
            v = getattr(hit, name)
            if hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    raise AttributeError(
        "no location-like field on HitResult; available: %s"
        % [n for n in dir(hit) if not n.startswith("__")][:40])


def ground_z(x, y, ignore_actors=None, default_z=0.0):
    """Line-trace straight down at (x, y) and return the hit Z.

    Traces (x, y, 5000) -> (x, y, -2000) against complex collision. If tracing
    is unavailable or misses, returns default_z (mid-zone relief is only
    1-2 m, so z=0 is an acceptable degradation -- logged once)."""
    if not CTX["trace_ok"]:
        return default_z
    try:
        world = get_editor_world()
        if world is None:
            raise RuntimeError("no editor world available for tracing")
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            unreal.Vector(x, y, 5000.0),
            unreal.Vector(x, y, -2000.0),
            getattr(unreal.TraceTypeQuery, "ECC_VISIBILITY",
                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1),  # Visibility (5.8 renamed the entry)
            True,  # trace complex
            ignore_actors or [],
            unreal.DrawDebugTrace.NONE,
            True,  # ignore self (n/a, no self)
        )
        # Python convention: bool-return + out-param functions return the
        # HitResult on success and None on a miss. Handle a tuple too, in
        # case the binding changes shape.
        if isinstance(hit, tuple):
            hit = hit[-1] if hit and hit[0] else None
        if hit is None:
            return default_z
        return _hit_result_z(hit)
    except Exception as exc:
        if CTX["trace_ok"]:
            warn("Ground trace unavailable (%s) -- snapping everything to z=0 "
                 "instead. Mid-zone relief is 1-2 m, so eyeball-fix any floater "
                 "rocks manually." % exc)
            CTX["trace_ok"] = False
        return default_z


def set_prop_if_exists(obj, name, value, context=""):
    """set_editor_property guarded for properties that may have moved in 5.8."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s" % (name, (" on " + context) if context else "", exc))
        return False


def get_static_mesh_component(actor):
    """StaticMeshActor component, tolerant of accessor differences."""
    try:
        comp = actor.static_mesh_component
        if comp is not None:
            return comp
    except Exception:
        pass
    return actor.get_component_by_class(unreal.StaticMeshComponent)


def label_actor(actor, label):
    actor.set_actor_label(label)
    return actor


def _require_level_ready():
    """Refuse to touch the open level unless step 5 succeeded.

    Step isolation means independent failures don't abort unrelated steps --
    NOT that dependent steps run against the wrong world. Without this gate a
    failed step 5 would let steps 6a-6e spawn the whole arena (and step 7 save
    it) into whatever level happens to be open in the editor."""
    if not CTX.get("level_ready"):
        raise RuntimeError(
            "level step failed, refusing to spawn into the open level "
            "(BossArena was not created/loaded)")


# ---------------------------------------------------------------------------
# Step 1: FBX import
# ---------------------------------------------------------------------------

def step1_import_meshes():
    imported, skipped, missing = [], [], []
    tasks = []

    for name in MESH_NAMES:
        asset_path = "%s/%s" % (MESH_DIR, name)
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            log("Mesh already imported, skipping: %s" % asset_path)
            skipped.append(name)
            continue

        fbx = os.path.join(SOURCE_ARENA_DIR, name + ".fbx")
        if not os.path.isfile(fbx):
            warn("MISSING SOURCE FILE: %s -- mesh will be absent from the level." % fbx)
            missing.append(name)
            continue

        ui = unreal.FbxImportUI()
        ui.set_editor_property("import_mesh", True)
        ui.set_editor_property("import_as_skeletal", False)
        ui.set_editor_property("import_animations", False)
        ui.set_editor_property("import_materials", False)
        ui.set_editor_property("import_textures", False)
        ui.set_editor_property("create_physics_asset", False)
        set_prop_if_exists(ui, "mesh_type_to_import",
                           unreal.FBXImportType.FBXIT_STATIC_MESH, "FbxImportUI")

        smd = ui.static_mesh_import_data
        smd.set_editor_property("combine_meshes", True)
        smd.set_editor_property("generate_lightmap_u_vs", False)
        smd.set_editor_property("auto_generate_collision", False)
        smd.set_editor_property("import_uniform_scale", 1.0)
        # build_nanite appeared on FbxStaticMeshImportData in 5.x; guard in
        # case 5.8 moved it (then: enable Nanite manually in the mesh editor).
        if not set_prop_if_exists(smd, "build_nanite", True, "static_mesh_import_data"):
            warn("build_nanite not settable at import -- enable Nanite manually on %s." % name)

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", fbx)
        task.set_editor_property("destination_path", MESH_DIR)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", False)
        task.set_editor_property("options", ui)
        tasks.append((name, task))

    if tasks:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t for _, t in tasks])
        for name, _task in tasks:
            if unreal.EditorAssetLibrary.does_asset_exist("%s/%s" % (MESH_DIR, name)):
                imported.append(name)
            else:
                warn("Import produced no asset for %s -- check the Output Log FBX section." % name)
                missing.append(name)

    # Terrain scale sanity: 200x200 m should be ~20000x20000 UU (+-5 %).
    terrain_path = "%s/%s" % (MESH_DIR, TERRAIN_NAME)
    if unreal.EditorAssetLibrary.does_asset_exist(terrain_path):
        terrain = unreal.EditorAssetLibrary.load_asset(terrain_path)
        try:
            box = terrain.get_bounding_box()
            size_x = float(box.max.x - box.min.x)
            size_y = float(box.max.y - box.min.y)
            lo = TERRAIN_EXPECTED_UU * (1.0 - TERRAIN_TOLERANCE)
            hi = TERRAIN_EXPECTED_UU * (1.0 + TERRAIN_TOLERANCE)
            if lo <= size_x <= hi and lo <= size_y <= hi:
                log("Terrain footprint OK: %.0f x %.0f UU (expected ~%.0f)."
                    % (size_x, size_y, TERRAIN_EXPECTED_UU))
            else:
                warn("=" * 70)
                warn("TERRAIN SCALE WRONG: %.0f x %.0f UU, expected %.0f +-5%%."
                     % (size_x, size_y, TERRAIN_EXPECTED_UU))
                warn("Blender export scale is off (visuals.md Pipeline B step 1: "
                     "re-run the 2 m cube round-trip test). Everything downstream "
                     "(rock ring radii, walls at r=%.0f) assumes 1 m = 100 UU." % WALL_RADIUS)
                warn("=" * 70)
        except Exception as exc:
            warn("Could not read terrain bounds for the scale assert: %s" % exc)

    if not imported and not skipped:
        raise RuntimeError("no meshes imported and none pre-existing (missing: %s)" % ", ".join(missing))
    return "imported %d, skipped %d, missing %d" % (len(imported), len(skipped), len(missing))


# ---------------------------------------------------------------------------
# Step 2: complex-as-simple collision
# ---------------------------------------------------------------------------

def step2_collision():
    done, failed = 0, 0
    for name in MESH_NAMES:
        asset_path = "%s/%s" % (MESH_DIR, name)
        if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            warn("Collision: %s does not exist, skipping." % asset_path)
            failed += 1
            continue
        mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
        body_setup = mesh.get_editor_property("body_setup")
        if body_setup is None:
            warn("Collision: %s has no BodySetup -- set Use Complex As Simple "
                 "manually in the Static Mesh editor." % name)
            failed += 1
            continue
        body_setup.set_editor_property(
            "collision_trace_flag",
            unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
        )
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)
        done += 1
    if done == 0:
        raise RuntimeError("no mesh got complex-as-simple collision")
    return "%d meshes set to complex-as-simple (%d skipped/failed)" % (done, failed)


# ---------------------------------------------------------------------------
# Step 3: texture import
# ---------------------------------------------------------------------------

def _texture_asset_name(role, kind):
    short = {"diff": "diff", "nor_dx": "nor", "arm": "arm"}[kind]
    return "T_%s_%s" % (role, short)


def step3_import_textures():
    if not os.path.isfile(MANIFEST_PATH):
        raise RuntimeError("manifest missing: %s" % MANIFEST_PATH)
    with open(MANIFEST_PATH, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    # kind -> (compression, srgb)
    tex_settings = {
        "diff": (unreal.TextureCompressionSettings.TC_DEFAULT, True),
        "nor_dx": (unreal.TextureCompressionSettings.TC_NORMALMAP, False),
        "arm": (unreal.TextureCompressionSettings.TC_MASKS, False),
    }

    imported, skipped, missing = 0, 0, 0
    for role in TEX_ROLES:
        entry = manifest.get(role)
        if not entry:
            warn("Manifest has no '%s' entry -- that texture set will be absent." % role)
            missing += len(TEX_KINDS)
            continue
        for kind in TEX_KINDS:
            asset_name = _texture_asset_name(role, kind)
            asset_path = "%s/%s" % (TEX_DIR, asset_name)

            src = entry.get(kind)
            if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
                log("Texture already imported, skipping: %s" % asset_path)
                skipped += 1
            elif not src or not os.path.isfile(src):
                warn("MISSING SOURCE TEXTURE: %s.%s -> %s" % (role, kind, src))
                missing += 1
                continue
            else:
                task = unreal.AssetImportTask()
                task.set_editor_property("filename", src)
                task.set_editor_property("destination_path", TEX_DIR)
                task.set_editor_property("destination_name", asset_name)
                task.set_editor_property("automated", True)
                task.set_editor_property("save", True)
                task.set_editor_property("replace_existing", False)
                unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
                if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
                    warn("Texture import failed for %s (%s)." % (asset_name, src))
                    missing += 1
                    continue
                imported += 1

            tex = unreal.EditorAssetLibrary.load_asset(asset_path)
            compression, srgb = tex_settings[kind]
            tex.set_editor_property("compression_settings", compression)
            tex.set_editor_property("srgb", srgb)
            set_prop_if_exists(tex, "max_texture_size", 2048, asset_name)
            if kind == "nor_dx":
                # Source is already DirectX -- UE's convention. Do NOT flip green.
                set_prop_if_exists(tex, "flip_green_channel", False, asset_name)
            unreal.EditorAssetLibrary.save_loaded_asset(tex)
            CTX["textures"]["%s_%s" % (role, kind)] = tex

    if not CTX["textures"]:
        raise RuntimeError("no textures available (%d missing)" % missing)
    return "imported %d, skipped %d, missing %d" % (imported, skipped, missing)


# ---------------------------------------------------------------------------
# Step 4: M_Terrain
# ---------------------------------------------------------------------------

MEL = unreal.MaterialEditingLibrary


def _connect_expr(frm, out_names, to, in_names, what):
    """connect_material_expressions with candidate pin names ('' = first pin).
    Engine function pin names are notoriously unstable (one even ships with a
    typo), so try a list and raise loudly if nothing sticks -- the caller's
    fallback path depends on that raise."""
    for o in out_names:
        for i in in_names:
            try:
                if MEL.connect_material_expressions(frm, o, to, i):
                    return
            except Exception:
                continue
    raise RuntimeError("material connect failed: %s (outs=%s ins=%s)" % (what, out_names, in_names))


def _connect_prop(frm, out_names, mat_prop, what):
    for o in out_names:
        try:
            if MEL.connect_material_property(frm, o, mat_prop):
                return
        except Exception:
            continue
    raise RuntimeError("material property connect failed: %s (outs=%s)" % (what, out_names))


def _new_expr(mat, cls, x, y):
    node = MEL.create_material_expression(mat, cls, x, y)
    if node is None:
        raise RuntimeError("create_material_expression returned None for %s" % cls.__name__)
    return node


def _tex(key):
    tex = CTX["textures"].get(key)
    if tex is None:
        # Late-load in case step 3 skipped pre-existing assets on a re-run.
        role, kind = key.rsplit("_", 1) if key.count("_") == 1 else (key.split("_")[0], "_".join(key.split("_")[1:]))
        path = "%s/%s" % (TEX_DIR, _texture_asset_name(role, kind))
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            tex = unreal.EditorAssetLibrary.load_asset(path)
            CTX["textures"][key] = tex
    if tex is None:
        raise RuntimeError("texture not available: %s" % key)
    return tex


# Candidate pin names for the engine material functions. The engine's own
# WorldAlignedTexture input is literally named "ProjectionTansitionContrast"
# (typo shipped in-engine), which is a good reminder these names are data,
# not API -- hence candidates everywhere.
WAT_IN_TEX = ["TextureObject (T2d)", "TextureObject", "Texture Object (T2d)", "Texture Object", ""]
WAT_IN_SIZE = ["TextureSize (V3)", "TextureSize", "Texture Size (V3)", "Texture Size"]
WAT_OUT = ["XYZTexture", "XYZ Texture", ""]
WAN_OUT = ["XYZTexture", "XYZ Texture", "XYZNormal", "XYZ Normal", "Normal", ""]


def _make_world_aligned(mat, fn_asset, texture, size_node, x, y, is_normal, what):
    """TextureObject + WorldAligned(Texture|Normal) function call, wired."""
    tex_node = _new_expr(mat, unreal.MaterialExpressionTextureObject, x, y)
    tex_node.set_editor_property("texture", texture)
    if is_normal:
        set_prop_if_exists(tex_node, "sampler_type",
                           unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, what)

    call = _new_expr(mat, unreal.MaterialExpressionMaterialFunctionCall, x + 250, y)
    call.set_editor_property("material_function", fn_asset)
    _connect_expr(tex_node, [""], call, WAT_IN_TEX, what + ".TextureObject")
    _connect_expr(size_node, [""], call, WAT_IN_SIZE, what + ".TextureSize")
    return call


def _build_rich_material(mat):
    """Floor+rock world-aligned sets, slope-blended. Raises on any snag."""
    wat = unreal.EditorAssetLibrary.load_asset(WORLD_ALIGNED_TEXTURE_FN)
    wan = unreal.EditorAssetLibrary.load_asset(WORLD_ALIGNED_NORMAL_FN)
    if wat is None or wan is None:
        raise RuntimeError("WorldAlignedTexture/Normal engine functions not found")

    size = _new_expr(mat, unreal.MaterialExpressionConstant3Vector, -2200, -600)
    size.set_editor_property(
        "constant", unreal.LinearColor(TEXTURE_SIZE_UU, TEXTURE_SIZE_UU, TEXTURE_SIZE_UU, 1.0))

    # floor set (Lerp B input -- shows where surface is flat)
    floor_diff = _make_world_aligned(mat, wat, _tex("floor_diff"), size, -1800, -900, False, "floor_diff")
    floor_arm = _make_world_aligned(mat, wat, _tex("floor_arm"), size, -1800, -650, False, "floor_arm")
    floor_nor = _make_world_aligned(mat, wan, _tex("floor_nor_dx"), size, -1800, -400, True, "floor_nor")

    # rock set (Lerp A input -- shows on slopes)
    rock_diff = _make_world_aligned(mat, wat, _tex("rock_diff"), size, -1800, -100, False, "rock_diff")
    rock_arm = _make_world_aligned(mat, wat, _tex("rock_arm"), size, -1800, 150, False, "rock_arm")
    rock_nor = _make_world_aligned(mat, wan, _tex("rock_nor_dx"), size, -1800, 400, True, "rock_nor")

    # slope mask: VertexNormalWS.Z ^ 6, clamped. Flat ground -> 1 -> floor.
    vnorm = _new_expr(mat, unreal.MaterialExpressionVertexNormalWS, -1400, 700)
    mask_z = _new_expr(mat, unreal.MaterialExpressionComponentMask, -1200, 700)
    mask_z.set_editor_property("r", False)
    mask_z.set_editor_property("g", False)
    mask_z.set_editor_property("b", True)
    mask_z.set_editor_property("a", False)
    power = _new_expr(mat, unreal.MaterialExpressionPower, -1000, 700)
    power.set_editor_property("const_exponent", 6.0)
    clamp = _new_expr(mat, unreal.MaterialExpressionClamp, -800, 700)
    _connect_expr(vnorm, [""], mask_z, ["", "Input"], "slope.mask")
    _connect_expr(mask_z, [""], power, ["Base", ""], "slope.power")
    _connect_expr(power, [""], clamp, ["", "Input"], "slope.clamp")

    def lerp(a_node, b_node, x, y, what, a_outs=WAT_OUT, b_outs=WAT_OUT):
        node = _new_expr(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
        _connect_expr(a_node, a_outs, node, ["A"], what + ".A")
        _connect_expr(b_node, b_outs, node, ["B"], what + ".B")
        _connect_expr(clamp, [""], node, ["Alpha"], what + ".Alpha")
        return node

    lerp_color = lerp(rock_diff, floor_diff, -400, -800, "lerp_color")
    lerp_arm = lerp(rock_arm, floor_arm, -400, -200, "lerp_arm")
    lerp_nor = lerp(rock_nor, floor_nor, -400, 300, "lerp_nor", a_outs=WAN_OUT, b_outs=WAN_OUT)

    # ARM: R = AO, G = roughness (metal in B is ignored -- stone arena).
    rough_mask = _new_expr(mat, unreal.MaterialExpressionComponentMask, -150, -200)
    rough_mask.set_editor_property("r", False)
    rough_mask.set_editor_property("g", True)
    rough_mask.set_editor_property("b", False)
    rough_mask.set_editor_property("a", False)
    ao_mask = _new_expr(mat, unreal.MaterialExpressionComponentMask, -150, 0)
    ao_mask.set_editor_property("r", True)
    ao_mask.set_editor_property("g", False)
    ao_mask.set_editor_property("b", False)
    ao_mask.set_editor_property("a", False)
    _connect_expr(lerp_arm, [""], rough_mask, ["", "Input"], "arm.rough")
    _connect_expr(lerp_arm, [""], ao_mask, ["", "Input"], "arm.ao")

    _connect_prop(lerp_color, [""], unreal.MaterialProperty.MP_BASE_COLOR, "BaseColor")
    _connect_prop(lerp_nor, [""], unreal.MaterialProperty.MP_NORMAL, "Normal")
    _connect_prop(rough_mask, [""], unreal.MaterialProperty.MP_ROUGHNESS, "Roughness")
    _connect_prop(ao_mask, [""], unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "AO")


def _build_fallback_material(mat):
    """Guaranteed-simple: floor set mapped by world XY / 350. No engine
    function calls, no slope blend -- the level is at least textured."""
    wpos = _new_expr(mat, unreal.MaterialExpressionWorldPosition, -1200, 0)
    mask_rg = _new_expr(mat, unreal.MaterialExpressionComponentMask, -1000, 0)
    mask_rg.set_editor_property("r", True)
    mask_rg.set_editor_property("g", True)
    mask_rg.set_editor_property("b", False)
    mask_rg.set_editor_property("a", False)
    divide = _new_expr(mat, unreal.MaterialExpressionDivide, -800, 0)
    divide.set_editor_property("const_b", TEXTURE_SIZE_UU)
    _connect_expr(wpos, [""], mask_rg, ["", "Input"], "fb.mask")
    _connect_expr(mask_rg, [""], divide, ["A", ""], "fb.divide")

    def sample(key, y, is_normal):
        node = _new_expr(mat, unreal.MaterialExpressionTextureSample, -500, y)
        node.set_editor_property("texture", _tex(key))
        if is_normal:
            set_prop_if_exists(node, "sampler_type",
                               unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, key)
        _connect_expr(divide, [""], node, ["UVs", "Coordinates", ""], "fb.uv." + key)
        return node

    diff = sample("floor_diff", -300, False)
    nor = sample("floor_nor_dx", 0, True)
    arm = sample("floor_arm", 300, False)

    rough_mask = _new_expr(mat, unreal.MaterialExpressionComponentMask, -250, 300)
    rough_mask.set_editor_property("r", False)
    rough_mask.set_editor_property("g", True)
    rough_mask.set_editor_property("b", False)
    rough_mask.set_editor_property("a", False)
    ao_mask = _new_expr(mat, unreal.MaterialExpressionComponentMask, -250, 450)
    ao_mask.set_editor_property("r", True)
    ao_mask.set_editor_property("g", False)
    ao_mask.set_editor_property("b", False)
    ao_mask.set_editor_property("a", False)
    _connect_expr(arm, [""], rough_mask, ["", "Input"], "fb.rough")
    _connect_expr(arm, [""], ao_mask, ["", "Input"], "fb.ao")

    _connect_prop(diff, [""], unreal.MaterialProperty.MP_BASE_COLOR, "fb.BaseColor")
    _connect_prop(nor, [""], unreal.MaterialProperty.MP_NORMAL, "fb.Normal")
    _connect_prop(rough_mask, [""], unreal.MaterialProperty.MP_ROUGHNESS, "fb.Roughness")
    _connect_prop(ao_mask, [""], unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "fb.AO")


def step4_build_material():
    mat_path = "%s/M_Terrain" % MAT_DIR

    # Confirm the FALLBACK's own prerequisites (the floor set) BEFORE touching
    # the asset. Otherwise a re-run with missing source textures would gut a
    # previously good M_Terrain (delete_all below) and then have nothing to
    # rebuild it with. _tex raises if a texture is neither cached nor on disk.
    for key in ("floor_diff", "floor_nor_dx", "floor_arm"):
        _tex(key)

    if unreal.EditorAssetLibrary.does_asset_exist(mat_path):
        log("M_Terrain exists -- rebuilding its graph in place.")
        mat = unreal.EditorAssetLibrary.load_asset(mat_path)
    else:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "M_Terrain", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError("could not create/load %s" % mat_path)

    MEL.delete_all_material_expressions(mat)

    # The world-aligned graph is the riskiest scripted part of the whole
    # build (engine function pin names). On ANY failure, fall back to a
    # simple guaranteed material so the level is always textured.
    try:
        _build_rich_material(mat)
        CTX["material_mode"] = "rich"
    except Exception as exc:
        warn("Rich terrain material failed (%s) -- falling back to the simple "
             "world-XY-mapped material. Rebuild the slope blend by hand later "
             "(visuals.md Pipeline B step 13)." % exc)
        warn(traceback.format_exc())
        MEL.delete_all_material_expressions(mat)
        try:
            _build_fallback_material(mat)
            CTX["material_mode"] = "fallback"
        except Exception as fb_exc:
            # Double failure: never leave a half-built graph behind. Strip the
            # partial nodes so the asset recompiles/saves as a clean empty
            # material, and mark the mode so step6a refuses to assign it.
            warn("Fallback terrain material ALSO failed (%s) -- M_Terrain left "
                 "as a clean empty graph; terrain keeps its default material. "
                 "Rebuild by hand (visuals.md Pipeline B step 13)." % fb_exc)
            warn(traceback.format_exc())
            MEL.delete_all_material_expressions(mat)
            CTX["material_mode"] = "failed"

    MEL.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    if CTX["material_mode"] == "failed":
        CTX["material"] = None
        raise RuntimeError("both rich and fallback material graphs failed -- "
                           "M_Terrain saved as an empty material")
    CTX["material"] = mat
    return "built (%s graph)" % CTX["material_mode"]


# ---------------------------------------------------------------------------
# Step 5: level create / clean
# ---------------------------------------------------------------------------

def step5_level():
    les = get_level_subsystem()
    if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
        log("Map exists -- loading %s and deleting ARENA_* actors for a clean re-run." % MAP_PATH)
        if not les.load_level(MAP_PATH):
            raise RuntimeError("load_level failed for %s" % MAP_PATH)
        actors = get_actor_subsystem()
        doomed = [a for a in actors.get_all_level_actors()
                  if a is not None and str(a.get_actor_label()).startswith("ARENA_")]
        for a in doomed:
            actors.destroy_actor(a)
        CTX["level_ready"] = True
        return "reopened, %d old ARENA_* actors removed" % len(doomed)

    if not les.new_level(MAP_PATH):
        raise RuntimeError("new_level failed for %s" % MAP_PATH)
    CTX["level_ready"] = True
    return "created new level"


# ---------------------------------------------------------------------------
# Step 6: spawn everything
# ---------------------------------------------------------------------------

def _spawn_mesh(mesh_name, location, rotation, label):
    asset_path = "%s/%s" % (MESH_DIR, mesh_name)
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        warn("Cannot spawn %s -- asset missing: %s" % (label, asset_path))
        return None
    mesh = unreal.EditorAssetLibrary.load_asset(asset_path)
    actor = get_actor_subsystem().spawn_actor_from_object(mesh, location, rotation)
    if actor is None:
        warn("spawn_actor_from_object returned None for %s" % label)
        return None
    return label_actor(actor, label)


def _apply_terrain_material(comp, what):
    """Assign M_Terrain, but only when step 4 actually produced a usable graph.
    Loading blindly by path here would re-apply a broken/empty material left
    behind by a failed step 4. Shared by the terrain (6a) and the zone (6g)."""
    mat = CTX["material"] if CTX["material_mode"] in ("rich", "fallback") else None
    if mat is None and CTX["material_mode"] in ("rich", "fallback") \
            and unreal.EditorAssetLibrary.does_asset_exist("%s/M_Terrain" % MAT_DIR):
        mat = unreal.EditorAssetLibrary.load_asset("%s/M_Terrain" % MAT_DIR)
    if mat is not None:
        comp.set_material(0, mat)
    else:
        warn("M_Terrain unavailable (material_mode=%s) -- %s left with "
             "default material." % (CTX["material_mode"], what))


def step6a_terrain():
    _require_level_ready()
    actor = _spawn_mesh(TERRAIN_NAME, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0), "ARENA_Terrain")
    if actor is None:
        raise RuntimeError("terrain actor not spawned")
    comp = get_static_mesh_component(actor)
    if comp is not None:
        try:
            comp.set_mobility(unreal.ComponentMobility.STATIC)
        except Exception as exc:
            warn("Could not force terrain mobility STATIC: %s" % exc)
        _apply_terrain_material(comp, "terrain")
    CTX["terrain_actor"] = actor
    return "terrain at origin, material %s" % CTX["material_mode"]


def _in_entrance_sector(angle_deg):
    a = angle_deg % 360.0
    return a < ENTRANCE_HALF_ANGLE_DEG or a > 360.0 - ENTRANCE_HALF_ANGLE_DEG


def step6b_rocks_and_monolith():
    _require_level_ready()
    random.seed(42)
    rock_meshes = ["SM_Rock_%02d" % i for i in range(1, 7)
                   if unreal.EditorAssetLibrary.does_asset_exist("%s/SM_Rock_%02d" % (MESH_DIR, i))]
    spawned = []

    def place_rock(idx, r_min, r_max, s_min, s_max):
        if not rock_meshes:
            return
        for _attempt in range(64):
            ang = random.uniform(0.0, 360.0)
            if not _in_entrance_sector(ang):
                break
        radius = random.uniform(r_min, r_max)
        x = radius * math.cos(math.radians(ang))
        y = radius * math.sin(math.radians(ang))
        yaw = random.uniform(0.0, 360.0)
        scale = random.uniform(s_min, s_max)
        z = ground_z(x, y, ignore_actors=spawned) - 30.0  # sink 30 cm
        actor = _spawn_mesh(random.choice(rock_meshes),
                            unreal.Vector(x, y, z),
                            unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw),
                            "ARENA_Rock_%02d" % idx)
        if actor is not None:
            actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
            spawned.append(actor)

    n_ring = random.randint(16, 20)
    for i in range(n_ring):
        place_rock(i, RING_R_MIN, RING_R_MAX, 0.8, 2.2)
    for i in range(3):  # accent rocks in the mid zone
        place_rock(n_ring + i, ACCENT_R_MIN, ACCENT_R_MAX, 0.5, 0.9)

    # Monolith: the off-center landmark (visuals.md 'Set dressing' item 4).
    mx, my = -3200.0, 2400.0
    mz = ground_z(mx, my, ignore_actors=spawned) - 15.0
    mono = _spawn_mesh("SM_Monolith", unreal.Vector(mx, my, mz),
                       unreal.Rotator(roll=0.0, pitch=0.0, yaw=20.0), "ARENA_Monolith")
    if mono is not None:
        mono.set_actor_scale3d(unreal.Vector(1.3, 1.3, 1.3))

    if not spawned and mono is None:
        raise RuntimeError("no rocks or monolith spawned (rock meshes present: %d)" % len(rock_meshes))
    return "%d rocks + %s monolith (trace %s)" % (
        len(spawned), "1" if mono else "NO", "ok" if CTX["trace_ok"] else "FELL BACK TO z=0")


def step6c_lighting():
    _require_level_ready()
    actors = get_actor_subsystem()
    placed = []

    def rig_piece(what, fn):
        """Each of the five actors is independent -- a failed spawn costs one
        actor, not the rest of the rig (matching the file's per-step ethos)."""
        try:
            fn()
            placed.append(what)
        except Exception as exc:  # noqa: BLE001 - deliberate per-actor catch
            warn("Lighting rig: '%s' failed (%s) -- place it manually." % (what, exc))
            warn(traceback.format_exc())

    def _spawned(actor, label):
        if actor is None:
            raise RuntimeError("spawn_actor_from_class returned None for %s" % label)
        return label_actor(actor, label)

    # 1. Directional light -- movable, 5 lux, 5500 K, pitched -40 for silhouette.
    def _sun():
        sun = _spawned(actors.spawn_actor_from_class(
            unreal.DirectionalLight, unreal.Vector(0, 0, 5000),
            unreal.Rotator(roll=0.0, pitch=-40.0, yaw=35.0)), "ARENA_KeyLight")
        sun_comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
        if sun_comp is not None:
            sun_comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            sun_comp.set_editor_property("intensity", 5.0)  # lux
            sun_comp.set_editor_property("use_temperature", True)
            sun_comp.set_editor_property("temperature", 5500.0)
        else:
            warn("DirectionalLightComponent not found on ARENA_KeyLight.")
    rig_piece("sun", _sun)

    # 2. Sky atmosphere -- defaults are fine (visuals.md lighting recipe item 2).
    def _atmo():
        _spawned(actors.spawn_actor_from_class(
            unreal.SkyAtmosphere, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
            "ARENA_SkyAtmosphere")
    rig_piece("atmosphere", _atmo)

    # 3. Sky light -- movable + real-time capture.
    def _skylight():
        sky_light = _spawned(actors.spawn_actor_from_class(
            unreal.SkyLight, unreal.Vector(0, 0, 500), unreal.Rotator(0, 0, 0)),
            "ARENA_SkyLight")
        sl_comp = sky_light.get_component_by_class(unreal.SkyLightComponent)
        if sl_comp is not None:
            sl_comp.set_mobility(unreal.ComponentMobility.MOVABLE)
            if not set_prop_if_exists(sl_comp, "real_time_capture", True, "SkyLight"):
                warn("Check 'Real Time Capture' manually on ARENA_SkyLight.")
    rig_piece("skylight", _skylight)

    # 4. Height fog -- density 0.015, volumetric OFF (6 GB card).
    def _fog():
        fog = _spawned(actors.spawn_actor_from_class(
            unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
            "ARENA_HeightFog")
        fog_comp = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
        if fog_comp is not None:
            fog_comp.set_editor_property("fog_density", 0.015)
            # Python name for bEnableVolumetricFog is 'enable_volumetric_fog'
            # ('volumetric_fog' only exists as the set_volumetric_fog() method).
            set_prop_if_exists(fog_comp, "enable_volumetric_fog", False, "HeightFog")
    rig_piece("fog", _fog)

    # 5. PostProcessVolume -- unbound, clamped exposure, restrained bloom/grade.
    #    CRITICAL: every FPostProcessSettings field only takes effect with its
    #    matching override_<name>=True sibling set.
    def _ppv():
        ppv = _spawned(actors.spawn_actor_from_class(
            unreal.PostProcessVolume, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0)),
            "ARENA_PostProcess")
        ppv.set_editor_property("unbound", True)
        settings = ppv.get_editor_property("settings")  # struct COPY -- set back below
        pp_fields = [
            ("auto_exposure_method", unreal.AutoExposureMethod.AEM_HISTOGRAM),
            ("auto_exposure_min_brightness", 0.75),
            ("auto_exposure_max_brightness", 1.25),
            ("bloom_intensity", 0.35),
            ("color_saturation", unreal.Vector4(0.95, 0.95, 0.95, 1.0)),
            ("color_contrast", unreal.Vector4(1.05, 1.05, 1.05, 1.0)),
        ]
        for field, value in pp_fields:
            ok_v = set_prop_if_exists(settings, field, value, "PostProcessSettings")
            ok_o = set_prop_if_exists(settings, "override_" + field, True, "PostProcessSettings")
            if not (ok_v and ok_o):
                warn("Post-process field '%s' (or its override flag) did not stick -- "
                     "set it manually on ARENA_PostProcess." % field)
        ppv.set_editor_property("settings", settings)
    rig_piece("postprocess", _ppv)

    if not placed:
        raise RuntimeError("no lighting actors placed")
    return ", ".join(placed)


def _spawn_blocking_cube(actors, cube, x, y, yaw, scale, label):
    """One hidden BlockAll cube -- shared by the arena ring/gate (6d) and the
    zone perimeter backstop (6i). Returns the actor or None."""
    actor = actors.spawn_actor_from_object(
        cube, unreal.Vector(x, y, 1400.0),  # 30 m wall -> base ~at ground, 1 m buried
        unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
    if actor is None:
        warn("Wall spawn failed: %s" % label)
        return None
    label_actor(actor, label)
    actor.set_actor_scale3d(scale)
    actor.set_actor_hidden_in_game(True)
    comp = get_static_mesh_component(actor)
    if comp is not None:
        try:
            comp.set_collision_profile_name("BlockAll")
        except Exception as exc:
            warn("Could not set BlockAll on %s: %s" % (label, exc))
    return actor


def step6d_blocking_ring():
    _require_level_ready()
    cube = unreal.EditorAssetLibrary.load_asset(CUBE_MESH)
    if cube is None:
        raise RuntimeError("engine cube not found at %s" % CUBE_MESH)
    actors = get_actor_subsystem()
    count = 0

    def spawn_wall(x, y, yaw, scale, label):
        nonlocal count
        if _spawn_blocking_cube(actors, cube, x, y, yaw, scale, label) is not None:
            count += 1

    skipped_entrance = 0
    for i in range(WALL_COUNT):
        ang = 360.0 * i / WALL_COUNT
        # Leave the entrance sector (+X, +-18 deg) open -- same exclusion the
        # rocks use. Only the removable gate below seals the pass, so M3's
        # "delete ARENA_BV_EntranceGate" actually opens the arena.
        if _in_entrance_sector(ang):
            skipped_entrance += 1
            continue
        x = WALL_RADIUS * math.cos(math.radians(ang))
        y = WALL_RADIUS * math.sin(math.radians(ang))
        # Cube local X = 2 m thick, local Y = 40 m long. yaw = ang points local
        # Y along the tangent (-sin ang, cos ang) and local X radially, so the
        # segments form a ring. (yaw = ang + 90 aimed the 40 m axis at the
        # arena center -- 16 radial spokes, not a ring.)
        spawn_wall(x, y, ang, unreal.Vector(2.0, 40.0, 30.0), "ARENA_BV_Wall_%02d" % i)

    # Entrance gate across the +X pass (~14 m wide). yaw 0 -> the 20 m local-Y
    # axis runs along world Y, spanning the pass. Spawned unconditionally on
    # every run; step 6i deletes it again when the patrol zone spawned, so the
    # gate only survives on arena-only builds.
    spawn_wall(7400.0, 0.0, 0.0, unreal.Vector(2.0, 20.0, 30.0), "ARENA_BV_EntranceGate")

    if count == 0:
        raise RuntimeError("no blocking walls spawned")
    return "%d wall segments (%d skipped for entrance) + entrance gate" % (
        count - 1, skipped_entrance)


def step6e_player_start():
    _require_level_ready()
    actors = get_actor_subsystem()
    # Ride the actual sculpted floor: rocks/monolith are ground-traced, and the
    # bowl relief is 1-2 m, so a hardcoded z=120 could intersect or float the
    # capsule. ground_z degrades to 0 when tracing is unavailable -> z=120.
    z = ground_z(-1500.0, 0.0) + 120.0
    ps = actors.spawn_actor_from_class(
        unreal.PlayerStart, unreal.Vector(-1500.0, 0.0, z),
        unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))  # facing +X, toward the entrance
    if ps is None:
        raise RuntimeError("PlayerStart spawn failed")
    label_actor(ps, "ARENA_PlayerStart")
    return "at (-1500, 0, %.0f) yaw 0" % z


# ---------------------------------------------------------------------------
# Steps 6f-6i: patrol zone (M3)
# ---------------------------------------------------------------------------

def step6f_import_zone_mesh():
    """Import SM_PatrolZone exactly like the terrain (step 1 settings: Nanite,
    no lightmap UVs) + complex-as-simple collision (step 2). If the FBX has
    not been exported yet this SKIPs, and CTX['zone_available'] stays False so
    steps 6g-6i SKIP too -- the arena-only build is untouched."""
    asset_path = "%s/%s" % (MESH_DIR, ZONE_NAME)
    imported = False

    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        log("Zone mesh already imported, skipping import: %s" % asset_path)
    else:
        fbx = os.path.join(SOURCE_ARENA_DIR, ZONE_NAME + ".fbx")
        if not os.path.isfile(fbx):
            raise StepSkip("%s not exported yet -- steps 6g-6i will SKIP "
                           "(arena-only build)" % fbx)

        ui = unreal.FbxImportUI()
        ui.set_editor_property("import_mesh", True)
        ui.set_editor_property("import_as_skeletal", False)
        ui.set_editor_property("import_animations", False)
        ui.set_editor_property("import_materials", False)
        ui.set_editor_property("import_textures", False)
        ui.set_editor_property("create_physics_asset", False)
        set_prop_if_exists(ui, "mesh_type_to_import",
                           unreal.FBXImportType.FBXIT_STATIC_MESH, "FbxImportUI")
        smd = ui.static_mesh_import_data
        smd.set_editor_property("combine_meshes", True)
        smd.set_editor_property("generate_lightmap_u_vs", False)
        smd.set_editor_property("auto_generate_collision", False)
        smd.set_editor_property("import_uniform_scale", 1.0)
        if not set_prop_if_exists(smd, "build_nanite", True, "static_mesh_import_data"):
            warn("build_nanite not settable at import -- enable Nanite manually on %s." % ZONE_NAME)

        task = unreal.AssetImportTask()
        task.set_editor_property("filename", fbx)
        task.set_editor_property("destination_path", MESH_DIR)
        task.set_editor_property("destination_name", ZONE_NAME)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", False)
        task.set_editor_property("options", ui)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("import produced no asset for %s -- check the "
                               "Output Log FBX section" % ZONE_NAME)
        imported = True

    mesh = unreal.EditorAssetLibrary.load_asset(asset_path)

    # Footprint sanity: x 10000..35000, y -8500..8500 -> 25000 x 17000 UU +-5 %.
    # Warn-only, same spirit as the terrain scale assert in step 1.
    try:
        box = mesh.get_bounding_box()
        size_x = float(box.max.x - box.min.x)
        size_y = float(box.max.y - box.min.y)
        ex, ey = ZONE_EXPECTED_UU
        if not (ex * 0.95 <= size_x <= ex * 1.05 and ey * 0.95 <= size_y <= ey * 1.05):
            warn("ZONE SCALE SUSPECT: %.0f x %.0f UU, expected ~%.0f x %.0f. "
                 "Pads/patrol points below assume the authored world-space "
                 "coordinates -- re-check the Blender export scale." % (size_x, size_y, ex, ey))
    except Exception as exc:
        warn("Could not read zone bounds for the scale check: %s" % exc)

    body_setup = mesh.get_editor_property("body_setup")
    if body_setup is None:
        warn("Collision: %s has no BodySetup -- set Use Complex As Simple "
             "manually in the Static Mesh editor." % ZONE_NAME)
    else:
        body_setup.set_editor_property(
            "collision_trace_flag",
            unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE,
        )
        unreal.EditorAssetLibrary.save_loaded_asset(mesh)

    CTX["zone_available"] = True
    return "imported" if imported else "pre-existing, collision verified"


def step6g_spawn_zone():
    _require_level_ready()
    if not CTX["zone_available"]:
        raise StepSkip("zone mesh unavailable (see step 6f)")
    # Vertices are authored in world space -> spawn at origin, like the terrain.
    actor = _spawn_mesh(ZONE_NAME, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0),
                        "ARENA_PatrolZone")
    if actor is None:
        raise RuntimeError("patrol zone actor not spawned")
    comp = get_static_mesh_component(actor)
    if comp is not None:
        try:
            comp.set_mobility(unreal.ComponentMobility.STATIC)
        except Exception as exc:
            warn("Could not force zone mobility STATIC: %s" % exc)
        _apply_terrain_material(comp, "ARENA_PatrolZone")
    CTX["zone_actor"] = actor
    return "zone at origin, material %s" % CTX["material_mode"]


def step6h_patrol_points():
    _require_level_ready()
    if CTX.get("zone_actor") is None:
        raise StepSkip("patrol zone not spawned (see steps 6f/6g)")
    actors = get_actor_subsystem()

    # Feature-detect the C++ encounter spawner: once it compiles, spawn the
    # real thing at each pad center instead of a marker TargetPoint. Its
    # MinionClass stays unset either way -- assigning the minion BP is a
    # BP-side step (see the zone manual steps in the summary).
    spawner_cls = None
    try:
        spawner_cls = unreal.load_class(None, MINION_SPAWNER_CLASS_PATH)
    except Exception:
        spawner_cls = None
    if spawner_cls is None:
        log("%s not compiled yet -- placing TargetPoint markers at the pad "
            "centers instead (re-run after the C++ lands to swap them)."
            % MINION_SPAWNER_CLASS_PATH)

    points, spawns = 0, 0
    for i, (cx, cy) in enumerate(ZONE_PAD_CENTERS, start=1):
        # 4 patrol TargetPoints at r=1200, angles 0/90/180/270, inside the
        # ~1800 UU flattened pad so every point ground-snaps onto flat ground.
        for n in range(4):
            ang = math.radians(90.0 * n)
            x = cx + ZONE_PATROL_RADIUS * math.cos(ang)
            y = cy + ZONE_PATROL_RADIUS * math.sin(ang)
            z = ground_z(x, y) + 50.0  # keep the marker visible above the pad
            tp = actors.spawn_actor_from_class(
                unreal.TargetPoint, unreal.Vector(x, y, z),
                unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
            if tp is None:
                warn("Patrol point spawn failed: P%d_%d" % (i, n + 1))
                continue
            label_actor(tp, "ARENA_PatrolPoint_P%d_%d" % (i, n + 1))
            points += 1

        cz = ground_z(cx, cy) + 50.0
        cls = spawner_cls if spawner_cls is not None else unreal.TargetPoint
        sp = actors.spawn_actor_from_class(
            cls, unreal.Vector(cx, cy, cz),
            unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
        if sp is None:
            warn("Minion spawn marker failed on pad %d" % i)
            continue
        label_actor(sp, "ARENA_MinionSpawn_P%d" % i)
        spawns += 1

    if points == 0 and spawns == 0:
        raise RuntimeError("no patrol points or minion spawns placed")
    return "%d patrol points + %d minion spawns (%s), trace %s" % (
        points, spawns,
        "MinionEncounterSpawner" if spawner_cls is not None else "TargetPoint markers",
        "ok" if CTX["trace_ok"] else "FELL BACK TO z=0")


def step6i_zone_bounds():
    _require_level_ready()
    if CTX.get("zone_actor") is None:
        raise StepSkip("patrol zone not spawned -- entrance gate stays sealed")
    actors = get_actor_subsystem()

    # The +X pass is now a real playable route: remove the arena's entrance
    # gate (step 6d spawns it unconditionally; on zone runs it dies here).
    doomed = [a for a in actors.get_all_level_actors()
              if a is not None and str(a.get_actor_label()) == "ARENA_BV_EntranceGate"]
    for a in doomed:
        actors.destroy_actor(a)

    cube = unreal.EditorAssetLibrary.load_asset(CUBE_MESH)
    if cube is None:
        raise RuntimeError("engine cube not found at %s" % CUBE_MESH)
    count, nn = 0, 0

    def spawn_wall(x, y, yaw, scale, label):
        nonlocal count
        if _spawn_blocking_cube(actors, cube, x, y, yaw, scale, label) is not None:
            count += 1

    # 10 backstop cubes just inside the in-mesh perimeter walls (same hidden
    # BlockAll pattern as the arena ring). North/south rows: yaw 90 points the
    # long local-Y axis along world X; 4 segments split the x 11000..34000
    # spread (5750 UU each, scaled to 5850 for a little overlap).
    seg = (34000.0 - 11000.0) / 4.0
    for row_y in (8300.0, -8300.0):
        for k in range(4):
            x = 11000.0 + seg * (k + 0.5)
            spawn_wall(x, row_y, 90.0,
                       unreal.Vector(2.0, seg / 100.0 + 1.0, 30.0),
                       "ARENA_BV_Zone_%02d" % nn)
            nn += 1
    # East cap at x=34600: two 86 m segments cover y -8500..8500 with overlap.
    for cap_y in (4200.0, -4200.0):
        spawn_wall(34600.0, cap_y, 0.0, unreal.Vector(2.0, 86.0, 30.0),
                   "ARENA_BV_Zone_%02d" % nn)
        nn += 1

    if count == 0:
        raise RuntimeError("no zone backstop cubes spawned")
    return "%d zone cubes, entrance gate %s" % (
        count, "removed" if doomed else "not found (already open)")


# ---------------------------------------------------------------------------
# Step 6j: NavMeshBoundsVolume (via parallel-developed C++ editor tool)
# ---------------------------------------------------------------------------

NAV_MANUAL_NOTE = (
    "NavMesh bounds: drag a NavMeshBoundsVolume from Place Actors over the "
    "WHOLE map -- location (12500, 0, 1000), scale the default 200 UU brush "
    "to 520 x 220 x 60 m (actor scale ~(260, 110, 30)), label it "
    "ARENA_NavBounds. Volumes spawned from plain python get NO brush "
    "geometry, so without the C++ helper this drag stays manual. Press P to "
    "check the green navmesh covers the arena, the corridor and all 3 pads.")


def step6j_nav_bounds():
    """Spawn one whole-map NavMeshBoundsVolume through the C++ helper
    unreal.ArenaEditorTools.spawn_nav_bounds_volume (being written in parallel
    -- feature-detected, exact signature unknown, so several call shapes are
    tried). Plain python CANNOT do this: volumes spawned via spawn_actor_*
    get no brush geometry, hence the SKIP + manual-drag degradation."""
    _require_level_ready()

    tools_cls = getattr(unreal, "ArenaEditorTools", None)
    fn = getattr(tools_cls, "spawn_nav_bounds_volume", None) if tools_cls is not None else None
    if fn is None:
        CTX["extra_manual"].append(NAV_MANUAL_NOTE)
        raise StepSkip("unreal.ArenaEditorTools.spawn_nav_bounds_volume not "
                       "available (C++ tool not compiled yet) -- manual drag, "
                       "see the manual notes below")

    actors = get_actor_subsystem()
    # Re-run hygiene: kill any pre-existing volume with our label first.
    # (Step 5 already sweeps ARENA_*, but 6j must also be safe standalone.)
    doomed = [a for a in actors.get_all_level_actors()
              if a is not None and str(a.get_actor_label()) == NAV_BOUNDS_LABEL]
    for a in doomed:
        actors.destroy_actor(a)

    center = unreal.Vector(*NAV_BOUNDS_CENTER)
    extent = unreal.Vector(*NAV_BOUNDS_EXTENT)
    attempts = (
        lambda: fn(center, extent, NAV_BOUNDS_LABEL),
        lambda: fn(center, extent),
        lambda: fn(get_editor_world(), center, extent, NAV_BOUNDS_LABEL),
        lambda: fn(get_editor_world(), center, extent),
    )
    result, last_exc = None, None
    called = False
    for attempt in attempts:
        try:
            result = attempt()
            called = True
            break
        except Exception as exc:  # noqa: BLE001 - signature probing
            last_exc = exc
    if not called:
        CTX["extra_manual"].append(NAV_MANUAL_NOTE)
        raise StepSkip("spawn_nav_bounds_volume exists but no known call "
                       "signature worked (last error: %s) -- manual drag, see "
                       "the manual notes below" % last_exc)

    # Confirm a volume actually landed; label it if the C++ side didn't.
    volume = result if isinstance(result, unreal.Actor) else None
    if volume is None:
        nav_cls = getattr(unreal, "NavMeshBoundsVolume", None)
        if nav_cls is not None:
            for a in actors.get_all_level_actors():
                if a is None or not isinstance(a, nav_cls):
                    continue
                if str(a.get_actor_label()) == NAV_BOUNDS_LABEL:
                    volume = a
                    break
                loc = a.get_actor_location()
                if (abs(loc.x - center.x) < 10.0 and abs(loc.y - center.y) < 10.0
                        and abs(loc.z - center.z) < 10.0):
                    volume = a
                    break
    if volume is None:
        CTX["extra_manual"].append(NAV_MANUAL_NOTE)
        raise StepSkip("helper ran but no NavMeshBoundsVolume found in the "
                       "level afterwards -- manual drag, see the manual notes "
                       "below")
    label_actor(volume, NAV_BOUNDS_LABEL)
    return "volume at (%.0f, %.0f, %.0f), extent (%.0f, %.0f, %.0f)" % (
        NAV_BOUNDS_CENTER + NAV_BOUNDS_EXTENT)


# ---------------------------------------------------------------------------
# Step 6k: minion bootstrap (placeholder visuals)
# ---------------------------------------------------------------------------

def _generated_class(bp_asset, class_path_hint):
    """Blueprint asset -> its generated UClass, tolerant of API drift."""
    try:
        cls = unreal.BlueprintEditorLibrary.generated_class(bp_asset)
        if cls is not None:
            return cls
    except Exception:
        pass
    try:
        cls = bp_asset.generated_class()
        if cls is not None:
            return cls
    except Exception:
        pass
    try:
        return unreal.load_class(None, class_path_hint)
    except Exception:
        return None


def _find_minion_skeleton_and_mesh(st):
    """6k.1a: resolve the UEFN mannequin Skeleton + SkeletalMesh. The project
    ships BOTH SK_UEFN_Mannequin and SKM_UEFN_Mannequin, and which one is the
    Skeleton vs the SkeletalMesh is naming-convention lore -- so type-check
    the loaded asset instead of trusting the prefix."""
    asset = unreal.EditorAssetLibrary.load_asset(SK_MANNEQUIN_PATH) \
        if unreal.EditorAssetLibrary.does_asset_exist(SK_MANNEQUIN_PATH) else None
    if asset is None:
        raise StepSkip("%s not found" % SK_MANNEQUIN_PATH)

    skeleton, mesh = None, None
    if isinstance(asset, unreal.SkeletalMesh):
        mesh = asset
        skeleton = asset.get_editor_property("skeleton")
    elif isinstance(asset, unreal.Skeleton):
        skeleton = asset
        if unreal.EditorAssetLibrary.does_asset_exist(SKM_MANNEQUIN_PATH):
            skm = unreal.EditorAssetLibrary.load_asset(SKM_MANNEQUIN_PATH)
            if isinstance(skm, unreal.SkeletalMesh):
                mesh = skm
    else:
        raise StepSkip("%s is a %s, expected Skeleton or SkeletalMesh"
                       % (SK_MANNEQUIN_PATH, type(asset).__name__))
    if skeleton is None:
        raise StepSkip("could not resolve a Skeleton from %s" % SK_MANNEQUIN_PATH)
    if mesh is None:
        warn("6k: no SkeletalMesh resolved (looked at %s and %s) -- BP_Minion "
             "will need its mesh set by hand." % (SK_MANNEQUIN_PATH, SKM_MANNEQUIN_PATH))
    st["skeleton"], st["skm"] = skeleton, mesh
    log("6k: skeleton=%s mesh=%s" % (skeleton.get_path_name(),
                                     mesh.get_path_name() if mesh else "NONE"))
    return "skeleton %s, mesh %s" % (skeleton.get_name(),
                                     mesh.get_name() if mesh else "MISSING")


def _find_hero_anim_class(st):
    """6k.1b: asset-registry search for /Game AnimBlueprints targeting the
    mannequin skeleton; prefer Manny/Hero/ABP names, never PostProcess rigs."""
    skeleton = st.get("skeleton")
    if skeleton is None:
        raise StepSkip("no skeleton resolved (see 6k.1a)")
    registry = unreal.AssetRegistryHelpers.get_asset_registry()

    assets = []
    try:  # 5.1+ signature
        assets = list(registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Engine", "AnimBlueprint"), True))
    except Exception:
        try:  # legacy string-name filter
            flt = unreal.ARFilter(class_names=["AnimBlueprint"],
                                  package_paths=["/Game"], recursive_paths=True,
                                  recursive_classes=True)
            assets = list(registry.get_assets(flt))
        except Exception as exc:
            raise StepSkip("asset registry AnimBlueprint query failed: %s" % exc)

    skel_pkg = str(skeleton.get_path_name()).split(".")[0]
    skel_name = str(skeleton.get_name())
    candidates = []
    for ad in assets:
        pkg = str(ad.package_name)
        if not pkg.startswith("/Game"):
            continue
        try:
            tag = str(ad.get_tag_value("TargetSkeleton") or "")
        except Exception:
            tag = ""
        # Tag formats vary by engine era: full export path or bare asset name.
        if skel_pkg not in tag and tag != skel_name:
            continue
        name = str(ad.asset_name)
        low = name.lower()
        if "postprocess" in low or "post_process" in low:
            continue  # linked-layer/post-process rigs, never a main anim class
        score = 0
        if "manny" in low:
            score += 4
        if "hero" in low:
            score += 4
        if "abp" in low:
            score += 1
        candidates.append((score, -len(name), name, pkg, ad))

    if not candidates:
        raise StepSkip("no /Game AnimBlueprint targets skeleton %s" % skel_pkg)
    candidates.sort(reverse=True)
    log("6k: hero-ABP candidates (score name): %s"
        % ", ".join("%d %s" % (c[0], c[2]) for c in candidates))
    score, _neg, name, pkg, ad = candidates[0]
    log("6k: picked hero AnimBP '%s' (%s, score %d)" % (name, pkg, score))

    abp = ad.get_asset()
    anim_cls = _generated_class(abp, "%s.%s_C" % (pkg, name)) if abp is not None else None
    if anim_cls is None:
        raise StepSkip("could not resolve generated class for AnimBP %s" % name)
    st["anim_class"], st["anim_bp_name"] = anim_cls, name
    return "AnimBP %s" % name


def _list_dir_asset_paths(directory):
    try:
        return [str(p).split(".")[0] for p in
                unreal.EditorAssetLibrary.list_assets(directory, recursive=True)]
    except Exception:
        return []


def _duplicate_montage(src_path, dst_name):
    """Duplicate src into MINION_DIR as dst_name (idempotent on re-runs).
    The duplicate is REQUIRED, not an optimization: PlayComboMontage /
    PlayHitReaction mutate BlendIn/BlendOut + root-motion flags on the montage
    ASSET before play, so sharing one montage across characters (hero + minion)
    interleaves those writes -- the project-wide montage-mutation rule."""
    dst_path = "%s/%s" % (MINION_DIR, dst_name)
    if unreal.EditorAssetLibrary.does_asset_exist(dst_path):
        log("6k: %s already exists -- reusing." % dst_path)
        return unreal.EditorAssetLibrary.load_asset(dst_path)
    if not unreal.EditorAssetLibrary.does_asset_exist(src_path):
        return None
    # The searches above are name-based; make sure the hit really is a montage
    # (an AnimSequence or redirector with a montage-ish name would otherwise
    # blow up later in 6k.3/6k.4 with confusing type errors).
    src = unreal.EditorAssetLibrary.load_asset(src_path)
    if not isinstance(src, unreal.AnimMontage):
        log("6k: %s is %s, not an AnimMontage -- ignoring it as a source."
            % (src_path, type(src).__name__))
        return None
    dup = unreal.EditorAssetLibrary.duplicate_asset(src_path, dst_path)
    if dup is None:
        return None
    unreal.EditorAssetLibrary.save_asset(dst_path, only_if_is_dirty=False)
    return dup


def _bootstrap_minion_montages(st):
    """6k.2: AM_Minion_Attack01 (from a Combo_01 hit-1) + AM_Minion_Death."""
    unreal.EditorAssetLibrary.make_directory(MINION_DIR)

    # Attack source: any Combo_01 montage whose name says hit1, else the
    # documented AM_Combo_01_Hit1.
    attack_src = None
    for path in _list_dir_asset_paths(COMBO01_DIR):
        low = path.rsplit("/", 1)[-1].lower()
        if ("hit1" in low or "hit_1" in low) and ("am_" in low or "montage" in low):
            attack_src = path
            break
    if attack_src is None and unreal.EditorAssetLibrary.does_asset_exist(ATTACK_MONTAGE_FALLBACK):
        attack_src = ATTACK_MONTAGE_FALLBACK

    # Death source: known candidates, else a name search under the retargeted dir.
    death_src = None
    for cand in DEATH_MONTAGE_CANDIDATES:
        if unreal.EditorAssetLibrary.does_asset_exist(cand):
            death_src = cand
            break
    if death_src is None:
        for path in _list_dir_asset_paths(RETARGETED_ANIM_DIR):
            low = path.rsplit("/", 1)[-1].lower()
            if "death" in low and "montage" in low:
                death_src = path
                break

    if attack_src is None and death_src is None:
        raise StepSkip("no source montages found (looked in %s and %s)"
                       % (COMBO01_DIR, RETARGETED_ANIM_DIR))

    st["am_attack"] = _duplicate_montage(attack_src, "AM_Minion_Attack01") if attack_src else None
    st["am_death"] = _duplicate_montage(death_src, "AM_Minion_Death") if death_src else None
    if st["am_attack"] is None and st["am_death"] is None:
        raise StepSkip("montage duplication produced nothing (attack src %s, "
                       "death src %s)" % (attack_src, death_src))
    return "attack %s, death %s" % (
        "OK(from %s)" % attack_src.rsplit("/", 1)[-1] if st["am_attack"] else "MISSING",
        "OK(from %s)" % death_src.rsplit("/", 1)[-1] if st["am_death"] else "MISSING")


def _bootstrap_minion_config(st):
    """6k.3: DA_MinionCombo -- one-entry ComboChain, 8 damage, Light."""
    if st.get("am_attack") is None:
        raise StepSkip("no AM_Minion_Attack01 (see 6k.2)")
    cfg_cls = None
    try:
        cfg_cls = unreal.load_class(None, COMBAT_ANIM_CONFIG_CLASS_PATH)
    except Exception:
        cfg_cls = None
    if cfg_cls is None:
        raise StepSkip("%s not compiled" % COMBAT_ANIM_CONFIG_CLASS_PATH)
    if not hasattr(unreal, "AttackAnimData"):
        raise StepSkip("unreal.AttackAnimData binding missing (module not "
                       "loaded in this editor session)")

    da_path = "%s/DA_MinionCombo" % MINION_DIR
    if unreal.EditorAssetLibrary.does_asset_exist(da_path):
        da = unreal.EditorAssetLibrary.load_asset(da_path)
    else:
        factory = unreal.DataAssetFactory()
        set_prop_if_exists(factory, "data_asset_class", cfg_cls, "DataAssetFactory")
        da = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "DA_MinionCombo", MINION_DIR, cfg_cls, factory)
    if da is None:
        raise RuntimeError("could not create/load %s" % da_path)

    # FAttackAnimData fields (CombatAnimConfig.h): Montage / DamageAmount /
    # DamageType; PlayRate/Blend* keep their C++ defaults.
    entry = unreal.AttackAnimData()
    entry.set_editor_property("montage", st["am_attack"])
    entry.set_editor_property("damage_amount", 8.0)
    entry.set_editor_property("damage_type", "Light")
    da.set_editor_property("combo_chain", [entry])
    unreal.EditorAssetLibrary.save_loaded_asset(da)
    st["da_combo"] = da
    return "DA_MinionCombo: 1-entry chain, 8 dmg Light"


def _minion_mesh_alignment():
    """Read BP_NeuralHero's mesh offsets if the CDO is readable (it is
    APawn-based, so the component property may not be named 'mesh'); fall
    back to the standard mannequin Z -88 / yaw -90."""
    loc = unreal.Vector(0.0, 0.0, MINION_MESH_REL_Z)
    rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=MINION_MESH_REL_YAW)
    try:
        hero_cls = unreal.load_class(None, HERO_BP_GEN_CLASS)
        hero_cdo = unreal.get_default_object(hero_cls)
        comp = hero_cdo.get_editor_property("mesh")
        if comp is not None:
            loc = comp.get_editor_property("relative_location")
            rot = comp.get_editor_property("relative_rotation")
            log("6k: using BP_NeuralHero mesh alignment: loc %s rot %s" % (loc, rot))
            return loc, rot
    except Exception as exc:
        log("6k: BP_NeuralHero mesh offsets unreadable (%s) -- using the "
            "standard mannequin Z=-88 / yaw=-90." % exc)
    return loc, rot


def _apply_minion_defaults(cdo, st):
    """Set BP_Minion CDO defaults; returns a list of what did NOT stick."""
    misses = []
    rel_loc, rel_rot = st["mesh_align"]

    mesh_comp = None
    try:
        mesh_comp = cdo.get_editor_property("mesh")  # ACharacter::Mesh
    except Exception:
        pass
    if mesh_comp is None:
        misses.append("mesh component not reachable on the CDO (candidates: %s)"
                      % ", ".join(sorted(n for n in dir(cdo) if "mesh" in n.lower())[:8]))
    else:
        if st.get("skm") is not None:
            # 5.1 renamed SkeletalMesh -> SkeletalMeshAsset; try both.
            if not (set_prop_if_exists(mesh_comp, "skeletal_mesh_asset", st["skm"])
                    or set_prop_if_exists(mesh_comp, "skeletal_mesh", st["skm"])):
                misses.append("skeletal mesh")
        else:
            misses.append("skeletal mesh (no SKM resolved in 6k.1)")
        if st.get("anim_class") is not None:
            set_prop_if_exists(mesh_comp, "animation_mode",
                               unreal.AnimationMode.ANIMATION_BLUEPRINT, "BP_Minion mesh")
            if not set_prop_if_exists(mesh_comp, "anim_class", st["anim_class"]):
                misses.append("anim class")
        else:
            misses.append("anim class (no hero ABP resolved in 6k.1)")
        if not set_prop_if_exists(mesh_comp, "relative_location", rel_loc):
            misses.append("mesh relative location")
        if not set_prop_if_exists(mesh_comp, "relative_rotation", rel_rot):
            misses.append("mesh relative rotation")

    combat = None
    try:
        combat = cdo.get_editor_property("combat_component")  # UPROPERTY CombatComponent
    except Exception:
        pass
    if combat is None:
        misses.append("combat_component not reachable on the CDO (candidates: %s)"
                      % ", ".join(sorted(n for n in dir(cdo) if "comp" in n.lower())[:8]))
    else:
        # Exact reflected names from CombatComponent.h: NeutralComboConfig,
        # DeathMontage, MaxHealth (python snake_case).
        if st.get("da_combo") is not None:
            if not set_prop_if_exists(combat, "neutral_combo_config", st["da_combo"]):
                misses.append("NeutralComboConfig")
        else:
            misses.append("NeutralComboConfig (no DA_MinionCombo from 6k.3)")
        if st.get("am_death") is not None:
            if not set_prop_if_exists(combat, "death_montage", st["am_death"]):
                misses.append("DeathMontage")
        else:
            misses.append("DeathMontage (no AM_Minion_Death from 6k.2)")
        if not set_prop_if_exists(combat, "max_health", 40.0):
            misses.append("MaxHealth")
    return misses


def _verify_minion_bp(st):
    """Spawn a throwaway instance from the generated class and assert the
    defaults propagated to it (CDO edits on BP-generated classes are a known
    can-silently-revert risk), then destroy the throwaway. NOTE: this proves
    in-memory CDO->instance propagation only -- unreal.load_class returns the
    already-loaded class, nothing is re-read from disk, so disk persistence
    is covered separately by checking save_loaded_asset's return value.
    Only defaults that 6k.1-6k.3 actually produced are asserted; upstream
    skips are reported as skipped checks, not persistence failures."""
    if not CTX.get("level_ready"):
        return None, "level not ready -- verification skipped"
    fresh = unreal.load_class(None, "%s/BP_Minion.BP_Minion_C" % MINION_DIR)
    if fresh is None:
        return False, "could not reload BP_Minion_C"
    actors = get_actor_subsystem()
    inst = actors.spawn_actor_from_class(
        fresh, unreal.Vector(0.0, 0.0, -5000.0), unreal.Rotator(0.0, 0.0, 0.0))
    if inst is None:
        return False, "throwaway spawn returned None"
    try:
        # Only assert defaults that were actually applied -- an upstream 6k
        # sub-goal skip (e.g. no DA_MinionCombo) must not read as a bogus
        # "did not persist" CDO bug.
        checks, skipped = [], []
        mc = inst.get_component_by_class(unreal.SkeletalMeshComponent)
        skm_val = None
        if mc is not None:
            for prop in ("skeletal_mesh_asset", "skeletal_mesh"):
                try:
                    skm_val = mc.get_editor_property(prop)
                    if skm_val is not None:
                        break
                except Exception:
                    continue
        if st.get("skm") is not None:
            checks.append(("mesh", skm_val is not None))
        else:
            skipped.append("mesh")
        anim_val = None
        if mc is not None:
            try:
                anim_val = mc.get_editor_property("anim_class")
            except Exception:
                anim_val = None
        if st.get("anim_class") is not None:
            checks.append(("anim class", anim_val is not None))
        else:
            skipped.append("anim class")

        cc_cls = getattr(unreal, "CombatComponent", None)
        if cc_cls is None:
            try:
                cc_cls = unreal.load_class(None, COMBAT_COMPONENT_CLASS_PATH)
            except Exception:
                cc_cls = None
        cc = inst.get_component_by_class(cc_cls) if cc_cls is not None else None
        cfg_val = death_val = None
        hp_ok = False
        if cc is not None:
            try:
                cfg_val = cc.get_editor_property("neutral_combo_config")
                death_val = cc.get_editor_property("death_montage")
                hp_ok = abs(float(cc.get_editor_property("max_health")) - 40.0) < 0.01
            except Exception:
                pass
        if st.get("da_combo") is not None:
            checks.append(("combo config", cfg_val is not None))
        else:
            skipped.append("combo config")
        if st.get("am_death") is not None:
            checks.append(("death montage", death_val is not None))
        else:
            skipped.append("death montage")
        checks.append(("MaxHealth 40", hp_ok))

        skipped_note = ((" (not checked -- upstream 6k skips, see other 6k "
                         "notes: %s)" % ", ".join(skipped)) if skipped else "")
        failed = [name for name, ok in checks if not ok]
        if failed:
            warn("6k: BP_Minion ASSERT FAIL -- did not propagate to a fresh "
                 "instance: %s%s" % (", ".join(failed), skipped_note))
            return False, "unset on a fresh instance: %s%s" % (
                ", ".join(failed), skipped_note)
        log("6k: BP_Minion ASSERT PASS -- all applied defaults stuck on a "
            "fresh instance.%s" % skipped_note)
        return True, "all applied defaults verified on a fresh instance%s" % skipped_note
    finally:
        actors.destroy_actor(inst)


def _bootstrap_minion_bp(st):
    """6k.4: BP_Minion (parent NPCMinionCharacter) with CDO defaults, then a
    spawn-and-assert verification pass. Verification FAILING marks the
    sub-goal SKIP with the exact manual checklist -- no pretending."""
    minion_cls = None
    try:
        minion_cls = unreal.load_class(None, MINION_CLASS_PATH)
    except Exception:
        minion_cls = None
    if minion_cls is None:
        raise StepSkip("%s not compiled" % MINION_CLASS_PATH)
    st["cpp_class"] = minion_cls

    bp_path = "%s/BP_Minion" % MINION_DIR
    if unreal.EditorAssetLibrary.does_asset_exist(bp_path):
        bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    else:
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", minion_cls)
        bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "BP_Minion", MINION_DIR, None, factory)
    if bp is None:
        raise RuntimeError("could not create/load %s" % bp_path)

    gen_cls = _generated_class(bp, bp_path + ".BP_Minion_C")
    if gen_cls is None:
        raise RuntimeError("BP_Minion has no resolvable generated class")

    st["mesh_align"] = _minion_mesh_alignment()
    cdo = unreal.get_default_object(gen_cls)
    misses = _apply_minion_defaults(cdo, st)

    # Compile can regenerate the CDO and drop pure-CDO edits -- so compile,
    # re-apply onto the (possibly new) CDO, then save, then verify fresh.
    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("6k: compile_blueprint failed (%s) -- continuing to save." % exc)
        gen_cls = _generated_class(bp, bp_path + ".BP_Minion_C") or gen_cls
        cdo = unreal.get_default_object(gen_cls)
        misses = _apply_minion_defaults(cdo, st)

    # 6k.5 can still wire spawners to the in-memory class even if the save or
    # verification below fails -- publish it before any raise.
    st["minion_bp_class"] = gen_cls
    CTX["minion_bp_class"] = gen_cls

    # save_loaded_asset returns False on a read-only/locked .uasset (LFS lock,
    # source control, file open elsewhere). The in-memory verification below
    # would still pass, but every default would be gone after an editor
    # restart -- surface it instead of silently reporting success.
    if not unreal.EditorAssetLibrary.save_loaded_asset(bp):
        raise StepSkip("BP_Minion defaults applied in memory but the asset "
                       "could not be SAVED to disk (read-only/locked .uasset?) "
                       "-- everything will be lost on editor restart")

    verified, why = _verify_minion_bp(st)
    if verified is None:
        raise StepSkip("BP_Minion created and saved but NOT verified (%s) -- "
                       "treat its defaults as unconfirmed" % why)
    if verified is False:
        # BP exists (spawners still get it in 6k.5) but its defaults are NOT
        # trustworthy -- surface the precise fix-up list instead of pretending.
        raise StepSkip("BP_Minion created but CDO defaults did not propagate "
                       "to a fresh instance (%s)%s" % (why,
                                   ("; also unset during apply: " + "; ".join(misses)) if misses else ""))
    if misses:
        raise StepSkip("BP_Minion created but some defaults could not be "
                       "applied: %s" % "; ".join(misses))
    return "BP_Minion verified (%s)" % why


def _bootstrap_minion_spawners(st):
    """6k.5: MinionClass + PatrolPoints on the three ARENA_MinionSpawn_P*."""
    _require_level_ready()
    if CTX.get("zone_actor") is None:
        # Arena-only build: the ARENA_MinionSpawn_P* / patrol points only
        # exist once the zone lands (steps 6f-6h). The default manual note
        # ("select each spawner...") would be impossible to follow, so
        # override it with the real next step.
        skip = StepSkip("patrol zone absent (arena-only build) -- the "
                        "ARENA_MinionSpawn_P* spawners do not exist yet")
        skip.manual_override = ("nothing to select yet -- export "
                                "SM_PatrolZone.fbx and re-run the script; "
                                "spawner wiring happens automatically then.")
        raise skip
    # Prefer the BP generated class (even if 6k.4's verification flagged its
    # defaults -- fixing defaults in the BP editor is still the right target);
    # fall back to the raw C++ class only when the BP never materialized.
    used_cpp_fallback = CTX.get("minion_bp_class") is None
    target_cls = CTX.get("minion_bp_class") or st.get("cpp_class")
    if target_cls is None:
        try:
            target_cls = unreal.load_class(None, MINION_CLASS_PATH)
        except Exception:
            target_cls = None
    if target_cls is None:
        raise StepSkip("no minion class available (BP and C++ both missing)")
    if used_cpp_fallback:
        CTX["minion_manual"].append(
            "6k 5-spawners NOTE: BP_Minion never materialized, so the "
            "spawners were wired to the raw C++ NPCMinionCharacter fallback "
            "(spawns invisible capsules -- no mesh/anim). MANUAL: after "
            "creating BP_Minion (see the 6k 4-blueprint note), set "
            "MinionClass=BP_Minion on ARENA_MinionSpawn_P1..P%d."
            % len(ZONE_PAD_CENTERS))

    spawner_cls = getattr(unreal, "MinionEncounterSpawner", None)
    if spawner_cls is None:
        try:
            spawner_cls = unreal.load_class(None, MINION_SPAWNER_CLASS_PATH)
        except Exception:
            spawner_cls = None

    actors_all = [a for a in get_actor_subsystem().get_all_level_actors() if a is not None]
    by_label = {str(a.get_actor_label()): a for a in actors_all}

    assigned, details = 0, []
    for i in range(1, len(ZONE_PAD_CENTERS) + 1):
        label = "ARENA_MinionSpawn_P%d" % i
        sp = by_label.get(label)
        if sp is None:
            details.append("%s missing" % label)
            continue
        if spawner_cls is not None and not isinstance(sp, spawner_cls):
            # Old-run TargetPoint marker (spawner C++ wasn't compiled when 6h
            # last ran) -- a full re-run replaces it; don't poke properties on it.
            details.append("%s is a %s, not a MinionEncounterSpawner (re-run "
                           "the script)" % (label, type(sp).__name__))
            continue
        if not set_prop_if_exists(sp, "minion_class", target_cls, label):
            details.append("%s: MinionClass not settable" % label)
            continue

        # PatrolPoints (exact reflected name from MinionEncounterSpawner.h),
        # ordered by the _1.._4 suffix from step 6h.
        prefix = "ARENA_PatrolPoint_P%d_" % i
        pts = []
        for lbl, a in by_label.items():
            if lbl.startswith(prefix):
                try:
                    pts.append((int(lbl[len(prefix):]), a))
                except ValueError:
                    continue
        pts.sort()
        if not set_prop_if_exists(sp, "patrol_points", [a for _n, a in pts], label):
            # Class stuck but patrol wiring didn't -- do NOT count this
            # spawner as fully assigned, or the summary would show two
            # contradictory lines and suppress the manual note.
            details.append("%s: class set but PatrolPoints not settable "
                           "(minions will stand at home)" % label)
            continue
        assigned += 1
        details.append("%s: class + %d patrol points" % (label, len(pts)))

    if assigned == 0:
        raise StepSkip("no spawner fully wired (class + patrol points): %s"
                       % "; ".join(details))
    st["spawners_assigned"] = assigned
    if used_cpp_fallback:
        details.append("C++ NPCMinionCharacter fallback in use -- see the "
                       "minion manual notes")
    return "; ".join(details)


def step6k_minion_bootstrap():
    """Placeholder-minion bootstrap. Each sub-goal is independently guarded;
    any SKIP/FAIL lands a precise manual-note line in the summary instead of
    failing the build. Assets go to /Game/Arena/Minions (saved by step 7)."""
    st = {}
    notes = CTX["minion_manual"]
    results = []

    def sub(tag, fn, manual_note):
        try:
            detail = fn(st)
            results.append("%s OK" % tag)
            log("  [6k] %s OK%s" % (tag, (" -- " + detail) if detail else ""))
            return True
        except StepSkip as why:
            results.append("%s SKIP" % tag)
            # A sub-goal may override the default manual note when the
            # standard instructions would be impossible to follow (e.g.
            # spawner wiring on an arena-only build with no zone actors).
            note = getattr(why, "manual_override", None) or manual_note
            notes.append("6k %s SKIPPED (%s). MANUAL: %s" % (tag, why, note))
            log("  [6k] %s SKIP -- %s" % (tag, why))
        except Exception as exc:  # noqa: BLE001 - per-sub-goal isolation
            results.append("%s FAIL" % tag)
            notes.append("6k %s FAILED (%s). MANUAL: %s" % (tag, exc, manual_note))
            warn("  [6k] %s FAIL -- %s" % (tag, exc))
            warn(traceback.format_exc())
        return False

    sub("1a-skeleton", _find_minion_skeleton_and_mesh,
        "open %s to identify the UEFN mannequin Skeleton/SkeletalMesh pair by "
        "hand." % SK_MANNEQUIN_PATH)
    sub("1b-animbp", _find_hero_anim_class,
        "find the AnimBP BP_NeuralHero's mesh uses (open BP_NeuralHero -> Mesh "
        "-> Anim Class) and assign it to BP_Minion's mesh.")
    sub("2-montages", _bootstrap_minion_montages,
        "Ctrl+D-duplicate %s -> %s/AM_Minion_Attack01 and Knock_Down_Death_Seq_"
        "Montage -> %s/AM_Minion_Death (duplicates are REQUIRED -- montages "
        "must never be shared across characters)." % (ATTACK_MONTAGE_FALLBACK, MINION_DIR, MINION_DIR))
    sub("3-comboconfig", _bootstrap_minion_config,
        "create DataAsset %s/DA_MinionCombo (class CombatAnimConfig): ComboChain "
        "= 1 entry, Montage=AM_Minion_Attack01, DamageAmount=8, DamageType=Light." % MINION_DIR)
    sub("4-blueprint", _bootstrap_minion_bp,
        "open %s/BP_Minion (create it with parent NPCMinionCharacter if absent) "
        "and set: Mesh->Skeletal Mesh=UEFN mannequin, Anim Class=hero AnimBP, "
        "relative location Z=-88, yaw=-90; CombatComponent->NeutralComboConfig="
        "DA_MinionCombo, DeathMontage=AM_Minion_Death, MaxHealth=40." % MINION_DIR)
    sub("5-spawners", _bootstrap_minion_spawners,
        "select each ARENA_MinionSpawn_P1..P%d in the level: set MinionClass="
        "BP_Minion and fill PatrolPoints with that pad's ARENA_PatrolPoint_P*_1"
        "..4 TargetPoints, in suffix order." % len(ZONE_PAD_CENTERS))

    if not any(r.endswith("OK") for r in results):
        raise StepSkip("all sub-goals skipped/failed -- see the minion manual "
                       "notes in the summary")
    return " | ".join(results)


# ---------------------------------------------------------------------------
# Step 7: save
# ---------------------------------------------------------------------------

def step7_save():
    saved = []
    if unreal.EditorAssetLibrary.does_directory_exist("/Game/Arena"):
        unreal.EditorAssetLibrary.save_directory("/Game/Arena", only_if_is_dirty=False)
        saved.append("/Game/Arena")
    if not CTX.get("level_ready"):
        # Step 5 failed -- the open level is NOT BossArena. Saving it would
        # persist whatever map the user had open. Asset save above is still fine.
        warn("Level step failed -- refusing to save the currently open level.")
        if not saved:
            raise RuntimeError("nothing saved (level not ready, no assets)")
        return ", ".join(saved) + " (level save skipped: level not ready)"
    les = get_level_subsystem()
    if les.save_current_level():
        saved.append(MAP_PATH)
    else:
        # save_current_level can report False for an already-clean level; try the
        # explicit save-all path before calling it a failure.
        try:
            if hasattr(les, "save_all_dirty_levels") and les.save_all_dirty_levels():
                saved.append(MAP_PATH + " (dirty-levels path)")
            else:
                warn("Level save reported no-op/failure -- Ctrl+S the map to be sure.")
        except Exception as exc:
            warn("Level save failed: %s -- save the map manually." % exc)
    if not saved:
        raise RuntimeError("nothing saved")
    return ", ".join(saved)


# ---------------------------------------------------------------------------
# Step 8: summary
# ---------------------------------------------------------------------------

MANUAL_STEPS = """
Remaining MANUAL steps (script cannot or should not do these):
  1. Verify Nanite took: viewport View Mode -> Nanite Visualization -> Triangles
     on the terrain (visuals.md Pipeline B step 12). Stand a pawn on it.
  2. Drop BP_NeuralHero + BP_Boss into the arena (or set the GameMode default
     pawn) and confirm spawn transforms -- CombatComponent captures them at
     BeginPlay for round resets.
  3. Exposure band: Show -> Visualize -> HDR (Eye Adaptation), note the settled
     EV100 in the arena, and tighten ARENA_PostProcess Min/Max to that +-0.5
     (script seeded 0.75/1.25 -- visuals.md says tune to the real reading).
  4. If the material fell back to the simple graph (see summary above), rebuild
     the slope-blend M_Terrain by hand per visuals.md Pipeline B step 13.
  5. Optional dirt layer: Mesh Paint the Red vertex channel + Lerp T_dirt_* in.
  6. Decals / foliage / Niagara dust per visuals.md set-dressing section.
  7. Project Settings -> Maps & Modes -> default map = BossArena when ready.
  8. Patrol zone: if steps 6f-6i said SKIP above, export SM_PatrolZone.fbx
     (world-space meters, like the terrain) and re-run -- the script then
     builds the zone and removes ARENA_BV_EntranceGate automatically.
"""

ZONE_MANUAL_STEPS = """
Patrol-zone MANUAL steps:
  9. NavMesh bounds: ONLY if step 6j said SKIP above -- see the 'Nav/minion
     manual follow-ups' list below for the exact drag (whole-map volume at
     (12500, 0, 1000), brush scaled to 520 x 220 x 60 m). If 6j PASSed,
     just press P and check the green navmesh covers corridor + all 3 pads.
 10. Minions: ONLY where step 6k sub-goals said SKIP/FAIL above -- the
     'Nav/minion manual follow-ups' list below spells out each fix
     (BP_Minion defaults, DA_MinionCombo, spawner MinionClass/PatrolPoints).
 11. Minion visuals are PLACEHOLDER (UEFN mannequin + hero AnimBP). When the
     Stone Golem pack lands: retarget its anims, duplicate fresh montages
     (never share montage assets across characters), swap BP_Minion's mesh/
     AnimBP, and update DA_MinionCombo.
"""


def print_summary():
    log("=" * 68)
    log("BossArena build summary:")
    worst = "PASS"
    for label, status, detail in STEP_RESULTS:
        line = "  [%s] %-38s %s" % (status, label, detail)
        if status == "FAIL":
            worst = "FAIL"
            warn(line)
        else:
            log(line)
    if CTX["material_mode"] == "fallback":
        warn("  NOTE: M_Terrain is the FALLBACK graph (no slope blend).")
    if CTX["material_mode"] == "failed":
        warn("  NOTE: BOTH M_Terrain graphs failed -- asset saved EMPTY and NOT "
             "assigned to the terrain. Rebuild by hand (Pipeline B step 13).")
    if not CTX["trace_ok"]:
        warn("  NOTE: ground snapping fell back to z=0 -- check rocks for floaters.")
    log("Overall: %s" % worst)
    for line in MANUAL_STEPS.strip("\n").split("\n"):
        log(line)
    if CTX.get("zone_actor") is not None:
        for line in ZONE_MANUAL_STEPS.strip("\n").split("\n"):
            log(line)
    manual_followups = CTX["extra_manual"] + CTX["minion_manual"]
    if manual_followups:
        warn("Nav/minion manual follow-ups (from 6j/6k SKIPs above):")
        for n, line in enumerate(manual_followups, start=1):
            warn("  %2d. %s" % (n, line))
    log("=" * 68)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("Building BossArena from %s ..." % SOURCE_ARENA_DIR)
    run_step("1. Import arena FBX meshes", step1_import_meshes)
    run_step("2. Complex-as-simple collision", step2_collision)
    run_step("3. Import textures", step3_import_textures)
    run_step("4. Build M_Terrain", step4_build_material)
    run_step("5. Create/clean level", step5_level)
    run_step("6a. Spawn terrain", step6a_terrain)
    run_step("6b. Rocks + monolith", step6b_rocks_and_monolith)
    run_step("6c. Lighting rig", step6c_lighting)
    run_step("6d. Blocking ring + gate", step6d_blocking_ring)
    run_step("6e. PlayerStart", step6e_player_start)
    run_step("6f. Import patrol-zone mesh", step6f_import_zone_mesh)
    run_step("6g. Spawn patrol zone", step6g_spawn_zone)
    run_step("6h. Patrol points + minion spawns", step6h_patrol_points)
    run_step("6i. Zone perimeter + gate removal", step6i_zone_bounds)
    run_step("6j. Nav bounds volume", step6j_nav_bounds)
    run_step("6k. Minion bootstrap", step6k_minion_bootstrap)
    run_step("7. Save assets + map", step7_save)
    print_summary()


main()
