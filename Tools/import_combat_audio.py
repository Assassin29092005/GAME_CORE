"""Import the guide.md 7.1 placeholder combat audio and wire it everywhere.

Steps (each guarded; PASS/FAIL/SKIP summary at the end):
  0. Verify the picked WAVs exist under SourceArt/Audio/picked/.
  1. Import them -> /Game/Arena/Audio (AssetImportTask, idempotent).
  2. BP_NeuralHero CDO edits: HitFeedbackComponent.ImpactSound/HeavyImpactSound
     (impact_light_a / impact_heavy_a) + CombatComponent.ParrySound (parry_ting)
     + CombatComponent.BlockSound (block_thud -- played from ApplyDamage's
     blocked branch; ANS_DealDamage suppresses the flesh impact on blocks)
     -- compile + force-save + fresh-spawn ASSERT (integrate_golem_minion step 7
     pattern).
  3. BP_Boss CDO edits: HitFeedbackComponent.ImpactSound/HeavyImpactSound
     (impact_light_b / impact_heavy_b -- the OTHER variants, so boss-on-hero
     hits read differently from hero-on-boss) + CombatComponent.BlockSound
     (block_thud) + BossActionComponent.TelegraphSound (telegraph_grunt).
     Same compile/save/spawn-verify. (ui_confirm imports in step 1 but stays
     unwired by design -- it is menu/UI material, not a component property.)
  4. Determine the heavy montage set (place_feel_notifies scheme: BP_Boss's
     HeavyAttackMontages set + CombatAnimConfig DamageType == 'Heavy', with the
     positional chain-finisher fallback).
  5. Whoosh notifies: on every hero combo montage and boss Attack_0X montage,
     add a UAnimNotify_PlaySound at swing start (just BEFORE the ANS_DealDamage
     window opens) with sound = whoosh_light (lights) / whoosh_heavy (heavies),
     Attach Name = hand_r, Follow = true (guide.md 7.1 step 1). Instanced-object
     property edits on the created notify (those stick; struct-array write-backs
     do NOT). Idempotent: montages already carrying any AnimNotify_PlaySound
     are skipped. Force-save + on-disk mtime verify per montage.

The C++ sound properties (ImpactSound / HeavyImpactSound / ParrySound /
TelegraphSound) only exist after a Build.bat pass -- steps 2/3 feature-detect
them and SKIP with manual instructions when the running editor predates the
rebuild. Step 5 needs no new C++ (AnimNotify_PlaySound is an engine class).

Run headless (editor CLOSED):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "D:\\GAME_CORE 5.8\\GAME_CORE.uproject" ^
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/import_combat_audio.py"
Or in-editor: Output Log 'Cmd' console ->
      py "D:/GAME_CORE 5.8/Tools/import_combat_audio.py"
"""

import os
import re
import traceback

import unreal

TAG = "[CombatAudio]"

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

PICKED_DIR = os.path.join(
    unreal.SystemLibrary.get_project_directory(), "SourceArt", "Audio", "picked")
DEST_DIR = "/Game/Arena/Audio"

# semantic name -> asset name after import (same stem)
PICKS = [
    "whoosh_light", "whoosh_heavy",
    "impact_light_a", "impact_light_b",
    "impact_heavy_a", "impact_heavy_b",
    "block_thud", "parry_ting", "telegraph_grunt", "ui_confirm",
]

BP_HERO_PATH = "/Game/Blueprints/BP_NeuralHero"
BP_BOSS_PATH = "/Game/Blueprints/BP_Boss"

RETARGET_DIR = "/Game/Retargeted_Animations"
COMBO_DIRS = ["%s/Combo_%02d" % (RETARGET_DIR, i) for i in range(1, 10)]
BOSS_DIR = RETARGET_DIR + "/BOSS"
BOSS_ATTACK_RE = re.compile(r"^Attack_0(\d)_Seq_Montage$")

# The ONLY folders this script may mutate/save assets in.
ALLOWED_PREFIXES = (DEST_DIR + "/", "/Game/Blueprints/", RETARGET_DIR + "/")

CLS_DEAL_DAMAGE = "ANS_DealDamage"
CLS_PLAY_SOUND = "AnimNotify_PlaySound"

WHOOSH_LEAD = 0.10        # s before the damage window opens = "swing start"
WHOOSH_ATTACH = "hand_r"  # guide.md 7.1 step 1: attach to the weapon hand
TRACK_NAME = "FeelNotifies"   # same track place_feel_notifies.py uses

GC_EVERY = 8              # collect_garbage cadence while chewing montages

STEP_RESULTS = []
MANUAL_NOTES = []
SOUNDS = {}               # semantic name -> USoundBase


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def manual(msg):
    MANUAL_NOTES.append(msg)
    warn("MANUAL: " + msg)


class StepSkip(Exception):
    """Deliberate no-op (missing class / missing API / nothing to do)."""


def run_step(label, fn):
    try:
        detail = fn()
        STEP_RESULTS.append((label, "PASS", detail or ""))
        log("STEP OK   : %s%s" % (label, (" -- " + detail) if detail else ""))
    except StepSkip as why:
        STEP_RESULTS.append((label, "SKIP", str(why)))
        log("STEP SKIP : %s -- %s" % (label, why))
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all per step
        STEP_RESULTS.append((label, "FAIL", str(exc)))
        warn("STEP FAIL : %s -- %s" % (label, exc))
        warn(traceback.format_exc())


# ---------------------------------------------------------------------------
# Shared helpers (force_save / prop helpers: integrate_golem_minion patterns)
# ---------------------------------------------------------------------------

def assert_allowed(asset):
    path = asset.get_path_name()
    if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
        raise RuntimeError("REFUSING to touch asset outside allowed folders: %s" % path)


def force_save(asset):
    """mark_package_dirty -> save_loaded_asset(only_if_is_dirty=False) ->
    verify the .uasset mtime ADVANCED on disk. Dirty-gated saves have been
    proven to silently write nothing -- never trust a bare save here."""
    assert_allowed(asset)
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
            raise RuntimeError("save reported success but %s was NOT rewritten "
                               "on disk" % disk_path)


def set_prop_if_exists(obj, name, value, context=""):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s"
             % (name, (" on " + context) if context else "", exc))
        return False


def set_first_prop(obj, names, value):
    """Try several property spellings (5.x drift); return the one that stuck."""
    for name in names:
        try:
            obj.set_editor_property(name, value)
            return name
        except Exception:
            continue
    return None


def _generated_class(bp_asset, class_path_hint):
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


def find_component_templates(bp, cdo, class_keyword):
    """All component templates on a BP whose class name contains class_keyword.
    Strategy 1: SCS walk via SubobjectDataSubsystem (BP-added components never
    exist on the CDO). Strategy 2: CDO get_components_by_class (C++-added).
    Same tactic as place_feel_notifies.bp_boss_heavy_montage_pkgs."""
    found = []
    try:
        sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        lib = getattr(unreal, "SubobjectDataBlueprintFunctionLibrary", None)
        if sds is not None and lib is not None:
            for handle in sds.k2_gather_subobject_data_for_blueprint(bp):
                try:
                    obj = lib.get_object(lib.get_data(handle))
                except Exception:
                    continue
                if obj is not None and class_keyword in str(obj.get_class().get_name()):
                    found.append(obj)
    except Exception as exc:
        log("SCS walk unavailable (%s) -- trying the CDO" % exc)
    if not found and cdo is not None:
        try:
            comp_cls = unreal.load_class(None, "/Script/GAME_CORE." + class_keyword)
        except Exception:
            comp_cls = None
        if comp_cls is not None:
            try:
                found.extend(list(cdo.get_components_by_class(comp_cls)))
            except Exception:
                pass
    return found


# ---------------------------------------------------------------------------
# Notify API feature-detect (place_feel_notifies pattern, write-side add_evt)
# ---------------------------------------------------------------------------

LIB = getattr(unreal, "AnimationLibrary", None) \
    or getattr(unreal, "AnimationBlueprintLibrary", None)

API = {}


def _resolve(key, exact_names, regex):
    if LIB is None:
        API[key] = None
        return
    for name in exact_names:
        if hasattr(LIB, name):
            API[key] = getattr(LIB, name)
            return
    pat = re.compile(regex)
    for name in dir(LIB):
        if not name.startswith("_") and pat.fullmatch(name):
            API[key] = getattr(LIB, name)
            return
    API[key] = None


_resolve("events", ["get_animation_notify_events"], r"get_animation_notify_events?")
_resolve("trig", ["get_anim_notify_event_trigger_time"],
         r"get_anim(ation)?_notify_event_trigger_time")
_resolve("dur", ["get_anim_notify_event_duration"],
         r"get_anim(ation)?_notify_event_duration")
_resolve("add_evt", ["add_animation_notify_event"], r"add_animation_notify_event")
_resolve("tracks", ["get_animation_notify_track_names"],
         r"get_animation_notify_track_names")
_resolve("add_track", ["add_animation_notify_track"], r"add_animation_notify_track")


def _require_api(*keys):
    missing = [k for k in keys if API.get(k) is None]
    if missing:
        raise StepSkip("notify API missing: %s -- place the PlaySound notifies "
                       "manually per guide.md 7.1 step 1" % ", ".join(missing))


def get_events(m):
    return list(API["events"](m))


def event_class_name(ev):
    # NOTE: 'notify_state_class' on FAnimNotifyEvent is the notify-state
    # INSTANCE despite the name (engine quirk).
    for prop in ("notify", "notify_state_class"):
        try:
            obj = ev.get_editor_property(prop)
        except Exception:
            continue
        if obj is not None:
            try:
                return str(obj.get_class().get_name())
            except Exception:
                continue
    try:
        return str(ev.get_editor_property("notify_name"))
    except Exception:
        return ""


def has_notify_class(m, class_keyword):
    return any(class_keyword in event_class_name(ev) for ev in get_events(m))


def deal_damage_window(m):
    start, end = None, None
    for ev in get_events(m):
        if CLS_DEAL_DAMAGE not in event_class_name(ev):
            continue
        t = float(API["trig"](ev))
        d = float(API["dur"](ev)) if API.get("dur") is not None else 0.0
        start = t if start is None else min(start, t)
        end = (t + d) if end is None else max(end, t + d)
    return None if start is None else (start, end)


def ensure_track(m):
    names = []
    if API.get("tracks") is not None:
        try:
            names = [str(n) for n in API["tracks"](m)]
        except Exception:
            names = []
    if TRACK_NAME in names:
        return TRACK_NAME
    if API.get("add_track") is not None:
        try:
            API["add_track"](m, TRACK_NAME)
            return TRACK_NAME
        except Exception:
            pass
    if names:
        return names[0]
    raise RuntimeError("no notify track on %s and cannot create one" % m.get_name())


def list_montages(directory, name_filter=None):
    if not unreal.EditorAssetLibrary.does_directory_exist(directory):
        return []
    found = []
    for obj_path in unreal.EditorAssetLibrary.list_assets(directory, recursive=True):
        asset_name = str(obj_path).split("/")[-1].split(".")[0]
        if name_filter is not None and not name_filter(asset_name):
            continue
        asset = unreal.EditorAssetLibrary.load_asset(obj_path)
        if isinstance(asset, unreal.AnimMontage):
            found.append(asset)
    return sorted(found, key=lambda a: a.get_name())


# ---------------------------------------------------------------------------
# Step 0: verify source WAVs
# ---------------------------------------------------------------------------

def step0_verify_sources():
    missing = [n for n in PICKS
               if not os.path.isfile(os.path.join(PICKED_DIR, n + ".wav"))]
    if missing:
        raise RuntimeError(
            "picked WAVs missing under %s: %s -- re-run the Track 4 download/"
            "convert pass first" % (PICKED_DIR, ", ".join(missing)))
    return "%d WAVs present in %s" % (len(PICKS), PICKED_DIR)


# ---------------------------------------------------------------------------
# Step 1: import -> /Game/Arena/Audio
# ---------------------------------------------------------------------------

def step1_import():
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    imported, already, failed = 0, 0, 0
    for name in PICKS:
        asset_path = "%s/%s" % (DEST_DIR, name)
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            snd = unreal.EditorAssetLibrary.load_asset(asset_path)
            if isinstance(snd, unreal.SoundWave):
                SOUNDS[name] = snd
                already += 1
                log("  %-18s already imported -- skipped (idempotent)" % name)
                continue
            warn("  %-18s exists but is NOT a SoundWave -- reimporting over it" % name)
        task = unreal.AssetImportTask()
        task.set_editor_property("automated", True)
        task.set_editor_property("destination_path", DEST_DIR)
        task.set_editor_property("filename", os.path.join(PICKED_DIR, name + ".wav"))
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", False)   # force_save below does disk-truth
        tools.import_asset_tasks([task])
        snd = unreal.EditorAssetLibrary.load_asset(asset_path)
        if not isinstance(snd, unreal.SoundWave):
            failed += 1
            warn("  %-18s import FAILED (no SoundWave at %s)" % (name, asset_path))
            continue
        force_save(snd)
        SOUNDS[name] = snd
        imported += 1
        log("  %-18s imported -> %s" % (name, asset_path))
    if failed and not (imported or already):
        raise RuntimeError("every import failed (%d)" % failed)
    if failed:
        raise RuntimeError("imported %d, already %d, but %d FAILED"
                           % (imported, already, failed))
    return "imported %d, already-present %d" % (imported, already)


def _sound(name):
    snd = SOUNDS.get(name)
    if snd is None:
        raise StepSkip("sound '%s' not available (step 1 failed?)" % name)
    return snd


# ---------------------------------------------------------------------------
# Steps 2/3: BP CDO edits (integrate_golem_minion step 7 pattern)
# ---------------------------------------------------------------------------

def _assign_bp_sounds(bp_path, bp_label, assignments):
    """assignments: list of (component class keyword, python prop name,
    semantic sound name). Applies to every matching component template,
    compiles, re-applies (compile can regenerate the CDO and drop pure-CDO
    edits), force-saves, then fresh-spawn ASSERTs propagation."""
    if not unreal.EditorAssetLibrary.does_asset_exist(bp_path):
        raise StepSkip("%s does not exist" % bp_path)
    bp = unreal.EditorAssetLibrary.load_asset(bp_path)
    gen_cls = _generated_class(bp, bp_path + ".%s_C" % bp_label)
    if gen_cls is None:
        raise RuntimeError("%s has no resolvable generated class" % bp_label)

    def apply_all(cdo):
        misses = []
        for comp_kw, prop, sound_name in assignments:
            comps = find_component_templates(bp, cdo, comp_kw)
            if not comps:
                misses.append("%s not found on %s" % (comp_kw, bp_label))
                continue
            snd = _sound(sound_name)
            for comp in comps:
                if not set_prop_if_exists(comp, prop, snd,
                                          "%s.%s" % (bp_label, comp_kw)):
                    misses.append(
                        "%s.%s (property missing -- C++ not rebuilt yet? "
                        "Build.bat, then re-run)" % (comp_kw, prop))
        return misses

    cdo = unreal.get_default_object(gen_cls)
    misses = apply_all(cdo)

    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("compile_blueprint failed (%s) -- continuing to save." % exc)
        gen_cls = _generated_class(bp, bp_path + ".%s_C" % bp_label) or gen_cls
        cdo = unreal.get_default_object(gen_cls)
        misses = apply_all(cdo)

    force_save(bp)

    # Fresh-spawn ASSERT (build_arena_level 6k pattern).
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    inst = None
    try:
        inst = actors.spawn_actor_from_class(
            gen_cls, unreal.Vector(0.0, 0.0, -5000.0),
            unreal.Rotator(0.0, 0.0, 0.0))
    except Exception:
        inst = None
    if inst is None:
        if misses:
            raise StepSkip("%s saved but unverified (no level open?) and some "
                           "props did not stick: %s" % (bp_label, "; ".join(misses)))
        raise StepSkip("%s saved but NOT spawn-verified (no level open?)" % bp_label)
    try:
        unset = []
        for comp_kw, prop, sound_name in assignments:
            comp_cls = None
            try:
                comp_cls = unreal.load_class(None, "/Script/GAME_CORE." + comp_kw)
            except Exception:
                pass
            comp = inst.get_component_by_class(comp_cls) if comp_cls else None
            val = None
            if comp is not None:
                try:
                    val = comp.get_editor_property(prop)
                except Exception:
                    val = None
            if val is None or sound_name not in str(val.get_path_name()):
                unset.append("%s.%s != %s" % (comp_kw, prop, sound_name))
        if unset:
            raise RuntimeError("%s ASSERT FAIL -- unset on a fresh instance: %s%s"
                               % (bp_label, "; ".join(unset),
                                  ("; apply-time misses: " + "; ".join(misses))
                                  if misses else ""))
    finally:
        try:
            actors.destroy_actor(inst)
        except Exception:
            pass
    if misses:
        raise StepSkip("%s saved + spawn-verified for what applied, but: %s"
                       % (bp_label, "; ".join(misses)))
    return "%s verified on a fresh instance (%d sound assignment(s))" \
        % (bp_label, len(assignments))


def step2_hero_sounds():
    return _assign_bp_sounds(BP_HERO_PATH, "BP_NeuralHero", [
        ("HitFeedbackComponent", "impact_sound", "impact_light_a"),
        ("HitFeedbackComponent", "heavy_impact_sound", "impact_heavy_a"),
        ("CombatComponent", "parry_sound", "parry_ting"),
        ("CombatComponent", "block_sound", "block_thud"),
    ])


def step3_boss_sounds():
    # The _b impact variants on purpose: boss-on-hero hits must not be
    # sample-identical to hero-on-boss hits (cheap perceived variety).
    return _assign_bp_sounds(BP_BOSS_PATH, "BP_Boss", [
        ("HitFeedbackComponent", "impact_sound", "impact_light_b"),
        ("HitFeedbackComponent", "heavy_impact_sound", "impact_heavy_b"),
        ("CombatComponent", "block_sound", "block_thud"),
        ("BossActionComponent", "telegraph_sound", "telegraph_grunt"),
    ])


# ---------------------------------------------------------------------------
# Step 4: heavy set (place_feel_notifies scheme)
# ---------------------------------------------------------------------------

HEAVY_PKGS = set()


def _bp_boss_heavy_pkgs():
    """BP_Boss's BossActionComponent.HeavyAttackMontages -- the boss's actual
    heavy source of truth. Empty set on any failure (caller falls back)."""
    if not unreal.EditorAssetLibrary.does_asset_exist(BP_BOSS_PATH):
        return set()
    bp = unreal.EditorAssetLibrary.load_asset(BP_BOSS_PATH)
    gen_cls = _generated_class(bp, BP_BOSS_PATH + ".BP_Boss_C")
    cdo = unreal.get_default_object(gen_cls) if gen_cls else None
    pkgs = set()
    for comp in find_component_templates(bp, cdo, "BossActionComponent"):
        try:
            heavy = comp.get_editor_property("heavy_attack_montages")
        except Exception:
            continue
        for mont in (list(heavy) if heavy is not None else []):
            if mont is not None:
                pkgs.add(str(mont.get_path_name()).split(".")[0])
    return pkgs


def step4_heavy_set():
    global HEAVY_PKGS
    HEAVY_PKGS |= _bp_boss_heavy_pkgs()
    boss_n = len(HEAVY_PKGS)

    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_class(
        unreal.TopLevelAssetPath("/Script/GAME_CORE", "CombatAnimConfig"), True)
    by_type, by_position = set(), set()
    for asset_data in assets:
        cfg = asset_data.get_asset()
        if cfg is None:
            continue
        chain = cfg.get_editor_property("combo_chain")
        n = len(chain)
        for i in range(n):
            try:
                mont = chain[i].get_editor_property("montage")
            except Exception:
                mont = None
            if mont is None:
                continue
            pkg = str(mont.get_path_name()).split(".")[0]
            dtype = ""
            try:
                dtype = str(chain[i].get_editor_property("damage_type"))
            except Exception:
                pass
            if dtype.lower() == "heavy":
                by_type.add(pkg)
            if n > 1 and i == n - 1:
                by_position.add(pkg)
    if by_type:
        HEAVY_PKGS |= by_type
        src = "damage_type"
    elif by_position:
        HEAVY_PKGS |= by_position
        src = "finisher_position (set_combo_damage.py not run yet?)"
    else:
        src = "none from configs"
    log("Heavy montages: %s" % (", ".join(
        sorted(p.split("/")[-1] for p in HEAVY_PKGS)) or "<none>"))
    return "%d heavy (boss-set %d, config source: %s)" % (len(HEAVY_PKGS), boss_n, src)


def is_heavy(m):
    return str(m.get_path_name()).split(".")[0] in HEAVY_PKGS


# ---------------------------------------------------------------------------
# Step 5: whoosh PlaySound notifies at swing start
# ---------------------------------------------------------------------------

def step5_whoosh_notifies():
    _require_api("events", "trig", "add_evt")
    notify_cls = getattr(unreal, "AnimNotify_PlaySound", None)
    if notify_cls is None:
        try:
            notify_cls = unreal.load_class(None, "/Script/Engine.AnimNotify_PlaySound")
        except Exception:
            notify_cls = None
    if notify_cls is None:
        raise StepSkip("AnimNotify_PlaySound class not found in this build -- "
                       "place Play Sound notifies manually (guide.md 7.1 step 1)")
    if isinstance(notify_cls, type):   # python wrapper class -> UClass
        notify_cls = notify_cls.static_class()

    montages = []
    for d in COMBO_DIRS:
        montages += list_montages(d, lambda n: n.startswith("AM_"))
    montages += list_montages(BOSS_DIR, lambda n: BOSS_ATTACK_RE.match(n) is not None)
    if not montages:
        raise StepSkip("no hero/boss attack montages discovered")

    whoosh_light = _sound("whoosh_light")
    whoosh_heavy = _sound("whoosh_heavy")

    placed, already, no_window, failed = 0, 0, 0, 0
    for idx, m in enumerate(montages):
        try:
            if has_notify_class(m, CLS_PLAY_SOUND):
                log("  %-32s already has a PlaySound notify -- skipped (idempotent)"
                    % m.get_name())
                already += 1
                continue
            window = deal_damage_window(m)
            if window is None:
                log("  %-32s no ANS_DealDamage window -- not an attack montage, skipped"
                    % m.get_name())
                no_window += 1
                continue
            heavy = is_heavy(m)
            snd = whoosh_heavy if heavy else whoosh_light
            t = max(0.0, window[0] - WHOOSH_LEAD)
            track = ensure_track(m)
            created = API["add_evt"](m, track, float(t), notify_cls)
            if created is None:
                raise RuntimeError("add_animation_notify_event returned None")
            # Instanced-object property edits on the created notify -- these
            # stick (struct-array write-backs do NOT; the project-wide rule).
            if not set_prop_if_exists(created, "sound", snd, m.get_name()):
                raise RuntimeError("could not set Sound on the created notify")
            if set_first_prop(created, ["follow", "b_follow"], True) is None:
                warn("  %-32s Follow not settable -- sound plays at spawn point"
                     % m.get_name())
            if set_first_prop(created, ["attach_name"], WHOOSH_ATTACH) is None:
                warn("  %-32s AttachName not settable" % m.get_name())
            set_first_prop(created, ["volume_multiplier"], 1.0)
            save_ok_msg = "whoosh_%s @ %.3f s (track %s)" % (
                "heavy" if heavy else "light", t, track)
            force_save(m)
            placed += 1
            log("  %-32s %s" % (m.get_name(), save_ok_msg))
        except Exception as exc:  # noqa: BLE001 - per-montage isolation
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
        if (idx + 1) % GC_EVERY == 0:
            unreal.SystemLibrary.collect_garbage()
    if placed == 0 and already == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return ("placed %d, already-had %d, no-damage-window %d, failed %d"
            % (placed, already, no_window, failed))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("=" * 70)
    log("import_combat_audio -- guide.md 7.1 placeholder audio pass")
    log("=" * 70)

    run_step("0. Verify picked WAVs", step0_verify_sources)
    if STEP_RESULTS[0][1] != "PASS":
        for label in ("1. Import -> /Game/Arena/Audio",
                      "2. BP_NeuralHero sounds (CDO + verify)",
                      "3. BP_Boss sounds (CDO + verify)",
                      "4. Determine heavy montage set",
                      "5. Whoosh PlaySound notifies"):
            STEP_RESULTS.append((label, "SKIP", "step 0 did not pass"))
    else:
        run_step("1. Import -> /Game/Arena/Audio", step1_import)
        run_step("2. BP_NeuralHero sounds (CDO + verify)", step2_hero_sounds)
        run_step("3. BP_Boss sounds (CDO + verify)", step3_boss_sounds)
        run_step("4. Determine heavy montage set", step4_heavy_set)
        run_step("5. Whoosh PlaySound notifies", step5_whoosh_notifies)

    unreal.SystemLibrary.collect_garbage()
    log("=" * 70)
    log("SUMMARY")
    for label, status, detail in STEP_RESULTS:
        log("  %-4s %-44s %s" % (status, label, detail))
    if MANUAL_NOTES:
        log("-" * 70)
        log("MANUAL FOLLOW-UPS (%d):" % len(MANUAL_NOTES))
        for note in MANUAL_NOTES:
            log("  MANUAL: " + note)
    log("Re-run safe: imported sounds, assigned properties and montages already "
        "carrying a PlaySound notify are all skipped.")
    log("=" * 70)


main()
