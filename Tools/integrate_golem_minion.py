"""Swap BP_Minion from the mannequin placeholder to the Stone Golem pack.

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the 'Cmd' dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/integrate_golem_minion.py"
  (or Tools -> Execute Python Script... and pick this file)

What the Stone Golem pack ACTUALLY ships (scanned 2026-07-05):
  /Game/Stone_Golem/mesh/SKM_Stone_Golem            SkeletalMesh
  /Game/Stone_Golem/mesh/SK_Stone_Golem_Skeleton    Skeleton
  /Game/Stone_Golem/mesh/PA_Stone_Golem_PhysicsAsset
  /Game/Stone_Golem/demo/animations/ThirdPerson*    7 AnimSequences -- ALL
        target SK_Stone_Golem_Skeleton (Idle/Walk/Run/Jump_Start/Loop/End/Jump)
  NO attack anim. NO death anim. NO AnimBlueprint. (materials/textures/demo map)

So: locomotion is coverable in-pack; attack + death REQUIRE a retarget pass
(mannequin -> golem) first -- steps 3/4/6-entry0 degrade to a loud MANUAL
block until retargeted sequences exist, and this script is safe to RE-RUN
after the retarget to finish the job (idempotent throughout).

Steps (each isolated; PASS/FAIL/SKIP summary at the end):
  0. Resolve golem Skeleton + SkeletalMesh (type-checked, never prefix-trusted)
  1. Cap Stone_Golem pack textures at max_texture_size=2048 (VRAM budget)
  2. Inventory AnimSequences ON THE GOLEM SKELETON (asset registry +
     name heuristics: attack/punch/slam/smash | death/die | idle | walk/run)
  3. Create montages in /Game/Arena/Minions/: AM_Golem_Attack01 (+02),
     AM_Golem_Death via AnimMontageFactory (source_animation/target_skeleton
     feature-detected; slot verified == DefaultSlot by read-back)
  4. ANS_DealDamage window at 35%%-55%% on the golem attack montage(s),
     instance props trace_radius=60 / trace_forward_offset=150 (instanced-
     UObject edits -- the pattern proven to stick; verified by re-read)
  5. Golem AnimBlueprint: reuse one targeting the golem skeleton if any
     exists, else create the ASSET (AnimBlueprintFactory) -- the GRAPH is
     not python-authorable, so a click-level MANUAL recipe is printed
  6. DA_MinionCombo entry 0 -> AM_Golem_Attack01, 8 dmg, Light (whole-array
     rewrite -- NEVER element write-back -- verified by re-read)
  7. BP_Minion CDO: mesh=SKM_Stone_Golem, anim class=golem ABP, capsule from
     measured mesh bounds (logged), mesh scale 1.15, DeathMontage=AM_Golem_Death;
     compile + force-save + fresh-spawn ASSERT (build_arena_level 6k pattern)
  8. Summary incl. every MANUAL: line

HARD RULES honored:
  - struct-array element write-backs are NEVER used (whole-array set + verify)
  - every save is force-dirty + save_loaded_asset(only_if_is_dirty=False)
    + on-disk mtime verification (the place_feel_notifies save() pattern)
  - only /Game/Arena/Minions and /Game/Stone_Golem are ever written to
  - montage slot must be DefaultSlot (DefaultGroup) or it plays invisibly
"""

import os
import re
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[GolemMinion]"

GOLEM_DIR = "/Game/Stone_Golem"
GOLEM_TEX_DIR = GOLEM_DIR + "/textures"
GOLEM_SKM_PATH = GOLEM_DIR + "/mesh/SKM_Stone_Golem"
GOLEM_SKEL_PATH = GOLEM_DIR + "/mesh/SK_Stone_Golem_Skeleton"

MINION_DIR = "/Game/Arena/Minions"
BP_MINION_PATH = MINION_DIR + "/BP_Minion"
DA_COMBO_PATH = MINION_DIR + "/DA_MinionCombo"
ABP_NAME = "ABP_StoneGolem"
ABP_PATH = "%s/%s" % (MINION_DIR, ABP_NAME)

AM_ATTACK01 = "AM_Golem_Attack01"
AM_ATTACK02 = "AM_Golem_Attack02"
AM_DEATH = "AM_Golem_Death"

# The ONLY folders this script may mutate/save assets in.
ALLOWED_PREFIXES = (MINION_DIR + "/", GOLEM_DIR + "/")

# Extra roots scanned when the asset registry skeleton-tag path fails AND for
# retargeted output the user drops in later (re-run picks these up).
FALLBACK_SCAN_DIRS = [GOLEM_DIR, MINION_DIR, "/Game/Retargeted_Animations"]

MAX_TEXTURE_SIZE = 2048

# ANS_DealDamage window + instance props (ANS_DealDamage.h: TraceRadius,
# TraceForwardOffset -- python snake_case).
DMG_WINDOW_START_FRAC = 0.35
DMG_WINDOW_END_FRAC = 0.55
DMG_INSTANCE_PROPS = {"trace_radius": 60.0, "trace_forward_offset": 150.0}
TRACK_NAME = "FeelNotifies"  # same track name place_feel_notifies.py uses

# DA_MinionCombo entry 0 (FAttackAnimData reflected names, CombatAnimConfig.h)
ENTRY0_DAMAGE = 8.0
ENTRY0_TYPE = "Light"

# BP_Minion visuals
MESH_SCALE = 1.15
MESH_REL_YAW = -90.0           # standard content-forward -> +X convention
CAPSULE_RADIUS_MIN, CAPSULE_RADIUS_MAX = 34.0, 90.0

# Name heuristics (case-insensitive, on the asset name)
RE_ATTACK = re.compile(r"attack|punch|slam|smash|swing", re.I)
RE_DEATH = re.compile(r"death|die", re.I)
RE_IDLE = re.compile(r"idle", re.I)
RE_MOVE = re.compile(r"walk|run", re.I)

STEP_RESULTS = []   # (label, "PASS"/"FAIL"/"SKIP", detail)
MANUAL_NOTES = []   # every degraded sub-goal lands here as a "MANUAL:" line

# Shared state between steps
ST = {
    "skeleton": None,       # unreal.Skeleton (golem)
    "skm": None,            # unreal.SkeletalMesh (golem)
    "seq_attacks": [],      # golem-skeleton attack AnimSequences (sorted)
    "seq_death": None,
    "seq_idle": None,
    "seq_move": None,
    "am_attacks": [],       # created/reused AnimMontages
    "am_death": None,
    "anim_class": None,     # golem ABP generated class
    "abp_created_now": False,
    "da_combo": None,
    "capsule": None,        # (half_height, radius) actually applied
}


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def manual(msg):
    """Register + immediately print a MANUAL follow-up line."""
    MANUAL_NOTES.append(msg)
    warn("MANUAL: " + msg)


class StepSkip(Exception):
    """Deliberate no-op (missing input / not scriptable) -- not a failure."""


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
# Small helpers (build_arena_level / place_feel_notifies patterns)
# ---------------------------------------------------------------------------

def set_prop_if_exists(obj, name, value, context=""):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s"
             % (name, (" on " + context) if context else "", exc))
        return False


def set_first_prop(obj, names, value, context=""):
    """Try several property spellings (5.x drift); return the one that stuck
    or None. NO warning per miss -- only the caller decides if it matters."""
    for name in names:
        try:
            obj.set_editor_property(name, value)
            return name
        except Exception:
            continue
    return None


def get_first_prop(obj, names):
    for name in names:
        try:
            v = obj.get_editor_property(name)
            if v is not None:
                return v
        except Exception:
            continue
    return None


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
    pkg_name = asset.get_outer().get_name()  # e.g. /Game/Arena/Minions/AM_...
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


def _generated_class(bp_asset, class_path_hint):
    """Blueprint asset -> generated UClass, tolerant of API drift."""
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


def seq_length(seq):
    for fn in ("get_play_length",):
        if hasattr(seq, fn):
            try:
                return float(getattr(seq, fn)())
            except Exception:
                pass
    lib = getattr(unreal, "AnimationLibrary", None) \
        or getattr(unreal, "AnimationBlueprintLibrary", None)
    if lib is not None:
        for fn in ("get_sequence_length", "get_play_length"):
            if hasattr(lib, fn):
                try:
                    return float(getattr(lib, fn)(seq))
                except Exception:
                    pass
    try:
        return float(seq.get_editor_property("sequence_length"))
    except Exception as exc:
        raise RuntimeError("cannot read length of %s (%s)" % (seq.get_name(), exc))


def _skeleton_pkg():
    return str(ST["skeleton"].get_path_name()).split(".")[0]


def _asset_skeleton_matches(asset):
    try:
        skel = asset.get_editor_property("skeleton")
    except Exception:
        return False
    return skel is not None and \
        str(skel.get_path_name()).split(".")[0] == _skeleton_pkg()


# ---------------------------------------------------------------------------
# Step 0: golem skeleton + mesh (type-checked like build_arena_level 6k.1a)
# ---------------------------------------------------------------------------

def step0_resolve_golem():
    if not unreal.EditorAssetLibrary.does_asset_exist(GOLEM_SKM_PATH):
        raise StepSkip("%s missing -- Stone_Golem pack not imported?" % GOLEM_SKM_PATH)
    skm = unreal.EditorAssetLibrary.load_asset(GOLEM_SKM_PATH)
    if not isinstance(skm, unreal.SkeletalMesh):
        raise RuntimeError("%s is a %s, expected SkeletalMesh"
                           % (GOLEM_SKM_PATH, type(skm).__name__))
    skeleton = skm.get_editor_property("skeleton")
    if skeleton is None and unreal.EditorAssetLibrary.does_asset_exist(GOLEM_SKEL_PATH):
        cand = unreal.EditorAssetLibrary.load_asset(GOLEM_SKEL_PATH)
        if isinstance(cand, unreal.Skeleton):
            skeleton = cand
    if skeleton is None:
        raise RuntimeError("could not resolve the golem Skeleton (looked at the "
                           "SKM's skeleton property and %s)" % GOLEM_SKEL_PATH)
    ST["skm"], ST["skeleton"] = skm, skeleton
    return "mesh %s, skeleton %s" % (skm.get_name(), skeleton.get_name())


# ---------------------------------------------------------------------------
# Step 1: cap pack textures at 2048 (project rule for any touched pack)
# ---------------------------------------------------------------------------

def step1_cap_textures():
    if not unreal.EditorAssetLibrary.does_directory_exist(GOLEM_TEX_DIR):
        raise StepSkip("%s does not exist" % GOLEM_TEX_DIR)
    capped, already, failed = 0, 0, 0
    for obj_path in unreal.EditorAssetLibrary.list_assets(GOLEM_TEX_DIR, recursive=True):
        try:
            tex = unreal.EditorAssetLibrary.load_asset(obj_path)
            if not isinstance(tex, unreal.Texture2D):
                continue
            cur = 0
            try:
                cur = int(tex.get_editor_property("max_texture_size"))
            except Exception:
                pass
            if 0 < cur <= MAX_TEXTURE_SIZE:
                already += 1
                continue
            tex.set_editor_property("max_texture_size", MAX_TEXTURE_SIZE)
            force_save(tex)
            capped += 1
            log("  capped %s -> max_texture_size=%d" % (tex.get_name(), MAX_TEXTURE_SIZE))
        except Exception as exc:  # noqa: BLE001 - per-item isolation
            failed += 1
            warn("  texture cap FAILED on %s: %s" % (obj_path, exc))
    return "capped %d, already-capped %d, failed %d" % (capped, already, failed)


# ---------------------------------------------------------------------------
# Step 2: inventory golem-skeleton AnimSequences
# ---------------------------------------------------------------------------

def _registry_anim_sequences():
    """AssetData list of every /Game AnimSequence; [] if the query API drifted."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        return list(registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Engine", "AnimSequence"), True))
    except Exception:
        try:
            flt = unreal.ARFilter(class_names=["AnimSequence"],
                                  package_paths=["/Game"], recursive_paths=True,
                                  recursive_classes=True)
            return list(registry.get_assets(flt))
        except Exception as exc:
            warn("asset registry AnimSequence query failed (%s) -- falling back "
                 "to a directory scan of %s" % (exc, FALLBACK_SCAN_DIRS))
            return []


def _golem_sequences():
    """[(name, loaded AnimSequence)] whose Skeleton IS the golem skeleton.
    Registry 'Skeleton' tag pre-filters (KiteDemo etc. make a load-everything
    scan unaffordable); every tag hit is load-confirmed before use."""
    skel_pkg = _skeleton_pkg()
    out, seen = [], set()

    ads = _registry_anim_sequences()
    if ads:
        for ad in ads:
            pkg = str(ad.package_name)
            if not pkg.startswith("/Game") or pkg in seen:
                continue
            try:
                tag = str(ad.get_tag_value("Skeleton") or "")
            except Exception:
                tag = ""
            if tag and skel_pkg not in tag:
                continue
            seq = ad.get_asset()
            if isinstance(seq, unreal.AnimSequence) and _asset_skeleton_matches(seq):
                seen.add(pkg)
                out.append((str(ad.asset_name), seq))
    else:
        for d in FALLBACK_SCAN_DIRS:
            if not unreal.EditorAssetLibrary.does_directory_exist(d):
                continue
            for obj_path in unreal.EditorAssetLibrary.list_assets(d, recursive=True):
                pkg = str(obj_path).split(".")[0]
                if pkg in seen:
                    continue
                seq = unreal.EditorAssetLibrary.load_asset(obj_path)
                if isinstance(seq, unreal.AnimSequence) and _asset_skeleton_matches(seq):
                    seen.add(pkg)
                    out.append((seq.get_name(), seq))
    return sorted(out, key=lambda t: t[0].lower())


RETARGET_MANUAL = (
    "Retarget attack + death anims to the golem skeleton, then RE-RUN this "
    "script. Fastest path: edit the constants block at the top of "
    "Tools/batch_retarget_anims.py (source = the mannequin attack/death "
    "AnimSequences under /Game/Retargeted_Animations, e.g. the Combo_01 hit "
    "sequences + Knock_Down_Death/Hit_Death; target skeleton = "
    + GOLEM_SKEL_PATH + "; output dir = " + MINION_DIR + "/GolemAnims; keep "
    "'Attack'/'Death' in the output names so the heuristics find them) and run "
    "it from the editor Cmd console. Click-level alternative: Content Browser "
    "-> right-click -> Animation -> IK Rig (one for SKM_UEFN_Mannequin, one "
    "for SKM_Stone_Golem; add a Full Body retarget chain root->hips, chains "
    "for spine/arms/legs/head) -> right-click -> IK Retargeter (source "
    "mannequin rig, target golem rig) -> open it -> Export Selected "
    "Animations -> pick the attack + death sequences -> export into "
    + MINION_DIR + "/GolemAnims. Then: py \"D:/GAME_CORE 5.8/Tools/"
    "integrate_golem_minion.py\" again.")


def step2_inventory():
    pairs = _golem_sequences()
    log("Golem-skeleton AnimSequences found: %d" % len(pairs))
    for name, seq in pairs:
        log("  %-40s %s" % (name, str(seq.get_path_name()).split(".")[0]))

    attacks, deaths, idles, moves = [], [], [], []
    for name, seq in pairs:
        if RE_ATTACK.search(name):
            attacks.append(seq)
        elif RE_DEATH.search(name):
            deaths.append(seq)
        elif RE_IDLE.search(name):
            idles.append(seq)
        elif RE_MOVE.search(name):
            moves.append(seq)

    ST["seq_attacks"] = attacks[:2]
    ST["seq_death"] = deaths[0] if deaths else None
    ST["seq_idle"] = idles[0] if idles else None
    # prefer Walk over Run for the Move state (calmer patrol gait)
    moves.sort(key=lambda s: (0 if "walk" in s.get_name().lower() else 1,
                              s.get_name().lower()))
    ST["seq_move"] = moves[0] if moves else None

    if not pairs:
        manual(RETARGET_MANUAL)
        raise RuntimeError("NO AnimSequence in the project targets the golem "
                           "skeleton AT ALL -- not even the pack's demo "
                           "locomotion resolved. Wrong skeleton asset? "
                           "See the MANUAL retarget block above.")
    if not attacks or not deaths:
        warn("=" * 70)
        warn("The Stone Golem pack ships LOCOMOTION ONLY on its skeleton "
             "(ThirdPersonIdle/Walk/Run/Jump*). Missing on the golem skeleton: %s."
             % " and ".join((["ATTACK"] if not attacks else [])
                            + (["DEATH"] if not deaths else [])))
        warn("Montage/damage/DA-entry steps below will SKIP until you retarget.")
        warn("=" * 70)
        manual(RETARGET_MANUAL)
    return ("attack=%d death=%s idle=%s move=%s (of %d golem sequences)"
            % (len(attacks),
               ST["seq_death"].get_name() if ST["seq_death"] else "NONE",
               ST["seq_idle"].get_name() if ST["seq_idle"] else "NONE",
               ST["seq_move"].get_name() if ST["seq_move"] else "NONE",
               len(pairs)))


# ---------------------------------------------------------------------------
# Step 3: montages via AnimMontageFactory
# ---------------------------------------------------------------------------

def _montage_slot_name(m):
    """Read-back of slot_anim_tracks[0].slot_name (reading a struct array is
    fine -- only WRITE-backs silently fail)."""
    try:
        tracks = m.get_editor_property("slot_anim_tracks")
        if tracks and len(tracks) > 0:
            return str(tracks[0].get_editor_property("slot_name"))
    except Exception as exc:
        warn("could not read slot_anim_tracks on %s: %s" % (m.get_name(), exc))
    return None


def _check_slot(m):
    slot = _montage_slot_name(m)
    if slot == "DefaultSlot":
        return True
    # Struct-array write-back is BANNED (proven silent failure) and no
    # dedicated set-slot library call exists -- manual is the only safe fix.
    manual("%s has slot '%s' (must be DefaultSlot or it plays invisibly): "
           "open the montage -> select the slot track header -> Slot name "
           "dropdown -> DefaultGroup.DefaultSlot -> Save." % (m.get_name(), slot))
    return False


def _create_montage(name, seq):
    """Create MINION_DIR/name from AnimSequence seq (idempotent)."""
    dst_path = "%s/%s" % (MINION_DIR, name)
    if unreal.EditorAssetLibrary.does_asset_exist(dst_path):
        m = unreal.EditorAssetLibrary.load_asset(dst_path)
        if not isinstance(m, unreal.AnimMontage):
            raise RuntimeError("%s exists but is %s, not AnimMontage -- delete "
                               "it and re-run" % (dst_path, type(m).__name__))
        if not _asset_skeleton_matches(m):
            raise RuntimeError("%s exists but targets the WRONG skeleton -- "
                               "delete it and re-run" % dst_path)
        log("  %s already exists -- reusing (idempotent)." % dst_path)
        _check_slot(m)
        return m

    factory = unreal.AnimMontageFactory()
    # 5.8 feature-detect: both historical spellings of both inputs.
    skel_prop = set_first_prop(factory, ("target_skeleton", "skeleton"),
                               ST["skeleton"], "AnimMontageFactory")
    src_prop = set_first_prop(factory, ("source_animation", "source_anim",
                                        "anim_sequence"), seq, "AnimMontageFactory")
    if src_prop is None:
        manual("AnimMontageFactory has no source-animation input in this build "
               "-- create %s by hand: Content Browser -> %s -> right-click %s "
               "-> Create -> Create AnimMontage, rename to %s, drag it to %s, "
               "confirm slot DefaultGroup.DefaultSlot, Save. Then re-run this "
               "script." % (name, str(seq.get_path_name()).split(".")[0],
                            seq.get_name(), name, MINION_DIR))
        raise StepSkip("montage-from-sequence not scriptable (no source_animation "
                       "property on AnimMontageFactory; tried source_animation/"
                       "source_anim/anim_sequence)")
    if skel_prop is None:
        log("  factory skeleton property missing (tried target_skeleton/"
            "skeleton) -- relying on source_animation to imply it.")

    m = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, MINION_DIR, unreal.AnimMontage, factory)
    if m is None:
        raise RuntimeError("create_asset returned None for %s" % dst_path)
    if not _asset_skeleton_matches(m):
        raise RuntimeError("created %s but its skeleton is not the golem "
                           "skeleton -- factory ignored the inputs" % dst_path)
    _check_slot(m)
    force_save(m)
    log("  created %s from %s (factory props: skeleton=%s source=%s, slot=%s)"
        % (name, seq.get_name(), skel_prop, src_prop, _montage_slot_name(m)))
    return m


def step3_montages():
    if not ST["seq_attacks"] and ST["seq_death"] is None:
        raise StepSkip("no golem-skeleton attack/death sequences (step 2) -- "
                       "see the MANUAL retarget block")
    unreal.EditorAssetLibrary.make_directory(MINION_DIR)
    made = []
    if ST["seq_attacks"]:
        ST["am_attacks"] = []
        for i, seq in enumerate(ST["seq_attacks"]):
            name = AM_ATTACK01 if i == 0 else AM_ATTACK02
            try:
                ST["am_attacks"].append(_create_montage(name, seq))
                made.append(name)
            except StepSkip:
                raise
            except Exception as exc:  # noqa: BLE001 - per-item isolation
                warn("  %s FAILED: %s" % (name, exc))
                warn(traceback.format_exc())
    if ST["seq_death"] is not None:
        try:
            ST["am_death"] = _create_montage(AM_DEATH, ST["seq_death"])
            made.append(AM_DEATH)
        except StepSkip:
            raise
        except Exception as exc:  # noqa: BLE001
            warn("  %s FAILED: %s" % (AM_DEATH, exc))
            warn(traceback.format_exc())
    if not made and not ST["am_attacks"] and ST["am_death"] is None:
        raise RuntimeError("every montage creation failed -- see per-item logs")
    return "ready: %s" % (", ".join(made) or "(all pre-existing)")


# ---------------------------------------------------------------------------
# Step 4: ANS_DealDamage window + instance props
# ---------------------------------------------------------------------------

def _anim_lib():
    lib = getattr(unreal, "AnimationLibrary", None) \
        or getattr(unreal, "AnimationBlueprintLibrary", None)
    if lib is None:
        raise StepSkip("neither unreal.AnimationLibrary nor "
                       "unreal.AnimationBlueprintLibrary exists in this build")
    return lib


def _event_instance(ev):
    """The notify-state INSTANCE of an event. Engine quirk (documented in
    place_feel_notifies.py): FAnimNotifyEvent.notify_state_class holds the
    instance despite the name."""
    for prop in ("notify_state_class", "notify"):
        try:
            obj = ev.get_editor_property(prop)
        except Exception:
            continue
        if obj is not None:
            return obj
    return None


def _find_deal_damage_instance(lib, m):
    try:
        events = list(lib.get_animation_notify_events(m))
    except Exception as exc:
        raise RuntimeError("get_animation_notify_events failed on %s (%s)"
                           % (m.get_name(), exc))
    for ev in events:
        inst = _event_instance(ev)
        if inst is not None and "ANS_DealDamage" in str(inst.get_class().get_name()):
            return inst
    return None


def _ensure_track(lib, m):
    names = []
    try:
        names = [str(n) for n in lib.get_animation_notify_track_names(m)]
    except Exception:
        pass
    if TRACK_NAME in names:
        return TRACK_NAME
    try:
        lib.add_animation_notify_track(m, TRACK_NAME)
        return TRACK_NAME
    except Exception:
        try:
            lib.add_animation_notify_track(m, TRACK_NAME,
                                           unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
            return TRACK_NAME
        except Exception as exc:
            warn("could not add track '%s' on %s (%s) -- using an existing one"
                 % (TRACK_NAME, m.get_name(), exc))
    if names:
        return names[0]
    raise RuntimeError("no notify track on %s and cannot create one" % m.get_name())


def _apply_damage_window(lib, cls, m):
    inst = _find_deal_damage_instance(lib, m)
    placed = False
    if inst is None:
        if not hasattr(lib, "add_animation_notify_state_event"):
            raise StepSkip("add_animation_notify_state_event missing from the "
                           "animation library in this build")
        length = seq_length(m)
        start = DMG_WINDOW_START_FRAC * length
        duration = (DMG_WINDOW_END_FRAC - DMG_WINDOW_START_FRAC) * length
        track = _ensure_track(lib, m)
        inst = lib.add_animation_notify_state_event(
            m, track, float(start), float(duration), cls)
        if inst is None:
            # some builds return None but still add -- re-find before failing
            inst = _find_deal_damage_instance(lib, m)
        if inst is None:
            raise RuntimeError("add_animation_notify_state_event returned None "
                               "on %s and no instance found after" % m.get_name())
        placed = True
        log("  %s: ANS_DealDamage window @ %.3f..%.3f s (of %.3f s, track %s)"
            % (m.get_name(), start, start + duration, length, track))
    else:
        log("  %s already has ANS_DealDamage -- updating instance props only "
            "(idempotent)" % m.get_name())

    # Instanced-UObject property edits (the pattern PROVEN to stick) + verify.
    for name, val in DMG_INSTANCE_PROPS.items():
        inst.set_editor_property(name, val)
    fresh = _find_deal_damage_instance(lib, m)  # re-read through the montage
    if fresh is None:
        raise RuntimeError("instance vanished after property set on %s" % m.get_name())
    for name, val in DMG_INSTANCE_PROPS.items():
        got = float(fresh.get_editor_property(name))
        if abs(got - val) > 0.01:
            raise RuntimeError("%s: %s did NOT stick (wanted %s, read back %s)"
                               % (m.get_name(), name, val, got))
    force_save(m)
    return placed


def step4_damage_window():
    if not ST["am_attacks"]:
        raise StepSkip("no golem attack montage (step 3) -- see the MANUAL "
                       "retarget block")
    lib = _anim_lib()
    try:
        cls = unreal.load_class(None, "/Script/GAME_CORE.ANS_DealDamage")
    except Exception:
        cls = None
    if cls is None:
        manual("ANS_DealDamage class not compiled -- after a Build.bat pass, "
               "re-run this script (or place the window by hand: open "
               "%s -> Notifies -> Add Notify State -> Deal Damage Window at "
               "35%%-55%%, details panel: TraceRadius 60, TraceForwardOffset "
               "150)." % AM_ATTACK01)
        raise StepSkip("/Script/GAME_CORE.ANS_DealDamage not found")
    placed, updated = 0, 0
    for m in ST["am_attacks"]:
        if _apply_damage_window(lib, cls, m):
            placed += 1
        else:
            updated += 1
    return ("placed %d, updated-props-only %d (radius=%.0f fwd=%.0f verified "
            "by re-read)" % (placed, updated,
                             DMG_INSTANCE_PROPS["trace_radius"],
                             DMG_INSTANCE_PROPS["trace_forward_offset"]))


# ---------------------------------------------------------------------------
# Step 5: golem AnimBlueprint (asset scriptable, graph is NOT)
# ---------------------------------------------------------------------------

ABP_GRAPH_RECIPE = (
    "Finish the golem AnimBP graph (the ONLY human step of this integration; "
    "~10 minutes): open " + ABP_PATH + " -> "
    "(1) Event Graph: from 'Event Blueprint Update Animation' -> Try Get Pawn "
    "Owner -> Get Velocity -> Vector Length -> promote to float variable "
    "'Speed' (Set Speed). "
    "(2) AnimGraph: right-click -> State Machines -> Add New State Machine "
    "('Locomotion'). Open it: add state 'Idle' (drag ThirdPersonIdle from the "
    "Asset Browser into it, tick Loop), add state 'Move' (ThirdPersonWalk or "
    "ThirdPersonRun, Loop). Transition Idle->Move: Speed > 3. Move->Idle: "
    "Speed <= 3. "
    "(3) Back in AnimGraph: chain Locomotion -> 'Slot DefaultSlot' node "
    "(search 'Slot', keep DefaultGroup.DefaultSlot) -> Output Pose. "
    "(4) Compile + Save. Without the Slot node the attack/death montages "
    "play invisibly -- do not skip it.")


def _find_existing_golem_abp():
    """Asset-registry hunt for an AnimBP already targeting the golem skeleton
    (the _find_hero_anim_class pattern; never PostProcess rigs)."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = list(registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Engine", "AnimBlueprint"), True))
    except Exception:
        try:
            flt = unreal.ARFilter(class_names=["AnimBlueprint"],
                                  package_paths=["/Game"], recursive_paths=True,
                                  recursive_classes=True)
            assets = list(registry.get_assets(flt))
        except Exception as exc:
            warn("AnimBlueprint registry query failed: %s" % exc)
            return None
    skel_pkg, skel_name = _skeleton_pkg(), str(ST["skeleton"].get_name())
    best = None
    for ad in assets:
        pkg = str(ad.package_name)
        if not pkg.startswith("/Game"):
            continue
        try:
            tag = str(ad.get_tag_value("TargetSkeleton") or "")
        except Exception:
            tag = ""
        if skel_pkg not in tag and tag != skel_name:
            continue
        name = str(ad.asset_name)
        low = name.lower()
        if "postprocess" in low or "post_process" in low:
            continue
        score = (4 if "golem" in low else 0) + (1 if low.startswith("abp") else 0)
        if best is None or score > best[0]:
            best = (score, name, pkg, ad)
    if best is None:
        return None
    _score, name, pkg, ad = best
    abp = ad.get_asset()
    if abp is None:
        return None
    log("  found existing golem AnimBP: %s (%s)" % (name, pkg))
    return abp, "%s.%s_C" % (pkg, name)


def step5_anim_blueprint():
    found = _find_existing_golem_abp()
    if found is None:
        if unreal.EditorAssetLibrary.does_asset_exist(ABP_PATH):
            abp = unreal.EditorAssetLibrary.load_asset(ABP_PATH)
            hint = "%s.%s_C" % (ABP_PATH, ABP_NAME)
        else:
            factory = unreal.AnimBlueprintFactory()
            if set_first_prop(factory, ("target_skeleton", "skeleton"),
                              ST["skeleton"], "AnimBlueprintFactory") is None:
                manual("AnimBlueprintFactory has no target_skeleton property in "
                       "this build -- create the AnimBP by hand: Content "
                       "Browser -> %s -> right-click -> Animation -> Animation "
                       "Blueprint -> skeleton %s -> name %s. Then: %s"
                       % (MINION_DIR, ST["skeleton"].get_name(), ABP_NAME,
                          ABP_GRAPH_RECIPE))
                raise StepSkip("AnimBP asset creation not scriptable (no "
                               "skeleton property on AnimBlueprintFactory)")
            set_first_prop(factory, ("parent_class",), unreal.AnimInstance)
            abp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                ABP_NAME, MINION_DIR, None, factory)
            if abp is None:
                raise RuntimeError("create_asset returned None for %s" % ABP_PATH)
            force_save(abp)
            ST["abp_created_now"] = True
            hint = "%s.%s_C" % (ABP_PATH, ABP_NAME)
            log("  created empty AnimBP asset %s (graph authoring is not "
                "possible from python -- manual recipe queued)" % ABP_PATH)
    else:
        abp, hint = found

    gen = _generated_class(abp, hint)
    if gen is None:
        raise RuntimeError("could not resolve the AnimBP generated class (%s)" % hint)
    ST["anim_class"] = gen

    if ST["abp_created_now"] or found is None:
        manual(ABP_GRAPH_RECIPE)
        return ("%s asset ready + wired to BP_Minion in step 7; the GRAPH is "
                "the one manual step (recipe in the summary)" % ABP_NAME)
    return "reusing existing golem AnimBP (graph assumed already authored)"


# ---------------------------------------------------------------------------
# Step 6: DA_MinionCombo entry 0
# ---------------------------------------------------------------------------

def step6_update_combo_config():
    if not ST["am_attacks"]:
        raise StepSkip("no AM_Golem_Attack01 (steps 2/3) -- entry 0 still "
                       "points at the mannequin montage, which CANNOT play on "
                       "the golem mesh: minion attacks stay invisible AND deal "
                       "no damage until the retarget + re-run")
    am_attack = ST["am_attacks"][0]
    if not unreal.EditorAssetLibrary.does_asset_exist(DA_COMBO_PATH):
        manual("DA_MinionCombo missing at %s -- run Tools/build_arena_level.py "
               "(6k.3) or create a CombatAnimConfig DataAsset there, then "
               "re-run this script." % DA_COMBO_PATH)
        raise StepSkip("%s does not exist" % DA_COMBO_PATH)
    da = unreal.EditorAssetLibrary.load_asset(DA_COMBO_PATH)
    if not hasattr(unreal, "AttackAnimData"):
        raise StepSkip("unreal.AttackAnimData binding missing (GAME_CORE module "
                       "not loaded in this editor session)")

    chain = list(da.get_editor_property("combo_chain") or [])
    want_pkg = str(am_attack.get_path_name()).split(".")[0]

    def _entry_matches(e):
        try:
            mont = e.get_editor_property("montage")
            return (mont is not None
                    and str(mont.get_path_name()).split(".")[0] == want_pkg
                    and abs(float(e.get_editor_property("damage_amount")) - ENTRY0_DAMAGE) < 0.01
                    and str(e.get_editor_property("damage_type")) == ENTRY0_TYPE)
        except Exception:
            return False

    if chain and _entry_matches(chain[0]):
        return "entry 0 already correct (idempotent)"

    # Build a FRESH entry and set the WHOLE array back. Never mutate chain[i]
    # in place -- struct-array element write-backs silently fail from python.
    entry = unreal.AttackAnimData()
    entry.set_editor_property("montage", am_attack)
    entry.set_editor_property("damage_amount", ENTRY0_DAMAGE)
    entry.set_editor_property("damage_type", ENTRY0_TYPE)
    new_chain = [entry] + list(chain[1:])
    da.set_editor_property("combo_chain", new_chain)

    # verify by re-read (rule: verify EVERY struct-array write)
    check = list(da.get_editor_property("combo_chain") or [])
    if not check or not _entry_matches(check[0]):
        raise RuntimeError("combo_chain[0] did NOT stick after whole-array set "
                           "-- edit DA_MinionCombo by hand: entry 0 Montage=%s, "
                           "DamageAmount=%s, DamageType=%s" %
                           (AM_ATTACK01, ENTRY0_DAMAGE, ENTRY0_TYPE))
    force_save(da)
    ST["da_combo"] = da
    return ("entry 0 -> %s, %.0f dmg, %s (re-read verified, %d entr%s total)"
            % (AM_ATTACK01, ENTRY0_DAMAGE, ENTRY0_TYPE, len(check),
               "y" if len(check) == 1 else "ies"))


# ---------------------------------------------------------------------------
# Step 7: BP_Minion CDO
# ---------------------------------------------------------------------------

def _golem_bounds_extent():
    """Half-extents (unscaled) of the golem mesh bounds, feature-detected."""
    skm = ST["skm"]
    bounds = None
    if hasattr(skm, "get_bounds"):
        try:
            bounds = skm.get_bounds()
        except Exception:
            bounds = None
    if bounds is None:
        bounds = get_first_prop(skm, ("extended_bounds", "imported_bounds"))
    if bounds is None:
        return None
    ext = get_first_prop(bounds, ("box_extent",))
    if ext is None and hasattr(bounds, "box_extent"):
        ext = bounds.box_extent
    return ext


def _capsule_numbers():
    """(half_height, radius) for the SCALED golem, from measured bounds."""
    ext = _golem_bounds_extent()
    if ext is None:
        warn("  golem mesh bounds unreadable -- keeping ACharacter defaults "
             "(88/34); eyeball-fix the capsule in the BP if the golem clips.")
        manual("Could not read SKM_Stone_Golem bounds: open BP_Minion -> "
               "CapsuleComponent -> set Half Height / Radius so the capsule "
               "just wraps the scaled golem (viewport check).")
        return None
    half_height = float(ext.z) * MESH_SCALE
    radius = min(float(ext.x), float(ext.y)) * MESH_SCALE
    radius = max(CAPSULE_RADIUS_MIN, min(CAPSULE_RADIUS_MAX, radius))
    radius = min(radius, half_height)  # capsule invariant
    log("  golem bounds half-extents (unscaled): x=%.1f y=%.1f z=%.1f -- "
        "capsule @ scale %.2f: half_height=%.1f radius=%.1f"
        % (float(ext.x), float(ext.y), float(ext.z), MESH_SCALE,
           half_height, radius))
    return half_height, radius


def _apply_bp_defaults(cdo):
    """Set the golem defaults on BP_Minion's CDO; returns misses list."""
    misses = []
    capsule = ST.get("capsule")

    mesh_comp = None
    try:
        mesh_comp = cdo.get_editor_property("mesh")  # ACharacter::Mesh
    except Exception:
        pass
    if mesh_comp is None:
        misses.append("mesh component not reachable on the CDO")
    else:
        if not (set_prop_if_exists(mesh_comp, "skeletal_mesh_asset", ST["skm"])
                or set_prop_if_exists(mesh_comp, "skeletal_mesh", ST["skm"])):
            misses.append("skeletal mesh")
        if ST.get("anim_class") is not None:
            set_prop_if_exists(mesh_comp, "animation_mode",
                               unreal.AnimationMode.ANIMATION_BLUEPRINT,
                               "BP_Minion mesh")
            if not set_prop_if_exists(mesh_comp, "anim_class", ST["anim_class"]):
                misses.append("anim class")
        else:
            misses.append("anim class (step 5 did not produce one)")
        rel_z = -(capsule[0] if capsule else 88.0)
        if not set_prop_if_exists(mesh_comp, "relative_location",
                                  unreal.Vector(0.0, 0.0, rel_z)):
            misses.append("mesh relative location")
        if not set_prop_if_exists(mesh_comp, "relative_rotation",
                                  unreal.Rotator(roll=0.0, pitch=0.0,
                                                 yaw=MESH_REL_YAW)):
            misses.append("mesh relative rotation")
        if not set_prop_if_exists(mesh_comp, "relative_scale3d",
                                  unreal.Vector(MESH_SCALE, MESH_SCALE, MESH_SCALE)):
            misses.append("mesh scale %.2f" % MESH_SCALE)

    if capsule is not None:
        cap_comp = None
        try:
            cap_comp = cdo.get_editor_property("capsule_component")
        except Exception:
            pass
        if cap_comp is None:
            misses.append("capsule component not reachable on the CDO")
        else:
            if not set_prop_if_exists(cap_comp, "capsule_half_height", capsule[0]):
                misses.append("capsule half height")
            if not set_prop_if_exists(cap_comp, "capsule_radius", capsule[1]):
                misses.append("capsule radius")

    if ST.get("am_death") is not None:
        combat = None
        try:
            combat = cdo.get_editor_property("combat_component")
        except Exception:
            pass
        if combat is None:
            misses.append("combat_component not reachable on the CDO")
        elif not set_prop_if_exists(combat, "death_montage", ST["am_death"]):
            misses.append("DeathMontage")
    return misses


def _verify_bp(gen_cls):
    """Fresh-spawn ASSERT (build_arena_level 6k pattern): spawn a throwaway
    from the generated class, check propagation, destroy it."""
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    inst = None
    try:
        inst = actors.spawn_actor_from_class(
            gen_cls, unreal.Vector(0.0, 0.0, -5000.0),
            unreal.Rotator(0.0, 0.0, 0.0))
    except Exception as exc:
        return None, "throwaway spawn unavailable (%s) -- no level open?" % exc
    if inst is None:
        return None, "throwaway spawn returned None -- no level open?"
    try:
        checks = []
        mc = inst.get_component_by_class(unreal.SkeletalMeshComponent)
        skm_val = get_first_prop(mc, ("skeletal_mesh_asset", "skeletal_mesh")) \
            if mc is not None else None
        checks.append(("mesh is SKM_Stone_Golem",
                       skm_val is not None and
                       str(skm_val.get_path_name()).split(".")[0] == GOLEM_SKM_PATH))
        if ST.get("anim_class") is not None:
            anim_val = None
            try:
                anim_val = mc.get_editor_property("anim_class") if mc else None
            except Exception:
                pass
            checks.append(("anim class", anim_val is not None))
        cap = ST.get("capsule")
        if cap is not None:
            cc = inst.get_component_by_class(unreal.CapsuleComponent)
            hh = None
            if cc is not None:
                try:
                    hh = float(cc.get_editor_property("capsule_half_height"))
                except Exception:
                    hh = None
            checks.append(("capsule half height %.1f" % cap[0],
                           hh is not None and abs(hh - cap[0]) < 1.0))
        if ST.get("am_death") is not None:
            comb_cls = getattr(unreal, "CombatComponent", None)
            if comb_cls is None:
                try:
                    comb_cls = unreal.load_class(None, "/Script/GAME_CORE.CombatComponent")
                except Exception:
                    comb_cls = None
            comb = inst.get_component_by_class(comb_cls) if comb_cls else None
            dm = None
            if comb is not None:
                try:
                    dm = comb.get_editor_property("death_montage")
                except Exception:
                    pass
            checks.append(("death montage", dm is not None and
                           AM_DEATH in str(dm.get_path_name())))
        failed = [name for name, ok in checks if not ok]
        if failed:
            return False, "unset on a fresh instance: %s" % ", ".join(failed)
        return True, "verified on a fresh instance: %s" % \
            ", ".join(name for name, _ok in checks)
    finally:
        try:
            actors.destroy_actor(inst)
        except Exception:
            pass


def step7_bp_minion():
    if not unreal.EditorAssetLibrary.does_asset_exist(BP_MINION_PATH):
        manual("BP_Minion missing at %s -- run Tools/build_arena_level.py "
               "(6k.4) first, then re-run this script." % BP_MINION_PATH)
        raise StepSkip("%s does not exist" % BP_MINION_PATH)
    bp = unreal.EditorAssetLibrary.load_asset(BP_MINION_PATH)
    gen_cls = _generated_class(bp, BP_MINION_PATH + ".BP_Minion_C")
    if gen_cls is None:
        raise RuntimeError("BP_Minion has no resolvable generated class")

    ST["capsule"] = _capsule_numbers()
    cdo = unreal.get_default_object(gen_cls)
    misses = _apply_bp_defaults(cdo)

    # Compile can regenerate the CDO and drop pure-CDO edits -- compile,
    # re-apply on the (possibly new) CDO, then save, then verify fresh.
    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("compile_blueprint failed (%s) -- continuing to save." % exc)
        gen_cls = _generated_class(bp, BP_MINION_PATH + ".BP_Minion_C") or gen_cls
        cdo = unreal.get_default_object(gen_cls)
        misses = _apply_bp_defaults(cdo)

    force_save(bp)

    verified, why = _verify_bp(gen_cls)
    if verified is None:
        raise StepSkip("BP_Minion saved but NOT spawn-verified (%s) -- treat "
                       "the defaults as unconfirmed" % why)
    if verified is False:
        raise RuntimeError("BP_Minion ASSERT FAIL -- %s%s"
                           % (why, ("; also unset during apply: " +
                                    "; ".join(misses)) if misses else ""))
    if misses:
        raise StepSkip("BP_Minion saved + spawn-verified for what applied, but "
                       "some defaults could not be set: %s" % "; ".join(misses))
    if ST.get("am_death") is None:
        manual("BP_Minion still carries the mannequin AM_Minion_Death as "
               "DeathMontage -- it cannot play on the golem mesh (skeleton "
               "mismatch), so dead golems will freeze in their last pose "
               "until the retarget + re-run replaces it with %s." % AM_DEATH)
    return "BP_Minion %s (capsule %s, mesh scale %.2f)" % (
        why,
        ("hh=%.1f r=%.1f" % ST["capsule"]) if ST["capsule"] else "left at defaults",
        MESH_SCALE)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

STEPS = [
    ("0. Resolve golem skeleton + mesh", step0_resolve_golem),
    ("1. Cap pack textures at 2048", step1_cap_textures),
    ("2. Inventory golem-skeleton sequences", step2_inventory),
    ("3. Create golem montages", step3_montages),
    ("4. ANS_DealDamage window + trace props", step4_damage_window),
    ("5. Golem AnimBlueprint", step5_anim_blueprint),
    ("6. DA_MinionCombo entry 0", step6_update_combo_config),
    ("7. BP_Minion CDO + verify", step7_bp_minion),
]


def main():
    log("=" * 70)
    log("integrate_golem_minion -- BP_Minion mannequin -> Stone Golem")
    log("=" * 70)
    for i, (label, fn) in enumerate(STEPS):
        if i > 0 and STEP_RESULTS and STEP_RESULTS[0][1] != "PASS":
            STEP_RESULTS.append((label, "SKIP", "step 0 did not pass"))
            continue
        run_step(label, fn)
    log("=" * 70)
    log("SUMMARY")
    for label, status, detail in STEP_RESULTS:
        log("  %-4s %-42s %s" % (status, label, detail))
    if MANUAL_NOTES:
        log("-" * 70)
        log("MANUAL FOLLOW-UPS (%d):" % len(MANUAL_NOTES))
        for note in MANUAL_NOTES:
            log("  MANUAL: " + note)
    else:
        log("No manual follow-ups -- the golem minion is fully wired.")
    log("Re-run safe: existing montages/notifies/ABP/DA entries are reused or "
        "updated idempotently; re-run after retargeting attack/death anims.")
    log("=" * 70)


main()
