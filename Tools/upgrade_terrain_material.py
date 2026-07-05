"""LEVER 1 -- M_Terrain v2 rebuild for /Game/Maps/BossArena (four-lever spec).

Run headlessly (proven pattern -- in-editor python crashes this machine):
  UnrealEditor-Cmd.exe "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/upgrade_terrain_material.py"
(or, if you must, editor Cmd console: py "D:/GAME_CORE 5.8/Tools/upgrade_terrain_material.py")

LEVEL GUARD: verifies the open level IS /Game/Maps/BossArena (loads it if
not, dress_arena ensure_bossarena_open pattern). If the guard fails, every
step records FAIL and NOTHING is touched -- no asset writes, no level save.

WHAT IT DOES (each step isolated; PASS/FAIL/SKIP summary at the end):
  1. Texture caps: T_CliffRock_03_N + the LeafPathStones D/N pair -> max 2048
     (dress_arena _cap_texture: never raises an existing lower cap, so the
     KiteDemo 1024-forced backdrop sets can never be undone from here --
     these three live outside those dirs anyway).
  2. Preflight: the six /Game/Arena/Textures floor/rock maps MUST exist
     (they are the fallback's own prerequisites -- build_arena_level step-4
     precedent: never gut a good M_Terrain and then have nothing to rebuild
     it with); optional v2 textures + expression classes feature-detected.
  3. Rebuild M_Terrain IN PLACE (delete_all_material_expressions first):
       rich v2 graph = v1 base (WorldAligned floor/rock @350uu, slope mask
       VertexNormalWS.Z^6->Clamp, ARM unpack) + four groups:
         1a macro variation  (T_Default_MacroVariation, 2 octaves 80m/230m,
                              remap Lerp(0.83,1.0) multiplied into BaseColor)
         1b distance tiling  (same sets duplicated @1400uu, near/far blend by
                              Distance(AbsWP, CameraWS)->SmoothStep(2000,6000);
                              Subtract/Divide/Clamp fallback if SmoothStep is
                              missing in this build)
         1c detail normal    (T_CliffRock_03_N via WorldAlignedNormal @50uu,
                              flattened 0.3, whiteout Add on RG, near-band only)
         1d dead-leaf dirt   (LeafPathStones D/N @350uu, mask = OneMinus(macro)
                              x flatness, Power 2)
       ANY exception in the v2 build -> delete_all + rebuild the PROVEN v1
       rich graph (verbatim from build_arena_level step 4); if THAT throws ->
       delete_all + the guaranteed simple world-XY floor material. The
       terrain is never left unmaterialed. recompile + force-save with
       on-disk mtime verify. If ALL THREE tiers fail, NOTHING is recompiled
       or saved: the on-disk M_Terrain (the last working graph) is preserved
       and reloaded back into memory so not even a later save-all can flush
       the gutted graph.
  4./5. Assign M_Terrain to slot 0 of ARENA_Terrain and ARENA_PatrolZone
     (zone absent on arena-only builds = SKIP) and VERIFY by re-reading
     get_material(0) -- struct-array-style silent write failures don't apply
     to set_material, but the re-read rule is blanket policy.
  6. Save the level.

DIAL-BACK KNOBS (perf budget: expected +0.35-0.55 ms GPU, ceiling 0.8):
  DO_DETAIL_NORMAL = False   -> first dial-back (spec order)
  DO_DISTANCE_BLEND = False  -> second (collapses 1b to near-only, 6 fetches)
  DO_LEAF_LAYER / DO_MACRO   -> last resorts
Flip a flag and re-run -- the rebuild is idempotent (in-place, delete-first).
After the run: 'stat streaming' pool MUST stay under 2200 (visuals.md);
never touch the dress_arena atmosphere numbers or r.Streaming.PoolSize.

No ground traces are performed by this script, so the ARENA_BV_* trace-ignore
rule is N/A (no placement); only material/texture assets + two material slots
are written. Idempotent: re-runs rebuild the same graph, caps skip, slot
assignment skips when already M_Terrain.
"""

import os
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[TerrainMatV2]"
MAP_PATH = "/Game/Maps/BossArena"       # the ONLY level this script may touch

MAT_DIR = "/Game/Arena/Materials"
MAT_PATH = MAT_DIR + "/M_Terrain"
TEX_DIR = "/Game/Arena/Textures"

WORLD_ALIGNED_TEXTURE_FN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedTexture"
WORLD_ALIGNED_NORMAL_FN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/WorldAlignedNormal"

# Base (v1) texture sets -- REQUIRED (fallback prerequisites)
BASE_TEX_KEYS = ("floor_diff", "floor_nor", "floor_arm",
                 "rock_diff", "rock_nor", "rock_arm")

# v2 optional textures -- each group degrades to skip when its texture is absent
MACRO_TEX = "/Engine/EngineMaterials/T_Default_MacroVariation"
DETAIL_NOR_TEX = "/Game/KiteDemo/Textures/T_CliffRock_03_N"
LEAF_DIFF_TEX = "/Game/KiteDemo/Environments/GroundTiles/LeafyPath/T_GDC_Tiling_LeafPathStones_D_R"
# NOTE the lowercase 'p' in Leafpath -- exact on-disk name, do not "fix" it.
LEAF_NOR_TEX = "/Game/KiteDemo/Environments/GroundTiles/LeafyPath/T_GDC_Tiling_LeafpathStones_N"

CAP_TEXTURES = [DETAIL_NOR_TEX, LEAF_DIFF_TEX, LEAF_NOR_TEX]
MAX_TEX_SIZE = 2048

# Tiling sizes (UU)
SIZE_NEAR = 350.0        # v1 base repeat (keep)
SIZE_FAR = 1400.0        # 1b distance-tiling repeat
SIZE_DETAIL = 50.0       # 1c detail normal repeat

# 1b near/far camera-distance band (UU)
DIST_NEAR = 2000.0
DIST_FAR = 6000.0

# 1a macro octaves (UU per repeat) + darkening band
MACRO_OCTAVE_1 = 8000.0   # 80 m
MACRO_OCTAVE_2 = 23000.0  # 230 m
MACRO_DARK_MIN = 0.83     # Lerp(0.83, 1.0, noise) -> 0-17 % darkening

DETAIL_FLATTEN = 0.3      # Lerp(float3(0,0,1) -> detail, 0.3)

# Dial-back knobs (spec order: 1c first, then collapse 1b)
DO_MACRO = True           # group 1a
DO_DISTANCE_BLEND = True  # group 1b
DO_DETAIL_NORMAL = True   # group 1c
DO_LEAF_LAYER = True      # group 1d

# Level actors whose slot 0 must carry M_Terrain
TERRAIN_LABEL = "ARENA_Terrain"
ZONE_LABEL = "ARENA_PatrolZone"

GC_EVERY_SAVES = 12
_SAVE_COUNT = [0]

STEP_RESULTS = []  # (step label, "PASS"/"FAIL"/"SKIP", detail)

CTX = {
    "textures": {},        # key -> unreal.Texture2D (required + optional)
    "material": None,
    "material_mode": "none",  # "rich_v2" | "rich_v1" | "fallback" | "failed"
    "preflight_ok": False,
    "groups": [],          # v2 groups actually built (for the summary)
}


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def record(step, status, detail=""):
    STEP_RESULTS.append((step, status, detail))
    log("%-26s %-4s %s" % (step, status, detail))


def gc_now():
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Editor helpers (patterns proven in dress_arena.py / build_arena_level.py)
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
    """Package path of a UWorld, e.g. '/Game/Maps/BossArena' (drift-tolerant)."""
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


def set_prop_if_exists(obj, name, value, context=""):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s" % (name, (" on " + context) if context else "", exc))
        return False


def get_static_mesh_component(actor):
    try:
        comp = actor.static_mesh_component
        if comp is not None:
            return comp
    except Exception:
        pass
    return actor.get_component_by_class(unreal.StaticMeshComponent)


def force_save_asset(asset):
    """mark dirty -> save(only_if_is_dirty=False) -> verify the .uasset mtime
    advanced on disk (dirty-gated saves silently wrote NOTHING earlier)."""
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
    if before is not None:
        after = os.path.getmtime(disk_path)
        if after <= before:
            raise RuntimeError("save reported success but %s was NOT rewritten on disk"
                               % disk_path)
    _SAVE_COUNT[0] += 1
    if _SAVE_COUNT[0] % GC_EVERY_SAVES == 0:
        gc_now()


# ---------------------------------------------------------------------------
# Step 1: texture caps (before any material references them)
# ---------------------------------------------------------------------------

def _cap_texture(path, cap):
    """Cap one texture; 'capped'/'skip'/'fail'. NEVER raises an existing
    lower cap (the KiteDemo 1024-forced sets stay 1024)."""
    try:
        tex = unreal.EditorAssetLibrary.load_asset(path)
        if tex is None or not isinstance(tex, unreal.Texture2D):
            return "skip"
        cur = int(tex.get_editor_property("max_texture_size"))
        if 0 < cur <= cap:
            return "skip"
        tex.set_editor_property("max_texture_size", cap)
        if int(tex.get_editor_property("max_texture_size")) != cap:
            raise RuntimeError("max_texture_size write-back did not stick")
        force_save_asset(tex)
        return "capped"
    except Exception as exc:
        warn("  texture cap FAILED for %s: %s" % (path, exc))
        return "fail"


def step_texture_caps():
    capped, skipped, failed, missing = 0, 0, 0, 0
    for path in CAP_TEXTURES:
        if not unreal.EditorAssetLibrary.does_asset_exist(path):
            warn("texture cap: asset missing (its v2 group will skip): %s" % path)
            missing += 1
            continue
        res = _cap_texture(path, MAX_TEX_SIZE)
        capped += res == "capped"
        skipped += res == "skip"
        failed += res == "fail"
    # ANY per-item cap failure must surface in the status column -- an
    # uncapped 4K detail texture feeds the v2 groups and can bust the 2200
    # streaming-pool budget (missing textures stay non-fatal: their groups
    # degrade to skip in preflight).
    status = "FAIL" if failed else "PASS"
    record("1 texture caps", status,
           "%d capped to %d, %d already <=, %d failed, %d missing"
           % (capped, MAX_TEX_SIZE, skipped, failed, missing))


# ---------------------------------------------------------------------------
# Step 2: preflight -- load everything the build (and its FALLBACK) needs
# ---------------------------------------------------------------------------

def _base_tex_path(key):
    return "%s/T_%s" % (TEX_DIR, key)


def _load_tex(path):
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return None
    asset = unreal.EditorAssetLibrary.load_asset(path)
    return asset if isinstance(asset, unreal.Texture) else None


def step_preflight():
    # Required: the six base maps. Missing ANY -> refuse to touch M_Terrain
    # (a delete_all with nothing to rebuild from would gut a good material).
    missing = []
    for key in BASE_TEX_KEYS:
        tex = _load_tex(_base_tex_path(key))
        if tex is None:
            missing.append(key)
        else:
            CTX["textures"][key] = tex
    if missing:
        record("2 preflight", "FAIL",
               "REQUIRED base textures missing: %s -- M_Terrain left untouched"
               % ", ".join(missing))
        return

    wat = unreal.EditorAssetLibrary.load_asset(WORLD_ALIGNED_TEXTURE_FN)
    wan = unreal.EditorAssetLibrary.load_asset(WORLD_ALIGNED_NORMAL_FN)
    if wat is None or wan is None:
        # v1-rich also needs these; only the simple fallback would survive.
        # That is a downgrade of a working material -- refuse instead.
        record("2 preflight", "FAIL",
               "WorldAlignedTexture/Normal engine functions not found -- "
               "M_Terrain left untouched")
        return
    CTX["wat"], CTX["wan"] = wat, wan

    # Optional v2 inputs -- absence degrades the matching group to skip.
    notes = []
    for key, path, flag in (("macro", MACRO_TEX, DO_MACRO),
                            ("detail_nor", DETAIL_NOR_TEX, DO_DETAIL_NORMAL),
                            ("leaf_diff", LEAF_DIFF_TEX, DO_LEAF_LAYER),
                            ("leaf_nor", LEAF_NOR_TEX, DO_LEAF_LAYER)):
        if not flag:
            continue
        tex = _load_tex(path)
        if tex is None:
            notes.append("%s ABSENT (group skips)" % key)
        else:
            CTX["textures"][key] = tex
    for cls in ("MaterialExpressionDistance", "MaterialExpressionCameraPositionWS"):
        if not hasattr(unreal, cls):
            notes.append("%s ABSENT (1b collapses to near-only)" % cls)
    if not hasattr(unreal, "MaterialExpressionSmoothStep"):
        notes.append("SmoothStep absent (Subtract/Divide/Clamp fallback)")

    CTX["preflight_ok"] = True
    record("2 preflight", "PASS",
           "6 base + %d optional textures; %s"
           % (sum(1 for k in ("macro", "detail_nor", "leaf_diff", "leaf_nor")
                  if k in CTX["textures"]),
              "; ".join(notes) if notes else "all v2 inputs available"))


# ---------------------------------------------------------------------------
# MEL graph helpers (build_arena_level step-4 patterns, verbatim semantics)
# ---------------------------------------------------------------------------

MEL = unreal.MaterialEditingLibrary

# Candidate pin names for the engine material functions. The engine's own
# WorldAlignedTexture input is literally named "ProjectionTansitionContrast"
# (typo shipped in-engine) -- these names are data, not API.
WAT_IN_TEX = ["TextureObject (T2d)", "TextureObject", "Texture Object (T2d)", "Texture Object", ""]
WAT_IN_SIZE = ["TextureSize (V3)", "TextureSize", "Texture Size (V3)", "Texture Size"]
WAT_OUT = ["XYZTexture", "XYZ Texture", ""]
WAN_OUT = ["XYZTexture", "XYZ Texture", "XYZNormal", "XYZ Normal", "Normal", ""]
ANY_OUT = [""]


def _connect_expr(frm, out_names, to, in_names, what):
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
        raise RuntimeError("texture not available: %s" % key)
    return tex


def _const3(mat, v, x, y):
    node = _new_expr(mat, unreal.MaterialExpressionConstant3Vector, x, y)
    node.set_editor_property("constant", unreal.LinearColor(v[0], v[1], v[2], 1.0))
    return node


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


def _lerp(mat, a, b, alpha, x, y, what,
          a_outs=ANY_OUT, b_outs=ANY_OUT, alpha_outs=ANY_OUT, const_alpha=None):
    """LinearInterpolate; alpha is a node OR None with const_alpha set."""
    node = _new_expr(mat, unreal.MaterialExpressionLinearInterpolate, x, y)
    _connect_expr(a, a_outs, node, ["A"], what + ".A")
    _connect_expr(b, b_outs, node, ["B"], what + ".B")
    if alpha is not None:
        _connect_expr(alpha, alpha_outs, node, ["Alpha"], what + ".Alpha")
    elif const_alpha is not None:
        if not set_prop_if_exists(node, "const_alpha", float(const_alpha), what):
            raise RuntimeError("%s: const_alpha did not stick" % what)
    return node


def _mask(mat, r, g, b, a, x, y):
    node = _new_expr(mat, unreal.MaterialExpressionComponentMask, x, y)
    node.set_editor_property("r", r)
    node.set_editor_property("g", g)
    node.set_editor_property("b", b)
    node.set_editor_property("a", a)
    return node


def _slope_mask(mat):
    """VertexNormalWS.Z ^ 6, clamped. Flat ground -> 1 -> floor set."""
    vnorm = _new_expr(mat, unreal.MaterialExpressionVertexNormalWS, -1400, 1400)
    mask_z = _mask(mat, False, False, True, False, -1200, 1400)
    power = _new_expr(mat, unreal.MaterialExpressionPower, -1000, 1400)
    power.set_editor_property("const_exponent", 6.0)
    clamp = _new_expr(mat, unreal.MaterialExpressionClamp, -800, 1400)
    _connect_expr(vnorm, [""], mask_z, ["", "Input"], "slope.mask")
    _connect_expr(mask_z, [""], power, ["Base", ""], "slope.power")
    _connect_expr(power, [""], clamp, ["", "Input"], "slope.clamp")
    return clamp


def _wa_set(mat, size_node, x, y, tag):
    """floor+rock diff/arm/nor WorldAligned sextet at one tiling size."""
    wat, wan = CTX["wat"], CTX["wan"]
    return {
        "floor_diff": _make_world_aligned(mat, wat, _tex("floor_diff"), size_node, x, y, False, tag + ".floor_diff"),
        "floor_arm": _make_world_aligned(mat, wat, _tex("floor_arm"), size_node, x, y + 250, False, tag + ".floor_arm"),
        "floor_nor": _make_world_aligned(mat, wan, _tex("floor_nor"), size_node, x, y + 500, True, tag + ".floor_nor"),
        "rock_diff": _make_world_aligned(mat, wat, _tex("rock_diff"), size_node, x, y + 750, False, tag + ".rock_diff"),
        "rock_arm": _make_world_aligned(mat, wat, _tex("rock_arm"), size_node, x, y + 1000, False, tag + ".rock_arm"),
        "rock_nor": _make_world_aligned(mat, wan, _tex("rock_nor"), size_node, x, y + 1250, True, tag + ".rock_nor"),
    }


def _slope_lerps(mat, wa, slope, x, y, tag):
    """rock (A, slopes) -> floor (B, flat) blends for diff/arm/nor."""
    return {
        "diff": _lerp(mat, wa["rock_diff"], wa["floor_diff"], slope, x, y,
                      tag + ".diff", a_outs=WAT_OUT, b_outs=WAT_OUT),
        "arm": _lerp(mat, wa["rock_arm"], wa["floor_arm"], slope, x, y + 250,
                     tag + ".arm", a_outs=WAT_OUT, b_outs=WAT_OUT),
        "nor": _lerp(mat, wa["rock_nor"], wa["floor_nor"], slope, x, y + 500,
                     tag + ".nor", a_outs=WAN_OUT, b_outs=WAN_OUT),
    }


def _distance_alpha(mat):
    """Camera-distance 0(near)->1(far) mask over DIST_NEAR..DIST_FAR.
    Returns the alpha node, or None when the expression classes are absent
    (caller then collapses 1b to near-only)."""
    if not (hasattr(unreal, "MaterialExpressionDistance")
            and hasattr(unreal, "MaterialExpressionCameraPositionWS")):
        return None
    wpos = _new_expr(mat, unreal.MaterialExpressionWorldPosition, -2600, 1800)
    campos = _new_expr(mat, unreal.MaterialExpressionCameraPositionWS, -2600, 1950)
    dist = _new_expr(mat, unreal.MaterialExpressionDistance, -2400, 1850)
    _connect_expr(wpos, [""], dist, ["A", ""], "dist.A")
    _connect_expr(campos, [""], dist, ["B"], "dist.B")

    if hasattr(unreal, "MaterialExpressionSmoothStep"):
        try:
            ss = _new_expr(mat, unreal.MaterialExpressionSmoothStep, -2100, 1850)
            ok_min = set_prop_if_exists(ss, "const_min", DIST_NEAR, "smoothstep")
            ok_max = set_prop_if_exists(ss, "const_max", DIST_FAR, "smoothstep")
            if not (ok_min and ok_max):
                raise RuntimeError("SmoothStep const_min/const_max did not stick")
            _connect_expr(dist, [""], ss, ["Value", ""], "dist.smoothstep")
            return ss
        except Exception as exc:
            warn("SmoothStep path failed (%s) -- Subtract/Divide/Clamp fallback." % exc)
    sub = _new_expr(mat, unreal.MaterialExpressionSubtract, -2100, 1850)
    sub.set_editor_property("const_b", DIST_NEAR)
    div = _new_expr(mat, unreal.MaterialExpressionDivide, -1950, 1850)
    div.set_editor_property("const_b", DIST_FAR - DIST_NEAR)
    clamp = _new_expr(mat, unreal.MaterialExpressionClamp, -1800, 1850)
    _connect_expr(dist, [""], sub, ["A", ""], "dist.sub")
    _connect_expr(sub, [""], div, ["A", ""], "dist.div")
    _connect_expr(div, [""], clamp, ["", "Input"], "dist.clamp")
    return clamp


def _macro_nodes(mat):
    """Two-octave macro noise. Returns (raw_noise, darkening_remap) or
    (None, None) when the macro texture is unavailable / disabled."""
    macro_tex = CTX["textures"].get("macro")
    if not DO_MACRO or macro_tex is None:
        return None, None
    # sampler: engine macro texture is typically linear -- match its srgb flag
    try:
        srgb = bool(macro_tex.get_editor_property("srgb"))
    except Exception:
        srgb = True
    sampler = (unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if srgb
               else unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)

    wpos = _new_expr(mat, unreal.MaterialExpressionWorldPosition, -2600, 2300)
    mask_rg = _mask(mat, True, True, False, False, -2400, 2300)
    _connect_expr(wpos, [""], mask_rg, ["", "Input"], "macro.maskrg")

    def octave(divisor, y):
        div = _new_expr(mat, unreal.MaterialExpressionDivide, -2200, y)
        div.set_editor_property("const_b", divisor)
        _connect_expr(mask_rg, [""], div, ["A", ""], "macro.div%d" % divisor)
        ts = _new_expr(mat, unreal.MaterialExpressionTextureSample, -2000, y)
        ts.set_editor_property("texture", macro_tex)
        set_prop_if_exists(ts, "sampler_type", sampler, "macro.sample")
        _connect_expr(div, [""], ts, ["UVs", "Coordinates", ""], "macro.uv%d" % divisor)
        return ts

    ts1 = octave(MACRO_OCTAVE_1, 2250)
    ts2 = octave(MACRO_OCTAVE_2, 2450)
    mult = _new_expr(mat, unreal.MaterialExpressionMultiply, -1750, 2350)
    _connect_expr(ts1, ["R", ""], mult, ["A"], "macro.mult.A")
    _connect_expr(ts2, ["R", ""], mult, ["B"], "macro.mult.B")
    # remap Lerp(0.83, 1.0, noise) via const A/B -- only Alpha is wired
    remap = _new_expr(mat, unreal.MaterialExpressionLinearInterpolate, -1550, 2350)
    if not (set_prop_if_exists(remap, "const_a", MACRO_DARK_MIN, "macro.remap")
            and set_prop_if_exists(remap, "const_b", 1.0, "macro.remap")):
        raise RuntimeError("macro remap const_a/const_b did not stick")
    _connect_expr(mult, [""], remap, ["Alpha"], "macro.remap.Alpha")
    return mult, remap


def _build_rich_v2(mat):
    """v1 base + groups 1a/1b/1c/1d. Raises on any snag; caller falls back."""
    groups = ["base350"]

    size_near = _const3(mat, (SIZE_NEAR, SIZE_NEAR, SIZE_NEAR), -3400, -600)
    slope = _slope_mask(mat)

    near = _wa_set(mat, size_near, -3000, -1200, "near")
    near_l = _slope_lerps(mat, near, slope, -1300, -1200, "near")

    # ---- 1b distance tiling breakup ------------------------------------
    dist_alpha = _distance_alpha(mat) if DO_DISTANCE_BLEND else None
    if dist_alpha is not None:
        size_far = _const3(mat, (SIZE_FAR, SIZE_FAR, SIZE_FAR), -3400, -400)
        far = _wa_set(mat, size_far, -3000, 300, "far")
        far_l = _slope_lerps(mat, far, slope, -1300, 300, "far")
        diff_nf = _lerp(mat, near_l["diff"], far_l["diff"], dist_alpha, -1000, -1100, "nf.diff")
        arm_nf = _lerp(mat, near_l["arm"], far_l["arm"], dist_alpha, -1000, -850, "nf.arm")
        nor_nf = _lerp(mat, near_l["nor"], far_l["nor"], dist_alpha, -1000, -600, "nf.nor")
        groups.append("1b_distance")
    else:
        diff_nf, arm_nf, nor_nf = near_l["diff"], near_l["arm"], near_l["nor"]
        if DO_DISTANCE_BLEND:
            warn("1b skipped: Distance/CameraPositionWS expressions unavailable.")

    # ---- 1a macro variation ---------------------------------------------
    macro_raw, macro_remap = _macro_nodes(mat)
    if macro_remap is not None:
        groups.append("1a_macro")
    elif DO_MACRO:
        warn("1a skipped: %s unavailable." % MACRO_TEX)

    # ---- 1d dead-leaf dirt layer -----------------------------------------
    diff_leaf, nor_leaf = diff_nf, nor_nf
    if (DO_LEAF_LAYER and macro_raw is not None
            and CTX["textures"].get("leaf_diff") is not None):
        leaf_d = _make_world_aligned(mat, CTX["wat"], _tex("leaf_diff"),
                                     size_near, -3000, 2700, False, "leaf.diff")
        inv = _new_expr(mat, unreal.MaterialExpressionOneMinus, -1550, 2650)
        _connect_expr(macro_raw, [""], inv, ["", "Input"], "leaf.oneminus")
        m1 = _new_expr(mat, unreal.MaterialExpressionMultiply, -1400, 2650)
        _connect_expr(inv, [""], m1, ["A"], "leaf.mult.A")
        _connect_expr(slope, [""], m1, ["B"], "leaf.mult.B")
        m2 = _new_expr(mat, unreal.MaterialExpressionPower, -1250, 2650)
        m2.set_editor_property("const_exponent", 2.0)
        _connect_expr(m1, [""], m2, ["Base", ""], "leaf.power")
        diff_leaf = _lerp(mat, diff_nf, leaf_d, m2, -700, -1100, "leaf.diff.lerp",
                          b_outs=WAT_OUT)
        if CTX["textures"].get("leaf_nor") is not None:
            leaf_n = _make_world_aligned(mat, CTX["wan"], _tex("leaf_nor"),
                                         size_near, -3000, 2950, True, "leaf.nor")
            nor_leaf = _lerp(mat, nor_nf, leaf_n, m2, -700, -600, "leaf.nor.lerp",
                             b_outs=WAN_OUT)
        groups.append("1d_leafdirt")
    elif DO_LEAF_LAYER:
        warn("1d skipped: needs macro noise + %s." % LEAF_DIFF_TEX)

    # ---- BaseColor: macro darkening multiply ------------------------------
    base_color = diff_leaf
    if macro_remap is not None:
        dark = _new_expr(mat, unreal.MaterialExpressionMultiply, -400, -1100)
        _connect_expr(diff_leaf, [""], dark, ["A"], "macro.dark.A")
        _connect_expr(macro_remap, [""], dark, ["B"], "macro.dark.B")
        base_color = dark

    # ---- 1c detail normal (near band only) --------------------------------
    nor_final = nor_leaf
    if DO_DETAIL_NORMAL and CTX["textures"].get("detail_nor") is not None:
        size_det = _const3(mat, (SIZE_DETAIL, SIZE_DETAIL, SIZE_DETAIL), -3400, -200)
        det = _make_world_aligned(mat, CTX["wan"], _tex("detail_nor"),
                                  size_det, -3000, 3300, True, "detail.nor")
        flat = _const3(mat, (0.0, 0.0, 1.0), -2600, 3300)
        det_flat = _lerp(mat, flat, det, None, -2300, 3300, "detail.flatten",
                         b_outs=WAN_OUT, const_alpha=DETAIL_FLATTEN)
        det_rg = _mask(mat, True, True, False, False, -2100, 3300)
        _connect_expr(det_flat, [""], det_rg, ["", "Input"], "detail.maskrg")
        det_scaled = det_rg
        if dist_alpha is not None:
            near_amt = _new_expr(mat, unreal.MaterialExpressionOneMinus, -2100, 3450)
            _connect_expr(dist_alpha, [""], near_amt, ["", "Input"], "detail.nearband")
            sc = _new_expr(mat, unreal.MaterialExpressionMultiply, -1900, 3350)
            _connect_expr(det_rg, [""], sc, ["A"], "detail.scale.A")
            _connect_expr(near_amt, [""], sc, ["B"], "detail.scale.B")
            det_scaled = sc
        base_rg = _mask(mat, True, True, False, False, -700, -350)
        base_b = _mask(mat, False, False, True, False, -700, -200)
        _connect_expr(nor_leaf, [""], base_rg, ["", "Input"], "detail.base.rg")
        _connect_expr(nor_leaf, [""], base_b, ["", "Input"], "detail.base.b")
        add_rg = _new_expr(mat, unreal.MaterialExpressionAdd, -500, -350)
        _connect_expr(base_rg, [""], add_rg, ["A"], "detail.add.A")
        _connect_expr(det_scaled, [""], add_rg, ["B"], "detail.add.B")
        nor_final = _new_expr(mat, unreal.MaterialExpressionAppendVector, -300, -300)
        _connect_expr(add_rg, [""], nor_final, ["A"], "detail.append.A")
        _connect_expr(base_b, [""], nor_final, ["B"], "detail.append.B")
        groups.append("1c_detailnormal")
    elif DO_DETAIL_NORMAL:
        warn("1c skipped: %s unavailable." % DETAIL_NOR_TEX)

    # ---- ARM unpack (R = AO, G = roughness; metal ignored -- stone) --------
    rough_mask = _mask(mat, False, True, False, False, -400, -850)
    ao_mask = _mask(mat, True, False, False, False, -400, -700)
    _connect_expr(arm_nf, [""], rough_mask, ["", "Input"], "arm.rough")
    _connect_expr(arm_nf, [""], ao_mask, ["", "Input"], "arm.ao")

    _connect_prop(base_color, [""], unreal.MaterialProperty.MP_BASE_COLOR, "BaseColor")
    _connect_prop(nor_final, [""], unreal.MaterialProperty.MP_NORMAL, "Normal")
    _connect_prop(rough_mask, [""], unreal.MaterialProperty.MP_ROUGHNESS, "Roughness")
    _connect_prop(ao_mask, [""], unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "AO")

    CTX["groups"] = groups
    return groups


def _build_rich_v1(mat):
    """The PROVEN current graph (build_arena_level step 4, verbatim
    semantics): floor+rock world-aligned @350, slope-blended, ARM unpack."""
    size = _const3(mat, (SIZE_NEAR, SIZE_NEAR, SIZE_NEAR), -2200, -600)
    slope = _slope_mask(mat)
    wa = _wa_set(mat, size, -1800, -900, "v1")
    lerps = _slope_lerps(mat, wa, slope, -400, -800, "v1")

    rough_mask = _mask(mat, False, True, False, False, -150, -200)
    ao_mask = _mask(mat, True, False, False, False, -150, 0)
    _connect_expr(lerps["arm"], [""], rough_mask, ["", "Input"], "v1.arm.rough")
    _connect_expr(lerps["arm"], [""], ao_mask, ["", "Input"], "v1.arm.ao")

    _connect_prop(lerps["diff"], [""], unreal.MaterialProperty.MP_BASE_COLOR, "v1.BaseColor")
    _connect_prop(lerps["nor"], [""], unreal.MaterialProperty.MP_NORMAL, "v1.Normal")
    _connect_prop(rough_mask, [""], unreal.MaterialProperty.MP_ROUGHNESS, "v1.Roughness")
    _connect_prop(ao_mask, [""], unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "v1.AO")


def _build_fallback_simple(mat):
    """Guaranteed-simple: floor set mapped by world XY / 350. No engine
    function calls, no slope blend -- the terrain is at least textured."""
    wpos = _new_expr(mat, unreal.MaterialExpressionWorldPosition, -1200, 0)
    mask_rg = _mask(mat, True, True, False, False, -1000, 0)
    divide = _new_expr(mat, unreal.MaterialExpressionDivide, -800, 0)
    divide.set_editor_property("const_b", SIZE_NEAR)
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
    nor = sample("floor_nor", 0, True)
    arm = sample("floor_arm", 300, False)

    rough_mask = _mask(mat, False, True, False, False, -250, 300)
    ao_mask = _mask(mat, True, False, False, False, -250, 450)
    _connect_expr(arm, [""], rough_mask, ["", "Input"], "fb.rough")
    _connect_expr(arm, [""], ao_mask, ["", "Input"], "fb.ao")

    _connect_prop(diff, [""], unreal.MaterialProperty.MP_BASE_COLOR, "fb.BaseColor")
    _connect_prop(nor, [""], unreal.MaterialProperty.MP_NORMAL, "fb.Normal")
    _connect_prop(rough_mask, [""], unreal.MaterialProperty.MP_ROUGHNESS, "fb.Roughness")
    _connect_prop(ao_mask, [""], unreal.MaterialProperty.MP_AMBIENT_OCCLUSION, "fb.AO")


# ---------------------------------------------------------------------------
# Step 3: rebuild M_Terrain (v2 -> v1 -> simple ladder; never unmaterialed)
# ---------------------------------------------------------------------------

def _restore_material_from_disk(mat):
    """Triple-failure path: discard the gutted in-memory graph by reloading
    the material's package from disk (the disk copy is the last WORKING
    M_Terrain). Verified by re-reading the expression count so a later
    interactive save-all cannot flush an empty graph either."""
    try:
        pkg = mat.get_outer()
        unreal.EditorLoadingAndSavingUtils.reload_packages([pkg])
    except Exception as exc:
        warn("reload_packages(M_Terrain) failed: %s" % exc)
    try:
        check = unreal.EditorAssetLibrary.load_asset(MAT_PATH)
        n = MEL.get_num_material_expressions(check) if check is not None else -1
        if n > 0:
            log("M_Terrain reloaded from disk (%d nodes back in memory)." % n)
            return True
        warn("M_Terrain reload could NOT be verified (%s nodes) -- the "
             "in-memory graph may still be empty. The on-disk asset is "
             "untouched, but do NOT 'save all' in this editor session." % n)
    except Exception as exc:
        warn("M_Terrain reload verify failed: %s -- on-disk asset untouched; "
             "do NOT 'save all' in this editor session." % exc)
    return False


def step_rebuild_material():
    if not CTX["preflight_ok"]:
        record("3 rebuild M_Terrain", "FAIL", "preflight failed -- untouched")
        return

    if unreal.EditorAssetLibrary.does_asset_exist(MAT_PATH):
        log("M_Terrain exists -- rebuilding its graph in place.")
        mat = unreal.EditorAssetLibrary.load_asset(MAT_PATH)
    else:
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "M_Terrain", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        record("3 rebuild M_Terrain", "FAIL", "could not create/load %s" % MAT_PATH)
        return

    MEL.delete_all_material_expressions(mat)
    try:
        groups = _build_rich_v2(mat)
        CTX["material_mode"] = "rich_v2"
        detail = "v2 graph: %s" % "+".join(groups)
    except Exception as exc:
        warn("v2 terrain graph failed (%s) -- rebuilding the PROVEN v1 rich "
             "graph instead." % exc)
        warn(traceback.format_exc())
        MEL.delete_all_material_expressions(mat)
        gc_now()
        try:
            _build_rich_v1(mat)
            CTX["material_mode"] = "rich_v1"
            detail = "v2 FAILED -> proven v1 rich graph rebuilt (terrain looks as before)"
        except Exception as v1_exc:
            warn("v1 rich graph ALSO failed (%s) -- simple world-XY fallback." % v1_exc)
            warn(traceback.format_exc())
            MEL.delete_all_material_expressions(mat)
            try:
                _build_fallback_simple(mat)
                CTX["material_mode"] = "fallback"
                detail = "v2+v1 FAILED -> simple world-XY floor material"
            except Exception as fb_exc:
                # Triple failure (realistic cause: MEL dysfunction in a
                # headless commandlet -- all three ladder tiers share the
                # same MEL helpers, so they are not independent failure
                # domains). Do NOT recompile or save: the on-disk M_Terrain
                # is the last WORKING graph and ARENA_Terrain/_PatrolZone
                # slot 0 already reference it -- saving the gutted in-memory
                # graph would ship a black/empty 200 m terrain.
                warn("Simple fallback ALSO failed (%s) -- preserving the "
                     "on-disk M_Terrain; NOT recompiling, NOT saving." % fb_exc)
                warn(traceback.format_exc())
                CTX["material_mode"] = "failed"
                detail = ("ALL graphs failed -- on-disk M_Terrain preserved "
                          "(NOT saved), slots untouched")

    if CTX["material_mode"] == "failed":
        # Only rich_v2/rich_v1/fallback may reach recompile+save. Reload the
        # package from disk so a later interactive save-all in this editor
        # session cannot flush the gutted graph either.
        CTX["material"] = None
        _restore_material_from_disk(mat)
        record("3 rebuild M_Terrain", "FAIL", detail)
        return

    MEL.recompile_material(mat)
    try:
        n_nodes = MEL.get_num_material_expressions(mat)
    except Exception:
        n_nodes = -1
    try:
        force_save_asset(mat)
    except Exception as exc:
        record("3 rebuild M_Terrain", "FAIL",
               "%s BUT SAVE FAILED: %s" % (detail, exc))
        CTX["material"] = mat
        return
    gc_now()

    CTX["material"] = mat
    record("3 rebuild M_Terrain", "PASS",
           "%s (%d nodes, recompiled, saved+mtime-verified)" % (detail, n_nodes))


# ---------------------------------------------------------------------------
# Steps 4/5: assign to the terrain + zone actors, verify by re-read
# ---------------------------------------------------------------------------

def _find_actor_by_label(label):
    for a in get_actor_subsystem().get_all_level_actors():
        try:
            if a is not None and str(a.get_actor_label()) == label:
                return a
        except Exception:
            continue
    return None


def _assign_material_to(label, step_name, required):
    mat = CTX["material"]
    if mat is None or CTX["material_mode"] not in ("rich_v2", "rich_v1", "fallback"):
        record(step_name, "FAIL",
               "no usable M_Terrain (mode=%s) -- slot untouched" % CTX["material_mode"])
        return False
    actor = _find_actor_by_label(label)
    if actor is None:
        if required:
            record(step_name, "FAIL", "actor '%s' not found in %s" % (label, MAP_PATH))
        else:
            record(step_name, "SKIP",
                   "actor '%s' absent (arena-only build)" % label)
        return False
    comp = get_static_mesh_component(actor)
    if comp is None:
        record(step_name, "FAIL", "'%s' has no StaticMeshComponent" % label)
        return False

    want = mat.get_path_name()
    try:
        cur = comp.get_material(0)
        cur_path = cur.get_path_name() if cur is not None else "<none>"
    except Exception:
        cur_path = "<unreadable>"

    if cur_path != want:
        comp.set_material(0, mat)
    # verify by re-read (blanket write-back rule)
    got = comp.get_material(0)
    got_path = got.get_path_name() if got is not None else "<none>"
    if got_path != want:
        record(step_name, "FAIL",
               "slot 0 re-read '%s' != '%s' -- assign manually" % (got_path, want))
        return False
    record(step_name, "PASS",
           "slot 0 = M_Terrain (%s)" %
           ("already assigned" if cur_path == want else "assigned now"))
    return cur_path != want  # True -> level actually changed


def step_assign_terrain():
    changed = _assign_material_to(TERRAIN_LABEL, "4 assign ARENA_Terrain", required=True)
    CTX["level_dirty"] = CTX.get("level_dirty", False) or bool(changed)


def step_assign_zone():
    changed = _assign_material_to(ZONE_LABEL, "5 assign ARENA_PatrolZone", required=False)
    CTX["level_dirty"] = CTX.get("level_dirty", False) or bool(changed)


# ---------------------------------------------------------------------------
# Step 6: save level
# ---------------------------------------------------------------------------

def step_save_level():
    if not CTX.get("level_dirty", False):
        record("6 save level", "SKIP", "no actor slot changed (asset saves already verified)")
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
    "1 texture caps", "2 preflight", "3 rebuild M_Terrain",
    "4 assign ARENA_Terrain", "5 assign ARENA_PatrolZone", "6 save level")


def print_summary():
    log("=" * 72)
    log("M_TERRAIN V2 SUMMARY  (mode=%s, groups=%s)"
        % (CTX["material_mode"], "+".join(CTX["groups"]) or "-"))
    for step, status, detail in STEP_RESULTS:
        log("  %-4s %-26s %s" % (status, step, detail))
    n_fail = sum(1 for _, s, _ in STEP_RESULTS if s == "FAIL")
    log("-" * 72)
    log("PERF GATE (spec lever 1): expected +0.35-0.55 ms GPU @1080p/80% SP,")
    log("ceiling 0.8. If over: DO_DETAIL_NORMAL=False first, then")
    log("DO_DISTANCE_BLEND=False (near-only), and re-run (idempotent).")
    log("Run 'stat streaming' -- pool must stay under 2200 (visuals.md);")
    log("never touch r.Streaming.PoolSize or the dress_arena atmosphere numbers.")
    if n_fail:
        warn("%d step(s) FAILED -- see warnings above." % n_fail)
    log("=" * 72)


def main():
    log("M_Terrain v2 upgrade (lever 1) -- map %s, material %s" % (MAP_PATH, MAT_PATH))
    log("Groups enabled: macro=%s distance=%s detail=%s leaf=%s"
        % (DO_MACRO, DO_DISTANCE_BLEND, DO_DETAIL_NORMAL, DO_LEAF_LAYER))
    # BLOCKER guard: never touch assets/actors or SAVE outside BossArena.
    if not ensure_bossarena_open():
        for label in ALL_STEP_LABELS:
            record(label, "FAIL",
                   "wrong level open and %s could not be loaded -- NOTHING "
                   "was touched" % MAP_PATH)
        print_summary()
        return
    steps = [step_texture_caps,
             step_preflight,
             step_rebuild_material,
             step_assign_terrain,
             step_assign_zone,
             step_save_level]
    for fn in steps:
        try:
            fn()
        except Exception as exc:  # per-step isolation -- never abort the rest
            record(fn.__name__, "FAIL", str(exc))
            warn(traceback.format_exc())
        gc_now()  # crash resistance between steps (16 GB box)
    print_summary()


if __name__ == "__main__":
    main()
