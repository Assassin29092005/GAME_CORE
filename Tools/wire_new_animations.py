"""Wire the new-animation plan (section E) into montages, DAs and BPs.

RE-RUNNABLE end-to-end wiring for the animation plan's three characters. For
every retargeted sequence it finds in the plan's output folders it creates the
montage, places the plan's notify windows + trails, builds/extends the
CombatAnimConfig data assets, and wires the receivers (BP_NeuralHero /
BP_Boss / BP_Minion). Folders that don't exist yet (retarget batches not run)
SKIP loudly per group -- exactly the integrate_golem_minion.py gating: run
the retarget batch, then RE-RUN this script to finish that group.

GROUPS + their retarget-batch dependency (Tools/batch_retarget_anims.py /
setup_retargeters -- Batch numbers per the plan's section D):
  A1 Hero "Flurry"  (SideComboConfig)    needs Batch 1 -> Combo_05 or Fighter dir
  A2 Hero "Breaker" (ForwardComboConfig) needs NOTHING  -> reuses existing BOSS/Attack_0{1,4,6}_Seq
  A3 Hero AM_Hit_Heavy                   needs Batch 1 -> Hit or Fighter dir
  B  Boss ChargeAttack/Slam/RunAttack    needs Batch 1 -> BOSS or Fighter dir (new seqs)
  C  Golem attacks/hit/death             needs Batch 3 -> /Game/Arena/Minions/GolemAnims

FOLDER CONTRACT with Tools/setup_retargeters.py (keep in sync!): its Fighter
pair outputs FTR_* sequences flat into /Game/Retargeted_Animations/Fighter and
its StoneGolem pair outputs GOL_* into /Game/Arena/Minions/GolemAnims (the same
dir integrate_golem_minion.py documents). Step 2 therefore scans the Fighter
out_folder IN ADDITION to the legacy Combo_05/Hit/BOSS dirs (the name regexes
use search() so the FTR_ prefix is tolerated), and GOLEM_RT_DIR points at
GolemAnims.

BOSS WIRING TRUTH (BossActionComponent.h:47/:126, verified): the boss has a
SINGLE `AttackMontage` UPROPERTY and a `HeavyAttackMontages` TSet -- there is
NO montage array. Per instructions this script does NOT hack around that: it
adds the new heavies to HeavyAttackMontages (additive, safe) and emits a
MANUAL note with the exact C++ array-extension spec. AttackMontage itself is
left untouched so the currently-working attack keeps working.

WINDOW GEOMETRY (plan section E):
  hero lights    ANS_DealDamage 30-55%%, ANS_CancelWindow dmg-end+0.05 -> 85%%
  hero finishers ANS_DealDamage 35-60%%, NO cancel window (finishers commit)
  boss attacks   ANS_DealDamage 50-65%% (ESTIMATE -- retime after the Windup
                 section is authored), AN_RestoreRate at the dmg-window start,
                 ANS_HyperArmor dmg-window +-0.1 s on heavies only
  golem attacks  ANS_DealDamage 35-60%%
  trails         TimedNiagaraEffect over dmg-window +-0.1 s
                 (hero NS_SlashTrail_Basic / boss NS_SlashTrail_Dark)

HARD RULES honored:
  - struct-array ELEMENT write-backs are never trusted alone: every slot /
    combo-chain / struct write is a whole-array (or whole-struct) set-back
    verified by re-read (fix_montage_slots.py / integrate_golem_minion.py
    step-6 patterns).
  - every save is mark_package_dirty + save_loaded_asset(only_if_is_dirty=
    False) + on-disk mtime verification.
  - montages are per-character duplicates; sequences are shared freely.
  - unreal.SystemLibrary.collect_garbage() every ~12 asset ops + per step.
  - only the folders in ALLOWED_PREFIXES are ever written.

Run headless (editor CLOSED -- the proven path on this machine):
  "C:\\Program Files\\Epic Games\\UE_5.8\\Engine\\Binaries\\Win64\\UnrealEditor-Cmd.exe" ^
      "D:\\GAME_CORE 5.8\\GAME_CORE.uproject" ^
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/wire_new_animations.py"
(only the commandlet SHUTDOWN may crash cosmetically -- work + saves complete first)
"""

import os
import re
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[WireNewAnims]"

RETARGET_DIR = "/Game/Retargeted_Animations"
FLURRY_DIR = RETARGET_DIR + "/Combo_05"
BOSS_DIR = RETARGET_DIR + "/BOSS"
HIT_DIR = RETARGET_DIR + "/Hit"
HEAVY_DIR = RETARGET_DIR + "/Heavy"          # new hero Breaker montages land here
PARRY_DIR = RETARGET_DIR + "/Parry"          # parked assets (no wiring target yet)
# FOLDER CONTRACT (see module docstring): these two are setup_retargeters.py
# out_folders -- Fighter-pair FTR_* sequences and StoneGolem-pair GOL_*
# sequences respectively. Keep in sync with that script's PAIRS table.
FIGHTER_RT_DIR = RETARGET_DIR + "/Fighter"
GOLEM_RT_DIR = "/Game/Arena/Minions/GolemAnims"
MINION_DIR = "/Game/Arena/Minions"
DA_DIR = "/Game/Arena/Combat"                # new hero CombatAnimConfig DAs

BP_HERO_PATH = "/Game/Blueprints/BP_NeuralHero"
BP_BOSS_PATH = "/Game/Blueprints/BP_Boss"
BP_MINION_PATH = MINION_DIR + "/BP_Minion"

DA_FLURRY_PATH = DA_DIR + "/DA_Combo_Flurry"
DA_BREAKER_PATH = DA_DIR + "/DA_Combo_Breaker"
DA_GOLEM_PATH = MINION_DIR + "/DA_GolemCombat"

# The ONLY folders this script may mutate/save assets in.
ALLOWED_PREFIXES = (
    RETARGET_DIR + "/",
    "/Game/Stone_Golem/",
    "/Game/Arena/",
    "/Game/Blueprints/",
)

# Slots (project convention: 'Attack'/'Block'/'DefaultSlot', DefaultGroup).
SLOT_HERO_BOSS = "Attack"      # per task spec; verify visibly in PIE -- if a
                               # swing is invisible the ABP lacks the slot node
                               # and fix_montage_slots.py (DefaultSlot) applies
SLOT_DEFAULT = "DefaultSlot"   # golem + reaction montages

# Notify classes (feature-detected; group SKIPs when not compiled).
CLS_DEAL_DAMAGE = "ANS_DealDamage"
CLS_CANCEL = "ANS_CancelWindow"
CLS_HYPER = "ANS_HyperArmor"
CLS_RESTORE = "AN_RestoreRate"

DMG_INSTANCE_PROPS = {"trace_radius": 60.0, "trace_forward_offset": 150.0}
TRACK_NAME = "FeelNotifies"    # same track place_feel_notifies.py uses
FX_TRACK_NAME = "FX"           # same track equip_weapons_and_trails.py uses

# Window geometry
HERO_LIGHT_DMG = (0.30, 0.55)
HERO_FINISHER_DMG = (0.35, 0.60)
BOSS_DMG = (0.50, 0.65)        # estimate until the Windup section exists
GOLEM_DMG = (0.35, 0.60)
CANCEL_GAP_AFTER_DAMAGE = 0.05
CANCEL_END_FRACTION = 0.85
HYPER_ARMOR_PAD = 0.10
TRAIL_PAD = 0.10
MIN_WINDOW_DURATION = 0.02

# Trails (equip_weapons_and_trails.py config)
NS_TRAIL_HERO = "/Game/SlashTrail_SoftTofu/Niagara/Basic/NS_SlashTrail_Basic"
NS_TRAIL_BOSS = "/Game/SlashTrail_SoftTofu/Niagara/Dark/NS_SlashTrail_Dark"
TIMED_NIAGARA_CLASS_CANDIDATES = (
    "/Script/Niagara.AnimNotifyState_TimedNiagaraEffect",
    "/Script/Niagara.AnimNotifyState_TimedNiagaraEffectAdvanced",
    "/Script/NiagaraAnimNotifies.AnimNotifyState_TimedNiagaraEffect",
)
TIMED_NIAGARA_KEYWORD = "TimedNiagaraEffect"
SOCKET_FALLBACK = "hand_r"

GOLEM_SKEL_PATH = "/Game/Stone_Golem/mesh/SK_Stone_Golem_Skeleton"

# ---------------------------------------------------------------------------
# The plan tables (section A / B / C). Damage scheme matches
# Tools/set_combo_damage.py exactly for the hero chains.
# Row: (seq_key, montage_name, dmg, dtype, blend_in, play_rate, hit_stop, shake, finisher)
# ---------------------------------------------------------------------------

FLURRY_ROWS = [
    ("flurry1", "AM_Combo_05_Hit1", 10.0, "Light", 0.06, 1.00, 0.05, 0.7, False),
    ("flurry2", "AM_Combo_05_Hit2", 15.0, "Light", 0.10, 1.00, 0.08, 1.0, False),
    ("flurry3", "AM_Combo_05_Hit3", 20.0, "Light", 0.10, 1.00, 0.08, 1.0, False),
    ("flurry4", "AM_Combo_05_Hit4", 25.0, "Heavy", 0.12, 0.95, 0.15, 1.5, True),
]

# Breaker reuses EXISTING boss-skeleton-family sequences (hero + boss share
# SK_UEFN_Mannequin); the sequences are shared, the montages are NEW hero-only
# duplicates (montage mutation caveat).
BREAKER_ROWS = [
    (BOSS_DIR + "/Attack_01_Seq", "AM_Heavy_Hit1", 10.0, "Light", 0.08, 0.90, 0.08, 1.0, False),
    (BOSS_DIR + "/Attack_04_Seq", "AM_Heavy_Hit2", 15.0, "Light", 0.12, 0.85, 0.08, 1.0, False),
    (BOSS_DIR + "/Attack_06_Seq", "AM_Heavy_Hit3", 25.0, "Heavy", 0.15, 0.80, 0.15, 1.5, True),
]

# Boss rows: (seq_key, montage_name, heavy)
BOSS_ROWS = [
    ("charge", "AM_BOSS_ChargeAttack", True),
    ("slam", "AM_BOSS_Slam", True),
    ("run", "AM_BOSS_RunAttack", False),
]

# Golem DA chain (plan section C, pre-nerfed: minions must not out-hit the
# hero's step 1 -- NOTE set_combo_damage.py would overwrite these to 10/25).
GOLEM_ROWS = [
    ("AM_GLM_Attack_01", 8.0, "Light"),
    ("AM_GLM_Attack_02", 12.0, "Heavy"),
]

BOSS_CPP_SPEC = (
    "Boss attack VARIETY needs a small C++ extension (BossActionComponent has "
    "only a single AttackMontage UPROPERTY -- verified .h:47): replace "
    "'TObjectPtr<UAnimMontage> AttackMontage' with "
    "'TArray<TObjectPtr<UAnimMontage>> AttackMontages', pick into a new "
    "'CurrentAttackMontage' member at the top of DoAttack, and repoint the "
    "existing AttackMontage uses: min-duration calc (.cpp:343), "
    "Montage_SetPlayRate (:397), HeavyAttackMontages.Contains + 'Windup' "
    "section lookup (:404-409), and BOTH 'Montage == AttackMontage' checks in "
    "OnActionMontageEnded (:711 hyper-armor backstop, :745 recovery lockout) "
    "-> compare CurrentAttackMontage. Reflected-property change => full "
    "Build.bat rebuild with the editor closed, then assign the new AM_BOSS_* "
    "montages to the array on BP_Boss. Until then the new boss montages are "
    "notify-wired + heavy-tagged but NOT selectable by DoAttack.")

STEP_RESULTS = []   # (label, "PASS"/"FAIL"/"SKIP", detail)
MANUAL_NOTES = []
WIRED = {"hero": 0, "boss": 0, "golem": 0}
_SLOT_MANUAL = []   # montages whose slot write failed -> one aggregated note

# Cross-step state
ST = {
    "hero_skel": None,      # SK_UEFN_Mannequin (resolved from existing assets)
    "golem_skel": None,
    "seqs": {},             # seq_key -> AnimSequence (discovery step)
    "golem_seqs": {},       # attack1/attack2/hit/death -> AnimSequence
    "flurry_montages": [],  # in chain order (None gaps never allowed)
    "breaker_montages": [],
    "hit_heavy_montage": None,
    "boss_montages": {},    # montage_name -> AnimMontage
    "golem_montages": {},   # AM_GLM_* -> AnimMontage
    "da_flurry": None,
    "da_breaker": None,
    "da_golem": None,
    "ns_hero": None,
    "ns_boss": None,
    "timed_niagara_cls": None,
}

_OPS = [0]


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def manual(msg):
    MANUAL_NOTES.append(msg)
    warn("MANUAL: " + msg)


def gc_tick(force=False):
    """collect_garbage every ~12 asset ops (16 GB RAM budget)."""
    _OPS[0] += 1
    if force or _OPS[0] % 12 == 0:
        try:
            unreal.SystemLibrary.collect_garbage()
        except Exception:
            pass


class StepSkip(Exception):
    """Deliberate no-op (missing retarget output / class / API) -- not a failure."""


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
    gc_tick(force=True)


# ---------------------------------------------------------------------------
# Shared helpers (force-save / props / classes)
# ---------------------------------------------------------------------------

def assert_allowed(asset):
    path = asset.get_path_name()
    if not any(path.startswith(p) for p in ALLOWED_PREFIXES):
        raise RuntimeError("REFUSING to touch asset outside allowed folders: %s" % path)


def force_save(asset):
    """mark_package_dirty -> save_loaded_asset(only_if_is_dirty=False) ->
    verify the .uasset mtime ADVANCED on disk (dirty-gated saves have been
    proven to silently write nothing in this repo)."""
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
    gc_tick()


def set_prop_if_exists(obj, name, value, context=""):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s"
             % (name, (" on " + context) if context else "", exc))
        return False


def set_first_prop(obj, names, value):
    for name in names:
        try:
            obj.set_editor_property(name, value)
            return name
        except Exception:
            continue
    return None


def load_asset_if_exists(path):
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            return unreal.EditorAssetLibrary.load_asset(path)
    except Exception:
        pass
    return None


def load_game_class(short_name):
    try:
        return unreal.load_class(None, "/Script/GAME_CORE.%s" % short_name)
    except Exception:
        return None


def require_notify_class(short_name):
    cls = load_game_class(short_name)
    if cls is None:
        raise StepSkip("/Script/GAME_CORE.%s not compiled -- Build.bat first, "
                       "then re-run" % short_name)
    return cls


def pkg_of(asset):
    return str(asset.get_path_name()).split(".")[0]


def skeleton_matches(asset, skeleton):
    try:
        skel = asset.get_editor_property("skeleton")
    except Exception:
        return False
    return skel is not None and pkg_of(skel) == pkg_of(skeleton)


# ---------------------------------------------------------------------------
# Notify API (place_feel_notifies.py detection tactic)
# ---------------------------------------------------------------------------

LIB = getattr(unreal, "AnimationLibrary", None) \
    or getattr(unreal, "AnimationBlueprintLibrary", None)

API = {}
API_NAMES = {}


def _resolve(key, exact_names, regex):
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
        raise RuntimeError("neither unreal.AnimationLibrary nor "
                           "unreal.AnimationBlueprintLibrary exists")
    _resolve("events", ["get_animation_notify_events"], r"get_animation_notify_events?")
    _resolve("trig", ["get_anim_notify_event_trigger_time"],
             r"get_anim(ation)?_notify_event_trigger_time")
    _resolve("dur", ["get_anim_notify_event_duration"],
             r"get_anim(ation)?_notify_event_duration")
    _resolve("add_state", ["add_animation_notify_state_event"],
             r"add_animation_notify_state_event")
    _resolve("add_evt", ["add_animation_notify_event"], r"add_animation_notify_event")
    _resolve("tracks", ["get_animation_notify_track_names"],
             r"get_animation_notify_track_names")
    _resolve("add_track", ["add_animation_notify_track"], r"add_animation_notify_track")
    _resolve("length", ["get_sequence_length"], r"get_(sequence|play)_length")
    for key in ("events", "trig", "dur", "add_state", "add_evt",
                "tracks", "add_track", "length"):
        log("API %-10s -> %s" % (key, API_NAMES.get(key, "<unresolved>")))
    missing = [k for k in ("events", "trig", "add_state") if API.get(k) is None]
    if missing:
        raise RuntimeError("core notify API missing (%s) -- refusing to guess"
                           % ", ".join(missing))
    # Trail bits (equip_weapons config)
    ST["ns_hero"] = load_asset_if_exists(NS_TRAIL_HERO)
    ST["ns_boss"] = load_asset_if_exists(NS_TRAIL_BOSS)
    for path in TIMED_NIAGARA_CLASS_CANDIDATES:
        try:
            cls = unreal.load_class(None, path)
        except Exception:
            cls = None
        if cls is not None:
            ST["timed_niagara_cls"] = cls
            log("TimedNiagaraEffect notify class: %s" % path)
            break
    if ST["timed_niagara_cls"] is None:
        warn("TimedNiagaraEffect class unavailable -- trails will be skipped "
             "with a manual note.")
    return "AnimationLibrary resolved (%s); NS hero=%s boss=%s" % (
        LIB.__name__,
        "ok" if ST["ns_hero"] else "MISSING",
        "ok" if ST["ns_boss"] else "MISSING")


def montage_length(m):
    if API.get("length") is not None:
        try:
            return float(API["length"](m))
        except Exception:
            pass
    if hasattr(m, "get_play_length"):
        try:
            return float(m.get_play_length())
        except Exception:
            pass
    return float(m.get_editor_property("sequence_length"))


def get_events(m):
    return list(API["events"](m))


def _event_instance(ev):
    """NOTE: 'notify_state_class' on FAnimNotifyEvent is the notify-state
    INSTANCE despite the name (engine quirk, documented in place_feel_notifies)."""
    for prop in ("notify_state_class", "notify"):
        try:
            obj = ev.get_editor_property(prop)
        except Exception:
            continue
        if obj is not None:
            return obj
    return None


def event_class_name(ev):
    obj = _event_instance(ev)
    if obj is not None:
        try:
            return str(obj.get_class().get_name())
        except Exception:
            pass
    try:
        return str(ev.get_editor_property("notify_name"))
    except Exception:
        return ""


def has_notify_class(m, keyword):
    return any(keyword in event_class_name(ev) for ev in get_events(m))


def find_instance(m, keyword):
    for ev in get_events(m):
        inst = _event_instance(ev)
        if inst is not None and keyword in str(inst.get_class().get_name()):
            return inst
    return None


def deal_damage_window(m):
    start, end = None, None
    for ev in get_events(m):
        if CLS_DEAL_DAMAGE not in event_class_name(ev):
            continue
        t = float(API["trig"](ev))
        d = 0.0
        if API.get("dur") is not None:
            try:
                d = float(API["dur"](ev))
            except Exception:
                d = 0.0
        start = t if start is None else min(start, t)
        end = (t + d) if end is None else max(end, t + d)
    return None if start is None else (start, end)


def ensure_track(m, name=TRACK_NAME):
    names = []
    if API.get("tracks") is not None:
        try:
            names = [str(n) for n in API["tracks"](m)]
        except Exception:
            names = []
    if name in names:
        return name
    if API.get("add_track") is not None:
        try:
            API["add_track"](m, name)
            return name
        except Exception:
            try:
                API["add_track"](m, name, unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
                return name
            except Exception as exc:
                warn("could not add track '%s' on %s (%s)" % (name, m.get_name(), exc))
    if names:
        return names[0]
    raise RuntimeError("no notify track on %s and cannot create one" % m.get_name())


def add_state_window(m, cls, start, end, what, track=TRACK_NAME):
    assert_allowed(m)
    duration = end - start
    if duration < MIN_WINDOW_DURATION:
        raise RuntimeError("%s window degenerate on %s (%.3f..%.3f s)"
                           % (what, m.get_name(), start, end))
    tr = ensure_track(m, track)
    inst = API["add_state"](m, tr, float(start), float(duration), cls)
    if inst is None:
        inst = find_instance(m, cls.get_name() if hasattr(cls, "get_name") else str(cls))
    if inst is None:
        raise RuntimeError("add_animation_notify_state_event returned None for "
                           "%s on %s" % (what, m.get_name()))
    log("  %-28s %s @ %.3f..%.3f s" % (m.get_name(), what, start, end))
    return inst


def add_point_notify(m, cls, time, what):
    assert_allowed(m)
    if API.get("add_evt") is None:
        raise StepSkip("add_animation_notify_event missing -- %s must be "
                       "placed by hand" % what)
    tr = ensure_track(m)
    created = API["add_evt"](m, tr, float(time), cls)
    if created is None:
        raise RuntimeError("add_animation_notify_event returned None for %s on %s"
                           % (what, m.get_name()))
    log("  %-28s %s @ %.3f s" % (m.get_name(), what, time))


def set_verified(inst, prop, value, what):
    """Instanced-UObject write + re-read verify -- the ONLY trusted write."""
    inst.set_editor_property(prop, value)
    back = inst.get_editor_property(prop)
    if isinstance(value, unreal.Object):
        ok = back is not None and back.get_path_name() == value.get_path_name()
    elif isinstance(value, float):
        ok = abs(float(back) - value) < 0.01
    else:
        ok = str(back) == str(value)
    if not ok:
        raise RuntimeError("%s: wrote %s=%r but read back %r" % (what, prop, value, back))


# ---------------------------------------------------------------------------
# Montage creation + slot enforcement
# ---------------------------------------------------------------------------

def montage_slot_names(m):
    try:
        tracks = m.get_editor_property("slot_anim_tracks")
        return [str(t.get_editor_property("slot_name")) for t in (tracks or [])]
    except Exception as exc:
        warn("could not read slot_anim_tracks on %s: %s" % (m.get_name(), exc))
        return []


def ensure_slot(m, want):
    """Slot write via the fix_montage_slots.py PROVEN pattern: element edit +
    WHOLE-ARRAY set-back + re-read verify. Failure -> aggregated manual note."""
    names = montage_slot_names(m)
    if names and all(n == want for n in names):
        return True
    if len(names) != 1:
        _SLOT_MANUAL.append("%s (has %d slot tracks: %s -> want %s)"
                            % (m.get_name(), len(names), ", ".join(names) or "?", want))
        return False
    try:
        tracks = m.get_editor_property("slot_anim_tracks")
        tracks[0].set_editor_property("slot_name", want)
        m.set_editor_property("slot_anim_tracks", tracks)
        check = str(m.get_editor_property("slot_anim_tracks")[0]
                    .get_editor_property("slot_name"))
        if check != want:
            raise RuntimeError("write did not stick (still '%s')" % check)
        log("  %-28s slot %s -> %s" % (m.get_name(), names[0], want))
        return True
    except Exception as exc:
        _SLOT_MANUAL.append("%s ('%s' -> '%s': %s)" % (m.get_name(), names[0], want, exc))
        return False


def create_montage(dest_dir, name, seq, skeleton, want_slot):
    """Create dest_dir/name from AnimSequence seq (idempotent; golem-script
    pattern). Slot enforced via ensure_slot. Returns the montage."""
    dst_path = "%s/%s" % (dest_dir, name)
    if unreal.EditorAssetLibrary.does_asset_exist(dst_path):
        m = unreal.EditorAssetLibrary.load_asset(dst_path)
        if not isinstance(m, unreal.AnimMontage):
            raise RuntimeError("%s exists but is %s, not AnimMontage -- delete "
                               "it and re-run" % (dst_path, type(m).__name__))
        if not skeleton_matches(m, skeleton):
            raise RuntimeError("%s exists but targets the WRONG skeleton -- "
                               "delete it and re-run" % dst_path)
        log("  %s already exists -- reusing (idempotent)" % dst_path)
        if ensure_slot(m, want_slot):
            force_save(m)
        return m

    unreal.EditorAssetLibrary.make_directory(dest_dir)
    factory = unreal.AnimMontageFactory()
    skel_prop = set_first_prop(factory, ("target_skeleton", "skeleton"), skeleton)
    src_prop = set_first_prop(factory, ("source_animation", "source_anim",
                                        "anim_sequence"), seq)
    if src_prop is None:
        manual("AnimMontageFactory has no source-animation input in this build "
               "-- create %s by hand from %s (right-click -> Create -> "
               "AnimMontage, slot %s), then re-run." % (name, seq.get_name(), want_slot))
        raise StepSkip("montage-from-sequence not scriptable on this build")
    if skel_prop is None:
        log("  factory skeleton property missing -- relying on source_animation")
    m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, dest_dir, unreal.AnimMontage, factory)
    if m is None:
        raise RuntimeError("create_asset returned None for %s" % dst_path)
    if not skeleton_matches(m, skeleton):
        raise RuntimeError("created %s but its skeleton is wrong -- factory "
                           "ignored the inputs" % dst_path)
    ensure_slot(m, want_slot)
    force_save(m)
    log("  created %s from %s (slot(s) %s)"
        % (name, seq.get_name(), ",".join(montage_slot_names(m))))
    return m


# ---------------------------------------------------------------------------
# Notify placement per plan section E
# ---------------------------------------------------------------------------

def apply_damage_window(m, frac):
    """ANS_DealDamage over frac of the montage + instance trace props
    (idempotent: existing window gets its props refreshed only)."""
    cls = require_notify_class(CLS_DEAL_DAMAGE)
    inst = find_instance(m, CLS_DEAL_DAMAGE)
    if inst is None:
        length = montage_length(m)
        inst = add_state_window(m, cls, frac[0] * length, frac[1] * length,
                                CLS_DEAL_DAMAGE)
    else:
        log("  %-28s already has %s -- refreshing props only" % (m.get_name(), CLS_DEAL_DAMAGE))
    for prop, val in DMG_INSTANCE_PROPS.items():
        set_verified(inst, prop, val, m.get_name() + "." + CLS_DEAL_DAMAGE)
    # re-read through the montage (instance edits proven to stick, but verify)
    fresh = find_instance(m, CLS_DEAL_DAMAGE)
    if fresh is None:
        raise RuntimeError("%s: damage instance vanished after prop set" % m.get_name())
    for prop, val in DMG_INSTANCE_PROPS.items():
        if abs(float(fresh.get_editor_property(prop)) - val) > 0.01:
            raise RuntimeError("%s: %s did NOT stick" % (m.get_name(), prop))


def apply_cancel_window(m):
    """ANS_CancelWindow from dmg-end+0.05 to 85% (hero lights only)."""
    cls = require_notify_class(CLS_CANCEL)
    if has_notify_class(m, CLS_CANCEL):
        log("  %-28s already has %s -- skipped" % (m.get_name(), CLS_CANCEL))
        return
    window = deal_damage_window(m)
    if window is None:
        raise RuntimeError("%s has no ANS_DealDamage window to anchor the "
                           "cancel window" % m.get_name())
    length = montage_length(m)
    start = window[1] + CANCEL_GAP_AFTER_DAMAGE
    end = CANCEL_END_FRACTION * length
    if start >= end - MIN_WINDOW_DURATION:
        warn("  %-28s no room for a cancel window (dmg ends %.3f of %.3f s)"
             % (m.get_name(), window[1], length))
        return
    add_state_window(m, cls, start, end, CLS_CANCEL)


def apply_restore_rate(m):
    """AN_RestoreRate at the dmg-window start (the 'Active' boundary --
    place_feel_notifies.py step-6 anchor rule)."""
    cls = require_notify_class(CLS_RESTORE)
    if has_notify_class(m, CLS_RESTORE):
        log("  %-28s already has %s -- skipped" % (m.get_name(), CLS_RESTORE))
        return
    window = deal_damage_window(m)
    if window is None:
        raise RuntimeError("%s has no ANS_DealDamage window to anchor "
                           "AN_RestoreRate" % m.get_name())
    add_point_notify(m, cls, window[0], CLS_RESTORE)


def apply_hyper_armor(m):
    """ANS_HyperArmor over the dmg window +-0.1 s (never the windup)."""
    cls = require_notify_class(CLS_HYPER)
    if has_notify_class(m, CLS_HYPER):
        log("  %-28s already has %s -- skipped" % (m.get_name(), CLS_HYPER))
        return
    window = deal_damage_window(m)
    if window is None:
        raise RuntimeError("%s has no ANS_DealDamage window to anchor "
                           "hyper-armor" % m.get_name())
    length = montage_length(m)
    add_state_window(m, cls, max(0.0, window[0] - HYPER_ARMOR_PAD),
                     min(length, window[1] + HYPER_ARMOR_PAD), CLS_HYPER)


def _trail_configured(inst, ns):
    cur = None
    for cand in ("template", "niagara_system", "system", "niagara_system_asset"):
        try:
            cur = inst.get_editor_property(cand)
            break
        except Exception:
            continue
    return cur is not None and cur.get_path_name() == ns.get_path_name()


def apply_trail(m, ns, socket):
    """TimedNiagaraEffect over the dmg window +-0.1 s (equip_weapons config)."""
    cls = ST.get("timed_niagara_cls")
    if cls is None or ns is None:
        manual("%s: slash trail not placed (TimedNiagaraEffect class or the "
               "Niagara system unavailable) -- add by hand: notify state "
               "TimedNiagaraEffect over the damage window, Template=%s, "
               "Socket=%s." % (m.get_name(), ns.get_name() if ns else "NS_SlashTrail_*", socket))
        return
    existing = find_instance(m, TIMED_NIAGARA_KEYWORD)
    if existing is not None:
        if _trail_configured(existing, ns):
            log("  %-28s already has a configured trail -- skipped" % m.get_name())
            return
        inst = existing
        log("  %-28s refreshing an unconfigured trail" % m.get_name())
    else:
        window = deal_damage_window(m)
        if window is None:
            warn("  %-28s no dmg window -- trail not placed" % m.get_name())
            return
        length = montage_length(m)
        inst = add_state_window(m, cls, max(0.0, window[0] - TRAIL_PAD),
                                min(length, window[1] + TRAIL_PAD),
                                TIMED_NIAGARA_KEYWORD, track=FX_TRACK_NAME)
    tprop = None
    for cand in ("template", "niagara_system", "system", "niagara_system_asset"):
        try:
            inst.get_editor_property(cand)
            tprop = cand
            break
        except Exception:
            continue
    if tprop is None:
        raise RuntimeError("%s: no template-ish property on %s"
                           % (m.get_name(), inst.get_class().get_name()))
    set_verified(inst, tprop, ns, m.get_name() + ".trail")
    try:
        set_verified(inst, "socket_name", socket, m.get_name() + ".trail")
    except Exception as exc:
        warn("  %s: socket_name not set (%s)" % (m.get_name(), exc))
    try:
        set_verified(inst, "destroy_at_end", True, m.get_name() + ".trail")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Blueprint plumbing (SCS walk + CDO fallback + fresh-spawn verify)
# ---------------------------------------------------------------------------

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


def find_component_templates(bp, class_keyword):
    """All live component templates on a BP whose class name contains
    class_keyword. SCS walk first (BP-added components never exist on the
    CDO), then the generated-class CDO (C++-added components)."""
    out = []
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
                    out.append(obj)
    except Exception as exc:
        log("SCS walk unavailable (%s) -- trying the CDO" % exc)
    if not out:
        try:
            gen = _generated_class(bp, "")
            cdo = unreal.get_default_object(gen) if gen is not None else None
            if cdo is not None:
                for comp in list(cdo.get_components_by_class(unreal.ActorComponent)):
                    if class_keyword in str(comp.get_class().get_name()):
                        out.append(comp)
        except Exception:
            pass
    return out


def compile_and_save_bp(bp):
    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("compile_blueprint failed (%s) -- continuing to save" % exc)
    force_save(bp)


def spawn_and_check(bp, bp_path, checks):
    """Fresh-spawn ASSERT (integrate_golem_minion step-7 pattern). checks:
    [(label, fn(actor)->bool)]. Returns (True|False|None, why)."""
    gen_cls = _generated_class(bp, "%s.%s_C" % (bp_path, bp_path.rsplit("/", 1)[-1]))
    if gen_cls is None:
        return None, "no resolvable generated class"
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    inst = None
    try:
        inst = actors.spawn_actor_from_class(
            gen_cls, unreal.Vector(0.0, 0.0, -5000.0), unreal.Rotator(0.0, 0.0, 0.0))
    except Exception as exc:
        return None, "throwaway spawn unavailable (%s) -- no level open?" % exc
    if inst is None:
        return None, "throwaway spawn returned None -- no level open?"
    try:
        failed = []
        for label, fn in checks:
            ok = False
            try:
                ok = bool(fn(inst))
            except Exception as exc:
                warn("  spawn-check '%s' raised: %s" % (label, exc))
            if not ok:
                failed.append(label)
        if failed:
            return False, "unset on a fresh instance: %s" % ", ".join(failed)
        return True, "verified on a fresh instance: %s" % \
            ", ".join(label for label, _fn in checks)
    finally:
        try:
            actors.destroy_actor(inst)
        except Exception:
            pass


def get_component_on_actor(actor, short_class_name):
    cls = load_game_class(short_class_name)
    if cls is None:
        return None
    try:
        return actor.get_component_by_class(cls)
    except Exception:
        return None


def weapon_socket_for(bp_path):
    """Trail socket: read the WeaponMesh template's attach socket if the equip
    script already placed one; else 'hand_r' (its own fallback)."""
    bp = load_asset_if_exists(bp_path)
    if bp is not None:
        for tmpl in find_component_templates(bp, "StaticMeshComponent"):
            try:
                if "WeaponMesh" not in str(tmpl.get_name()):
                    continue
                sock = str(tmpl.get_editor_property("attach_socket_name"))
                if sock and sock != "None":
                    return sock
            except Exception:
                continue
    return SOCKET_FALLBACK


# ---------------------------------------------------------------------------
# CombatAnimConfig data assets
# ---------------------------------------------------------------------------

def build_attack_entry(montage, dmg, dtype, blend_in, play_rate, hit_stop, shake):
    entry = unreal.AttackAnimData()
    entry.set_editor_property("montage", montage)
    entry.set_editor_property("damage_amount", float(dmg))
    entry.set_editor_property("damage_type", dtype)
    entry.set_editor_property("blend_in_time", float(blend_in))
    entry.set_editor_property("play_rate", float(play_rate))
    entry.set_editor_property("hit_stop_duration", float(hit_stop))
    entry.set_editor_property("camera_shake_scale", float(shake))
    return entry


def _entry_matches(entry, montage, dmg, dtype):
    try:
        mont = entry.get_editor_property("montage")
        return (mont is not None
                and pkg_of(mont) == pkg_of(montage)
                and abs(float(entry.get_editor_property("damage_amount")) - dmg) < 0.01
                and str(entry.get_editor_property("damage_type")) == dtype)
    except Exception:
        return False


def ensure_combat_config(da_path, rows):
    """Create-or-update a CombatAnimConfig at da_path with rows =
    [(montage, dmg, dtype, blend_in, play_rate, hit_stop, shake)]. WHOLE-ARRAY
    combo_chain set + re-read verify (never element write-back)."""
    if not hasattr(unreal, "AttackAnimData"):
        raise StepSkip("unreal.AttackAnimData binding missing (GAME_CORE module "
                       "not loaded in this editor session)")
    cfg_cls = load_game_class("CombatAnimConfig")
    if cfg_cls is None:
        raise StepSkip("/Script/GAME_CORE.CombatAnimConfig not compiled")

    da = load_asset_if_exists(da_path)
    if da is None:
        dest_dir, name = da_path.rsplit("/", 1)
        unreal.EditorAssetLibrary.make_directory(dest_dir)
        factory = unreal.DataAssetFactory()
        if set_first_prop(factory, ("data_asset_class",), cfg_cls) is None:
            manual("DataAssetFactory has no data_asset_class in this build -- "
                   "create %s by hand (right-click -> Misc -> Data Asset -> "
                   "CombatAnimConfig), then re-run." % da_path)
            raise StepSkip("DataAsset creation not scriptable on this build")
        da = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            name, dest_dir, None, factory)
        if da is None:
            raise RuntimeError("create_asset returned None for %s" % da_path)
        log("  created %s" % da_path)
    if "CombatAnimConfig" not in str(da.get_class().get_name()):
        raise RuntimeError("%s exists but is a %s, not CombatAnimConfig -- "
                           "delete it and re-run" % (da_path, da.get_class().get_name()))

    chain = list(da.get_editor_property("combo_chain") or [])
    if (len(chain) == len(rows)
            and all(_entry_matches(chain[i], rows[i][0], rows[i][1], rows[i][2])
                    for i in range(len(rows)))):
        log("  %s combo_chain already correct (idempotent)" % da.get_name())
        return da

    new_chain = [build_attack_entry(*row) for row in rows]
    da.set_editor_property("combo_chain", new_chain)
    check = list(da.get_editor_property("combo_chain") or [])
    if (len(check) != len(rows)
            or not all(_entry_matches(check[i], rows[i][0], rows[i][1], rows[i][2])
                       for i in range(len(rows)))):
        raise RuntimeError("%s: combo_chain did NOT stick after whole-array set"
                           % da.get_name())
    force_save(da)
    log("  %s combo_chain -> %d entr%s (re-read verified)"
        % (da.get_name(), len(check), "y" if len(check) == 1 else "ies"))
    return da


# ---------------------------------------------------------------------------
# Step 1: resolve skeletons
# ---------------------------------------------------------------------------

def step1_skeletons():
    # Hero/boss skeleton (SK_UEFN_Mannequin) resolved from an existing
    # retargeted asset rather than a hardcoded mesh path.
    probe_paths = [BOSS_DIR + "/Attack_01_Seq"]
    if unreal.EditorAssetLibrary.does_directory_exist(RETARGET_DIR + "/Combo_01"):
        for p in unreal.EditorAssetLibrary.list_assets(RETARGET_DIR + "/Combo_01",
                                                       recursive=True):
            probe_paths.append(str(p).split(".")[0])
            break
    for path in probe_paths:
        asset = load_asset_if_exists(path)
        if asset is None:
            continue
        try:
            skel = asset.get_editor_property("skeleton")
        except Exception:
            skel = None
        if skel is not None:
            ST["hero_skel"] = skel
            break
    if ST["hero_skel"] is None:
        raise RuntimeError("could not resolve the hero/boss skeleton from any "
                           "existing retargeted asset (probed: %s)" % ", ".join(probe_paths))

    golem = load_asset_if_exists(GOLEM_SKEL_PATH)
    if isinstance(golem, unreal.Skeleton):
        ST["golem_skel"] = golem
    else:
        warn("golem skeleton missing at %s -- golem groups will SKIP" % GOLEM_SKEL_PATH)
    return "hero/boss skel=%s, golem skel=%s" % (
        ST["hero_skel"].get_name(),
        ST["golem_skel"].get_name() if ST["golem_skel"] else "MISSING")


# ---------------------------------------------------------------------------
# Step 2: discover retargeted sequences (fuzzy -- batch outputs are
# PREFIX + source-name, so match by content not exact path)
# ---------------------------------------------------------------------------

def _sequences_in(directory, skeleton):
    if not unreal.EditorAssetLibrary.does_directory_exist(directory):
        return []
    out = []
    for obj_path in unreal.EditorAssetLibrary.list_assets(directory, recursive=True):
        seq = unreal.EditorAssetLibrary.load_asset(obj_path)
        gc_tick()
        if isinstance(seq, unreal.AnimSequence) and \
                (skeleton is None or skeleton_matches(seq, skeleton)):
            out.append(seq)
    return sorted(out, key=lambda s: s.get_name().lower())


def _single_part(seqs, *keywords, exclude=()):
    """Pick ONE sequence matching all keywords (and NONE of `exclude`),
    preferring a combined take (no start/loop/end suffix), then 'start'.
    Returns (seq, multipart_names)."""
    hits = [s for s in seqs
            if all(k in s.get_name().lower() for k in keywords)
            and not any(x in s.get_name().lower() for x in exclude)]
    if not hits:
        return None, []
    whole = [s for s in hits
             if not re.search(r"start|loop|end|_in\b|_out\b", s.get_name(), re.I)]
    if whole:
        return whole[0], [s.get_name() for s in hits]
    starts = [s for s in hits if "start" in s.get_name().lower()]
    return (starts[0] if starts else hits[0]), [s.get_name() for s in hits]


def step2_discover():
    found, missing = [], []

    # setup_retargeters.py's Fighter batch lands FTR_* sequences flat in
    # FIGHTER_RT_DIR -- scan it alongside each group's legacy dir (the
    # regexes below all search(), so the FTR_ prefix is tolerated).
    fighter_seqs = _sequences_in(FIGHTER_RT_DIR, ST["hero_skel"])

    # A1 Flurry: 4 step sequences in Combo_05 (or the Fighter out_folder).
    flurry_seqs = _sequences_in(FLURRY_DIR, ST["hero_skel"]) + fighter_seqs
    for i in (1, 2, 3, 4):
        pat = re.compile(r"combo[_\-]?05\D*%d(_seq)?$" % i, re.I)
        step_hits = [s for s in flurry_seqs if pat.search(s.get_name())]
        if step_hits:
            ST["seqs"]["flurry%d" % i] = step_hits[0]
    got = sum(1 for i in (1, 2, 3, 4) if "flurry%d" % i in ST["seqs"])
    if got == 4:
        found.append("Flurry(4/4)")
    else:
        missing.append("Flurry %d/4 (dirs %s + %s have %d seqs: %s)"
                       % (got, FLURRY_DIR, FIGHTER_RT_DIR, len(flurry_seqs),
                          ", ".join(s.get_name() for s in flurry_seqs) or "<none>"))
        for i in (1, 2, 3, 4):
            ST["seqs"].pop("flurry%d" % i, None)

    # A2 Breaker: exact existing sequences (no retarget needed).
    breaker_ok = True
    for src_path, _n, _d, _t, _b, _p, _h, _s, _f in BREAKER_ROWS:
        seq = load_asset_if_exists(src_path)
        if not isinstance(seq, unreal.AnimSequence):
            breaker_ok = False
            missing.append("Breaker source missing: %s" % src_path)
        else:
            ST["seqs"][src_path] = seq
    if breaker_ok:
        found.append("Breaker(3/3)")

    # A3 Hit_Heavy.
    hit_seqs = _sequences_in(HIT_DIR, ST["hero_skel"]) + fighter_seqs
    hh, hh_all = _single_part(hit_seqs, "hit", "heavy")
    if hh is not None:
        ST["seqs"]["hit_heavy"] = hh
        found.append("Hit_Heavy(%s of %d)" % (hh.get_name(), len(hh_all)))
    else:
        missing.append("Hit_Heavy (dirs %s + %s have %d seqs)"
                       % (HIT_DIR, FIGHTER_RT_DIR, len(hit_seqs)))

    # Parry: parked only -- log if present.
    parry = [s for s in hit_seqs + _sequences_in(PARRY_DIR, ST["hero_skel"])
             if "parry" in s.get_name().lower()]
    if parry:
        log("Parry_L/R found (%s) -- PARKED, no wiring target until "
            "CombatComponent gains a parry-visual slot (per plan)."
            % ", ".join(s.get_name() for s in parry))

    # B Boss: new Fighter-pack sequences inside BOSS_DIR or the Fighter
    # out_folder (the existing Attack_0X_Seq family is NOT matched by these
    # keywords). 'charge' must EXCLUDE 'air': the pack ships both
    # Charge_Attack_* and Charge_Air_Attack_* families, and the
    # case-insensitive sort would otherwise pick the AIR wind-up first.
    boss_seqs = _sequences_in(BOSS_DIR, ST["hero_skel"]) + fighter_seqs
    for key, kws, excl in (("charge", ("charge",), ("air",)),
                           ("slam", ("air", "floor"), ()),
                           ("run", ("run", "attack"), ())):
        seq, parts = _single_part(boss_seqs, *kws, exclude=excl)
        if seq is not None:
            ST["seqs"][key] = seq
            ST["seqs"][key + "_parts"] = parts
    got_boss = [k for k, _n, _h in BOSS_ROWS if k in ST["seqs"]]
    if got_boss:
        found.append("Boss(%d/3: %s)" % (len(got_boss), ",".join(got_boss)))
    if len(got_boss) < 3:
        missing.append("Boss new attacks %d/3 (dirs %s + %s; want Charge_Attack"
                       " / Attack_Air_to_Floor / Run_Attack retargets)"
                       % (len(got_boss), BOSS_DIR, FIGHTER_RT_DIR))

    # C Golem (heuristics like integrate_golem_minion step 2).
    if ST["golem_skel"] is not None:
        gseqs = _sequences_in(GOLEM_RT_DIR, ST["golem_skel"])
        attacks = [s for s in gseqs
                   if re.search(r"attack|punch|slam|smash|swing", s.get_name(), re.I)]
        hits = [s for s in gseqs
                if re.search(r"hit", s.get_name(), re.I)
                and not re.search(r"death", s.get_name(), re.I)]
        deaths = [s for s in gseqs if re.search(r"death|die|knock_down", s.get_name(), re.I)]
        if attacks:
            ST["golem_seqs"]["attack1"] = attacks[0]
        if len(attacks) > 1:
            ST["golem_seqs"]["attack2"] = attacks[1]
        if hits:
            # AM_GLM_Hit_F is the FRONT flinch -- prefer a *_Hit_F_* source
            # over the alphabetically-first (GOL_Hit_B_Seq sorts before it).
            front = [s for s in hits if re.search(r"hit_f", s.get_name(), re.I)]
            ST["golem_seqs"]["hit"] = (front or hits)[0]
        if deaths:
            ST["golem_seqs"]["death"] = deaths[0]
    if ST["golem_seqs"].get("attack1"):
        found.append("Golem(%s)" % ",".join(sorted(ST["golem_seqs"].keys())))
    else:
        missing.append("Golem (dir %s -- Batch 3 UEFN->Golem not run?)" % GOLEM_RT_DIR)

    if missing:
        warn("=" * 70)
        warn("MISSING RETARGET OUTPUT -- these groups SKIP until the batches run:")
        for msg in missing:
            warn("  - " + msg)
        warn("Run the retarget batches (Tools/setup_retargeters.py -- Fighter "
             "pair -> %s, StoneGolem pair -> %s; or Tools/batch_retarget_anims"
             ".py per the plan's section D), then RE-RUN this script -- it is "
             "idempotent." % (FIGHTER_RT_DIR, GOLEM_RT_DIR))
        warn("=" * 70)
        manual("Retarget batches incomplete: %s. Run setup/batch retargeting "
               "(plan section D), then re-run Tools/wire_new_animations.py."
               % "; ".join(missing))
    if not found:
        raise RuntimeError("NO wiring group has its sequences yet -- nothing "
                           "to do (see the missing list above)")
    return "found: %s%s" % (", ".join(found),
                            ("; missing: %d group(s)" % len(missing)) if missing else "")


# ---------------------------------------------------------------------------
# Steps 3-4: hero chains (montages + notifies + trails + DA)
# ---------------------------------------------------------------------------

def _build_hero_chain(rows, dest_dir, seq_lookup, group):
    """Create montages + notifies + trails for one hero chain. Returns
    [(montage, dmg, dtype, blend, rate, stop, shake)] in chain order."""
    socket = weapon_socket_for(BP_HERO_PATH)
    out = []
    for seq_key, name, dmg, dtype, blend, rate, stop, shake, finisher in rows:
        seq = seq_lookup(seq_key)
        if seq is None:
            raise StepSkip("%s: sequence for %s missing (step 2)" % (group, name))
        m = create_montage(dest_dir, name, seq, ST["hero_skel"], SLOT_HERO_BOSS)
        apply_damage_window(m, HERO_FINISHER_DMG if finisher else HERO_LIGHT_DMG)
        if not finisher:
            apply_cancel_window(m)
        apply_trail(m, ST["ns_hero"], socket)
        force_save(m)
        out.append((m, dmg, dtype, blend, rate, stop, shake))
        WIRED["hero"] += 1
    return out


def step3_flurry():
    if "flurry1" not in ST["seqs"]:
        raise StepSkip("Flurry sequences not retargeted yet (Batch 1) -- "
                       "Combo_05 group gated off; re-run after the batch")
    rows = _build_hero_chain(FLURRY_ROWS, FLURRY_DIR,
                             lambda k: ST["seqs"].get(k), "Flurry")
    ST["flurry_montages"] = [r[0] for r in rows]
    ST["da_flurry"] = ensure_combat_config(DA_FLURRY_PATH, rows)
    return "4 montages + %s ready" % DA_FLURRY_PATH.rsplit("/", 1)[-1]


def step4_breaker():
    for src_path, _n, _d, _t, _b, _p, _h, _s, _f in BREAKER_ROWS:
        if src_path not in ST["seqs"]:
            raise StepSkip("Breaker source sequences missing under %s -- "
                           "unexpected (these predate this plan); check step 2"
                           % BOSS_DIR)
    rows = _build_hero_chain(BREAKER_ROWS, HEAVY_DIR,
                             lambda k: ST["seqs"].get(k), "Breaker")
    ST["breaker_montages"] = [r[0] for r in rows]
    ST["da_breaker"] = ensure_combat_config(DA_BREAKER_PATH, rows)
    return "3 montages + %s ready" % DA_BREAKER_PATH.rsplit("/", 1)[-1]


def step5_hit_heavy():
    seq = ST["seqs"].get("hit_heavy")
    if seq is None:
        raise StepSkip("Hit_Heavy not retargeted yet (Batch 1) -- re-run after")
    m = create_montage(HIT_DIR, "AM_Hit_Heavy", seq, ST["hero_skel"], SLOT_DEFAULT)
    force_save(m)
    ST["hit_heavy_montage"] = m
    WIRED["hero"] += 1
    return "AM_Hit_Heavy ready (no notifies -- reaction montage)"


# ---------------------------------------------------------------------------
# Step 6: boss montages
# ---------------------------------------------------------------------------

def step6_boss_montages():
    available = [(k, n, h) for k, n, h in BOSS_ROWS if k in ST["seqs"]]
    if not available:
        raise StepSkip("no new boss sequences retargeted yet (Batch 1) -- "
                       "re-run after the batch")
    socket = weapon_socket_for(BP_BOSS_PATH)
    made = []
    for key, name, heavy in available:
        try:
            seq = ST["seqs"][key]
            parts = ST["seqs"].get(key + "_parts", [])
            if len(parts) > 1:
                manual("%s was built from '%s' ONLY -- the retarget produced "
                       "%d parts (%s). Compose the full start+loop+end montage "
                       "by hand in the montage editor (drag the parts in order, "
                       "rename the wind-up section to 'Windup'), then re-run: "
                       "the notify pass is idempotent."
                       % (name, seq.get_name(), len(parts), ", ".join(parts)))
            m = create_montage(BOSS_DIR, name, seq, ST["hero_skel"], SLOT_HERO_BOSS)
            apply_damage_window(m, BOSS_DMG)
            apply_restore_rate(m)
            if heavy:
                apply_hyper_armor(m)
            apply_trail(m, ST["ns_boss"], socket)
            force_save(m)
            ST["boss_montages"][name] = m
            made.append(name + ("(H)" if heavy else ""))
            WIRED["boss"] += 1
        except StepSkip:
            raise
        except Exception as exc:  # noqa: BLE001 - per-item isolation
            warn("  %s FAILED: %s" % (name, exc))
            warn(traceback.format_exc())
    if not made:
        raise RuntimeError("every boss montage failed -- see per-item logs")
    manual("New AM_BOSS_* montages have NO 'Windup' montage section (sections "
           "are not python-authorable -- struct-array ban). Until you rename/"
           "add the section in the montage editor, FallbackWindupSectionLength "
           "(0.4 s) drives the telegraph timing and the ANS_DealDamage window "
           "at 50-65%% is an ESTIMATE -- retime it against the actual swing.")
    return "created/updated: %s" % ", ".join(made)


# ---------------------------------------------------------------------------
# Steps 7-8: golem montages + DA_GolemCombat
# ---------------------------------------------------------------------------

def step7_golem_montages():
    if ST["golem_skel"] is None or not ST["golem_seqs"].get("attack1"):
        raise StepSkip("golem retargets not present (Batch 3 UEFN->Golem) -- "
                       "re-run after; dir: %s" % GOLEM_RT_DIR)
    plan = [("attack1", "AM_GLM_Attack_01", True),
            ("attack2", "AM_GLM_Attack_02", True),
            ("hit", "AM_GLM_Hit_F", False),
            ("death", "AM_GLM_Death", False)]
    made = []
    for key, name, is_attack in plan:
        seq = ST["golem_seqs"].get(key)
        if seq is None:
            warn("  golem '%s' sequence missing -- %s skipped this run" % (key, name))
            continue
        try:
            m = create_montage(GOLEM_RT_DIR, name, seq, ST["golem_skel"], SLOT_DEFAULT)
            if is_attack:
                apply_damage_window(m, GOLEM_DMG)
            force_save(m)
            ST["golem_montages"][name] = m
            made.append(name)
            WIRED["golem"] += 1
        except StepSkip:
            raise
        except Exception as exc:  # noqa: BLE001
            warn("  %s FAILED: %s" % (name, exc))
            warn(traceback.format_exc())
    if not made:
        raise RuntimeError("every golem montage failed -- see per-item logs")
    return "created/updated: %s" % ", ".join(made)


def step8_golem_da():
    a1 = ST["golem_montages"].get("AM_GLM_Attack_01")
    if a1 is None:
        raise StepSkip("no golem attack montage (step 7) -- DA_GolemCombat "
                       "deferred to the re-run")
    rows = []
    for name, dmg, dtype in GOLEM_ROWS:
        m = ST["golem_montages"].get(name)
        if m is None:
            continue
        # golem feedback: opener-class numbers, montage-driven timing
        rows.append((m, dmg, dtype, 0.10, 1.0, 0.05 if dtype == "Light" else 0.10,
                     0.7 if dtype == "Light" else 1.0))
    ST["da_golem"] = ensure_combat_config(DA_GOLEM_PATH, rows)
    manual("DA_GolemCombat damage is deliberately pre-nerfed to 8/12 (minions "
           "must not out-hit the hero's opener). Re-running Tools/"
           "set_combo_damage.py will overwrite it to the 10/25 scheme -- "
           "re-run THIS script afterwards to restore, or exclude the golem DA.")
    return "%s with %d entr%s" % (DA_GOLEM_PATH.rsplit("/", 1)[-1], len(rows),
                                  "y" if len(rows) == 1 else "ies")


# ---------------------------------------------------------------------------
# Step 9: wire BP_NeuralHero (SideComboConfig / ForwardComboConfig /
#          HeavyHitReactions.HitFront)
# ---------------------------------------------------------------------------

def _prop_pkg(obj, prop):
    try:
        v = obj.get_editor_property(prop)
        return pkg_of(v) if v is not None else None
    except Exception:
        return None


def step9_wire_hero():
    if ST["da_flurry"] is None and ST["da_breaker"] is None and \
            ST["hit_heavy_montage"] is None:
        raise StepSkip("nothing hero-side got built this run -- no BP edit")
    bp = load_asset_if_exists(BP_HERO_PATH)
    if bp is None:
        raise StepSkip("%s not found" % BP_HERO_PATH)

    changed, applied, misses = False, [], []

    combats = find_component_templates(bp, "CombatComponent")
    combats = [c for c in combats
               if "CombatStateComponent" not in str(c.get_class().get_name())]
    if not combats:
        misses.append("CombatComponent template not reachable")
    else:
        combat = combats[0]
        for prop, da, label in (("side_combo_config", ST["da_flurry"], "Side=Flurry"),
                                ("forward_combo_config", ST["da_breaker"], "Forward=Breaker")):
            if da is None:
                continue
            if _prop_pkg(combat, prop) == pkg_of(da):
                applied.append(label + "(already)")
                continue
            if set_prop_if_exists(combat, prop, da, "BP_NeuralHero.CombatComponent"):
                if _prop_pkg(combat, prop) == pkg_of(da):
                    applied.append(label)
                    changed = True
                else:
                    misses.append("%s did not verify on re-read" % prop)
            else:
                misses.append(prop)

    if ST["hit_heavy_montage"] is not None:
        reacts = find_component_templates(bp, "HitReactionComponent")
        if not reacts:
            misses.append("HitReactionComponent template not reachable")
        else:
            react = reacts[0]
            try:
                # whole-STRUCT read-modify-write + verify (never field-poke a
                # returned struct copy and hope)
                heavy = react.get_editor_property("heavy_hit_reactions")
                cur = None
                try:
                    v = heavy.get_editor_property("hit_front")
                    cur = pkg_of(v) if v is not None else None
                except Exception:
                    pass
                if cur == pkg_of(ST["hit_heavy_montage"]):
                    applied.append("HeavyHitFront(already)")
                else:
                    heavy.set_editor_property("hit_front", ST["hit_heavy_montage"])
                    react.set_editor_property("heavy_hit_reactions", heavy)
                    back = react.get_editor_property("heavy_hit_reactions") \
                        .get_editor_property("hit_front")
                    if back is None or pkg_of(back) != pkg_of(ST["hit_heavy_montage"]):
                        raise RuntimeError("HeavyHitReactions.HitFront did not stick")
                    applied.append("HeavyHitFront=AM_Hit_Heavy")
                    changed = True
            except Exception as exc:
                misses.append("HeavyHitReactions.HitFront (%s)" % exc)

    if changed:
        compile_and_save_bp(bp)
        # compile may regenerate templates -- re-verify on a fresh spawn
        checks = []
        if ST["da_flurry"] is not None:
            checks.append(("SideComboConfig", lambda a: _prop_pkg(
                get_component_on_actor(a, "CombatComponent"), "side_combo_config")
                == pkg_of(ST["da_flurry"])))
        if ST["da_breaker"] is not None:
            checks.append(("ForwardComboConfig", lambda a: _prop_pkg(
                get_component_on_actor(a, "CombatComponent"), "forward_combo_config")
                == pkg_of(ST["da_breaker"])))
        if ST["hit_heavy_montage"] is not None:
            def _hh(a):
                r = get_component_on_actor(a, "HitReactionComponent")
                if r is None:
                    return False
                v = r.get_editor_property("heavy_hit_reactions") \
                     .get_editor_property("hit_front")
                return v is not None and pkg_of(v) == pkg_of(ST["hit_heavy_montage"])
            checks.append(("HeavyHitFront", _hh))
        verified, why = spawn_and_check(bp, BP_HERO_PATH, checks)
        if verified is None:
            raise StepSkip("BP_NeuralHero saved but NOT spawn-verified (%s) -- "
                           "treat as unconfirmed; applied: %s" % (why, ", ".join(applied)))
        if verified is False:
            raise RuntimeError("BP_NeuralHero ASSERT FAIL -- %s" % why)
    if misses:
        raise StepSkip("partially wired (%s) -- unreachable: %s"
                       % (", ".join(applied) or "nothing", "; ".join(misses)))
    manual("New hero montages use slot '%s' -- verify a swing is VISIBLE in "
           "PIE. If it plays invisibly the hero ABP has no '%s' slot node; "
           "either add the slot node or run Tools/fix_montage_slots.py "
           "(flips to DefaultSlot)." % (SLOT_HERO_BOSS, SLOT_HERO_BOSS))
    return "applied: %s%s" % (", ".join(applied) or "nothing new",
                              " (spawn-verified)" if changed else " (no change needed)")


# ---------------------------------------------------------------------------
# Step 10: wire BP_Boss (HeavyAttackMontages ∪ new heavies; AttackMontage
#           deliberately untouched -- single-slot C++, see BOSS_CPP_SPEC)
# ---------------------------------------------------------------------------

def step10_wire_boss():
    new_heavies = [ST["boss_montages"][n] for k, n, h in BOSS_ROWS
                   if h and n in ST["boss_montages"]]
    if not ST["boss_montages"]:
        raise StepSkip("no new boss montage was built this run -- no BP edit")
    bp = load_asset_if_exists(BP_BOSS_PATH)
    if bp is None:
        raise StepSkip("%s not found" % BP_BOSS_PATH)

    manual(BOSS_CPP_SPEC)

    if not new_heavies:
        return ("only AM_BOSS_RunAttack (yellow) built -- nothing to add to "
                "HeavyAttackMontages; C++ note emitted")

    comps = find_component_templates(bp, "BossActionComponent")
    if not comps:
        raise StepSkip("BossActionComponent template not reachable on BP_Boss "
                       "-- add %s to HeavyAttackMontages by hand"
                       % ", ".join(m.get_name() for m in new_heavies))
    comp = comps[0]
    try:
        existing = list(comp.get_editor_property("heavy_attack_montages") or [])
    except Exception as exc:
        raise RuntimeError("could not read heavy_attack_montages (%s)" % exc)
    existing_pkgs = {pkg_of(m) for m in existing if m is not None}
    to_add = [m for m in new_heavies if pkg_of(m) not in existing_pkgs]
    if not to_add:
        return "HeavyAttackMontages already contains the new heavies (idempotent)"

    merged = [m for m in existing if m is not None] + to_add
    wrote = False
    for value in (merged, set(merged)):
        try:
            comp.set_editor_property("heavy_attack_montages", value)
            wrote = True
            break
        except Exception:
            continue
    if not wrote:
        raise RuntimeError("heavy_attack_montages refused both list and set "
                           "assignment -- add %s by hand on BP_Boss"
                           % ", ".join(m.get_name() for m in to_add))
    back = {pkg_of(m) for m in
            list(comp.get_editor_property("heavy_attack_montages") or []) if m is not None}
    missing = [m.get_name() for m in to_add if pkg_of(m) not in back]
    if missing:
        raise RuntimeError("HeavyAttackMontages write did NOT stick for: %s"
                           % ", ".join(missing))
    compile_and_save_bp(bp)

    def _check(a):
        c = get_component_on_actor(a, "BossActionComponent")
        if c is None:
            return False
        got = {pkg_of(m) for m in
               list(c.get_editor_property("heavy_attack_montages") or []) if m is not None}
        return all(pkg_of(m) in got for m in to_add)
    verified, why = spawn_and_check(bp, BP_BOSS_PATH, [("HeavyAttackMontages", _check)])
    if verified is None:
        raise StepSkip("BP_Boss saved but NOT spawn-verified (%s)" % why)
    if verified is False:
        raise RuntimeError("BP_Boss ASSERT FAIL -- %s" % why)
    return ("added %s to HeavyAttackMontages (spawn-verified); AttackMontage "
            "untouched -- see the C++ MANUAL note"
            % ", ".join(m.get_name() for m in to_add))


# ---------------------------------------------------------------------------
# Step 11: wire BP_Minion (DA_GolemCombat + DeathMontage + Hit_F)
# ---------------------------------------------------------------------------

def step11_wire_golem():
    if ST["da_golem"] is None and not ST["golem_montages"]:
        raise StepSkip("no golem asset was built this run -- no BP edit")
    bp = load_asset_if_exists(BP_MINION_PATH)
    if bp is None:
        manual("BP_Minion missing at %s -- run Tools/build_arena_level.py / "
               "integrate_golem_minion.py first, then re-run this script."
               % BP_MINION_PATH)
        raise StepSkip("%s does not exist" % BP_MINION_PATH)
    gen_cls = _generated_class(bp, BP_MINION_PATH + ".BP_Minion_C")
    if gen_cls is None:
        raise RuntimeError("BP_Minion has no resolvable generated class")
    cdo = unreal.get_default_object(gen_cls)

    def _apply(target_cdo):
        applied, misses = [], []
        combat = None
        try:
            combat = target_cdo.get_editor_property("combat_component")
        except Exception:
            pass
        if combat is None:
            for c in find_component_templates(bp, "CombatComponent"):
                if "CombatStateComponent" not in str(c.get_class().get_name()):
                    combat = c
                    break
        if combat is None:
            misses.append("combat_component not reachable")
        else:
            if ST["da_golem"] is not None:
                if _prop_pkg(combat, "neutral_combo_config") == pkg_of(ST["da_golem"]):
                    applied.append("NeutralComboConfig(already)")
                elif set_prop_if_exists(combat, "neutral_combo_config",
                                        ST["da_golem"], "BP_Minion.CombatComponent") \
                        and _prop_pkg(combat, "neutral_combo_config") == pkg_of(ST["da_golem"]):
                    applied.append("NeutralComboConfig=DA_GolemCombat")
                else:
                    misses.append("neutral_combo_config")
            death = ST["golem_montages"].get("AM_GLM_Death")
            if death is not None:
                if _prop_pkg(combat, "death_montage") == pkg_of(death):
                    applied.append("DeathMontage(already)")
                elif set_prop_if_exists(combat, "death_montage", death,
                                        "BP_Minion.CombatComponent") \
                        and _prop_pkg(combat, "death_montage") == pkg_of(death):
                    applied.append("DeathMontage=AM_GLM_Death")
                else:
                    misses.append("death_montage")
        hit = ST["golem_montages"].get("AM_GLM_Hit_F")
        if hit is not None:
            react = None
            try:
                react = target_cdo.get_component_by_class(
                    load_game_class("HitReactionComponent"))
            except Exception:
                react = None
            if react is None:
                templates = find_component_templates(bp, "HitReactionComponent")
                react = templates[0] if templates else None
            if react is None:
                misses.append("HitReactionComponent not reachable")
            else:
                try:
                    light = react.get_editor_property("light_hit_reactions")
                    v = None
                    try:
                        v = light.get_editor_property("hit_front")
                    except Exception:
                        pass
                    if v is not None and pkg_of(v) == pkg_of(hit):
                        applied.append("LightHitFront(already)")
                    else:
                        light.set_editor_property("hit_front", hit)
                        react.set_editor_property("light_hit_reactions", light)
                        back = react.get_editor_property("light_hit_reactions") \
                            .get_editor_property("hit_front")
                        if back is None or pkg_of(back) != pkg_of(hit):
                            raise RuntimeError("write did not stick")
                        applied.append("LightHitFront=AM_GLM_Hit_F")
                except Exception as exc:
                    misses.append("LightHitReactions.HitFront (%s)" % exc)
        return applied, misses

    applied, misses = _apply(cdo)
    # compile can regenerate the CDO -- compile, re-apply, save (golem step-7)
    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("compile_blueprint failed (%s) -- continuing to save" % exc)
        gen_cls = _generated_class(bp, BP_MINION_PATH + ".BP_Minion_C") or gen_cls
        cdo = unreal.get_default_object(gen_cls)
        applied, misses = _apply(cdo)
    force_save(bp)

    checks = []
    if ST["da_golem"] is not None:
        checks.append(("NeutralComboConfig", lambda a: _prop_pkg(
            get_component_on_actor(a, "CombatComponent"), "neutral_combo_config")
            == pkg_of(ST["da_golem"])))
    death = ST["golem_montages"].get("AM_GLM_Death")
    if death is not None:
        checks.append(("DeathMontage", lambda a: _prop_pkg(
            get_component_on_actor(a, "CombatComponent"), "death_montage")
            == pkg_of(death)))
    verified, why = spawn_and_check(bp, BP_MINION_PATH, checks) \
        if checks else (True, "nothing spawn-checkable")
    if verified is None:
        raise StepSkip("BP_Minion saved but NOT spawn-verified (%s); applied: %s"
                       % (why, ", ".join(applied)))
    if verified is False:
        raise RuntimeError("BP_Minion ASSERT FAIL -- %s" % why)
    if misses:
        raise StepSkip("saved + verified for what applied (%s) but unreachable: %s"
                       % (", ".join(applied), "; ".join(misses)))
    return "applied: %s (%s)" % (", ".join(applied) or "nothing new", why)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STEPS = [
    ("0. Feature-detect notify API + trail assets", step0_detect_api),
    ("1. Resolve skeletons", step1_skeletons),
    ("2. Discover retargeted sequences (gated)", step2_discover),
    ("3. HERO Flurry: montages+notifies+trails+DA", step3_flurry),
    ("4. HERO Breaker: montages+notifies+trails+DA", step4_breaker),
    ("5. HERO AM_Hit_Heavy", step5_hit_heavy),
    ("6. BOSS montages: notifies+trails", step6_boss_montages),
    ("7. GOLEM montages: damage windows", step7_golem_montages),
    ("8. GOLEM DA_GolemCombat", step8_golem_da),
    ("9. Wire BP_NeuralHero + verify", step9_wire_hero),
    ("10. Wire BP_Boss heavies + verify", step10_wire_boss),
    ("11. Wire BP_Minion + verify", step11_wire_golem),
]

def _status_of(index):
    return STEP_RESULTS[index][1] if index < len(STEP_RESULTS) else "FAIL"


def main():
    log("=" * 70)
    log("wire_new_animations -- plan section E: montages / notifies / DAs / BPs")
    log("=" * 70)
    for i, (label, fn) in enumerate(STEPS):
        if i in (1, 2) and _status_of(0) == "FAIL":
            STEP_RESULTS.append((label, "SKIP", "step 0 failed"))
            continue
        if i >= 3 and (_status_of(1) != "PASS" or _status_of(2) == "FAIL"):
            STEP_RESULTS.append((label, "SKIP", "steps 1/2 did not pass"))
            continue
        run_step(label, fn)

    if _SLOT_MANUAL:
        manual("Montage slot writes that need the editor click (montage editor "
               "-> slot track header -> pick the slot -> Save): %s"
               % "; ".join(_SLOT_MANUAL))

    log("=" * 70)
    log("SUMMARY")
    for label, status, detail in STEP_RESULTS:
        log("  %-4s %-46s %s" % (status, label, detail))
    log("-" * 70)
    log("WIRED COUNTS: hero=%d montage(s), boss=%d, golem=%d"
        % (WIRED["hero"], WIRED["boss"], WIRED["golem"]))
    if MANUAL_NOTES:
        log("-" * 70)
        log("MANUAL FOLLOW-UPS (%d):" % len(MANUAL_NOTES))
        for note in MANUAL_NOTES:
            log("  MANUAL: " + note)
    else:
        log("No manual follow-ups.")
    log("Re-run safe: montages/notifies/DAs/BP props are reused, refreshed or "
        "skipped idempotently. Re-run after each retarget batch lands.")
    log("=" * 70)


main()
