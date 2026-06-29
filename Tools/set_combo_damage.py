"""Set DamageAmount/DamageType on every entry of every CombatAnimConfig asset.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Python' -> paste:
      py "D:/GAME_CORE 5.8/Tools/set_combo_damage.py"
  (or Tools -> Execute Python Script... and pick this file)

Damage scheme per ComboChain of length N (0-based step i):
  N == 1          : 15 dmg, "Light"   (single-swing config, e.g. the boss)
  i <  N-1        : 10 + 5*i dmg, "Light"   (10, 15, 20, ...)
  i == N-1, N > 1 : 25 dmg, "Heavy"   (finisher -> forces a heavy reaction)

NOTE: this touches ALL CombatAnimConfig assets, including the boss's if it has
one — it prints every asset it changed, so adjust the boss's numbers after if
you want it to hit harder than entry-0 of this scheme.
"""

import unreal

registry = unreal.AssetRegistryHelpers.get_asset_registry()
assets = registry.get_assets_by_class(
    unreal.TopLevelAssetPath("/Script/GAME_CORE", "CombatAnimConfig"), True
)

if not assets:
    unreal.log_warning("No CombatAnimConfig assets found — is the class name right?")

changed = 0
for asset_data in assets:
    cfg = asset_data.get_asset()
    if cfg is None:
        unreal.log_warning(f"Could not load {asset_data.package_name}")
        continue

    chain = cfg.get_editor_property("combo_chain")
    n = len(chain)
    if n == 0:
        unreal.log(f"{asset_data.asset_name}: empty ComboChain — skipped")
        continue

    summary = []
    for i in range(n):
        entry = chain[i]
        if n == 1:
            dmg, dtype = 15.0, "Light"
        elif i == n - 1:
            dmg, dtype = 25.0, "Heavy"
        else:
            dmg, dtype = 10.0 + 5.0 * i, "Light"
        entry.set_editor_property("damage_amount", dmg)
        entry.set_editor_property("damage_type", dtype)
        chain[i] = entry
        summary.append(f"step{i}={dmg:.0f}/{dtype}")

    cfg.set_editor_property("combo_chain", chain)
    unreal.EditorAssetLibrary.save_loaded_asset(cfg)
    changed += 1
    unreal.log(f"{asset_data.package_name}: {', '.join(summary)}")

unreal.log(f"Done — {changed} CombatAnimConfig asset(s) updated and saved.")
