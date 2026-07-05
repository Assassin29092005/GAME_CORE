"""[NNEImport] Import SourceArt/Models/boss_untrained.onnx -> /Game/Arena/Models/NNM_BossUntrained.

M5 pipeline step between Python/make_test_onnx.py (produces the .onnx) and the
in-engine check (`boss.NNESelfTest` console command / UNNEBossPolicyComponent).
The asset is imported as UNNEModelData via the engine's UNNEModelDataFactory
(Engine/Source/Editor/NNEEditor — registered for the "onnx" extension, so the
plain AssetImportTask path routes to it automatically). Nothing is assigned to
any component here — wiring is via Project Settings -> Game -> Game Feel
(NNEBossModelData) or the BP_Boss component properties later.

NNE model import is editor/plugin-provided: the script feature-detects
unreal.NNEModelData and the import result, and SKIPs loudly with the manual
drag-drop recipe if this build can't import ONNX from script.

Steps (each guarded; PASS/FAIL/SKIP summary at the end):
  1. Preflight: source .onnx exists, unreal.NNEModelData class available.
  2. AssetImportTask import (automated, replace_existing -> idempotent).
  3. Verify the asset loads as UNNEModelData.
  4. Force-save + on-disk mtime verify.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/import_onnx_model.py"
  (or Tools -> Execute Python Script... and pick this file)

Or headless (editor CLOSED -- it opens its own commandlet editor):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "D:\\GAME_CORE 5.8\\GAME_CORE.uproject" ^
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/import_onnx_model.py"
"""

import os
import time
import traceback

import unreal

TAG = "[NNEImport]"

SOURCE_ONNX = "D:/GAME_CORE 5.8/SourceArt/Models/boss_untrained.onnx"
DEST_DIR = "/Game/Arena/Models"
ASSET_NAME = "NNM_BossUntrained"
ASSET_PATH = "%s/%s" % (DEST_DIR, ASSET_NAME)
UASSET_DISK_PATH = "D:/GAME_CORE 5.8/Content/Arena/Models/%s.uasset" % ASSET_NAME

MANUAL_RECIPE = (
    "Manual drag-drop recipe: open the editor -> Content Browser -> navigate to "
    "/Game/Arena/Models (create the folder if needed) -> drag "
    "SourceArt/Models/boss_untrained.onnx into it (or Import button) -> rename the "
    "new asset to NNM_BossUntrained -> Save. Requires the NNERuntimeORT plugin "
    "(already enabled in GAME_CORE.uproject); the importer is engine-provided "
    "(NNEEditor module, UNNEModelDataFactory)."
)

STEP_RESULTS = []  # (label, "PASS"/"FAIL"/"SKIP", detail)
SCRIPT_START = time.time()


def record(label, status, detail=""):
    STEP_RESULTS.append((label, status, detail))
    unreal.log("%s %s: %s %s" % (TAG, label, status, detail))


def step_preflight():
    if not os.path.isfile(SOURCE_ONNX):
        record("preflight", "FAIL",
               "source missing: %s — run Python/make_test_onnx.py (venv) first." % SOURCE_ONNX)
        return False

    # Feature-detect the NNE model-data asset class. UNNEModelData is
    # BlueprintType, so a build with the NNE runtime exposes it to Python; if it
    # is absent, script import cannot verify the asset class either.
    if not hasattr(unreal, "NNEModelData"):
        record("preflight", "SKIP",
               "unreal.NNEModelData not exposed in this build — cannot import/verify "
               "from script. " + MANUAL_RECIPE)
        return False

    record("preflight", "PASS", "source found (%d bytes), unreal.NNEModelData available."
           % os.path.getsize(SOURCE_ONNX))
    return True


def step_import():
    """AssetImportTask -> UNNEModelDataFactory (picked by the 'onnx' extension).

    replace_existing makes re-runs idempotent: the asset is recreated in place
    with the same object path, so references (settings soft path, BP properties)
    survive.
    """
    try:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", SOURCE_ONNX)
        task.set_editor_property("destination_path", DEST_DIR)
        task.set_editor_property("destination_name", ASSET_NAME)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", False)  # explicit force-save step below

        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

        imported = list(task.get_editor_property("imported_object_paths") or [])
        if not imported:
            record("import", "SKIP",
                   "AssetImportTask produced nothing — this build's commandlet import "
                   "path may not support ONNX. " + MANUAL_RECIPE)
            return False

        record("import", "PASS", "imported: %s" % ", ".join(str(p) for p in imported))
        return True
    except Exception:
        record("import", "FAIL", "exception:\n%s" % traceback.format_exc())
        return False


def step_verify_class():
    try:
        asset = unreal.EditorAssetLibrary.load_asset(ASSET_PATH)
        if asset is None:
            record("verify-class", "FAIL", "asset did not load: %s" % ASSET_PATH)
            return False
        if not isinstance(asset, unreal.NNEModelData):
            record("verify-class", "FAIL",
                   "asset is %s, expected NNEModelData — wrong factory handled the file?"
                   % type(asset).__name__)
            return False
        record("verify-class", "PASS", "%s loads as NNEModelData." % ASSET_PATH)
        return True
    except Exception:
        record("verify-class", "FAIL", "exception:\n%s" % traceback.format_exc())
        return False


def step_save_and_verify():
    try:
        mtime_before = os.path.getmtime(UASSET_DISK_PATH) if os.path.isfile(UASSET_DISK_PATH) else 0.0

        # Force-save regardless of dirty state — the on-disk mtime is the proof
        # the import actually persisted (project convention).
        if not unreal.EditorAssetLibrary.save_asset(ASSET_PATH, only_if_is_dirty=False):
            record("save", "FAIL", "save_asset returned False for %s" % ASSET_PATH)
            return False

        if not os.path.isfile(UASSET_DISK_PATH):
            record("save", "FAIL", "no .uasset on disk at %s after save." % UASSET_DISK_PATH)
            return False

        # Proof the write actually happened THIS run (project convention):
        # the .uasset must be newer than script start (2 s FS-granularity slack).
        mtime_after = os.path.getmtime(UASSET_DISK_PATH)
        if mtime_after < SCRIPT_START - 2.0:
            record("save", "FAIL", "on-disk .uasset predates this run (%s, was %s) — save did not write."
                   % (time.ctime(mtime_after), time.ctime(mtime_before)))
            return False

        record("save", "PASS", "%s saved at %s (%d bytes)."
               % (UASSET_DISK_PATH, time.ctime(mtime_after), os.path.getsize(UASSET_DISK_PATH)))
        return True
    except Exception:
        record("save", "FAIL", "exception:\n%s" % traceback.format_exc())
        return False


def main():
    unreal.log("%s === import boss_untrained.onnx -> %s ===" % (TAG, ASSET_PATH))

    ok = step_preflight()
    if ok:
        ok = step_import()
    if ok:
        ok = step_verify_class() and step_save_and_verify()

    # GC cadence: drop the loaded asset references before the commandlet exits.
    unreal.SystemLibrary.collect_garbage()

    unreal.log("%s ----- summary -----" % TAG)
    fails = 0
    for label, status, detail in STEP_RESULTS:
        unreal.log("%s   %-14s %s  %s" % (TAG, label, status, detail.splitlines()[0] if detail else ""))
        if status == "FAIL":
            fails += 1
    if fails:
        unreal.log_error("%s DONE WITH FAILURES (%d) — see lines above." % (TAG, fails))
    else:
        unreal.log("%s DONE. Next: wire the asset via Project Settings -> Game -> Game Feel -> "
                   "NNEBossModelData (= %s), then verify headlessly with "
                   "-game -RenderOffscreen -ExecCmds=\"boss.NNESelfTest, quit\"." % (TAG, ASSET_PATH))


if __name__ == "__main__":
    main()
