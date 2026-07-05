"""Equip visible weapons + slash-trail / impact FX (guide.md Phase 5 flavor).

Does (each sub-goal guarded; PASS/FAIL/SKIP summary at the end):
  1. BP_Boss       -> add a StaticMeshComponent 'WeaponMesh' (SubobjectDataSubsystem),
                      mesh = /Game/Sword/Sword/SM_Sword (the Thornblade), attached
                      under the SkeletalMeshComponent at socket 'weapon_r' if the
                      boss skeleton has it, else 'hand_r'. NoCollision. Starting
                      grip: loc (0,0,0) rot (0,0,90) -- NUDGE IN THE BP VIEWPORT
                      if it clips, this is a first-guess grip.
  2. BP_NeuralHero -> same, with a one-handed sword. NOTE: Content/Weapons_Free
                      turned out to be a MODERN pack (pistols/rifles/axe/bat/knife
                      -- no sword), so the pick order is: any sword-named SM in
                      /Game/Weapons_Free (future-proofing) -> RamsterZ
                      OneHandSword_Mesh -> a long-thin-bounds scan of
                      /Game/Medieval_MWP/Mesh (SM_MMW_*).
  3. Slash trails  -> AnimNotifyState_TimedNiagaraEffect on every hero combo
                      montage (Combo_0*/AM_*) and boss Attack_0*_Seq_Montage,
                      spanning the ANS_DealDamage window +-0.1 s.
                      Hero = NS_SlashTrail_Basic, boss = NS_SlashTrail_Dark
                      (SlashTrail_SoftTofu pack), socket 'hand_r' (or whatever
                      socket step 1/2 resolved), destroy_at_end.
  4. Impact FX     -> log-only recommendation (NS_Hit_*_Once wiring is a
                      HitFeedbackComponent/C++ change -- NOT done here).
  5. Texture cap   -> max_texture_size=2048 on every Texture2D under
                      /Game/Sword, /Game/SlashTrail_SoftTofu and the pack of
                      whichever hero sword was picked (project rule: any pack
                      integrated into always-rendered gameplay gets capped --
                      a 4K Thornblade set is a permanent VRAM tax on the 6 GB
                      4050). Write-back verified + force-saved.

Idempotent: WeaponMesh components and montages already carrying a CONFIGURED
TimedNiagaraEffect are skipped with a log line (unconfigured ones from an
interrupted run get their instance props refreshed). Only assets under
/Game/Blueprints and /Game/Retargeted_Animations are ever SAVED -- plus,
for the texture-cap step ONLY, Texture2Ds inside the weapon/trail pack
folders listed above.

KNOWN-FRAGILE APIs (feature-detected, loud manual fallbacks -- see the
MANUAL FOLLOW-UPS block at the end of the run):
  * SubobjectDataSubsystem add/rename/parent-socket flow (5.8 python surface
    drifted across 5.1-5.8; the parent-socket write especially may not be
    exposed). The socket is only reported set after a FRESH-SPAWN assert
    (throwaway actor from the compiled class, get_attach_socket_name checked)
    -- a template attach_socket_name re-read alone can lie, because the SCS
    node's AttachToName wins at construction. If the assert fails the
    component still lands and you set Parent Socket by hand (manual note).
  * AnimNotifyState_TimedNiagaraEffect property names ('template' etc.) --
    every instanced-object write is verified by re-read (struct-array
    write-backs are known to silently fail from python; instanced-UObject
    property edits are the proven-to-stick pattern in this repo).

Run INSIDE the UE editor (the editor's Python, not the venv):
  Output Log -> set the dropdown to 'Cmd' -> paste:
      py "D:/GAME_CORE 5.8/Tools/equip_weapons_and_trails.py"
  (or Tools -> Execute Python Script... and pick this file)
"""

import os
import re
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

BP_BOSS_PATH = "/Game/Blueprints/BP_Boss"
BP_HERO_PATH = "/Game/Blueprints/BP_NeuralHero"

BOSS_SWORD_PATH = "/Game/Sword/Sword/SM_Sword"  # the Thornblade

# Hero sword pick order (first that loads as a StaticMesh wins).
# Weapons_Free is scanned first only in case a sword-named SM appears later --
# as of this writing that pack is firearms/tools only (verified: no sword).
HERO_SWORD_DIR_SCAN = "/Game/Weapons_Free"          # registry scan, sword-ish names
HERO_SWORD_EXPLICIT = "/Game/RamsterZ_FreeAnims_Volume1/Demo/Props/OneHandSword_Mesh"
HERO_SWORD_BOUNDS_SCAN = "/Game/Medieval_MWP/Mesh"  # SM_MMW_* long-thin heuristic
SWORD_NAME_RE = re.compile(r"sword|blade|katana|saber|sabre", re.IGNORECASE)

WEAPON_COMPONENT_NAME = "WeaponMesh"
SOCKET_PREFERRED = "weapon_r"
SOCKET_FALLBACK = "hand_r"
GRIP_LOCATION = unreal.Vector(0.0, 0.0, 0.0)
GRIP_ROTATION = unreal.Rotator(roll=0.0, pitch=0.0, yaw=90.0)

RETARGET_DIR = "/Game/Retargeted_Animations"
COMBO_DIRS = ["%s/Combo_%02d" % (RETARGET_DIR, i) for i in range(1, 10)]
BOSS_DIR = RETARGET_DIR + "/BOSS"
BOSS_ATTACK_RE = re.compile(r"^Attack_0(\d)_Seq_Montage$")

NIAGARA_DIR = "/Game/SlashTrail_SoftTofu/Niagara"
NS_TRAIL_HERO = NIAGARA_DIR + "/Basic/NS_SlashTrail_Basic"
NS_TRAIL_BOSS = NIAGARA_DIR + "/Dark/NS_SlashTrail_Dark"
NS_HIT_HERO_ONCE = NIAGARA_DIR + "/Basic/NS_Hit_Basic_Once"
NS_HIT_BOSS_ONCE = NIAGARA_DIR + "/Dark/NS_Hit_Dark_Once"

# TimedNiagaraEffect notify-state class candidates (feature-detected).
TIMED_NIAGARA_CLASS_CANDIDATES = (
    "/Script/Niagara.AnimNotifyState_TimedNiagaraEffect",
    "/Script/Niagara.AnimNotifyState_TimedNiagaraEffectAdvanced",
    "/Script/NiagaraAnimNotifies.AnimNotifyState_TimedNiagaraEffect",
)
TIMED_NIAGARA_KEYWORD = "TimedNiagaraEffect"   # idempotency check keyword

TRAIL_PAD = 0.10                # s either side of the ANS_DealDamage window
MIN_WINDOW_DURATION = 0.02      # refuse degenerate slivers
TRACK_NAME = "FX"               # created if possible; else FeelNotifies/first
CLS_DEAL_DAMAGE = "ANS_DealDamage"

# The ONLY folders this script may SAVE assets in. The texture-cap step
# widens this per-save via force_save(extra_prefixes=...) for JUST the pack
# folder it is capping -- never globally.
ALLOWED_SAVE_PREFIXES = ("/Game/Blueprints/", RETARGET_DIR + "/")

# Texture-cap targets (session rule: cap any touched pack at 2048).
MAX_TEXTURE_SIZE = 2048
WEAPON_TEX_DIRS = ["/Game/Sword", "/Game/SlashTrail_SoftTofu"]

STEP_RESULTS = []   # (label, "PASS"/"FAIL"/"SKIP", detail)
MANUAL_NOTES = []   # printed at the end for anything that degraded
CTX = {}            # cross-step state (resolved sockets, meshes, classes)


def log(msg):
    unreal.log("[EquipWeapons] " + str(msg))


def warn(msg):
    unreal.log_warning("[EquipWeapons] " + str(msg))


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


def set_prop_if_exists(obj, name, value, context=""):
    """set_editor_property guarded for properties that may have moved in 5.8."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s" % (name, (" on " + context) if context else "", exc))
        return False


def assert_save_allowed(asset, extra_prefixes=()):
    path = asset.get_path_name()
    allowed = tuple(ALLOWED_SAVE_PREFIXES) + tuple(extra_prefixes)
    if not any(path.startswith(p) for p in allowed):
        raise RuntimeError("REFUSING to save asset outside allowed folders: %s" % path)


def force_save(asset, extra_prefixes=()):
    """mark_package_dirty -> save_loaded_asset(only_if_is_dirty=False) ->
    verify the .uasset mtime advanced on disk. The dirty-gated default save
    has been PROVEN to silently write nothing in this repo -- never trust a
    save that isn't disk-verified. extra_prefixes: per-call widening of the
    save allowlist (texture-cap step only)."""
    assert_save_allowed(asset, extra_prefixes)
    try:
        asset.get_outer().mark_package_dirty()
    except Exception:
        pass
    pkg_name = asset.get_outer().get_name()  # e.g. /Game/Blueprints/BP_Boss
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
            raise RuntimeError("save reported success but %s was NOT rewritten on disk"
                               % disk_path)
    log("  saved + disk-verified: %s" % pkg_name)


def load_asset_if_exists(path):
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            return unreal.EditorAssetLibrary.load_asset(path)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# SubobjectDataSubsystem plumbing (THE fragile bit -- everything detected)
# ---------------------------------------------------------------------------

def get_subobject_subsystem():
    """SubobjectDataSubsystem is an ENGINE subsystem in 5.1-5.8, but try the
    editor-subsystem accessor too in case 5.8 moved it."""
    sds = None
    cls = getattr(unreal, "SubobjectDataSubsystem", None)
    if cls is None:
        raise StepSkip("unreal.SubobjectDataSubsystem not bound in this build -- "
                       "add the WeaponMesh component by hand (see manual notes)")
    for accessor in ("get_engine_subsystem", "get_editor_subsystem"):
        fn = getattr(unreal, accessor, None)
        if fn is None:
            continue
        try:
            sds = fn(cls)
        except Exception:
            sds = None
        if sds is not None:
            log("SubobjectDataSubsystem via unreal.%s" % accessor)
            return sds
    raise StepSkip("SubobjectDataSubsystem exists but neither get_engine_subsystem "
                   "nor get_editor_subsystem returned it")


def gather_handles(sds, bp):
    """All subobject handles for a Blueprint asset (5.8 name drift guarded)."""
    for name in ("k2_gather_subobject_data_for_blueprint",
                 "gather_subobject_data_for_blueprint"):
        fn = getattr(sds, name, None)
        if fn is None:
            continue
        try:
            handles = list(fn(bp))
            return handles
        except Exception as exc:
            warn("%s failed on %s: %s" % (name, bp.get_name(), exc))
    raise RuntimeError(
        "no working gather_subobject_data_for_blueprint variant; sds methods: %s"
        % ", ".join(n for n in dir(sds) if "gather" in n.lower() or "subobject" in n.lower()))


def handle_object(handle):
    """SubobjectDataHandle -> the live template UObject (or None)."""
    lib = getattr(unreal, "SubobjectDataBlueprintFunctionLibrary", None)
    if lib is None:
        return None
    try:
        return lib.get_object(lib.get_data(handle))
    except Exception:
        return None


def find_handle_by_class(handles, klass):
    """First (handle, obj) whose template object is an instance of klass."""
    for h in handles:
        obj = handle_object(h)
        if obj is not None and isinstance(obj, klass):
            return h, obj
    return None, None


def find_component_named(handles, name_fragment):
    """(handle, obj) of the first component whose object name contains the
    fragment (SCS template names look like 'WeaponMesh_GEN_VARIABLE')."""
    for h in handles:
        obj = handle_object(h)
        if obj is not None and name_fragment in str(obj.get_name()):
            return h, obj
    return None, None


def resolve_socket(skel_comp_template, skm_asset, who):
    """'weapon_r' if the skeleton actually has it, else 'hand_r'.
    Checks: component does_socket_exist (covers sockets AND bones -- may not
    work on an unregistered SCS template), then SkeletalMesh.find_socket
    (sockets only). Falls back to 'hand_r' loudly."""
    for probe, note in (
            (lambda: skel_comp_template.does_socket_exist(SOCKET_PREFERRED),
             "component does_socket_exist"),
            (lambda: skm_asset is not None and skm_asset.find_socket(SOCKET_PREFERRED) is not None,
             "SkeletalMesh.find_socket")):
        try:
            if probe():
                log("%s: socket '%s' confirmed via %s" % (who, SOCKET_PREFERRED, note))
                return SOCKET_PREFERRED
        except Exception:
            continue
    log("%s: '%s' not found/checkable -- using '%s' (mannequin-style hand bone)"
        % (who, SOCKET_PREFERRED, SOCKET_FALLBACK))
    return SOCKET_FALLBACK


def try_set_parent_socket(template, socket_name, who):
    """Best-effort Parent Socket write onto the SCS template. TENTATIVE ONLY:
    the BP-editor 'Parent Socket' lives on the USCS_Node (AttachToName), and
    USceneComponent.attach_socket_name on an SCS template is overwritten at
    construction from the node -- so a passing re-read here can LIE. The
    authoritative check is verify_socket_on_spawn() after compile + save.
    (The old fallback that blind-invoked every SubobjectDataSubsystem method
    containing 'socket' with guessed args was REMOVED -- calling unknown
    editor APIs with a live handle risks arbitrary side effects on the BP.)"""
    try:
        template.set_editor_property("attach_socket_name", socket_name)
        back = str(template.get_editor_property("attach_socket_name"))
        if back == socket_name:
            log("%s: template.attach_socket_name = '%s' (tentative -- the "
                "fresh-spawn check after save is authoritative)" % (who, socket_name))
            return True
        warn("%s: attach_socket_name wrote but read back '%s'" % (who, back))
    except Exception as exc:
        log("%s: template attach_socket_name not writable (%s)" % (who, exc))
    return False


def _generated_class(bp_asset, class_path_hint):
    """Blueprint asset -> generated UClass, tolerant of API drift (pattern
    from integrate_golem_minion.py)."""
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


def verify_socket_on_spawn(bp, bp_path, socket_name, sword_sm, who):
    """Fresh-spawn ASSERT (the integrate_golem_minion.py step-7 pattern):
    spawn a throwaway actor from the generated class, find the WeaponMesh
    StaticMeshComponent, and check get_attach_socket_name() == socket_name.
    Returns (True|False|None, why) -- None means 'could not verify'."""
    gen_cls = _generated_class(
        bp, "%s.%s_C" % (bp_path, bp_path.rsplit("/", 1)[-1]))
    if gen_cls is None:
        return None, "no resolvable generated class"
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
        comp = None
        try:
            comps = list(inst.get_components_by_class(unreal.StaticMeshComponent))
        except Exception as exc:
            return None, "get_components_by_class failed (%s)" % exc
        for c in comps:
            try:
                if WEAPON_COMPONENT_NAME in str(c.get_name()):
                    comp = c
                    break
                sm = c.get_editor_property("static_mesh")
                if (sm is not None and sword_sm is not None
                        and sm.get_path_name() == sword_sm.get_path_name()):
                    comp = c  # fallback match by assigned mesh (rename failed?)
            except Exception:
                continue
        if comp is None:
            return False, "no WeaponMesh StaticMeshComponent on a fresh spawn"
        try:
            got = str(comp.get_attach_socket_name())
        except Exception as exc:
            return None, "get_attach_socket_name unavailable (%s)" % exc
        if got == socket_name:
            return True, "fresh spawn attaches WeaponMesh at '%s'" % got
        return False, ("fresh spawn attaches WeaponMesh at '%s', wanted '%s'"
                       % (got or "<mesh root>", socket_name))
    finally:
        try:
            actors.destroy_actor(inst)
        except Exception:
            pass


def add_weapon_mesh(bp_path, sword_sm, who):
    """Shared worker for steps 2/3: add + configure WeaponMesh on one BP.
    Returns the summary string; stores resolved socket in CTX['socket_'+who]."""
    bp = load_asset_if_exists(bp_path)
    if bp is None:
        raise StepSkip("%s not found" % bp_path)
    if sword_sm is None:
        raise StepSkip("no sword static mesh resolved for %s" % who)

    sds = get_subobject_subsystem()
    handles = gather_handles(sds, bp)
    log("%s: gathered %d subobject handle(s)" % (who, len(handles)))

    # Parent: the (first) SkeletalMeshComponent -- the character mesh.
    skel_handle, skel_template = find_handle_by_class(handles, unreal.SkeletalMeshComponent)
    if skel_handle is None:
        raise RuntimeError("%s: no SkeletalMeshComponent found among subobjects "
                           "-- cannot pick an attach parent" % who)
    skm_asset = None
    for prop in ("skeletal_mesh_asset", "skeletal_mesh"):
        try:
            skm_asset = skel_template.get_editor_property(prop)
            if skm_asset is not None:
                break
        except Exception:
            continue
    socket = resolve_socket(skel_template, skm_asset, who)
    CTX["socket_" + who] = socket

    # Idempotency: an existing WeaponMesh means a prior run (or hand work).
    existing_handle, existing = find_component_named(handles, WEAPON_COMPONENT_NAME)
    if existing is not None:
        return ("already has a '%s' component -- skipped (idempotent); socket "
                "resolved as '%s'" % (WEAPON_COMPONENT_NAME, socket))

    # Add the StaticMeshComponent under the skeletal mesh.
    params_cls = getattr(unreal, "AddNewSubobjectParams", None)
    if params_cls is None:
        raise StepSkip("unreal.AddNewSubobjectParams not bound -- add WeaponMesh "
                       "by hand (see manual notes)")
    params = params_cls()
    ok_parent = set_prop_if_exists(params, "parent_handle", skel_handle, "AddNewSubobjectParams")
    set_prop_if_exists(params, "new_class", unreal.StaticMeshComponent, "AddNewSubobjectParams")
    set_prop_if_exists(params, "blueprint_context", bp, "AddNewSubobjectParams")
    if not ok_parent:
        warn("%s: parent_handle did not set -- component may land under the root" % who)

    result = sds.add_new_subobject(params)
    # 5.x returns (handle, fail_reason Text) as a tuple from python; guard both shapes.
    if isinstance(result, tuple):
        new_handle, fail_reason = result[0], (result[1] if len(result) > 1 else "")
    else:
        new_handle, fail_reason = result, ""
    template = handle_object(new_handle)
    if template is None:
        raise RuntimeError("%s: add_new_subobject produced no live template "
                           "(fail_reason: %s)" % (who, fail_reason))
    log("%s: added subobject %s (fail_reason: '%s')"
        % (who, template.get_name(), fail_reason))

    # Rename to WeaponMesh (drift-guarded).
    renamed = False
    if hasattr(sds, "rename_subobject"):
        for new_name in (WEAPON_COMPONENT_NAME, unreal.Text(WEAPON_COMPONENT_NAME)):
            try:
                sds.rename_subobject(new_handle, new_name)
                renamed = True
                break
            except Exception:
                continue
    if not renamed:
        warn("%s: rename_subobject unavailable/failed -- component keeps its "
             "autogenerated name; idempotency on re-run will NOT see it. "
             "Rename it to '%s' in the BP editor." % (who, WEAPON_COMPONENT_NAME))
        MANUAL_NOTES.append("%s: rename the new StaticMeshComponent to '%s' in the "
                            "BP editor (python rename failed)." % (who, WEAPON_COMPONENT_NAME))

    # Configure the template (instanced-UObject writes -- the proven pattern).
    misses = []
    if not set_prop_if_exists(template, "static_mesh", sword_sm, who + ".WeaponMesh"):
        misses.append("static_mesh")
    if not set_prop_if_exists(template, "relative_location", GRIP_LOCATION):
        misses.append("relative_location")
    if not set_prop_if_exists(template, "relative_rotation", GRIP_ROTATION):
        misses.append("relative_rotation")
    collision_ok = False
    try:
        template.set_collision_profile_name("NoCollision")
        collision_ok = True
    except Exception:
        pass
    try:
        template.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        collision_ok = True
    except Exception:
        if not collision_ok:
            misses.append("collision (set NoCollision by hand)")

    socket_written = try_set_parent_socket(template, socket, who)

    # Verify the mesh assignment stuck (re-read).
    back = None
    try:
        back = template.get_editor_property("static_mesh")
    except Exception:
        pass
    if back is None or back.get_path_name() != sword_sm.get_path_name():
        misses.append("static_mesh DID NOT VERIFY on re-read")

    # Compile + force-save + re-gather verification.
    if hasattr(unreal, "BlueprintEditorLibrary"):
        try:
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
        except Exception as exc:
            warn("%s: compile_blueprint failed (%s) -- continuing to save" % (who, exc))
    force_save(bp)

    handles2 = gather_handles(sds, bp)
    check_name = WEAPON_COMPONENT_NAME if renamed else str(template.get_name())
    _, verify_obj = find_component_named(handles2, check_name)
    verified = verify_obj is not None
    if not verified:
        misses.append("component not found on post-save re-gather")

    # AUTHORITATIVE socket check: the template write above can pass its
    # re-read while the spawned pawn still attaches at the mesh root (the
    # SCS node's AttachToName wins at construction). Only a fresh-spawn
    # get_attach_socket_name() match counts as socket_ok.
    socket_ok = False
    sock_result, sock_why = verify_socket_on_spawn(bp, bp_path, socket, sword_sm, who)
    if sock_result is True:
        socket_ok = True
        log("%s: Parent Socket VERIFIED on a fresh spawn (%s)" % (who, sock_why))
    else:
        if sock_result is False:
            warn("%s: Parent Socket NOT effective (%s) -- sword will render at "
                 "the pelvis/origin until fixed by hand." % (who, sock_why))
        else:
            warn("%s: Parent Socket could not be spawn-verified (%s) -- treat "
                 "it as UNSET." % (who, sock_why))
        MANUAL_NOTES.append(
            "%s: Parent Socket '%s' did not verify on a fresh spawn (%s; "
            "template write %s). Open the BP, select WeaponMesh, Details -> "
            "Sockets -> Parent Socket -> '%s', compile, save. (Mesh, transform "
            "and collision ARE set -- only the socket needs the click.)"
            % (who, socket, sock_why,
               "appeared to stick" if socket_written else "also failed", socket))

    log("%s: WeaponMesh grip is a FIRST GUESS (loc %s / rot yaw=90). If the "
        "blade clips the forearm or points backward, nudge the relative "
        "transform in the BP viewport -- 30 seconds of eyeballing." % (who, GRIP_LOCATION))
    detail = ("mesh=%s socket=%s renamed=%s socket_spawn_verified=%s verified=%s"
              % (sword_sm.get_name(), socket, renamed, socket_ok, verified))
    if misses:
        detail += " -- MISSES: " + "; ".join(misses)
        warn("%s: %s" % (who, detail))
    return detail


# ---------------------------------------------------------------------------
# Step 1: resolve meshes + Niagara systems + notify class
# ---------------------------------------------------------------------------

def _sm_bounds_swordlike(sm):
    """Long-thin heuristic for the Medieval_MWP last resort: longest axis
    70-170 cm and >3x the middle axis (rules out shields/axes/maces-ish)."""
    try:
        box = sm.get_bounding_box()
        dims = sorted([abs(box.max.x - box.min.x),
                       abs(box.max.y - box.min.y),
                       abs(box.max.z - box.min.z)], reverse=True)
        return 70.0 <= dims[0] <= 170.0 and dims[1] > 0 and dims[0] / max(dims[1], 1e-3) > 3.0
    except Exception:
        return False


def pick_hero_sword():
    # 1. Weapons_Free registry scan for sword-ish StaticMesh names.
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        assets = registry.get_assets_by_path(HERO_SWORD_DIR_SCAN, recursive=True)
        for ad in assets or []:
            name = str(ad.asset_name)
            if SWORD_NAME_RE.search(name):
                asset = ad.get_asset()
                if isinstance(asset, unreal.StaticMesh):
                    log("Hero sword: found in Weapons_Free after all: %s" % name)
                    return asset
    except Exception as exc:
        warn("Weapons_Free registry scan failed (%s)" % exc)
    log("Hero sword: Weapons_Free has no sword SM (it is a modern firearms "
        "pack) -- falling through to RamsterZ OneHandSword_Mesh.")

    # 2. RamsterZ one-hand sword prop.
    asset = load_asset_if_exists(HERO_SWORD_EXPLICIT)
    if isinstance(asset, unreal.StaticMesh):
        return asset
    if asset is not None:
        warn("Hero sword: %s exists but is a %s, not a StaticMesh -- falling "
             "through" % (HERO_SWORD_EXPLICIT, asset.get_class().get_name()))

    # 3. Medieval_MWP bounds heuristic (48 unnamed SM_MMW_* meshes).
    try:
        for obj_path in unreal.EditorAssetLibrary.list_assets(
                HERO_SWORD_BOUNDS_SCAN, recursive=False):
            sm = unreal.EditorAssetLibrary.load_asset(obj_path)
            if isinstance(sm, unreal.StaticMesh) and _sm_bounds_swordlike(sm):
                log("Hero sword: bounds-heuristic pick from Medieval_MWP: %s "
                    "(VERIFY it is actually a sword -- the pack meshes are "
                    "unnamed)" % sm.get_name())
                MANUAL_NOTES.append(
                    "Hero sword came from the Medieval_MWP bounds heuristic (%s) "
                    "-- eyeball it in the BP viewport and swap the StaticMesh if "
                    "it is a spear/staff." % sm.get_name())
                return sm
    except Exception as exc:
        warn("Medieval_MWP scan failed (%s)" % exc)
    return None


def step1_resolve_assets():
    boss_sword = load_asset_if_exists(BOSS_SWORD_PATH)
    if not isinstance(boss_sword, unreal.StaticMesh):
        warn("Thornblade %s missing or not a StaticMesh" % BOSS_SWORD_PATH)
        boss_sword = None
    CTX["boss_sword"] = boss_sword

    CTX["hero_sword"] = pick_hero_sword()

    CTX["ns_hero"] = load_asset_if_exists(NS_TRAIL_HERO)
    CTX["ns_boss"] = load_asset_if_exists(NS_TRAIL_BOSS)

    # TimedNiagaraEffect class feature-detect.
    cls = None
    for path in TIMED_NIAGARA_CLASS_CANDIDATES:
        try:
            cls = unreal.load_class(None, path)
        except Exception:
            cls = None
        if cls is not None:
            log("TimedNiagaraEffect notify class: %s" % path)
            break
    if cls is None:
        candidates = [n for n in dir(unreal) if "niagara" in n.lower() and "notify" in n.lower()]
        warn("No TimedNiagaraEffect class at any known path. unreal-module "
             "notify-ish Niagara bindings present: %s" % (", ".join(candidates) or "<none>"))
    CTX["timed_niagara_cls"] = cls

    parts = []
    parts.append("boss sword=%s" % (boss_sword.get_name() if boss_sword else "MISSING"))
    parts.append("hero sword=%s" % (CTX["hero_sword"].get_name() if CTX["hero_sword"] else "MISSING"))
    parts.append("NS hero=%s boss=%s" % ("ok" if CTX["ns_hero"] else "MISSING",
                                         "ok" if CTX["ns_boss"] else "MISSING"))
    parts.append("notify class=%s" % ("ok" if cls else "MISSING"))
    if boss_sword is None and CTX["hero_sword"] is None and cls is None:
        raise RuntimeError("nothing resolved -- wrong project / packs not imported?")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Steps 2-3: WeaponMesh components
# ---------------------------------------------------------------------------

def step2_boss_weapon():
    return add_weapon_mesh(BP_BOSS_PATH, CTX.get("boss_sword"), "BP_Boss")


def step3_hero_weapon():
    return add_weapon_mesh(BP_HERO_PATH, CTX.get("hero_sword"), "BP_NeuralHero")


# ---------------------------------------------------------------------------
# Notify API (same detection tactic as place_feel_notifies.py)
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
    _resolve("tracks", ["get_animation_notify_track_names"],
             r"get_animation_notify_track_names")
    _resolve("add_track", ["add_animation_notify_track"], r"add_animation_notify_track")
    _resolve("length", ["get_sequence_length"], r"get_(sequence|play)_length")
    for key in ("events", "trig", "dur", "add_state", "tracks", "add_track", "length"):
        log("API %-10s -> %s" % (key, API_NAMES.get(key, "<unresolved>")))
    missing = [k for k in ("events", "trig", "add_state") if API.get(k) is None]
    if missing:
        raise RuntimeError("notify API missing (%s) -- trails must be placed "
                           "by hand" % ", ".join(missing))
    return "AnimationLibrary resolved (%s)" % LIB.__name__


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


def event_class_name(ev):
    """NOTE: 'notify_state_class' on FAnimNotifyEvent is the notify-state
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
            try:
                API["add_track"](m, TRACK_NAME, unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
                return TRACK_NAME
            except Exception as exc:
                warn("Could not add notify track '%s' on %s (%s) -- using an "
                     "existing track" % (TRACK_NAME, m.get_name(), exc))
    for preferred in ("FeelNotifies",):
        if preferred in names:
            return preferred
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
# Steps 4-5: slash trails
# ---------------------------------------------------------------------------

def set_verified(inst, prop, value, what):
    """Instanced-UObject write + re-read verify (the ONLY trusted write
    pattern in this repo -- struct-array write-backs silently fail)."""
    inst.set_editor_property(prop, value)
    back = inst.get_editor_property(prop)
    if isinstance(value, unreal.Object):
        ok = back is not None and back.get_path_name() == value.get_path_name()
    else:
        ok = str(back) == str(value)
    if not ok:
        raise RuntimeError("%s: wrote %s=%r but read back %r" % (what, prop, value, back))


def configure_trail_instance(inst, ns_system, socket_name, what):
    """Set Template/SocketName/bDestroyAtEnd on the created notify-state
    instance, feature-detecting the template property name."""
    template_prop = None
    for cand in ("template", "niagara_system", "system", "niagara_system_asset"):
        try:
            inst.get_editor_property(cand)
            template_prop = cand
            break
        except Exception:
            continue
    if template_prop is None:
        props = [n for n in dir(inst) if not n.startswith("_")][:40]
        raise RuntimeError("%s: no template-ish property found on %s; dir(): %s"
                           % (what, inst.get_class().get_name(), ", ".join(props)))
    set_verified(inst, template_prop, ns_system, what)
    try:
        set_verified(inst, "socket_name", socket_name, what)
    except Exception as exc:
        warn("%s: socket_name not set (%s) -- trail will spawn at component "
             "origin" % (what, exc))
    try:
        set_verified(inst, "destroy_at_end", True, what)
    except Exception as exc:
        log("%s: destroy_at_end not available (%s) -- fine for one-shot "
            "systems" % (what, exc))
    return template_prop


def _find_trail_instance(m):
    """The live notify-state instance of an existing TimedNiagaraEffect event
    on montage m (None when absent). Same event->instance access quirk as
    event_class_name: 'notify_state_class' holds the INSTANCE."""
    for ev in get_events(m):
        for prop in ("notify_state_class", "notify"):
            try:
                obj = ev.get_editor_property(prop)
            except Exception:
                continue
            if obj is not None and TIMED_NIAGARA_KEYWORD in str(obj.get_class().get_name()):
                return obj
    return None


def _trail_instance_configured(inst, ns_system, socket_name):
    """True when the existing instance already carries the wanted template +
    socket -- only then is 'skip (idempotent)' honest."""
    cur_tmpl = None
    for cand in ("template", "niagara_system", "system", "niagara_system_asset"):
        try:
            cur_tmpl = inst.get_editor_property(cand)
            break
        except Exception:
            continue
    if cur_tmpl is None or cur_tmpl.get_path_name() != ns_system.get_path_name():
        return False
    try:
        if str(inst.get_editor_property("socket_name")) != str(socket_name):
            return False
    except Exception:
        pass  # no socket prop on this class variant -- template match suffices
    return True


def place_trails(montages, ns_system, socket_name, group):
    cls = CTX.get("timed_niagara_cls")
    if cls is None:
        raise StepSkip("TimedNiagaraEffect class unavailable -- add the notify "
                       "state by hand on the %s montages (Template=%s, Socket=%s)"
                       % (group, ns_system.get_name() if ns_system else "?", socket_name))
    if ns_system is None:
        raise StepSkip("Niagara system missing for %s -- SlashTrail_SoftTofu "
                       "pack not imported?" % group)
    if not montages:
        raise StepSkip("no %s montages discovered" % group)

    placed, already, refreshed, no_window, failed = 0, 0, 0, 0, 0
    for m in montages:
        try:
            existing = _find_trail_instance(m)
            if existing is not None:
                # A bare 'exists' is NOT enough: a prior run may have added
                # the notify then died before configuring it (template unset
                # -> trail silently never spawns while the summary reads
                # clean). Mirror integrate_golem_minion._apply_damage_window:
                # re-apply + verify instance props on the existing notify,
                # saving only when something actually changed.
                if _trail_instance_configured(existing, ns_system, socket_name):
                    log("  %-32s already has a configured %s -- skipped "
                        "(idempotent)" % (m.get_name(), TIMED_NIAGARA_KEYWORD))
                    already += 1
                    continue
                tprop = configure_trail_instance(existing, ns_system, socket_name,
                                                 m.get_name() + ".trail(refresh)")
                force_save(m)
                log("  %-32s REFRESHED an existing but unconfigured %s "
                    "(prop '%s', socket %s)" % (m.get_name(),
                                                TIMED_NIAGARA_KEYWORD,
                                                tprop, socket_name))
                refreshed += 1
                continue
            window = deal_damage_window(m)
            if window is None:
                log("  %-32s no ANS_DealDamage window -- not an attack montage, "
                    "skipped" % m.get_name())
                no_window += 1
                continue
            length = montage_length(m)
            start = max(0.0, window[0] - TRAIL_PAD)
            end = min(length, window[1] + TRAIL_PAD)
            if end - start < MIN_WINDOW_DURATION:
                warn("  %-32s degenerate trail window (%.3f..%.3f)" % (m.get_name(), start, end))
                no_window += 1
                continue
            track = ensure_track(m)
            inst = API["add_state"](m, track, float(start), float(end - start), cls)
            if inst is None:
                raise RuntimeError("add_animation_notify_state_event returned None")
            tprop = configure_trail_instance(inst, ns_system, socket_name,
                                             m.get_name() + ".trail")
            force_save(m)
            log("  %-32s trail %s @ %.3f..%.3f s (track %s, prop '%s', socket %s)"
                % (m.get_name(), ns_system.get_name(), start, end, track, tprop, socket_name))
            placed += 1
        except Exception as exc:  # noqa: BLE001 - per-montage isolation
            failed += 1
            warn("  %-32s FAILED: %s" % (m.get_name(), exc))
            warn(traceback.format_exc())
    if placed == 0 and already == 0 and refreshed == 0 and failed > 0:
        raise RuntimeError("all placements failed (%d)" % failed)
    return ("placed %d, already-configured %d, refreshed-unconfigured %d, "
            "no-damage-window %d, failed %d"
            % (placed, already, refreshed, no_window, failed))


def step4_hero_trails():
    montages = []
    for d in COMBO_DIRS:
        montages += list_montages(d, lambda n: n.startswith("AM_"))
    socket = CTX.get("socket_BP_NeuralHero", SOCKET_FALLBACK)
    return place_trails(montages, CTX.get("ns_hero"), socket, "hero combo")


def step5_boss_trails():
    montages = list_montages(BOSS_DIR, lambda n: BOSS_ATTACK_RE.match(n) is not None)
    socket = CTX.get("socket_BP_Boss", SOCKET_FALLBACK)
    return place_trails(montages, CTX.get("ns_boss"), socket, "boss attack")


# ---------------------------------------------------------------------------
# Step 6: impact-FX recommendation (log-only, per instructions)
# ---------------------------------------------------------------------------

def step6_impact_fx_note():
    hero_ok = unreal.EditorAssetLibrary.does_asset_exist(NS_HIT_HERO_ONCE)
    boss_ok = unreal.EditorAssetLibrary.does_asset_exist(NS_HIT_BOSS_ONCE)
    log("-" * 60)
    log("IMPACT FX RECOMMENDATION (no C++ / component changes made):")
    log("  HitFeedbackComponent currently has no impact-particle hook. To add")
    log("  GoW-style hit sparks, give it a 'UNiagaraSystem* ImpactEffect'")
    log("  UPROPERTY spawned at the hit location in TriggerHitFeedback, then set:")
    log("    hero hits land -> %s  (exists: %s)" % (NS_HIT_HERO_ONCE, hero_ok))
    log("    boss hits land -> %s  (exists: %s)" % (NS_HIT_BOSS_ONCE, boss_ok))
    log("  (The *_Once variants are one-shot bursts -- the right fit for a")
    log("  per-hit spawn; the non-Once ones loop.)")
    log("-" * 60)
    return "suggestion logged (hero NS exists: %s, boss NS exists: %s)" % (hero_ok, boss_ok)


# ---------------------------------------------------------------------------
# Step 7: texture cap 2048 on the weapon/trail packs (session VRAM rule)
# ---------------------------------------------------------------------------

def _texture_paths_in(folder):
    """Texture2D package paths under folder via the asset registry (loading
    every asset in a pack just to type-check would be far slower) -- the
    dress_arena.py helper."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        assets = reg.get_assets_by_path(unreal.Name(folder), recursive=True)
    except Exception:
        assets = reg.get_assets_by_path(folder, recursive=True)
    out = []
    for ad in assets or []:
        cls = ""
        for attr in ("asset_class_path", "asset_class"):
            try:
                v = ad.get_editor_property(attr)
                cls = str(getattr(v, "asset_name", v))
                if cls:
                    break
            except Exception:
                continue
        if cls == "Texture2D":
            try:
                out.append(str(ad.get_editor_property("package_name")))
            except Exception:
                pass
    return out


def step7_texture_cap():
    dirs = list(WEAPON_TEX_DIRS)
    # + the pack of whichever hero sword mesh step 1 actually picked
    # (RamsterZ / Medieval_MWP / Weapons_Free -- resolved at runtime).
    hero = CTX.get("hero_sword")
    if hero is not None:
        pkg = str(hero.get_path_name()).split(".")[0]
        parts = pkg.split("/")  # ['', 'Game', '<PackRoot>', ...]
        if len(parts) > 2:
            pack_root = "/".join(parts[:3])
            if pack_root not in dirs:
                dirs.append(pack_root)
    capped, already, failed = 0, 0, 0
    for folder in dirs:
        if not unreal.EditorAssetLibrary.does_directory_exist(folder):
            log("texture cap: folder missing, skipping: %s" % folder)
            continue
        prefix = folder.rstrip("/") + "/"
        paths = _texture_paths_in(folder)
        log("texture cap: %d Texture2D under %s" % (len(paths), folder))
        for p in paths:
            try:
                tex = unreal.EditorAssetLibrary.load_asset(p)
                if tex is None or not isinstance(tex, unreal.Texture2D):
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
                # verify write-back stuck before trusting the save
                if int(tex.get_editor_property("max_texture_size")) != MAX_TEXTURE_SIZE:
                    raise RuntimeError("max_texture_size write-back did not stick")
                force_save(tex, extra_prefixes=(prefix,))
                capped += 1
                log("  capped %s -> max_texture_size=%d" % (tex.get_name(), MAX_TEXTURE_SIZE))
            except Exception as exc:  # noqa: BLE001 - per-item isolation
                failed += 1
                warn("  texture cap FAILED for %s: %s" % (p, exc))
    if capped == 0 and already == 0 and failed > 0:
        raise RuntimeError("every texture cap failed (%d)" % failed)
    return ("capped %d, already <=%d %d, failed %d (dirs: %s)"
            % (capped, MAX_TEXTURE_SIZE, already, failed, ", ".join(dirs)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log("=" * 70)
    log("equip_weapons_and_trails -- weapons in hands + slash trails + FX notes")
    log("=" * 70)

    run_step("0. Feature-detect notify API", step0_detect_api)
    run_step("1. Resolve meshes / Niagara / notify class", step1_resolve_assets)
    run_step("2. BP_Boss: WeaponMesh (Thornblade)", step2_boss_weapon)
    run_step("3. BP_NeuralHero: WeaponMesh (one-hand sword)", step3_hero_weapon)

    api_ok = STEP_RESULTS[0][1] == "PASS"
    if api_ok:
        run_step("4. Hero combos: slash trail (NS_SlashTrail_Basic)", step4_hero_trails)
        run_step("5. Boss attacks: slash trail (NS_SlashTrail_Dark)", step5_boss_trails)
    else:
        record_skip("4. Hero combos: slash trail (NS_SlashTrail_Basic)",
                    "notify API unavailable (step 0 failed)")
        record_skip("5. Boss attacks: slash trail (NS_SlashTrail_Dark)",
                    "notify API unavailable (step 0 failed)")

    run_step("6. Impact FX recommendation (log-only)", step6_impact_fx_note)
    run_step("7. Texture cap 2048 (weapon/trail packs)", step7_texture_cap)

    log("=" * 70)
    log("SUMMARY")
    for label, status, detail in STEP_RESULTS:
        log("  %-4s %-52s %s" % (status, label, detail))
    if MANUAL_NOTES:
        log("-" * 70)
        log("MANUAL FOLLOW-UPS:")
        for note in MANUAL_NOTES:
            log("  * " + note)
    log("Re-run safe: existing WeaponMesh components are skipped; montages with")
    log("a CONFIGURED TimedNiagaraEffect are skipped, unconfigured ones (from an")
    log("interrupted run) get their template/socket refreshed; capped textures")
    log("are skipped.")
    log("=" * 70)


main()
