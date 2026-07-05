# disable_hit_debug_spheres.py — untick bDrawDebugTrace on every ANS_DealDamage notify
# instance across the combat montages (the red/green wrist spheres from M0 debugging).
#
# Run INSIDE the editor: Output Log -> Cmd -> py "D:\GAME_CORE 5.8\Tools\disable_hit_debug_spheres.py"
# Safe to re-run. Unlike slot names (struct array — write-back fails), the notify state
# is an instanced UObject, so property edits stick.
import unreal

FOLDERS = ["/Game/Retargeted_Animations", "/Game/Arena/Minions"]


def log(msg):
    unreal.log("[HitDebugOff] %s" % msg)


def montages_under(folder):
    if not unreal.EditorAssetLibrary.does_directory_exist(folder):
        return []
    out = []
    for path in unreal.EditorAssetLibrary.list_assets(folder, recursive=True):
        data = unreal.EditorAssetLibrary.find_asset_data(path)
        if data.asset_class_path.asset_name == "AnimMontage":
            out.append(path)
    return sorted(out)


def set_flag_off(notify_obj):
    for prop in ("draw_debug_trace", "b_draw_debug_trace"):
        try:
            if notify_obj.get_editor_property(prop):
                notify_obj.set_editor_property(prop, False)
                return True   # was on, now off
            return False      # already off
        except Exception:
            continue
    raise RuntimeError("no draw-debug property found on %s" % notify_obj.get_name())


def main():
    changed, clean, failed = 0, 0, 0
    for folder in FOLDERS:
        for path in montages_under(folder):
            m = unreal.EditorAssetLibrary.load_asset(path)
            if not m:
                continue
            try:
                touched = False
                for ev in unreal.AnimationLibrary.get_animation_notify_events(m):
                    state = ev.get_editor_property("notify_state_class")
                    if state and state.get_class().get_name().startswith("ANS_DealDamage"):
                        if set_flag_off(state):
                            touched = True
                if touched:
                    m.get_outer().mark_package_dirty()
                    if not unreal.EditorAssetLibrary.save_loaded_asset(m, only_if_is_dirty=False):
                        raise RuntimeError("save failed")
                    log("%-36s debug spheres OFF (saved)" % m.get_name())
                    changed += 1
                else:
                    clean += 1
            except Exception as exc:  # noqa: BLE001
                unreal.log_warning("[HitDebugOff] %s FAILED: %s" % (path, exc))
                failed += 1
    log("=" * 50)
    log("changed %d | already clean %d | failed %d" % (changed, clean, failed))


main()
