"""Batch-retarget an animation pack onto this project's skeletons (IK Retargeter).

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/batch_retarget_anims.py"
  (or Tools -> Execute Python Script... and pick this file)

Typical uses: Fab packs authored on the stock UE4/UE5 mannequin skeletons ->
the project's UEFN mannequin (SK_UEFN_Mannequin), and later UEFN mannequin ->
MetaHuman. Edit the constants block below, re-run once per pack / character.

CREATE THE IK RETARGETER ASSET FIRST (one per source-skeleton family; ~2 min
in the UE 5.8 retargeter editor thanks to auto-generated IK Rigs):
  1. Content Browser -> right-click the SOURCE skeletal mesh (the mesh the Fab
     pack animates, e.g. SK_Mannequin) -> Create -> IK Retargeter.
  2. In the dialog pick the TARGET skeletal mesh (SK_UEFN_Mannequin). UE 5.8
     auto-generates an IK Rig for BOTH meshes and auto-maps the retarget
     chains -- no hand-built IK Rig assets needed.
  3. In the retargeter editor: verify the chain list (Root/Spine/Head, both
     Arms, both Legs mapped), click Auto Align if the source rest pose
     (A- vs T-pose) differs from the target, and scrub a test animation in
     the asset browser tab to eyeball the result.
  4. Save it (convention: /Game/Retargeting/RTG_<Source>_to_<Target>) and put
     its path in RETARGETER_ASSET below. This script reads the SOURCE and
     TARGET meshes from the retargeter's preview meshes (set automatically by
     steps 1-2), so no mesh paths are needed here unless you override them.

WHAT SURVIVES THE DUPLICATION:
  - duplicate_and_retarget DUPLICATES each asset first, then retargets the
    bone tracks on the copy. Montage structure -- sections, slot assignments,
    notifies and notify states (ANS_DealDamage windows etc.) -- is plain data
    on the montage asset, so it is copied verbatim with the same trigger
    times. Do verify slot names afterwards: a montage retargeted for a new
    character must use a slot that exists in THAT character's AnimBP (e.g.
    the hero's 'UpperBody.Block' upper-body slot -- see CLAUDE.md).
  - Montages batched TOGETHER with their source AnimSequences get their inner
    segment references remapped to the retargeted sequence copies. This
    script therefore always sends everything under SOURCE_FOLDER as ONE batch
    call -- don't split sequences and montages into separate invocations.

PER-CHARACTER COPY RULE (montage mutation caveat, CLAUDE.md): PlayComboMontage
/ RequestDodge / PlayHitReaction mutate the montage ASSET (blend times, root
motion flags) before play, so a montage may be assigned to exactly ONE
character. Every output of this script is already a fresh copy -- but if two
characters share the same target skeleton, run the batch once per character
with a different PREFIX (e.g. 'MIN_', 'BRUTE_'); never assign one output
montage to two characters, and never hand the hero's montages to the boss.

API NOTE (verified against the dev.epicgames.com python API docs, 5.3-5.8):
IKRetargetBatchOperation.duplicate_and_retarget(assets_to_retarget,
source_mesh, target_mesh, ik_retarget_asset, search='', replace='',
prefix='', suffix='', ...) -> Array[AssetData]. The first 8 parameters are
stable across 5.2-5.8; the 9th was RENAMED between engine versions
(remap_referenced_assets in 5.2/5.3 -> include_referenced_assets in 5.6+),
so this script passes the first 8 arguments positionally and omits the 9th
(default True everywhere) -- the call survives the rename in either
direction. Destination handling differs by version: 5.3/5.6 have NO
destination-folder parameter (duplicates are created next to their sources),
while 5.8 ADDED target_path='', use_source_path=False and
overwrite_existing_files=False after suffix. The script feature-detects this
at the call site: it first tries the keyword target_path=TARGET_FOLDER (5.8+,
outputs land directly in TARGET_FOLDER and the move pass below becomes a
no-op) and on TypeError falls back to the 8-arg call, then moves the
duplicates into TARGET_FOLDER via rename_asset.
"""

import unreal

# ---------------------------------------------------------------------------
# Config / constants -- edit per pack, then re-run
# ---------------------------------------------------------------------------

SOURCE_FOLDER = "/Game/Fab/SwordAnimSet"            # pack folder, scanned recursively
TARGET_FOLDER = "/Game/Retargeted_Animations/Minion"  # keep OUTSIDE SOURCE_FOLDER
RETARGETER_ASSET = "/Game/Retargeting/RTG_UE4Manny_to_UEFN"  # UIKRetargeter path
PREFIX = "MIN_"  # REQUIRED non-empty: avoids in-place name collisions and is
                 # how per-asset PASS/FAIL matches outputs back to sources.

# Optional overrides; leave "" to use the retargeter's own preview meshes.
SOURCE_MESH = ""
TARGET_MESH = ""

ANIM_CLASSES = ("AnimSequence", "AnimMontage")


def log(msg):
    unreal.log("[BatchRetarget] " + str(msg))


def warn(msg):
    unreal.log_warning("[BatchRetarget] " + str(msg))


def fail(msg):
    unreal.log_error("[BatchRetarget] FATAL: " + str(msg))


# ---------------------------------------------------------------------------
# Helpers (feature-detected for 5.x binding drift)
# ---------------------------------------------------------------------------

def asset_class_name(asset_data):
    """Class name off an AssetData across the 5.x drift: asset_class_path
    (5.1+, TopLevelAssetPath) first, the deprecated asset_class Name second."""
    try:
        return str(asset_data.asset_class_path.asset_name)
    except AttributeError:
        pass
    try:
        return str(asset_data.get_editor_property("asset_class"))
    except Exception:
        return ""


def load_skeletal_mesh_override(path, what):
    """Load an explicit SOURCE_MESH/TARGET_MESH override; raises on a bad path
    so a typo fails loudly instead of silently falling back to preview meshes."""
    if not path:
        return None
    mesh = unreal.EditorAssetLibrary.load_asset(path)
    if mesh is None or not isinstance(mesh, unreal.SkeletalMesh):
        raise RuntimeError("%s is not a loadable SkeletalMesh: %s" % (what, path))
    return mesh


def preview_mesh(retargeter, what):
    """Pull the source/target preview SkeletalMesh out of the retargeter.
    Primary: IKRetargeterController.get_preview_mesh (the documented 5.8
    path). Fallback: the raw <what>_preview_mesh editor property, in case the
    controller API drifts. what: 'source' | 'target'."""
    if hasattr(unreal, "IKRetargeterController") and hasattr(unreal, "RetargetSourceOrTarget"):
        side = (unreal.RetargetSourceOrTarget.SOURCE if what == "source"
                else unreal.RetargetSourceOrTarget.TARGET)
        try:
            ctrl = unreal.IKRetargeterController.get_controller(retargeter)
            if ctrl is not None:
                mesh = ctrl.get_preview_mesh(side)
                if mesh is not None:
                    return mesh
        except Exception as exc:
            warn("IKRetargeterController path failed for the %s mesh (%s) -- "
                 "trying the raw property." % (what, exc))
    else:
        warn("IKRetargeterController / RetargetSourceOrTarget missing from the "
             "python bindings -- trying the raw preview-mesh property.")
    try:
        mesh = retargeter.get_editor_property("%s_preview_mesh" % what)
        if mesh is not None and isinstance(mesh, unreal.SkeletalMesh):
            return mesh
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # -- 0. API surface checks: fail loudly on plugin-off / API drift -------
    if not hasattr(unreal, "IKRetargetBatchOperation"):
        fail("unreal.IKRetargetBatchOperation does not exist. Either the IK "
             "Rig plugin is disabled (Edit -> Plugins -> 'IK Rig') or the "
             "batch API moved in this engine version -- re-verify the class "
             "name on dev.epicgames.com python-api before editing this script.")
        return
    if not hasattr(unreal.IKRetargetBatchOperation, "duplicate_and_retarget"):
        fail("IKRetargetBatchOperation.duplicate_and_retarget is missing -- "
             "API drift. Check the python-api docs for your engine version "
             "for the replacement entry point.")
        return
    if not PREFIX:
        fail("PREFIX must be non-empty: on pre-5.8 signatures duplicates are "
             "first created NEXT TO their sources (no destination parameter), "
             "so an empty prefix name-collides with the originals, and the "
             "per-asset PASS/FAIL match keys on PREFIX + source name.")
        return

    # -- 1. Load the retargeter and resolve source/target meshes ------------
    if not unreal.EditorAssetLibrary.does_asset_exist(RETARGETER_ASSET):
        fail("RETARGETER_ASSET not found: %s -- create it first (see the "
             "docstring, ~2 min in the 5.8 retargeter editor)." % RETARGETER_ASSET)
        return
    retargeter = unreal.EditorAssetLibrary.load_asset(RETARGETER_ASSET)
    if retargeter is None or not isinstance(retargeter, unreal.IKRetargeter):
        fail("%s did not load as an IKRetargeter asset." % RETARGETER_ASSET)
        return

    try:
        source_mesh = (load_skeletal_mesh_override(SOURCE_MESH, "SOURCE_MESH")
                       or preview_mesh(retargeter, "source"))
        target_mesh = (load_skeletal_mesh_override(TARGET_MESH, "TARGET_MESH")
                       or preview_mesh(retargeter, "target"))
    except RuntimeError as exc:
        fail(exc)
        return
    if source_mesh is None or target_mesh is None:
        fail("Could not resolve the %s mesh from %s. Open the retargeter, set "
             "Source/Target Preview Mesh and save -- or fill the SOURCE_MESH "
             "/ TARGET_MESH constants with explicit SkeletalMesh paths."
             % ("source" if source_mesh is None else "target", RETARGETER_ASSET))
        return

    # -- 2. Collect AnimSequences + AnimMontages under SOURCE_FOLDER --------
    if not unreal.EditorAssetLibrary.does_directory_exist(SOURCE_FOLDER):
        fail("SOURCE_FOLDER does not exist: %s" % SOURCE_FOLDER)
        return
    to_retarget, skipped, seq_n, mon_n = [], 0, 0, 0
    for path in unreal.EditorAssetLibrary.list_assets(
            SOURCE_FOLDER, recursive=True, include_folder=False):
        # Never re-ingest our own outputs if TARGET_FOLDER nests under
        # SOURCE_FOLDER (prefer keeping it outside, but be safe anyway).
        if str(path).startswith(TARGET_FOLDER + "/"):
            continue
        asset_data = unreal.EditorAssetLibrary.find_asset_data(path)
        cls = asset_class_name(asset_data)
        if cls not in ANIM_CLASSES:
            continue
        name = str(asset_data.asset_name)
        # A PREFIX-named asset under SOURCE_FOLDER is a leftover output from a
        # prior run whose move to TARGET_FOLDER failed ("move it manually").
        # Never treat it as a source or it gets double-retargeted (MIN_MIN_*).
        if name.startswith(PREFIX):
            log("SKIP (leftover output from a failed move -- move it to %s "
                "manually): %s" % (TARGET_FOLDER, path))
            skipped += 1
            continue
        if unreal.EditorAssetLibrary.does_asset_exist(
                "%s/%s%s" % (TARGET_FOLDER, PREFIX, name)):
            log("SKIP (already retargeted): %s" % name)
            skipped += 1
            continue
        to_retarget.append(asset_data)
        if cls == "AnimSequence":
            seq_n += 1
        else:
            mon_n += 1

    if not to_retarget:
        log("Nothing to do -- 0 new assets under %s (%d already retargeted)."
            % (SOURCE_FOLDER, skipped))
        return

    # TARGET_FOLDER is flat and outputs are matched back to sources by bare
    # PREFIX + name, so two sources sharing a base name across SOURCE_FOLDER
    # subfolders (list_assets is recursive) would collide: the second output
    # would be silently dropped from the match map and strand next to its
    # source. Fail loudly up front instead.
    name_counts = {}
    for asset_data in to_retarget:
        n = str(asset_data.asset_name)
        name_counts[n] = name_counts.get(n, 0) + 1
    dupes = sorted(n for n, c in name_counts.items() if c > 1)
    if dupes:
        fail("Duplicate base asset name(s) across SOURCE_FOLDER subfolders: "
             "%s -- outputs are keyed by PREFIX + name into the flat "
             "TARGET_FOLDER, so these would collide. Rename the sources, or "
             "retarget the subfolders in separate runs with distinct PREFIX "
             "or TARGET_FOLDER values." % ", ".join(dupes))
        return
    log("Retargeting %d asset(s) (%d sequences, %d montages): %s -> %s via %s ..."
        % (len(to_retarget), seq_n, mon_n, source_mesh.get_name(),
           target_mesh.get_name(), RETARGETER_ASSET))

    # -- 3. ONE batch call (montage segment refs remap within the batch).
    #       First 8 args positional, 9th omitted -- see the API NOTE above.
    #       5.8+ accepts target_path (keyword) to place outputs directly in
    #       TARGET_FOLDER; older bindings raise TypeError on the unknown
    #       keyword BEFORE running the batch, so the fallback is safe. --
    try:
        try:
            created = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
                to_retarget, source_mesh, target_mesh, retargeter,
                "", "", PREFIX, "", target_path=TARGET_FOLDER)
            log("5.8+ API: outputs written directly to %s (target_path)."
                % TARGET_FOLDER)
        except TypeError:
            log("Pre-5.8 API (no target_path): duplicating next to sources, "
                "then moving into %s." % TARGET_FOLDER)
            created = unreal.IKRetargetBatchOperation.duplicate_and_retarget(
                to_retarget, source_mesh, target_mesh, retargeter, "", "", PREFIX, "")
    except Exception as exc:
        fail("duplicate_and_retarget raised: %s -- if this is a signature "
             "mismatch, the API drifted again; re-verify it against the "
             "python-api docs for this engine version." % exc)
        return
    created_by_name = {}
    for asset_data in list(created or []):
        created_by_name.setdefault(str(asset_data.asset_name), asset_data)

    # -- 4. Move the duplicates into TARGET_FOLDER, log per-asset PASS/FAIL -
    if not unreal.EditorAssetLibrary.does_directory_exist(TARGET_FOLDER):
        unreal.EditorAssetLibrary.make_directory(TARGET_FOLDER)

    passed, failed = 0, 0
    expected = set()
    for src in to_retarget:
        new_name = PREFIX + str(src.asset_name)
        expected.add(new_name)
        new_data = created_by_name.get(new_name)
        if new_data is None:
            warn("FAIL: %s -- no retargeted output named %s (check the Output "
                 "Log above for retargeter chain errors)." % (src.asset_name, new_name))
            failed += 1
            continue
        old_path = str(new_data.package_name)
        dest_path = "%s/%s" % (TARGET_FOLDER, new_name)
        if old_path == dest_path or unreal.EditorAssetLibrary.rename_asset(old_path, dest_path):
            log("PASS: %s -> %s" % (src.asset_name, dest_path))
            passed += 1
        else:
            warn("FAIL: %s retargeted OK but could not be moved %s -> %s -- "
                 "move it manually; the asset itself is usable."
                 % (src.asset_name, old_path, dest_path))
            failed += 1

    # Referenced assets the engine pulled into the batch on its own (e.g. a
    # sequence a montage uses that lives outside SOURCE_FOLDER) also land
    # next to their sources on pre-5.8 -- sweep them into TARGET_FOLDER so
    # none strand (a no-op when target_path already placed them there).
    extras = 0
    for name, asset_data in created_by_name.items():
        if name in expected:
            continue
        old_path = str(asset_data.package_name)
        dest_path = "%s/%s" % (TARGET_FOLDER, name)
        if old_path != dest_path:
            if unreal.EditorAssetLibrary.rename_asset(old_path, dest_path):
                log("moved referenced extra: %s -> %s" % (name, dest_path))
            else:
                warn("Referenced extra %s left at %s -- move it manually." % (name, old_path))
        extras += 1

    unreal.EditorAssetLibrary.save_directory(TARGET_FOLDER, only_if_is_dirty=True)
    log("Done -- %d PASS, %d FAIL, %d skipped (already existed), %d extra "
        "referenced asset(s). Outputs in %s. Reminder: one character per "
        "montage copy (montage mutation caveat, CLAUDE.md)."
        % (passed, failed, skipped, extras, TARGET_FOLDER))


main()
