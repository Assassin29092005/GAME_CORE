"""Batch-place the guide.md feel-notify windows on the project's montages.

Places (each group its own guarded step; PASS/FAIL/SKIP summary at the end):
  1. ANS_CancelWindow  on hero combo montages   (/Game/Retargeted_Animations/Combo_0*/AM_*)
     and minion copies (/Game/Arena/Minions/*)  -- guide.md 3.2 step 5:
     from (ANS_DealDamage window end + 0.05 s) to 85 % of montage length.
     Heavy entries (chain finishers per Tools/set_combo_damage.py's scheme)
     cancel late: window start clamped to >= 75 % of length ("heavies commit").
  2. ANS_Invulnerable  on dodge montages (name Dodge* under /Game/Retargeted_Animations)
     -- guide.md 3.5: 10 % to 60 % of the montage.
  3. AN_RestoreRate    on boss attacks (/Game/Retargeted_Animations/BOSS/Attack_0*_Seq_Montage)
     -- guide.md 4.4 step 3: single notify at the ANS_DealDamage window start
     (the 'Active' boundary; the wind-up slow-in itself is set in C++ at play
     time -- this notify only restores 1.0x).
  4. ANS_HyperArmor    on the HEAVY boss attacks only -- guide.md 4.5 step 4:
     over the ANS_DealDamage window +-0.1 s. Heavies are determined the same
     way Tools/set_combo_damage.py does (DamageType == "Heavy", i.e. the chain
     finisher); if no CombatAnimConfig marks a boss attack montage Heavy, the
     script falls back to the LAST TWO (Attack_05/06) and logs the assumption.

Idempotent: montages that already carry the target notify class are skipped
with a log line. Only assets under the folders above are ever touched.
All /Script/GAME_CORE notify classes are feature-detected -- if one is not
compiled yet, its group SKIPs with manual placement instructions instead.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/place_feel_notifies.py"
  (or Tools -> Execute Python Script... and pick this file)

Or headless (editor CLOSED -- it opens its own commandlet editor):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "D:\\GAME_CORE 5.8\\GAME_CORE.uproject" ^
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/place_feel_notifies.py"
"""

import re
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

RETARGET_DIR = "/Game/Retargeted_Animations"
COMBO_DIRS = ["%s/Combo_%02d" % (RETARGET_DIR, i) for i in range(1, 10)]
BOSS_DIR = RETARGET_DIR + "/BOSS"
MINION_DIR = "/Game/Arena/Minions"

# The ONLY folders this script may mutate/save assets in.
ALLOWED_PREFIXES = (RETARGET_DIR + "/", MINION_DIR + "/")

BOSS_ATTACK_RE = re.compile(r"^Attack_0(\d)_Seq_Montage$")
BOSS_FALLBACK_HEAVIES = ("Attack_05_Seq_Montage", "Attack_06_Seq_Montage")

# The boss's actual heavy source of truth (BossActionComponent.h: the
# HeavyAttackMontages TSet drives the telegraph flavor -- red vs yellow).
# Step 7 reads it from this BP before falling back to name conventions.
BP_BOSS_PATH = "/Game/Blueprints/BP_Boss"

# Notify classes (C++ -- may not be compiled yet; feature-detected).
CLS_DEAL_DAMAGE = "ANS_DealDamage"
CLS_CANCEL = "ANS_CancelWindow"
CLS_INVULN = "ANS_Invulnerable"
CLS_RESTORE = "AN_RestoreRate"
CLS_HYPER = "ANS_HyperArmor"

# Window geometry (guide.md 3.2 / 3.5 / 4.5)
CANCEL_GAP_AFTER_DAMAGE = 0.05  # s after the damage window closes
CANCEL_END_FRACTION = 0.85      # never let a cancel window reach 100 %
CANCEL_HEAVY_START_FRACTION = 0.75  # heavies cancel late: last quarter only
DODGE_IFRAME_START_FRACTION = 0.10
DODGE_IFRAME_END_FRACTION = 0.60
HYPER_ARMOR_PAD = 0.10          # s either side of the damage window
MIN_WINDOW_DURATION = 0.02      # s -- refuse to place degenerate slivers

TRACK_NAME = "FeelNotifies"     # created if possible; else first existing track

STEP_RESULTS = []   # (label, "PASS"/"FAIL"/"SKIP", detail)
MANUAL_NOTES = []   # printed at the end for anything that degraded


def log(msg):
    unreal.log("[FeelNotifies] " + str(msg))


def warn(msg):
    unreal.log_warning("[FeelNotifies] " + str(msg))


class StepSkip(Exception):
    """Deliberate no-op (missing class / missing API / nothing to do)."""


def record(label, ok, detail=""):
    STEP_RESULTS.append((label, "PASS" if ok else "FAIL", detail))


def record_skip(label, detail=""):
    STEP_RESULTS.append((label, "SKIP", detail))


def run_step(label, fn):
    """Run one step; never let its exception escape (build_arena_level ethos)."""
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
# Step 0: feature-detect the notify API (names shifted across 5.x)
# ---------------------------------------------------------------------------

# UAnimationBlueprintLibrary is exposed as unreal.AnimationLibrary in every
# 5.x binding seen so far, but guard the holder itself too.
LIB = getattr(unreal, "AnimationLibrary", None) \
    or getattr(unreal, "AnimationBlueprintLibrary", None)

API = {}  # key -> bound callable (or None)
API_NAMES = {}  # key -> resolved function name, for the log


def _resolve(key, exact_names, regex):
    """hasattr on the exact 5.4-5.6 names first, then a dir() regex scan so a
    5.8 rename is discovered instead of fatal (same tactic as
    build_arena_level's HitResult field discovery)."""
    if LIB is None:
        API[key] = None
        return
    for name in exact_names:
        if hasattr(LIB, name):
            API[key] = getattr(LIB, name)
            API_NAMES[key] = name
            return
    pat = re.compile(regex)
    for name in dir(LIB):
        if not name.startswith("_") and pat.fullmatch(name):
            API[key] = getattr(LIB, name)
            API_NAMES[key] = name + " (regex-discovered)"
            return
    API[key] = None
    API_NAMES[key] = "<MISSING: tried %s, regex %s>" % (exact_names, regex)


def step0_detect_api():
    if LIB is None:
        raise RuntimeError(
            "neither unreal.AnimationLibrary nor unreal.AnimationBlueprintLibrary "
            "exists -- notify editing API not available in this build")
    _resolve("events", ["get_animation_notify_events"],
             r"get_animation_notify_events?")
    _resolve("trig", ["get_anim_notify_event_trigger_time"],
             r"get_anim(ation)?_notify_event_trigger_time")
    _resolve("dur", ["get_anim_notify_event_duration"],
             r"get_anim(ation)?_notify_event_duration")
    _resolve("add_state", ["add_animation_notify_state_event"],
             r"add_animation_notify_state_event")
    _resolve("add_evt", ["add_animation_notify_event"],
             r"add_animation_notify_event")
    _resolve("tracks", ["get_animation_notify_track_names"],
             r"get_animation_notify_track_names")
    _resolve("add_track", ["add_animation_notify_track"],
             r"add_animation_notify_track")
    _resolve("length", ["get_sequence_length"],
             r"get_(sequence|play)_length")

    for key in ("events", "trig", "dur", "add_state", "add_evt",
                "tracks", "add_track", "length"):
        log("API %-10s -> %s" % (key, API_NAMES.get(key, "<unresolved>")))

    # Read-side (events + trig) is required by every group; write-side is
    # checked per group so e.g. a missing add_evt only kills RestoreRate.
    missing = [k for k in ("events", "trig") if API.get(k) is None]
    if missing:
        raise RuntimeError(
            "core notify read API missing (%s) -- refusing to guess; place "
            "the windows manually per guide.md 3.2/3.5/4.4/4.5" % ", ".join(missing))
    return "AnimationLibrary resolved (%s)" % LIB.__name__


def _require_api(*keys):
    missing = [k for k in keys if API.get(k) is None]
    if missing:
        raise StepSkip("required notify API missing: %s -- place manually "
                       "(see the manual notes at the end)" % ", ".join(missing))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def load_notify_class(short_name):
    """unreal.load_class for /Script/GAME_CORE.<name>; None if not compiled."""
    path = "/Script/GAME_CORE.%s" % short_name
    try:
        cls = unreal.load_class(None, path)
    except Exception:
        cls = None
    if cls is None:
        log("Notify class NOT available (not compiled yet?): %s" % path)
    return cls


def _require_class(short_name, manual_hint):
    cls = load_notify_class(short_name)
    if cls is None:
        MANUAL_NOTES.append("%s missing -- after the C++ class is built: %s"
                            % (short_name, manual_hint))
        raise StepSkip("/Script/GAME_CORE.%s not found -- build the C++ class "
                       "first (Build.bat, editor closed), then re-run" % short_name)
    return cls


def assert_allowed(montage):
    path = montage.get_path_name()
    if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
        raise RuntimeError("REFUSING to touch asset outside allowed folders: %s" % path)


def montage_length(m):
    if API.get("length") is not None:
        try:
            return float(API["length"](m))
        except Exception:
            pass
    # 5.x fallback: UAnimSequenceBase::GetPlayLength is BP-exposed
    if hasattr(m, "get_play_length"):
        try:
            return float(m.get_play_length())
        except Exception:
            pass
    try:
        return float(m.get_editor_property("sequence_length"))
    except Exception as exc:
        raise RuntimeError("cannot read montage length of %s (%s)"
                           % (m.get_name(), exc))


def get_events(m):
    try:
        return list(API["events"](m))
    except Exception as exc:
        raise RuntimeError("get_animation_notify_events failed on %s (%s)"
                           % (m.get_name(), exc))


def event_class_name(ev):
    """Class name of an event's payload; feature-detects the struct fields.
    NOTE: 'notify_state_class' on FAnimNotifyEvent is the notify-state
    INSTANCE despite the name (engine quirk)."""
    for prop in ("notify_state_class", "notify"):
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


def event_trigger_time(ev):
    return float(API["trig"](ev))


def event_duration(ev):
    if API.get("dur") is not None:
        try:
            return float(API["dur"](ev))
        except Exception:
            pass
    return 0.0


def has_notify_class(m, class_keyword):
    return any(class_keyword in event_class_name(ev) for ev in get_events(m))


def deal_damage_window(m):
    """(start, end) union of all ANS_DealDamage windows, or None."""
    start, end = None, None
    for ev in get_events(m):
        if CLS_DEAL_DAMAGE not in event_class_name(ev):
            continue
        t = event_trigger_time(ev)
        d = event_duration(ev)
        start = t if start is None else min(start, t)
        end = (t + d) if end is None else max(end, t + d)
    if start is None:
        return None
    return (start, end)


def ensure_track(m):
    """Return a notify track name to place on; prefer a dedicated one."""
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
            try:
                API["add_track"](m, TRACK_NAME, unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
                return TRACK_NAME
            except Exception as exc:
                warn("Could not add notify track '%s' on %s (%s) -- using an "
                     "existing track." % (TRACK_NAME, m.get_name(), exc))
    if names:
        return names[0]
    raise RuntimeError("no notify track on %s and cannot create one" % m.get_name())


def add_state_window(m, cls, start, end, what):
    assert_allowed(m)
    duration = end - start
    if duration < MIN_WINDOW_DURATION:
        raise RuntimeError("%s window degenerate on %s (%.3f..%.3f s)"
                           % (what, m.get_name(), start, end))
    track = ensure_track(m)
    created = API["add_state"](m, track, float(start), float(duration), cls)
    if created is None:
        raise RuntimeError("add_animation_notify_state_event returned None "
                           "for %s on %s" % (what, m.get_name()))
    log("  %-32s %s @ %.3f..%.3f s (track %s)"
        % (m.get_name(), what, start, end, track))


def add_point_notify(m, cls, time, what):
    assert_allowed(m)
    track = ensure_track(m)
    created = API["add_evt"](m, track, float(time), cls)
    if created is None:
        raise RuntimeError("add_animation_notify_event returned None for %s on %s"
                           % (what, m.get_name()))
    log("  %-32s %s @ %.3f s (track %s)" % (m.get_name(), what, time, track))


def save(m):
    assert_allowed(m)
    # only_if_is_dirty=False is load-bearing: the notify APIs do not reliably
    # dirty montage packages here, and the default dirty-gated save then
    # "succeeds" while writing NOTHING (burned a run on this: all steps PASS,
    # all timestamps untouched). Force the write, then verify on disk.
    try:
        m.get_outer().mark_package_dirty()
    except Exception:
        pass
    import os, time as _time
    pkg_name = m.get_outer().get_name()  # e.g. /Game/Retargeted_Animations/...
    disk_path = None
    if pkg_name.startswith("/Game/"):
        disk_path = os.path.join(
            unreal.Paths.project_content_dir(), pkg_name[len("/Game/"):] + ".uasset")
    before = os.path.getmtime(disk_path) if disk_path and os.path.isfile(disk_path) else None
    if not unreal.EditorAssetLibrary.save_loaded_asset(m, only_if_is_dirty=False):
        raise RuntimeError("save_loaded_asset failed for %s" % m.get_path_name())
    # Disk-truth guard: the .uasset's mtime must have advanced, or the "save"
    # silently wrote nothing again.
    if before is not None:
        after = os.path.getmtime(disk_path)
        if after <= before:
            raise RuntimeError("save reported success but %s was NOT rewritten on disk"
                               % disk_path)


def list_montages(directory, name_filter=None):
    """AnimMontage assets under directory (recursive), sorted by name."""
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
# Step 1: discovery
# ---------------------------------------------------------------------------

DISCOVERED = {
    "hero": [],    # combo attack montages
    "minion": [],  # minion montages (attacks filtered later by DealDamage presence)
    "dodge": [],   # Dodge* montages
    "boss": [],    # boss Attack_0X montages
}


def step1_discover():
    for d in COMBO_DIRS:
        DISCOVERED["hero"] += list_montages(d, lambda n: n.startswith("AM_"))
    DISCOVERED["minion"] = list_montages(MINION_DIR)
    DISCOVERED["dodge"] = [
        m for m in list_montages(RETARGET_DIR, lambda n: "Dodge" in n)
        if not str(m.get_path_name()).startswith(BOSS_DIR + "/")
    ]
    DISCOVERED["boss"] = list_montages(
        BOSS_DIR, lambda n: BOSS_ATTACK_RE.match(n) is not None)

    for key in ("hero", "minion", "dodge", "boss"):
        log("Discovered %-6s: %d montage(s): %s"
            % (key, len(DISCOVERED[key]),
               ", ".join(m.get_name() for m in DISCOVERED[key]) or "<none>"))
    if not any(DISCOVERED.values()):
        raise RuntimeError("no montages found in any target folder -- wrong project?")
    return ", ".join("%s=%d" % (k, len(v)) for k, v in DISCOVERED.items())


# ---------------------------------------------------------------------------
# Step 2: heavy determination (set_combo_damage.py scheme)
# ---------------------------------------------------------------------------

HEAVY_MONTAGE_PATHS = set()   # package paths of montages marked Heavy
HEAVY_SOURCE = "none"         # "damage_type" | "finisher_position" | "none"


def _entry_montage_pkg(entry):
    try:
        mont = entry.get_editor_property("montage")
    except Exception:
        return None
    if mont is None:
        return None
    return str(mont.get_path_name()).split(".")[0]


def step2_heavy_set():
    """Heavy = DamageType == 'Heavy' on a CombatAnimConfig entry (what
    Tools/set_combo_damage.py writes: the chain finisher of every N>1 chain).
    If no config carries a Heavy tag yet (set_combo_damage.py not run), fall
    back to the positional rule itself: last entry of every N>1 chain."""
    global HEAVY_SOURCE
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    assets = registry.get_assets_by_class(
        unreal.TopLevelAssetPath("/Script/GAME_CORE", "CombatAnimConfig"), True)
    if not assets:
        raise StepSkip("no CombatAnimConfig assets found -- heavy detection "
                       "unavailable; boss hyper-armor will use the Attack_05/06 fallback")

    by_type, by_position = set(), set()
    for asset_data in assets:
        cfg = asset_data.get_asset()
        if cfg is None:
            warn("Could not load %s" % asset_data.package_name)
            continue
        chain = cfg.get_editor_property("combo_chain")
        n = len(chain)
        for i in range(n):
            pkg = _entry_montage_pkg(chain[i])
            if pkg is None:
                continue
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
        HEAVY_MONTAGE_PATHS.update(by_type)
        HEAVY_SOURCE = "damage_type"
    elif by_position:
        HEAVY_MONTAGE_PATHS.update(by_position)
        HEAVY_SOURCE = "finisher_position"
        warn("No CombatAnimConfig entry has DamageType == 'Heavy' -- "
             "set_combo_damage.py apparently not run yet. Using the positional "
             "chain-finisher rule (last entry of every N>1 chain) instead.")
    else:
        raise StepSkip("configs exist but no heavy could be determined "
                       "(all chains empty/single?)")
    log("Heavy montages (%s): %s"
        % (HEAVY_SOURCE, ", ".join(sorted(p.split("/")[-1] for p in HEAVY_MONTAGE_PATHS))))
    return "%d heavy montage(s) via %s" % (len(HEAVY_MONTAGE_PATHS), HEAVY_SOURCE)


def is_heavy(m):
    return str(m.get_path_name()).split(".")[0] in HEAVY_MONTAGE_PATHS


# ---------------------------------------------------------------------------
# Steps 3/4: cancel windows (hero combos, minion copies)
# ---------------------------------------------------------------------------

CANCEL_MANUAL = ("open the montage -> Notifies track -> Add Notify State -> "
                 "Cancel Window -> drag from just after the ANS_DealDamage bar "
                 "to ~85%% of the montage (heavies: last quarter only) -- guide.md 3.2 step 5")


def _place_cancel_windows(montages, group):
    _require_api("dur", "add_state")
    cls = _require_class(CLS_CANCEL, CANCEL_MANUAL)
    if not montages:
        raise StepSkip("no %s montages discovered" % group)
    placed, already, no_window, failed = 0, 0, 0, 0
    for m in montages:
        try:
            if has_notify_class(m, CLS_CANCEL):
                log("  %-32s already has %s -- skipped (idempotent)"
                    % (m.get_name(), CLS_CANCEL))
                already += 1
                continue
            window = deal_damage_window(m)
            if window is None:
                log("  %-32s no ANS_DealDamage window -- not an attack montage, skipped"
                    % m.get_name())
                no_window += 1
                continue
            length = montage_length(m)
            start = window[1] + CANCEL_GAP_AFTER_DAMAGE
            rule = "light"
            if is_heavy(m):
                start = max(start, CANCEL_HEAVY_START_FRACTION * length)
                rule = "HEAVY (cancels late)"
            end = CANCEL_END_FRACTION * length
            if start >= end - MIN_WINDOW_DURATION:
                warn("  %-32s damage window ends too late (%.3f s of %.3f s) -- "
                     "no room for a cancel window; fix the timing per guide.md "
                     "3.1 first" % (m.get_name(), window[1], length))
                no_window += 1
                continue
            add_state_window(m, cls, start, end, "%s [%s]" % (CLS_CANCEL, rule))
            save(m)
            placed += 1
        except Exception as exc:  # noqa: BLE001 - per-montage isolation
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
    if placed == 0 and already == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return ("placed %d, already-had %d, no-damage-window %d, failed %d"
            % (placed, already, no_window, failed))


def step3_hero_cancel():
    return _place_cancel_windows(DISCOVERED["hero"], "hero combo")


def step4_minion_cancel():
    return _place_cancel_windows(DISCOVERED["minion"], "minion")


# ---------------------------------------------------------------------------
# Step 5: dodge i-frames
# ---------------------------------------------------------------------------

def step5_dodge_iframes():
    _require_api("add_state")
    cls = _require_class(
        CLS_INVULN,
        "open each Dodge* montage -> Add Notify State -> Invulnerable -> drag "
        "over 10%%-60%% of the montage -- guide.md 3.5 i-frames step 3")
    montages = DISCOVERED["dodge"]
    if not montages:
        raise StepSkip("no Dodge* montages found under " + RETARGET_DIR)
    placed, already, failed = 0, 0, 0
    for m in montages:
        try:
            if has_notify_class(m, CLS_INVULN):
                log("  %-32s already has %s -- skipped (idempotent)"
                    % (m.get_name(), CLS_INVULN))
                already += 1
                continue
            length = montage_length(m)
            add_state_window(m, cls,
                             DODGE_IFRAME_START_FRACTION * length,
                             DODGE_IFRAME_END_FRACTION * length,
                             CLS_INVULN)
            save(m)
            placed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
    if placed == 0 and already == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return "placed %d, already-had %d, failed %d" % (placed, already, failed)


# ---------------------------------------------------------------------------
# Step 6: boss AN_RestoreRate (telegraph 'Active' boundary)
# ---------------------------------------------------------------------------

def step6_boss_restore_rate():
    _require_api("add_evt")
    cls = _require_class(
        CLS_RESTORE,
        "open each boss Attack_0X montage -> Add Notify -> AN_RestoreRate at "
        "the start of the ANS_DealDamage window -- guide.md 4.4 step 3")
    montages = DISCOVERED["boss"]
    if not montages:
        raise StepSkip("no boss Attack_0X_Seq_Montage assets found in " + BOSS_DIR)
    placed, already, no_window, failed = 0, 0, 0, 0
    for m in montages:
        try:
            if has_notify_class(m, CLS_RESTORE):
                log("  %-32s already has %s -- skipped (idempotent)"
                    % (m.get_name(), CLS_RESTORE))
                already += 1
                continue
            window = deal_damage_window(m)
            if window is None:
                warn("  %-32s has NO ANS_DealDamage window -- cannot anchor "
                     "AN_RestoreRate; place the damage window first, then re-run"
                     % m.get_name())
                no_window += 1
                continue
            add_point_notify(m, cls, window[0], CLS_RESTORE)
            save(m)
            placed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
    if placed == 0 and already == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return ("placed %d, already-had %d, no-damage-window %d, failed %d"
            % (placed, already, no_window, failed))


# ---------------------------------------------------------------------------
# Step 7: boss hyper-armor (heavies only)
# ---------------------------------------------------------------------------

def bp_boss_heavy_montage_pkgs():
    """Package paths from BP_Boss's BossActionComponent.HeavyAttackMontages --
    the boss's ACTUAL heavy source of truth (drives the red/yellow telegraph;
    the CombatAnimConfig scan never marks boss montages Heavy because boss
    attacks aren't combo chains). Returns an empty set on any failure so the
    caller can fall back; every strategy is feature-detected (5.x API drift)."""
    try:
        cls = unreal.load_class(None, "/Script/GAME_CORE.BossActionComponent")
    except Exception:
        cls = None
    if cls is None:
        log("BossActionComponent class not compiled -- cannot read HeavyAttackMontages")
        return set()

    bp = None
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(BP_BOSS_PATH):
            bp = unreal.EditorAssetLibrary.load_asset(BP_BOSS_PATH)
    except Exception:
        bp = None
    if bp is None:
        log("BP_Boss not found at %s -- cannot read HeavyAttackMontages" % BP_BOSS_PATH)
        return set()

    candidates = []

    # Strategy 1: walk the BP's SCS nodes via SubobjectDataSubsystem (5.1+),
    # which yields the component TEMPLATE objects (BP-added components never
    # exist on the CDO).
    try:
        sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        lib = getattr(unreal, "SubobjectDataBlueprintFunctionLibrary", None)
        if sds is not None and lib is not None:
            for handle in sds.k2_gather_subobject_data_for_blueprint(bp):
                try:
                    obj = lib.get_object(lib.get_data(handle))
                except Exception:
                    continue
                if obj is not None and "BossActionComponent" in str(obj.get_class().get_name()):
                    candidates.append(obj)
    except Exception as exc:
        log("SCS walk unavailable (%s) -- trying the CDO" % exc)

    # Strategy 2: generated-class CDO (covers a C++-added/inherited component).
    if not candidates:
        try:
            gen = bp.generated_class()
            cdo = unreal.get_default_object(gen) if gen is not None else None
            if cdo is not None:
                candidates.extend(list(cdo.get_components_by_class(cls)))
        except Exception:
            pass

    pkgs = set()
    for comp in candidates:
        try:
            heavy = comp.get_editor_property("heavy_attack_montages")
        except Exception:
            continue
        for mont in (list(heavy) if heavy is not None else []):
            if mont is not None:
                pkgs.add(str(mont.get_path_name()).split(".")[0])
    return pkgs


def step7_boss_hyper_armor():
    _require_api("dur", "add_state")
    cls = _require_class(
        CLS_HYPER,
        "open each HEAVY boss attack montage -> Add Notify State -> "
        "ANS_HyperArmor over the ANS_DealDamage window +- a few frames -- "
        "guide.md 4.5 hyper-armor step 4")
    montages = DISCOVERED["boss"]
    if not montages:
        raise StepSkip("no boss Attack_0X_Seq_Montage assets found in " + BOSS_DIR)

    # Priority 1: the BP-configured HeavyAttackMontages set on BP_Boss's
    # BossActionComponent -- THE source of truth for which boss attacks
    # telegraph red/unblockable, so hyper-armor must land on exactly these.
    bp_pkgs = bp_boss_heavy_montage_pkgs()
    heavies = [m for m in montages
               if str(m.get_path_name()).split(".")[0] in bp_pkgs]
    if heavies:
        log("Boss heavies read from BP_Boss BossActionComponent.HeavyAttackMontages: %s"
            % ", ".join(m.get_name() for m in heavies))
    else:
        if bp_pkgs:
            warn("BP_Boss HeavyAttackMontages set has %d entr(ies) but none match "
                 "the discovered boss Attack_0X montages -- falling through."
                 % len(bp_pkgs))
        # Priority 2: the CombatAnimConfig scan (set_combo_damage.py scheme).
        heavies = [m for m in montages if is_heavy(m)]
        if heavies:
            log("Boss heavies determined from CombatAnimConfig (%s): %s"
                % (HEAVY_SOURCE, ", ".join(m.get_name() for m in heavies)))
    if not heavies:
        # Priority 3: hardcoded name convention -- loudly.
        heavies = [m for m in montages if m.get_name() in BOSS_FALLBACK_HEAVIES]
        warn("=" * 70)
        warn("ASSUMPTION: BP_Boss's BossActionComponent.HeavyAttackMontages could "
             "not be read (or is empty) AND no CombatAnimConfig marks any boss "
             "attack montage as Heavy, so hyper-armor goes on the LAST TWO "
             "attacks by convention: %s." % ", ".join(BOSS_FALLBACK_HEAVIES))
        warn("If the boss's real heavies differ, delete/move the ANS_HyperArmor "
             "bars by hand (guide.md 4.5 step 4).")
        warn("=" * 70)
        MANUAL_NOTES.append(
            "Hyper-armor used the Attack_05/06 fallback -- verify those are the "
            "boss's actual heavy swings and move the windows if not.")
    if not heavies:
        raise StepSkip("fallback heavies %s not found either" % (BOSS_FALLBACK_HEAVIES,))

    placed, already, no_window, failed = 0, 0, 0, 0
    for m in heavies:
        try:
            if has_notify_class(m, CLS_HYPER):
                log("  %-32s already has %s -- skipped (idempotent)"
                    % (m.get_name(), CLS_HYPER))
                already += 1
                continue
            window = deal_damage_window(m)
            if window is None:
                warn("  %-32s has NO ANS_DealDamage window -- cannot anchor "
                     "hyper-armor; place the damage window first, then re-run"
                     % m.get_name())
                no_window += 1
                continue
            length = montage_length(m)
            start = max(0.0, window[0] - HYPER_ARMOR_PAD)
            end = min(length, window[1] + HYPER_ARMOR_PAD)
            add_state_window(m, cls, start, end, CLS_HYPER)
            save(m)
            placed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
    if placed == 0 and already == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return ("placed %d on %d heavies, already-had %d, no-damage-window %d, failed %d"
            % (placed, len(heavies), already, no_window, failed))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("=" * 70)
    log("place_feel_notifies -- guide.md 3.2/3.5/4.4/4.5 notify placement")
    log("=" * 70)

    run_step("0. Feature-detect notify API", step0_detect_api)
    api_ok = STEP_RESULTS[-1][1] == "PASS"

    if api_ok:
        run_step("1. Discover montages", step1_discover)
        run_step("2. Determine heavies (set_combo_damage scheme)", step2_heavy_set)
        run_step("3. Hero combos: ANS_CancelWindow", step3_hero_cancel)
        run_step("4. Minion copies: ANS_CancelWindow", step4_minion_cancel)
        run_step("5. Dodge montages: ANS_Invulnerable", step5_dodge_iframes)
        run_step("6. Boss attacks: AN_RestoreRate", step6_boss_restore_rate)
        run_step("7. Boss heavies: ANS_HyperArmor", step7_boss_hyper_armor)
    else:
        for label in ("1. Discover montages",
                      "2. Determine heavies (set_combo_damage scheme)",
                      "3. Hero combos: ANS_CancelWindow",
                      "4. Minion copies: ANS_CancelWindow",
                      "5. Dodge montages: ANS_Invulnerable",
                      "6. Boss attacks: AN_RestoreRate",
                      "7. Boss heavies: ANS_HyperArmor"):
            record_skip(label, "notify API unavailable (step 0 failed)")

    log("=" * 70)
    log("SUMMARY")
    for label, status, detail in STEP_RESULTS:
        log("  %-4s %-48s %s" % (status, label, detail))
    if MANUAL_NOTES:
        log("-" * 70)
        log("MANUAL FOLLOW-UPS:")
        for note in MANUAL_NOTES:
            log("  * " + note)
    log("Re-run safe: montages already carrying a notify class are skipped.")
    log("=" * 70)


main()
