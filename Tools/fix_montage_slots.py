# fix_montage_slots.py — point every combat montage's slot track at DefaultGroup.DefaultSlot.
#
# WHY: the retargeted montages inherited their source pack's slot name. No AnimGraph in
# this project has a node for that slot, so montages "played" (notifies fired, damage
# landed, combo advanced) with ZERO visible pose — the invisible-attack bug.
#
# Run INSIDE the editor: Output Log -> Cmd console -> py "D:\GAME_CORE 5.8\Tools\fix_montage_slots.py"
# (Safe to re-run; already-correct montages are skipped. Assets are force-saved.)
import os
import unreal

FOLDERS = ["/Game/Retargeted_Animations", "/Game/Arena/Minions"]
TARGET_SLOT = "DefaultSlot"


def log(msg):
    unreal.log("[FixSlots] %s" % msg)


def warn(msg):
    unreal.log_warning("[FixSlots] %s" % msg)


def force_save(asset):
    try:
        asset.get_outer().mark_package_dirty()
    except Exception:
        pass
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError("save failed for %s" % asset.get_path_name())


def montages_under(folder):
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        return []
    out = []
    for path in unreal.EditorAssetLibrary.list_assets(folder, recursive=True):
        data = unreal.EditorAssetLibrary.find_asset_data(path)
        if data.asset_class_path.asset_name == "AnimMontage":
            out.append(path)
    return sorted(out)


def main():
    fixed, ok, skipped, failed = 0, 0, 0, 0
    seen_names = {}
    for folder in FOLDERS:
        for path in montages_under(folder):
            m = unreal.EditorAssetLibrary.load_asset(path)
            if not m:
                warn("could not load %s" % path)
                failed += 1
                continue
            try:
                tracks = m.get_editor_property("slot_anim_tracks")
                names = [str(t.get_editor_property("slot_name")) for t in tracks]
                for n in names:
                    seen_names[n] = seen_names.get(n, 0) + 1
                if all(n == TARGET_SLOT for n in names):
                    ok += 1
                    continue
                if len(tracks) != 1:
                    warn("%s has %d slot tracks (%s) -- fix by hand in the montage "
                         "editor (click the slot name on the track header)"
                         % (m.get_name(), len(tracks), ", ".join(names)))
                    skipped += 1
                    continue
                old = names[0]
                tracks[0].set_editor_property("slot_name", TARGET_SLOT)
                m.set_editor_property("slot_anim_tracks", tracks)
                # verify the write took before saving
                check = str(m.get_editor_property("slot_anim_tracks")[0]
                            .get_editor_property("slot_name"))
                if check != TARGET_SLOT:
                    warn("%s: slot write did not stick (still '%s') -- fix by hand"
                         % (m.get_name(), check))
                    failed += 1
                    continue
                force_save(m)
                log("%-36s %s -> %s" % (m.get_name(), old, TARGET_SLOT))
                fixed += 1
            except Exception as exc:  # noqa: BLE001 - per-asset isolation
                warn("%s FAILED: %s" % (path, exc))
                failed += 1

    log("=" * 60)
    log("slot names seen: %s" % seen_names)
    log("fixed %d | already-correct %d | multi-track skipped %d | failed %d"
        % (fixed, ok, skipped, failed))
    if fixed and not failed:
        log("Done. PIE and attack -- swings should be visible now.")


main()
