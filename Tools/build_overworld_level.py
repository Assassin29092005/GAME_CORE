"""Build the Overworld level end-to-end (Tier 4 Phase A2).

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/build_overworld_level.py"
  (or Tools -> Execute Python Script... and pick this file)

Prerequisites (produced by Tools/build_overworld_heightmap.py in Blender):
  D:/GAME_CORE 5.8/SourceArt/Overworld/Textures/T_Overworld_Heightmap.png   (2049x2049, 16-bit BW)
  D:/GAME_CORE 5.8/SourceArt/Overworld/Textures/T_Overworld_Weight_<Biome>.png x 5

What it does (each step isolated; one failure never aborts the rest):
  1. Ensure /Game/Overworld/{Textures,Materials} folders + import heightmap +
     five weightmap PNGs as Texture2D assets (Non-Color, TC_Grayscale).
  2. Build M_OverworldLandscape material (5-layer weightmap-blend landscape
     material; fallback single-layer if the multi-layer setup errors).
  3. Create /Game/Maps/Overworld (empty World Partition template if available;
     otherwise standard empty level + prints World Partition enable note).
  4. Nav bounds via unreal.ArenaEditorTools.spawn_nav_bounds_volume
     (feature-detected; SKIP + manual-drag note when absent).
  5. Print PASS/FAIL/SKIP summary + a MANUAL STEPS block with the exact
     Landscape Mode UI clicks (Python API for landscape heightmap import is
     limited in UE 5.8; the manual click sequence is short and reliable).

Idempotent: actor labels are prefixed 'OVERWORLD_*' so re-runs clean up
previously-spawned objects before spawning new ones.
"""

import os
import traceback

import unreal


# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

SOURCE_OVERWORLD_DIR = r"D:\GAME_CORE 5.8\SourceArt\Overworld\Textures"

TEX_DIR = "/Game/Overworld/Textures"
MAT_DIR = "/Game/Overworld/Materials"
MAP_DIR = "/Game/Maps"
MAP_PATH = "/Game/Maps/Overworld"

HEIGHTMAP_SRC = os.path.join(SOURCE_OVERWORLD_DIR, "T_Overworld_Heightmap.png")
WEIGHTMAP_BIOMES = ("Castle", "Marsh", "Desert", "Mountains", "Plains")

MATERIAL_NAME = "M_OverworldLandscape"

# 2 km world at 1 m/quad -> 2049 verts per side. UE landscape needs
# SectionSize * NumSectionsPerComponent + 1 = grid side. Recommended combos
# from Epic that come CLOSE to 2049:
#   127 * 16 + 1 = 2033  (loses 16 m on each axis)
#   63  * 32 + 1 = 2017  (loses 32 m)
#   255 * 8  + 1 = 2041  (loses 8 m)
# We recommend 255x1 sections/comp, 8x8 components (2041x2041) at 100 cm/quad.
# The exact number is printed in the MANUAL STEPS block below.
LANDSCAPE_SECTION_SIZE = 255
LANDSCAPE_SECTIONS_PER_COMP = 1
LANDSCAPE_COMPONENT_COUNT = 8  # per axis -> 8x8 = 64 components
LANDSCAPE_QUAD_SIZE_CM = 100.0
LANDSCAPE_HEIGHT_RANGE_CM = 30000.0  # 300 m elevation range (heightmap 0..1 -> 0..300 m)

# Nav bounds cover the walkable landscape footprint
NAV_BOUNDS_LABEL = "OVERWORLD_NavBounds"
NAV_BOUNDS_CENTER = (0.0, 0.0, 15000.0)                  # centered on landscape
NAV_BOUNDS_EXTENT = (110000.0, 110000.0, 30000.0)        # half-sizes UU (~2.2 km each side)

# Tag every spawned actor with this prefix so re-runs can sweep them
LABEL_PREFIX = "OVERWORLD_"

# Weightmap PNG -> layer blend colors for the fallback single-layer material
BIOME_TINT = {
    "Castle":    (0.62, 0.57, 0.52),
    "Marsh":     (0.15, 0.36, 0.32),
    "Desert":    (0.87, 0.76, 0.46),
    "Mountains": (0.36, 0.33, 0.31),
    "Plains":    (0.36, 0.55, 0.24),
}


# ---------------------------------------------------------------------------
# Framework: step contexts + summary
# ---------------------------------------------------------------------------

class StepSkip(Exception):
    """Raise from a step to record it as SKIP (not FAIL)."""


CTX = {
    "results": [],           # (step_name, status, message)
    "extra_manual": [],      # extra manual-step lines
}


def _record(step, status, msg=""):
    CTX["results"].append((step, status, msg))
    tag = {"PASS": "+", "SKIP": "~", "FAIL": "!"}.get(status, "?")
    unreal.log("[overworld] %s %s: %s" % (tag, step, msg or status))


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
                unreal.log_warning("[overworld] step %s failed:\n%s" % (name, tb))
                _record(name, "FAIL", str(e))
        return _inner
    return _wrap


# ---------------------------------------------------------------------------
# Editor helpers
# ---------------------------------------------------------------------------

def _ensure_dir(package_path):
    if not unreal.EditorAssetLibrary.does_directory_exist(package_path):
        unreal.EditorAssetLibrary.make_directory(package_path)


def _sweep_labeled_actors(prefix):
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.EditorLevelLibrary.get_editor_world()
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


def _asset_exists(path):
    return unreal.EditorAssetLibrary.does_asset_exist(path)


def _load(path):
    return unreal.EditorAssetLibrary.load_asset(path) if _asset_exists(path) else None


def _save(path):
    if _asset_exists(path):
        unreal.EditorAssetLibrary.save_loaded_asset(unreal.EditorAssetLibrary.load_asset(path))


# ---------------------------------------------------------------------------
# Step 1 - Import heightmap + weightmap textures
# ---------------------------------------------------------------------------

def _make_texture_import_task(src_png, dst_pkg, asset_name):
    task = unreal.AssetImportTask()
    task.filename = src_png
    task.destination_path = dst_pkg
    task.destination_name = asset_name
    task.replace_existing = True
    task.automated = True
    task.save = True
    return task


@_step("1. Import overworld textures")
def step_1_import_textures():
    _ensure_dir(TEX_DIR)

    missing = []
    tasks = []
    imports = [("T_Overworld_Heightmap.png", "T_Overworld_Heightmap")]
    for b in WEIGHTMAP_BIOMES:
        imports.append(("T_Overworld_Weight_%s.png" % b, "T_Overworld_Weight_%s" % b))

    for fname, asset_name in imports:
        src = os.path.join(SOURCE_OVERWORLD_DIR, fname)
        if not os.path.exists(src):
            missing.append(fname)
            continue
        tasks.append(_make_texture_import_task(src, TEX_DIR, asset_name))

    if missing:
        raise StepSkip("missing source PNGs: %s (run Tools/build_overworld_heightmap.py first)" % missing)

    if tasks:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    # Apply per-texture settings (Non-Color, TC_Grayscale)
    for _, asset_name in imports:
        asset_path = "%s/%s" % (TEX_DIR, asset_name)
        tex = _load(asset_path)
        if tex is None:
            continue
        tex.set_editor_property("srgb", False)
        tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
        tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
        _save(asset_path)
    return "imported %d texture(s)" % len(tasks)


# ---------------------------------------------------------------------------
# Step 2 - Build M_OverworldLandscape material
# ---------------------------------------------------------------------------

def _mk_expr(mat, cls, x, y):
    return unreal.MaterialEditingLibrary.create_material_expression(mat, cls, x, y)


def _connect(from_expr, from_pin, to_expr, to_pin):
    unreal.MaterialEditingLibrary.connect_material_expressions(
        from_expr, from_pin, to_expr, to_pin
    )


def _connect_to_prop(from_expr, from_pin, mat, prop):
    unreal.MaterialEditingLibrary.connect_material_property(
        from_expr, from_pin, prop
    )


@_step("2. Build M_OverworldLandscape material")
def step_2_material():
    _ensure_dir(MAT_DIR)

    mat_path = "%s/%s" % (MAT_DIR, MATERIAL_NAME)
    if _asset_exists(mat_path):
        unreal.EditorAssetLibrary.delete_asset(mat_path)

    factory = unreal.MaterialFactoryNew()
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        MATERIAL_NAME, MAT_DIR, unreal.Material, factory
    )
    if mat is None:
        raise StepSkip("MaterialFactory.create_asset returned None")

    # Landscape materials need LandscapeLayerBlend expression driving Base Color.
    # We create one LayerBlend with 5 layers (Castle/Marsh/Desert/Mountains/Plains),
    # each layer sampling a per-biome color constant. UE fills the layer weights
    # from the imported weightmaps at landscape-paint / landscape-import time.
    try:
        blend = _mk_expr(mat, unreal.MaterialExpressionLandscapeLayerBlend, -400, 0)

        # Create per-layer constant color inputs
        layers = []
        for i, name in enumerate(WEIGHTMAP_BIOMES):
            r, g, b = BIOME_TINT[name]
            const = _mk_expr(mat, unreal.MaterialExpressionConstant3Vector,
                             -800, i * 200 - 400)
            const.set_editor_property("constant", unreal.LinearColor(r, g, b, 1.0))
            layers.append((name, const))

        # Populate the LayerBlend layers array
        layer_infos = []
        for name, _const in layers:
            info = unreal.LandscapeLayerBlendInput()
            info.layer_name = name
            info.blend_type = unreal.LandscapeLayerBlendType.LB_WEIGHT_BLEND
            info.const_layer_input = unreal.LinearColor(0.0, 0.0, 0.0, 1.0)
            info.preview_weight = 0.2
            layer_infos.append(info)
        blend.set_editor_property("layers", layer_infos)

        # Connect each layer color const -> corresponding LayerInput pin
        # (LayerBlend exposes input pins named after the layers array)
        for idx, (name, const) in enumerate(layers):
            try:
                _connect(const, "", blend, name)
            except Exception:
                # Fall back to a numeric index attempt
                _connect(const, "", blend, str(idx))

        # Wire blend -> BaseColor
        _connect_to_prop(blend, "", mat, unreal.MaterialProperty.MP_BASE_COLOR)

        # Roughness/Specular baseline constants
        rough = _mk_expr(mat, unreal.MaterialExpressionConstant, -400, 400)
        rough.set_editor_property("r", 0.85)
        _connect_to_prop(rough, "", mat, unreal.MaterialProperty.MP_ROUGHNESS)

        spec = _mk_expr(mat, unreal.MaterialExpressionConstant, -400, 500)
        spec.set_editor_property("r", 0.15)
        _connect_to_prop(spec, "", mat, unreal.MaterialProperty.MP_SPECULAR)

        unreal.MaterialEditingLibrary.recompile_material(mat)
        _save(mat_path)
        return "5-layer landscape material built"

    except Exception as e:
        unreal.log_warning("[overworld] multi-layer material failed (%s); "
                           "falling back to single-color debug material" % e)
        # Fallback: simple mid-green constant
        for expr in list(mat.get_editor_property("expressions") or []):
            unreal.MaterialEditingLibrary.delete_material_expression(mat, expr)
        col = _mk_expr(mat, unreal.MaterialExpressionConstant3Vector, -400, 0)
        col.set_editor_property("constant", unreal.LinearColor(0.36, 0.55, 0.24, 1.0))
        _connect_to_prop(col, "", mat, unreal.MaterialProperty.MP_BASE_COLOR)
        unreal.MaterialEditingLibrary.recompile_material(mat)
        _save(mat_path)
        return "fallback single-color material built (Landscape LayerBlend errored)"


# ---------------------------------------------------------------------------
# Step 3 - Create the Overworld level (empty)
# ---------------------------------------------------------------------------

@_step("3. Create /Game/Maps/Overworld level")
def step_3_create_level():
    _ensure_dir(MAP_DIR)

    if _asset_exists(MAP_PATH):
        # Reopen + clean any prior OVERWORLD_ actors
        unreal.EditorLoadingAndSavingUtils.load_map(MAP_PATH)
        removed = _sweep_labeled_actors(LABEL_PREFIX)
        return "reopened existing level (%d prior OVERWORLD_ actors cleaned)" % removed

    # Try World Partition template first (UE 5.0+)
    tpl_used = None
    for template in (
        unreal.NewLevelTemplate.EMPTY_LEVEL,
        unreal.NewLevelTemplate.OPEN_WORLD,     # WP template if available
    ):
        try:
            ok = unreal.EditorLevelLibrary.new_level_from_template(MAP_PATH, template.value)
            if ok:
                tpl_used = template.name
                break
        except Exception:
            continue

    if tpl_used is None:
        # Bare new_level fallback
        unreal.EditorLevelLibrary.new_level(MAP_PATH)
        tpl_used = "EMPTY (bare)"

    unreal.EditorAssetLibrary.save_asset(MAP_PATH)
    return "level created from template=%s" % tpl_used


# ---------------------------------------------------------------------------
# Step 4 - Nav mesh bounds volume via ArenaEditorTools helper
# ---------------------------------------------------------------------------

NAV_MANUAL_NOTE = (
    "Nav bounds MANUAL step: Place Actors panel -> Volumes -> "
    "'Nav Mesh Bounds Volume' -> drop into level -> Details: "
    "Brush Shape=Box, Brush Settings: X=%.0f Y=%.0f Z=%.0f, "
    "Location=(%.0f, %.0f, %.0f)."
    % (NAV_BOUNDS_EXTENT[0]*2, NAV_BOUNDS_EXTENT[1]*2, NAV_BOUNDS_EXTENT[2]*2,
       NAV_BOUNDS_CENTER[0], NAV_BOUNDS_CENTER[1], NAV_BOUNDS_CENTER[2])
)


@_step("4. Nav Mesh Bounds volume")
def step_4_nav_bounds():
    tools_cls = getattr(unreal, "ArenaEditorTools", None)
    fn = getattr(tools_cls, "spawn_nav_bounds_volume", None) if tools_cls is not None else None
    if fn is None:
        CTX["extra_manual"].append(NAV_MANUAL_NOTE)
        raise StepSkip("unreal.ArenaEditorTools.spawn_nav_bounds_volume unavailable "
                       "(C++ module not compiled for editor?) -- see manual note")

    # Kill any prior nav bounds we spawned
    subsys = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    world = unreal.EditorLevelLibrary.get_editor_world()
    actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
    for a in actors:
        try:
            if a.get_actor_label() == NAV_BOUNDS_LABEL:
                subsys.destroy_actor(a)
        except Exception:
            pass

    cx, cy, cz = NAV_BOUNDS_CENTER
    ex, ey, ez = NAV_BOUNDS_EXTENT
    center = unreal.Vector(cx, cy, cz)
    extent = unreal.Vector(ex, ey, ez)

    # Try known call signatures
    last_exc = None
    for args in [
        (center, extent, NAV_BOUNDS_LABEL),
        (center, extent),
        (NAV_BOUNDS_LABEL, center, extent),
    ]:
        try:
            result = fn(*args)
            break
        except Exception as e:
            last_exc = e
            result = None
    if result is None:
        CTX["extra_manual"].append(NAV_MANUAL_NOTE)
        raise StepSkip("spawn_nav_bounds_volume exists but no known call "
                       "signature worked (last error: %s)" % last_exc)

    volume = result if isinstance(result, unreal.Actor) else None
    if volume is not None:
        try:
            if volume.get_actor_label() != NAV_BOUNDS_LABEL:
                volume.set_actor_label(NAV_BOUNDS_LABEL)
        except Exception:
            pass
    return "spawned via C++ helper"


# ---------------------------------------------------------------------------
# Manual steps summary
# ---------------------------------------------------------------------------

MANUAL_STEPS = """
=============================================================================
 MANUAL STEPS (Landscape Mode UI + World Partition switches)
 UE 5.8 Python API doesn't cover these reliably; direct clicks below.
-----------------------------------------------------------------------------

 A. LANDSCAPE IMPORT (~90 s)
    1. In the /Game/Maps/Overworld level (already open), switch to
       'Landscape Mode' (Modes dropdown top-left, or Shift+2).
    2. Manage tab -> New Landscape -> IMPORT FROM FILE.
    3. Heightmap File:
       D:/GAME_CORE 5.8/SourceArt/Overworld/Textures/T_Overworld_Heightmap.png
    4. Under 'Landscape Settings' verify:
         Section Size:         %d Quads
         Sections Per Component: %d
         Component Count:      %d x %d
         Overall Resolution:   %d x %d  (should say ~2041 x 2041)
         Location:             (0, 0, 0)
         Scale X, Y:           %.1f  (each = %.0f cm/quad)
         Scale Z:              %.4f  (elevation range = %.0f cm = %.0f m)
       (Z scale formula: HeightRangeCM / 512 for the default 16-bit signed range,
        or just tune Z visually if the math looks off.)
    5. Under 'Landscape Material' assign /Game/Overworld/Materials/%s
    6. Under 'Layers' -> click '+' 5 times -> Layer 1..5, Name each:
         Castle, Marsh, Desert, Mountains, Plains (exact spelling)
       For each layer:
         'Weightmap File' -> T_Overworld_Weight_<Name>.png
         Layer Info -> Create -> pick a save location (/Game/Overworld/LayerInfos)
    7. Click 'Import'. Wait for build (~30 s).

 B. WORLD PARTITION (if the level didn't get it from the template)
    1. In the Content Browser, right-click /Game/Maps/Overworld ->
       'Convert Level to World Partition' -> follow the wizard defaults.
    2. Runtime Grid: create/edit 'MainGrid' -> Cell Size 102400 (1024 m),
       Loading Range 51200, HLOD Layer HLOD1, HLOD1 cull distance 500000
       (5 km). Save.

 C. LEVEL DEFAULTS
    1. World Settings -> Game Mode: your default (BP_GameMode or the boss
       game mode). Not strictly needed for Phase A verification.
    2. Save the level.

 D. VERIFY (Phase A verification checklist)
    1. PIE -> hero spawns near (0,0) on castle plateau -> walks all four
       directions without terrain gaps.
    2. Framerate >= 45 fps at 1080p Medium ('stat unit' in PIE).

 E. NEXT STEPS AFTER MANUAL LANDSCAPE IMPORT
    Rerun this script to spawn the nav bounds volume (step 4) after the
    landscape exists. Everything after Phase A (camera, encounter volumes,
    dressing) is Python + C++ from Cursor / this MCP session -- no more
    editor clicks until Phase G playtest.
=============================================================================
""" % (
    LANDSCAPE_SECTION_SIZE,
    LANDSCAPE_SECTIONS_PER_COMP,
    LANDSCAPE_COMPONENT_COUNT, LANDSCAPE_COMPONENT_COUNT,
    LANDSCAPE_SECTION_SIZE * LANDSCAPE_SECTIONS_PER_COMP * LANDSCAPE_COMPONENT_COUNT + 1,
    LANDSCAPE_SECTION_SIZE * LANDSCAPE_SECTIONS_PER_COMP * LANDSCAPE_COMPONENT_COUNT + 1,
    LANDSCAPE_QUAD_SIZE_CM, LANDSCAPE_QUAD_SIZE_CM,
    LANDSCAPE_HEIGHT_RANGE_CM / 512.0, LANDSCAPE_HEIGHT_RANGE_CM, LANDSCAPE_HEIGHT_RANGE_CM / 100.0,
    MATERIAL_NAME,
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    unreal.log("[overworld] build_overworld_level starting...")
    step_1_import_textures()
    step_2_material()
    step_3_create_level()
    step_4_nav_bounds()

    unreal.log("[overworld] ===== SUMMARY =====")
    for step, status, msg in CTX["results"]:
        unreal.log("[overworld]  %-6s  %s  --  %s" % (status, step, msg))

    if CTX["extra_manual"]:
        unreal.log("[overworld] ----- EXTRA MANUAL NOTES -----")
        for note in CTX["extra_manual"]:
            unreal.log("[overworld]  %s" % note)

    print(MANUAL_STEPS)


if __name__ == "__main__":
    main()
