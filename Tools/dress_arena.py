"""Set-dressing pass V2 for /Game/Maps/BossArena -- BEAUTIFICATION PLAN v2 (A/C/D).

Run headlessly (proven pattern -- in-editor python crashes this machine):
  UnrealEditor-Cmd.exe "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/dress_arena.py"
(or, if you must, editor Cmd console: py "D:/GAME_CORE 5.8/Tools/dress_arena.py")

LEVEL GUARD: the script VERIFIES the open level is /Game/Maps/BossArena
before touching anything; if a different map is focused it loads BossArena
via LevelEditorSubsystem, and if THAT fails it records FAIL for every step
and exits without spawning, destroying, or saving anything.

V2 steps (each isolated; one failure never aborts the rest):
   0. Pre-clean: destroy every ARENA_DRESS_* actor (v1's 78 included; idempotent).
   1. TEXTURE CAPS **BEFORE placement** (plan D): 2048 on the four v1 packs
      + the KiteDemo textures referenced by our picks (material->texture
      dependency walk, subfolder fallback); 1024 FORCED on the Cliff01 /
      Mountain_RockFace_002 sets (they live 90 m+ behind fog).
   2. ATMOSPHERE (plan A): finds the build_arena_level rig actors by LOOSE
      label match (ARENA_KeyLight / ARENA_SkyAtmosphere / ARENA_SkyLight /
      ARENA_HeightFog / ARENA_PostProcess -- a full label dump is logged
      first) and applies the "cold overcast dusk, warm key" numbers: sun
      pitch -25 / yaw 155, 3.5 lux @ 4250 K, light-shaft bloom+occlusion,
      colder SkyAtmosphere scattering, fog 0.028 w/ start_distance 3000 +
      warm directional inscattering + second ground-haze layer, exposure
      0.35..0.85, cool grade + split-tone, vignette 0.35. Volumetric fog
      stays OFF (visuals.md). FPostProcessSettings fields are set with
      their override_* siblings; struct write-backs are RE-READ verified.
   3. BLENDER MESHES: import SourceArt/Arena/SM_ArenaFloorRing.fbx +
      SM_MountainBackdrop.fbx (build_arena_level step-1 settings, Nanite
      OFF at import -- the DO_NANITE pass covers them), spawn both at
      origin (authored world-space), collision NoCollision on BOTH (floor
      ring: root-motion contract; backdrop: unreachable). Floor ring gets
      a NEW simple M_FloorRing (RockyPath set, world-XY mapped -- the
      build_arena_level fallback-material pattern; M_Terrain would slope-
      blend the carve away), backdrop reuses M_Terrain. Missing FBX = SKIP.
   4-12. DRESSING V2 DENSITY (plan C, ~500 pieces, seed 7):
      backdrop ring 20 / rim crown 34 (11 clusters) / bowl interior ~167
      (scree skirt arcs, half-buried rocks w/ slope lean + <2 m stand rule,
      shadowless ground cover) / fight-floor + lane DECALS <=16 / monolith
      court +8 / canyon flanks + vines/scree/rocks + Dusk_Spire gate
      assembly / pad ruins 16x3 (Paragon Ruins upgrade, MedCastle landmark
      kept) / zone field 135 (alive trees for contrast, capped 24) / zone
      perimeter 28.
  13. Keep-clear guard (decals/floor-ring/backdrop exempt -- flat/no-collision
      by construction, sanctioned inside the fight floor).
  14. COUNT BUDGET: hard cap 600 dress actors, per-mesh cap 80 (shadowless
      ground cover: 120 -- grass/heather/ferns/leaves share single meshes),
      foliage-class <=250, alive trees <=24; per-zone counts logged.
  15. Nanite on PLACED meshes (DO_NANITE flag, default False -- crash
      resistance; foliage/tree meshes are NEVER nanited).
  16. Save level + PASS/FAIL/SKIP summary.

KEEP-CLEAR CONTRACT (by construction AND the final guard):
  - fight floor r < 2000 around (0,0): ZERO meshes -- only the flat
    no-collision floor ring + decals (exempt labels)
  - entrance corridor x 10000..13500, |y| < 1200 stays WALKABLE
    (gate assembly sits at x >= 13720, pillars at |y| 1350)
  - pad centers: nothing within 400 UU (minion spawns).

Placement is deterministic (random.Random(7)); labels ARENA_DRESS_<zone>_NN.
Only ARENA_DRESS_* actors are ever destroyed. Asset writes: texture caps in
the pack folders, Nanite flags on placed meshes, M_FloorRing in
/Game/Arena/Materials, imports into /Game/Arena/Meshes -- all with the
proven force-save + on-disk-mtime-verify pattern where it matters.
"""

import math
import os
import random
import traceback

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[ArenaDress]"
LABEL_PREFIX = "ARENA_DRESS_"
MAP_PATH = "/Game/Maps/BossArena"       # the ONLY level this script may touch
RNG = random.Random(7)  # deterministic layout

# Map geometry (UU) -- see CLAUDE.md / build_arena_level.py
FIGHT_FLOOR_KEEPOUT_R = 2100.0          # r < 2000 must stay empty (+margin)
CORRIDOR_X = (9800.0, 13700.0)          # walkable lane keep-out (+margin)
CORRIDOR_HALF_Y = 1300.0                # |y| < 1200 walkable (+margin)
RIM_R = (7950.0, 8600.0)                # crest ring (ARENA_BV_Wall_* r~7700-7900)
ENTRANCE_HALF_ANGLE_DEG = 20.0          # skip sector around +X
MONOLITH_XY = (-3200.0, 2400.0)
COURT_R = (600.0, 1200.0)
GATE_X = (9800.0, 13800.0)
GATE_ABS_Y = (1300.0, 2200.0)
PAD_CENTERS = [(17000.0, -4000.0), (22000.0, 3500.0), (29000.0, -1500.0)]
PAD_WALL_R = (1600.0, 2000.0)
PAD_CENTER_KEEPOUT = 400.0              # minion spawn ring safety
ZONE_RECT = (10000.0, 35000.0, -8500.0, 8500.0)  # x_min, x_max, y_min, y_max
SINK_CM = (10.0, 30.0)                  # default ground sink per piece

# V2 zones (plan C)
BACKDROP_R = (9000.0, 25000.0)
BOWL_R = (2100.0, 6800.0)
SCREE_SKIRT_R = (6300.0, 6900.0)
BOWL_ROCK_R = (2400.0, 6500.0)
BOWL_MAX_STAND_CM = 200.0               # nothing taller than 2 m in the bowl
DUSK_GATE_X = (13720.0, 13900.0)        # OUTSIDE corridor keep-clear (13700)
DUSK_GATE_PILLAR_Y = 1350.0

# Perf guardrails (plan D)
HARD_CAP = 600                          # dress-actor ceiling, asserted post-pass
PER_MESH_CAP = 80                       # per mesh type
GROUND_COVER_PER_MESH_CAP = 120         # shadowless ground cover ONLY (grass/
                                        # heather/ferns/leaves): the one class
                                        # where 80+ of a single mesh is intended
                                        # (bowl grass 60 + desire-line grass 45
                                        # share SM_FieldGrass_01)
FOLIAGE_CAP = 250                       # total foliage-class instances
ALIVE_TREE_CAP = 24
DECAL_CAP = 16

TRACE_TOP_Z = 20000.0                   # crest may be tall; trace well above
TRACE_BOTTOM_Z = -5000.0

PACK_DIRS = [
    "/Game/ParagonProps",
    "/Game/Medieval_MWP",
    "/Game/MedCastle",
    "/Game/ForestOfSpikes",
]
MAX_TEX_SIZE = 2048
KITE_ROOT = "/Game/KiteDemo"
# Backdrop-only sets forced to 1024 (90 m+ behind fog; 2048 is wasted pool)
KITE_1024_DIRS = [
    KITE_ROOT + "/Environments/Cliffs/Cliff01",
    KITE_ROOT + "/Environments/Rocks/Mountain_RockFace_002",
]
# Subfolder fallback when the dependency walk API is unavailable: cap only
# the KiteDemo subtrees our palette actually pulls from (never all of KiteDemo).
KITE_FALLBACK_DIRS = [
    KITE_ROOT + "/Environments/Rocks",
    KITE_ROOT + "/Environments/Cliffs/Cliff01",
    KITE_ROOT + "/Environments/Foliage",
    KITE_ROOT + "/Environments/Trees",
    KITE_ROOT + "/Environments/GroundTiles/RockyPath",
    KITE_ROOT + "/Environments/GroundTiles/Grass",
]

# Blender additions (plan B assets, imported here per the v2 task)
SOURCE_ARENA_DIR = r"D:\GAME_CORE 5.8\SourceArt\Arena"
MESH_DIR = "/Game/Arena/Meshes"
MAT_DIR = "/Game/Arena/Materials"
FLOOR_RING_NAME = "SM_ArenaFloorRing"
BACKDROP_NAME = "SM_MountainBackdrop"
RING_TEX_D = KITE_ROOT + "/Environments/GroundTiles/RockyPath/T_GDC_StonePath_Tile_D_R"
RING_TEX_N = KITE_ROOT + "/Environments/GroundTiles/RockyPath/T_GDC_StonePath_Tile_N"
RING_TEX_SIZE_UU = 300.0

# ---------------------------------------------------------------------------
# Curated palette V2. Missing assets warn + drop (valid_palette).
# Every path below verified against Content/ on disk 2026-07-05
# (plan's "HillTree_02" has no mesh asset -- the real one is HillTree_Tall_02).
# ---------------------------------------------------------------------------

_PP = "/Game/ParagonProps"
_MC = "/Game/MedCastle/Mesh"
_FS = "/Game/ForestOfSpikes/Meshes"
_KD = KITE_ROOT + "/Environments"
_RU = _PP + "/Monolith/Ruins/Meshes"
_DK = _PP + "/Monolith/Dusk/Meshes"
_MO = _PP + "/Monolith/Rocks/Meshes"
_AG = _PP + "/Agora/Rocks/Meshes"

NORDIC = ["%s/SM_RockNordic_%02d" % (_MO, i) for i in range(1, 9)]
NORDIC_SMALL = ["%s/SM_RockNordic_Small_%02d" % (_MO, i) for i in range(1, 5)]
SCREE = [
    _KD + "/Rocks/Scree001/Scree_001",
    _KD + "/Rocks/Scree001/Scree_001_A",
    _KD + "/Rocks/Scree001/Scree_001_B",
    _KD + "/Rocks/Scree002/SM_Scree002_NEW",
    _KD + "/Rocks/Scree002/SM_Scree002_Bend",
    _KD + "/Rocks/Scree002/SM_Scree002a",
    _KD + "/Rocks/Scree002/SM_Scree002b",
]

PALETTE = {
    # --- Backdrop ring r 9000-25000 (plan C: 20 pieces) ---
    "backdrop_cliff": [_KD + "/Cliffs/Cliff01/SM_Cliff01"],
    "backdrop_mountain": [
        _KD + "/Rocks/Mountain_RockFace_002/SM_MountainRock",
        _KD + "/Rocks/Mountain_RockFace_002/SM_MountainRock_Closed",
    ],
    "backdrop_volcanic": [
        _KD + "/Rocks/Large_Volcanic_Rock_001/LargeVolcanicRock_001",
        _KD + "/Rocks/Large_Volcanic_Rock_001/LargeVolcanicRock_002",
        _KD + "/Rocks/Large_Volcanic_Rock_001/LargeVolcanicRock_004",
    ],
    # --- Rim crown (34, clustered): v1 palette + MountainRock_Closed + Nordics
    "rim": [
        _PP + "/Agora/Props/Meshes/SM_Angelsjon_TriPillar",
        _AG + "/SM_HadriansWall",
        _AG + "/SM_HadriansWall_RockFace_002_RotatedFlat_NoGrass",
        _AG + "/SM_Agelsjon02_Cliff",
        _AG + "/SM_Agelsjon_Rock_Boulder_1",
        _AG + "/SM_LargePlainsBoulder002",
        _DK + "/SM_Dusk_WallA_Endcap01",
        _DK + "/SM_Dusk_WallA_Endcap02",
        _DK + "/SM_Dusk_WallA_Endcap_Spike",
        _KD + "/Rocks/Mountain_RockFace_002/SM_MountainRock_Closed",
    ] + NORDIC,
    # --- Bowl interior (plan C ~170) ---
    "bowl_scree": SCREE,
    "bowl_rocks": [
        _KD + "/Rocks/River_Rock_01/SM_River_Rock_01",
        _KD + "/Rocks/GroundRevealRock001/SM_GroundRevealRock001",
        _KD + "/Rocks/Medium_Boulder_001/Medium_Boulder_001",
        _KD + "/Rocks/Medium_Boulder_002/Medium_Boulder_LowPoly",
    ] + NORDIC_SMALL,
    "grass": [_KD + "/Foliage/Grass/FieldGrass/SM_FieldGrass_01"],
    "heather": [_KD + "/Foliage/Flowers/Heather/SM_Heather_Mesh_Clumps2"],
    "ferns": [
        _KD + "/Foliage/Ferns/SM_Fern_01",
        _KD + "/Foliage/Ferns/SM_Fern_02",
        _KD + "/Foliage/Ferns/SM_Fern_03",
    ],
    # --- Monolith court: v1 palette + the +8 upgrade pieces ---
    "court": [
        _DK + "/SM_Dusk_WallA_Endcap_Firepit",
        _PP + "/Agora/Props/Meshes/SM_Angelsjon_TriPillar",
        _PP + "/Agora/Props/Meshes/SM_Stairs_PM",
        _PP + "/Agora/Props/Meshes/SM_StairsEnd_PM",
        _PP + "/Agora/Props/Meshes/SM_Stairs_PM_2x3",
        _MO + "/SM_RockNordic_Small_01",
        _MO + "/SM_RockNordic_Small_02",
        _MO + "/SM_RockNordic_Small_03",
        _MC + "/Props/SM_Statue7",  # centerpiece accent
    ],
    "court_add_pillars": [
        _RU + "/JunglePillarBlockPiece_CombinedA",
        _RU + "/JunglePillarBlockPiece_CombinedB",
        _RU + "/JunglePillarBlockPiece_CombinedC",
    ],
    "court_add_trims": [
        _RU + "/Ruins_TrimStone_B",
        _RU + "/Ruins_TrimStone_D",
        _RU + "/Ruins_TrimStone_E",
    ],
    "dead_leaves": [_KD + "/Foliage/Leaves/SM_DeadLeaves"],
    "dead_leaves_flat": [_KD + "/Foliage/Leaves/SM_DeadLeaves_Flat"],
    # --- Canyon (v1 flanks kept + V2 additions + Dusk gate) ---
    "gate_trees": [
        _FS + "/Sm_SpikeTree_01",
        _FS + "/Sm_SpikeTree_09",
        _FS + "/Sm_SpikeTree_10",
        _FS + "/Sm_SpikeTree_11",
        _FS + "/Sm_SpikeTree_12",
        _FS + "/Sm_SpikeTree_14",
    ],
    "gate_rocks": [
        _FS + "/SM_Rock_01",
        _FS + "/SM_Rock_02",
        _FS + "/SM_Rock_03",
    ],
    "canyon_vines": [
        _FS + "/Sm_SpikeTree_GroundVines",
        _FS + "/Sm_SpikeTree_GroundVines_Hi",
    ],
    # --- Pad ruins upgrade (Paragon Ruins; MedCastle landmark kept from v1) ---
    "pad_walls": [
        _RU + "/JungleWall_02A",
        _RU + "/JungleWall_02B",
        _RU + "/JungleWall_02A_Curved01",
        _RU + "/JungleWall_02A_Curved02",
        _RU + "/JungleWall_02A_Curved03",
        _RU + "/JungleWall_02A_Curved04",
    ],
    "pad_pillars": [
        _RU + "/JunglePillarBlock_01A",
        _RU + "/JunglePillarBlock_02B",
        _RU + "/JunglePillarBlockPiece_CombinedA",
        _RU + "/JunglePillarBlockPiece_CombinedB",
        _RU + "/JunglePillarBlockPiece_CombinedC",
        _RU + "/JunglePillarBlockPiece_CombinedD1",
        _RU + "/JunglePillarBlockPiece_CombinedD2",
        _RU + "/JunglePillarBlockPiece_CombinedD3",
    ],
    "pad_rubble": [_RU + "/JungleRubblePile_A"],
    "pad_trims": [
        _RU + "/JungleTrim01_100",
        _RU + "/JungleTrim01_150",
        _RU + "/JungleTrim01_250",
        _RU + "/JungleTrim01Broken_100",
        _RU + "/JungleTrim01Broken_150",
        _RU + "/JungleTrim01Broken_250",
    ],
    "pad_landmarks": [
        _MC + "/Houses_Towers/SM_CastleTowerTall",
        _MC + "/Houses_Towers/SM_TowerA",
        _MC + "/Houses_Towers/SM_WatchC",
    ],
    # --- Zone field (135) ---
    "field_rocks": NORDIC,
    "field_boulders": [_KD + "/Rocks/Medium_Boulder_001/Medium_Boulder_001"],
    "field_pines": [
        _KD + "/Trees/ScotsPine_01/ScotsPine_01",
        _KD + "/Trees/ScotsPineTall_01/ScotsPineTall_01",
    ],
    "field_hilltrees": [_KD + "/Trees/HillTree_Tall_02/HillTree_Tall_02"],
    "field_stumps": [_KD + "/Trees/Tree_Stump_01/Tree_Stump_01"],
    "field_bushes": [
        _KD + "/Foliage/BogMyrtleBush_01/BogMyrtleBush_01",
        _KD + "/Foliage/BogMyrtleBush_02/BogMyrtleBush_02",
    ],
    "field_debris": [_KD + "/Trees/Vegetation_Debris_002/SM_Vegetation_Debris_002"],
    # --- Zone perimeter (28) ---
    "perimeter_walls": [
        _AG + "/SM_HadriansWall",
        _AG + "/SM_HadriansWall_RockFace_002_RotatedFlat_NoGrass",
    ],
    "perimeter_cliffs": [_AG + "/SM_Agelsjon02_Cliff"],
}

# Dusk Spire gate assembly (exact pieces, not scattered -- placed by hand math)
DUSK_GATE = {
    "gate": _DK + "/Dusk_Spire_Gate",
    "top": _DK + "/Dusk_Spire_Gate_Top",
    "pillar_a": _DK + "/Dusk_Spire_Gate_Pillar_A",
    "pillar_b": _DK + "/Dusk_Spire_Gate_Pillar_B",
    "filler": _DK + "/Dusk_Spire_Gate_Filler",
}

DECAL_CRACK_MATS = [
    _PP + "/Ground/Materials/M_Decal2_Inst",
    _PP + "/Ground/Materials/M_Decal2_Inst1",
]
DECAL_WET_MAT = _PP + "/Ground/Materials/M_WetDecal2_Inst"

# Foliage-class / alive-tree classification for the perf caps (plan D)
FOLIAGE_MARKERS = ("/Foliage/", "/FieldGrass/", "/Heather/", "/Ferns/",
                   "/Leaves/", "/BogMyrtleBush", "/Vegetation_Debris")
ALIVE_TREE_MARKERS = ("/ScotsPine", "/HillTree")
# Shadowless ground cover gets its own (higher) per-mesh cap; still counted
# against the foliage-class cap (250).
GROUND_COVER_MARKERS = ("/FieldGrass/", "/Heather/", "/Ferns/", "/Leaves/")
# Foliage/tree shaders are NEVER nanited -- includes the ForestOfSpikes trees
# and ground vines (Sm_SpikeTree_*), which live outside the KiteDemo markers.
NANITE_NEVER_MARKERS = FOLIAGE_MARKERS + ("/Trees/", "/ForestOfSpikes/")

STEP_RESULTS = []   # (step label, "PASS"/"FAIL"/"SKIP", detail)
SPAWNED = []        # actors created this run (trace ignore list + guard + cap)
USED_MESHES = {}    # asset path -> unreal.StaticMesh (load CACHE)
PLACED_MESHES = {}  # asset path -> StaticMesh ACTUALLY spawned (Nanite pass)
IGNORE_ACTORS = []  # invisible ARENA_BV_* blocking volumes -- never a snap surface
CTX = {"trace_ok": True}
ZONE_COUNTS = {}    # zone tag -> spawned count (budget log)
MESH_COUNTS = {}    # asset path -> spawned count (per-mesh cap 80)
COUNTS = {"foliage": 0, "alive_trees": 0, "decals": 0}
# Labels the keep-clear guard must NOT destroy: sanctioned flat/no-collision
# fight-floor dressing (plan: "floor ring + decals only").
GUARD_EXEMPT_SUBSTRINGS = ("_DECAL_", "_FLOORRING", "_BACKDROP")


# --- Crash resistance ------------------------------------------------------
# Nanite OFF by default (flip DO_NANITE and re-run for that pass alone), and
# periodic garbage collection during save loops and between steps (16 GB box).
DO_NANITE = False
GC_EVERY_SAVES = 12
_SAVE_COUNT = [0]


def gc_now():
    try:
        unreal.SystemLibrary.collect_garbage()
    except Exception:
        pass


def log(msg):
    unreal.log("%s %s" % (TAG, msg))


def warn(msg):
    unreal.log_warning("%s %s" % (TAG, msg))


def record(step, status, detail=""):
    STEP_RESULTS.append((step, status, detail))
    log("%-28s %-4s %s" % (step, status, detail))


# ---------------------------------------------------------------------------
# Editor helpers (patterns proven in build_arena_level.py / place_feel_notifies.py)
# ---------------------------------------------------------------------------

def get_actor_subsystem():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def get_editor_world():
    if hasattr(unreal, "UnrealEditorSubsystem"):
        try:
            sub = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            if sub is not None:
                world = sub.get_editor_world()
                if world is not None:
                    return world
        except Exception:
            pass
    if hasattr(unreal, "EditorLevelLibrary"):  # deprecated fallback, still in 5.x
        try:
            return unreal.EditorLevelLibrary.get_editor_world()
        except Exception:
            pass
    return None


def _world_package(world):
    """Package path of a UWorld, e.g. '/Game/Maps/BossArena' (drift-tolerant)."""
    if world is None:
        return ""
    try:
        name = str(world.get_outer().get_name())
        if name.startswith("/"):
            return name
    except Exception:
        pass
    try:
        return str(world.get_path_name()).split(".")[0]
    except Exception:
        return ""


def ensure_bossarena_open():
    """BLOCKER guard: refuse to dress + save whatever level happens to be
    focused. Verifies the open world IS BossArena; if not, loads it and
    re-verifies. Returns True only when the arena is confirmed open."""
    pkg = _world_package(get_editor_world())
    if pkg == MAP_PATH:
        log("Level guard: %s is open -- proceeding." % MAP_PATH)
        return True
    warn("Level guard: open level is '%s', NOT %s -- loading the arena..."
         % (pkg or "<unresolvable>", MAP_PATH))
    try:
        if not unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
            raise RuntimeError("%s does not exist on disk" % MAP_PATH)
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is None:
            raise RuntimeError("LevelEditorSubsystem unavailable")
        if not les.load_level(MAP_PATH):
            raise RuntimeError("load_level returned False")
    except Exception as exc:
        warn("Level guard: could not load %s (%s)" % (MAP_PATH, exc))
        return False
    pkg = _world_package(get_editor_world())
    if pkg != MAP_PATH:
        warn("Level guard: after load_level the open world is still '%s'" % pkg)
        return False
    log("Level guard: loaded %s." % MAP_PATH)
    return True


def collect_trace_ignores():
    """One-time sweep for the level's INVISIBLE BlockAll cubes (ARENA_BV_*).
    ground_z must ignore them or pieces snap onto hidden 30 m wall tops."""
    del IGNORE_ACTORS[:]
    try:
        for a in get_actor_subsystem().get_all_level_actors():
            try:
                if a is not None and str(a.get_actor_label()).startswith("ARENA_BV_"):
                    IGNORE_ACTORS.append(a)
            except Exception:
                continue
        log("ground_z will ignore %d ARENA_BV_* blocking volumes" % len(IGNORE_ACTORS))
    except Exception as exc:
        warn("Could not collect the ARENA_BV_* trace ignore list (%s) -- "
             "eyeball the crest after the run." % exc)


def _hit_result_z(hit):
    """Z of a HitResult hit point, tolerant of 5.x python field renames."""
    for name in ("location", "impact_point", "impact_location", "hit_location"):
        try:
            v = hit.get_editor_property(name)
            if v is not None and hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    for name in [n for n in dir(hit)
                 if ("impact" in n or "location" in n) and not n.startswith("_")]:
        try:
            v = getattr(hit, name)
            if hasattr(v, "z"):
                return float(v.z)
        except Exception:
            continue
    raise AttributeError(
        "no location-like field on HitResult; available: %s"
        % [n for n in dir(hit) if not n.startswith("__")][:40])


def ground_z(x, y, default_z=0.0):
    """Line-trace straight down at (x, y); returns hit Z or default_z.
    Ignores everything this run spawned AND the ARENA_BV_* cubes."""
    if not CTX["trace_ok"]:
        return default_z
    try:
        world = get_editor_world()
        if world is None:
            raise RuntimeError("no editor world available for tracing")
        hit = unreal.SystemLibrary.line_trace_single(
            world,
            unreal.Vector(x, y, TRACE_TOP_Z),
            unreal.Vector(x, y, TRACE_BOTTOM_Z),
            getattr(unreal.TraceTypeQuery, "ECC_VISIBILITY",
                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1),
            True,  # trace complex
            list(SPAWNED) + list(IGNORE_ACTORS),
            unreal.DrawDebugTrace.NONE,
            True,
        )
        if isinstance(hit, tuple):
            hit = hit[-1] if hit and hit[0] else None
        if hit is None:
            return default_z
        return _hit_result_z(hit)
    except Exception as exc:
        if CTX["trace_ok"]:
            warn("Ground trace unavailable (%s) -- everything snaps to z=%.0f. "
                 "Eyeball-fix floaters manually." % (exc, default_z))
            CTX["trace_ok"] = False
        return default_z


def slope_lean(x, y, yaw_deg, max_deg=12.0, probe=100.0):
    """Slope-aware pitch/roll (plan C): sample ground_z ahead of and beside
    the piece and lean it into the terrain, clamped to +-max_deg. Rocks only;
    trees stay vertical (caller's choice)."""
    if not CTX["trace_ok"]:
        return 0.0, 0.0
    rad = math.radians(yaw_deg)
    fx, fy = math.cos(rad), math.sin(rad)
    z0 = ground_z(x, y)
    z_fwd = ground_z(x + fx * probe, y + fy * probe, z0)
    z_rgt = ground_z(x - fy * probe, y + fx * probe, z0)
    pitch = max(-max_deg, min(max_deg, math.degrees(math.atan2(z_fwd - z0, probe))))
    roll = max(-max_deg, min(max_deg, math.degrees(math.atan2(z_rgt - z0, probe))))
    return pitch, roll


def load_mesh(asset_path):
    """Load + cache a StaticMesh; None (with a warn) when missing/not a SM."""
    if asset_path in USED_MESHES:
        return USED_MESHES[asset_path]
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        warn("Palette asset missing on disk: %s" % asset_path)
        return None
    asset = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not isinstance(asset, unreal.StaticMesh):
        warn("Palette asset is not a StaticMesh (skipped): %s" % asset_path)
        return None
    USED_MESHES[asset_path] = asset
    return asset


def mesh_bounds(mesh):
    """(origin Vector, extent Vector) in LOCAL space; feature-detected."""
    for getter in ("get_bounds", "get_bounding_box"):
        try:
            b = getattr(mesh, getter)()
            if hasattr(b, "box_extent"):
                return b.origin, b.box_extent
            if hasattr(b, "min") and hasattr(b, "max"):
                mn, mx = b.min, b.max
                origin = unreal.Vector((mn.x + mx.x) / 2.0,
                                       (mn.y + mx.y) / 2.0,
                                       (mn.z + mx.z) / 2.0)
                extent = unreal.Vector((mx.x - mn.x) / 2.0,
                                       (mx.y - mn.y) / 2.0,
                                       (mx.z - mn.z) / 2.0)
                return origin, extent
        except Exception:
            continue
    return None, None


def base_offset_z(mesh):
    """Pivot-to-base distance (bounds bottom below pivot). Pack pivots are
    inconsistent (center vs base); without this a center-pivot boulder ends
    up half-buried by accident instead of by design."""
    origin, extent = mesh_bounds(mesh)
    if origin is None:
        return 0.0
    return float(origin.z - extent.z)  # negative => bottom below pivot


def mesh_height(mesh, scale=1.0):
    _, ext = mesh_bounds(mesh)
    return (2.0 * float(ext.z) * scale) if ext is not None else 0.0


def set_prop_if_exists(obj, name, value, context=""):
    """set_editor_property guarded for properties that may have moved in 5.8."""
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        warn("Could not set '%s'%s: %s" % (name, (" on " + context) if context else "", exc))
        return False


def set_first_prop(obj, names, value, context=""):
    """Try candidate property names in order (5.x python renames); warn once
    if NONE stick. Returns True on the first success."""
    for n in names:
        try:
            obj.set_editor_property(n, value)
            return True
        except Exception:
            continue
    warn("None of %s settable%s" % (list(names), (" on " + context) if context else ""))
    return False


# ---------------------------------------------------------------------------
# Keep-clear contract
# ---------------------------------------------------------------------------

def placement_forbidden(x, y):
    """Returns a reason string when (x, y) violates the keep-clear contract,
    else None."""
    if math.hypot(x, y) < FIGHT_FLOOR_KEEPOUT_R:
        return "fight floor (r<%.0f)" % FIGHT_FLOOR_KEEPOUT_R
    if CORRIDOR_X[0] <= x <= CORRIDOR_X[1] and abs(y) < CORRIDOR_HALF_Y:
        return "entrance corridor"
    for px, py in PAD_CENTERS:
        if math.hypot(x - px, y - py) < PAD_CENTER_KEEPOUT:
            return "pad center (minion spawn)"
    return None


def in_zone_rect(x, y, margin=500.0):
    return (ZONE_RECT[0] - margin <= x <= ZONE_RECT[1] + margin
            and ZONE_RECT[2] - margin <= y <= ZONE_RECT[3] + margin)


def guard_exempt(label):
    return any(s in label for s in GUARD_EXEMPT_SUBSTRINGS)


# ---------------------------------------------------------------------------
# Spawning
# ---------------------------------------------------------------------------

def _zone_of(label):
    rest = label[len(LABEL_PREFIX):] if label.startswith(LABEL_PREFIX) else label
    return rest.split("_")[0] if rest else "?"


def _bump_counts(asset_path, label):
    ZONE_COUNTS[_zone_of(label)] = ZONE_COUNTS.get(_zone_of(label), 0) + 1
    MESH_COUNTS[asset_path] = MESH_COUNTS.get(asset_path, 0) + 1
    if any(m in asset_path for m in FOLIAGE_MARKERS):
        COUNTS["foliage"] += 1
    if any(m in asset_path for m in ALIVE_TREE_MARKERS):
        COUNTS["alive_trees"] += 1


def _per_mesh_cap_for(asset_path):
    """Ground cover (grass/heather/ferns/leaves) gets the higher cap; every
    other mesh keeps the flat 80."""
    return (GROUND_COVER_PER_MESH_CAP
            if any(m in asset_path for m in GROUND_COVER_MARKERS)
            else PER_MESH_CAP)


def _cap_blocked(asset_path):
    """Per-mesh (80; ground cover 120) / foliage-class (250) / alive-tree (24)
    / hard (600) ceilings enforced AT SPAWN so the budget can't be blown,
    only logged."""
    if len(SPAWNED) >= HARD_CAP:
        return "hard cap %d" % HARD_CAP
    mesh_cap = _per_mesh_cap_for(asset_path)
    if MESH_COUNTS.get(asset_path, 0) >= mesh_cap:
        return "per-mesh cap %d" % mesh_cap
    if any(m in asset_path for m in FOLIAGE_MARKERS) and COUNTS["foliage"] >= FOLIAGE_CAP:
        return "foliage cap %d" % FOLIAGE_CAP
    if any(m in asset_path for m in ALIVE_TREE_MARKERS) and COUNTS["alive_trees"] >= ALIVE_TREE_CAP:
        return "alive-tree cap %d" % ALIVE_TREE_CAP
    return None


def spawn_piece(asset_path, x, y, yaw, scale=1.0, label="", pitch=0.0, roll=0.0,
                sink_cm=None, sink_frac=None, cast_shadow=None,
                bypass_keepclear=False, max_stand_cm=None):
    """Ground-snapped deterministic spawn. Returns the actor or None (logged).

    sink_cm: (lo, hi) cm range; sink_frac: (lo, hi) fraction of scaled bounds
    height (plan C class rules); max_stand_cm: raise the sink until no more
    than this pokes above ground (bowl <2 m readability rule);
    cast_shadow=False: shadowless ground cover (VSM discipline, plan D)."""
    if not bypass_keepclear:
        reason = placement_forbidden(x, y)
        if reason is not None:
            warn("SKIP %s at (%.0f, %.0f): violates keep-clear [%s]" % (label, x, y, reason))
            return None
    cap = _cap_blocked(asset_path)
    if cap is not None:
        warn("SKIP %s: %s reached (%s)" % (label, cap, asset_path.rsplit("/", 1)[-1]))
        return None
    mesh = load_mesh(asset_path)
    if mesh is None:
        return None
    gz = ground_z(x, y)
    height = mesh_height(mesh, scale)
    if sink_frac is not None:
        sink = height * RNG.uniform(sink_frac[0], sink_frac[1])
    elif sink_cm is not None:
        sink = RNG.uniform(sink_cm[0], sink_cm[1])
    else:
        sink = RNG.uniform(SINK_CM[0], SINK_CM[1])
    if max_stand_cm is not None and height - sink > max_stand_cm:
        sink = min(height * 0.6, height - max_stand_cm)
    # Place the mesh BOTTOM at (ground - sink), whatever the pivot convention.
    z = gz - sink - base_offset_z(mesh) * scale
    actor = get_actor_subsystem().spawn_actor_from_object(
        mesh, unreal.Vector(x, y, z),
        unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw))
    if actor is None:
        warn("spawn_actor_from_object returned None for %s" % label)
        return None
    actor.set_actor_label(label)
    try:
        actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    except Exception as exc:
        warn("Could not scale %s: %s" % (label, exc))
    if cast_shadow is False:
        try:
            comp = actor.get_component_by_class(unreal.StaticMeshComponent)
            if comp is not None:
                comp.set_editor_property("cast_shadow", False)
        except Exception as exc:
            warn("Could not disable cast_shadow on %s: %s" % (label, exc))
    SPAWNED.append(actor)
    PLACED_MESHES[asset_path] = mesh
    _bump_counts(asset_path, label)
    log("  + %-34s %-46s (%.0f, %.0f, %.0f) yaw %.0f scale %.2f"
        % (label, asset_path.rsplit("/", 1)[-1], x, y, z, yaw, scale))
    return actor


def valid_palette(key):
    """Palette entries that actually exist on disk (warn + drop the rest)."""
    out = []
    for p in PALETTE[key]:
        if unreal.EditorAssetLibrary.does_asset_exist(p):
            out.append(p)
        else:
            warn("Palette[%s] missing: %s" % (key, p))
    return out


def cluster_points(n_total, center_fn, cluster_size=(2, 4), spread=(150.0, 450.0),
                   outlier_chance=0.5):
    """Plan C global scatter rule: clusters of 2-4 with one outlier at 2-3x
    the cluster radius (about half the clusters get one). center_fn() returns
    a candidate (x, y) cluster center. Yields (x, y, is_outlier)."""
    made = 0
    guard = 0
    while made < n_total and guard < n_total * 20:
        guard += 1
        cx, cy = center_fn()
        k = RNG.randint(cluster_size[0], cluster_size[1])
        radius = RNG.uniform(spread[0], spread[1])
        for _ in range(min(k, n_total - made)):
            ang = RNG.uniform(0.0, 2.0 * math.pi)
            r = RNG.uniform(0.0, radius)
            yield cx + r * math.cos(ang), cy + r * math.sin(ang), False
            made += 1
        if made < n_total and RNG.random() < outlier_chance:
            ang = RNG.uniform(0.0, 2.0 * math.pi)
            r = radius * RNG.uniform(2.0, 3.0)
            yield cx + r * math.cos(ang), cy + r * math.sin(ang), True
            made += 1


# ---------------------------------------------------------------------------
# Step 0: pre-clean
# ---------------------------------------------------------------------------

def step_preclean():
    actors = get_actor_subsystem()
    doomed = [a for a in actors.get_all_level_actors()
              if a is not None and a.get_actor_label().startswith(LABEL_PREFIX)]
    killed = 0
    for a in doomed:
        try:
            actors.destroy_actor(a)
            killed += 1
        except Exception as exc:
            warn("Could not destroy %s: %s" % (a.get_actor_label(), exc))
    record("0 pre-clean", "PASS", "destroyed %d ARENA_DRESS_* actors" % killed)


# ---------------------------------------------------------------------------
# Force-save (proven pattern)
# ---------------------------------------------------------------------------

def force_save_asset(asset):
    """mark dirty -> save(only_if_is_dirty=False) -> verify the .uasset mtime
    advanced on disk (dirty-gated saves silently wrote NOTHING earlier)."""
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
            raise RuntimeError("save reported success but %s was NOT rewritten on disk"
                               % disk_path)
    _SAVE_COUNT[0] += 1
    if _SAVE_COUNT[0] % GC_EVERY_SAVES == 0:
        gc_now()


# ---------------------------------------------------------------------------
# Step 1: texture caps -- BEFORE placement (plan D, mandatory ordering)
# ---------------------------------------------------------------------------

def _texture_paths_in(folder):
    """Texture2D package paths under folder via the asset registry."""
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


def _is_texture_package(pkg):
    """Asset-registry class check for one package (no load)."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        ads = reg.get_assets_by_package_name(unreal.Name(pkg))
    except Exception:
        try:
            ads = reg.get_assets_by_package_name(pkg)
        except Exception:
            return False
    for ad in ads or []:
        for attr in ("asset_class_path", "asset_class"):
            try:
                v = ad.get_editor_property(attr)
                if str(getattr(v, "asset_name", v)) == "Texture2D":
                    return True
            except Exception:
                continue
    return False


def _kitedemo_palette_packages():
    """Every /Game/KiteDemo package our palettes / floor-ring material touch."""
    pkgs = set()
    for key in PALETTE:
        for p in PALETTE[key]:
            if p.startswith(KITE_ROOT):
                pkgs.add(p)
    pkgs.update([RING_TEX_D, RING_TEX_N,
                 KITE_ROOT + "/Environments/GroundTiles/RockyPath/MI_PSM_RockyPath_Tile",
                 KITE_ROOT + "/Environments/GroundTiles/Grass/T_ground_Moss_D"])
    return [p for p in pkgs if unreal.EditorAssetLibrary.does_asset_exist(p)]


def _kitedemo_dependency_textures():
    """mesh -> material -> texture dependency walk (3 hops), restricted to
    /Game/KiteDemo. Returns texture package paths, or None when the registry
    dependency API is unavailable (caller then uses the subfolder fallback).
    This is the plan-C rule: cap ONLY the textures our picks reference --
    never carpet-cap the whole 8K-happy KiteDemo pack."""
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    if not hasattr(reg, "get_dependencies"):
        return None
    try:
        opts = unreal.AssetRegistryDependencyOptions(
            include_soft_package_references=True,
            include_hard_package_references=True)
    except Exception:
        opts = None
    seen = set()
    frontier = set(_kitedemo_palette_packages())
    for _hop in range(3):
        nxt = set()
        for pkg in frontier:
            if pkg in seen:
                continue
            seen.add(pkg)
            try:
                deps = (reg.get_dependencies(unreal.Name(pkg), opts)
                        if opts is not None else reg.get_dependencies(unreal.Name(pkg)))
            except Exception:
                try:
                    deps = reg.get_dependencies(pkg, opts)
                except Exception:
                    return None  # API shape unknown -- fall back to subfolders
            for d in deps or []:
                ds = str(d)
                if ds.startswith(KITE_ROOT) and ds not in seen:
                    nxt.add(ds)
        frontier = nxt
        if not frontier:
            break
    seen |= frontier
    return sorted(p for p in seen if _is_texture_package(p))


def _cap_texture(path, cap):
    """Cap one texture; returns 'capped'/'skip'/'fail'."""
    try:
        tex = unreal.EditorAssetLibrary.load_asset(path)
        if tex is None or not isinstance(tex, unreal.Texture2D):
            return "skip"
        cur = int(tex.get_editor_property("max_texture_size"))
        if 0 < cur <= cap:
            return "skip"
        tex.set_editor_property("max_texture_size", cap)
        if int(tex.get_editor_property("max_texture_size")) != cap:
            raise RuntimeError("max_texture_size write-back did not stick")
        force_save_asset(tex)
        return "capped"
    except Exception as exc:
        warn("  texture cap FAILED for %s: %s" % (path, exc))
        return "fail"


def step_texture_caps():
    capped, skipped, failed = 0, 0, 0

    # 1) the four v1 packs at 2048 (unchanged v1 behavior)
    for folder in PACK_DIRS:
        if not unreal.EditorAssetLibrary.does_directory_exist(folder):
            warn("texture cap: folder missing, skipping: %s" % folder)
            continue
        paths = _texture_paths_in(folder)
        log("texture cap: %d Texture2D under %s" % (len(paths), folder))
        for p in paths:
            res = _cap_texture(p, MAX_TEX_SIZE)
            capped += res == "capped"
            skipped += res == "skip"
            failed += res == "fail"

    # 2) KiteDemo: dependency-walked textures of OUR picks only, at 2048
    kite_mode = "dependency walk"
    kite_paths = None
    try:
        kite_paths = _kitedemo_dependency_textures()
    except Exception as exc:
        warn("KiteDemo dependency walk blew up (%s) -- subfolder fallback." % exc)
    if kite_paths is None:
        kite_mode = "subfolder fallback"
        kite_paths = []
        for folder in KITE_FALLBACK_DIRS:
            if unreal.EditorAssetLibrary.does_directory_exist(folder):
                kite_paths.extend(_texture_paths_in(folder))
    # de-dup; the 1024-forced sets are handled in pass 3 below
    kite_1024 = set()
    for folder in KITE_1024_DIRS:
        kite_1024.update(_texture_paths_in(folder))
    kite_paths = [p for p in sorted(set(kite_paths)) if p not in kite_1024]
    log("texture cap: %d KiteDemo textures via %s (+%d forced-1024)"
        % (len(kite_paths), kite_mode, len(kite_1024)))
    for p in kite_paths:
        res = _cap_texture(p, MAX_TEX_SIZE)
        capped += res == "capped"
        skipped += res == "skip"
        failed += res == "fail"

    # 3) backdrop-only sets FORCED to 1024 (Cliff01 / Mountain_RockFace_002:
    #    90 m+ behind fog -- T_Cliff01_D_CC_R alone is 129 MB at source)
    for p in sorted(kite_1024):
        res = _cap_texture(p, 1024)
        capped += res == "capped"
        skipped += res == "skip"
        failed += res == "fail"

    record("1 texture caps (pre-place)", "FAIL" if capped == 0 and failed > 0 else "PASS",
           "%d capped, %d already ok, %d failed (KiteDemo via %s)"
           % (capped, skipped, failed, kite_mode))
    gc_now()


# ---------------------------------------------------------------------------
# Step 2: ATMOSPHERE (plan A)
# ---------------------------------------------------------------------------

def find_rig_actor(substrings, cls=None):
    """Loose label match over all level actors (plan labels ARENA_KeyLight
    etc., but match tolerantly). ARENA_*-labelled hits win; class fallback."""
    best = None
    best_label = None
    for a in get_actor_subsystem().get_all_level_actors():
        try:
            label = str(a.get_actor_label())
        except Exception:
            continue
        ll = label.lower()
        if any(s in ll for s in substrings):
            if ll.startswith("arena_"):
                return a, label
            if best is None:
                best, best_label = a, label
    if best is not None:
        return best, best_label
    if cls is not None:
        for a in get_actor_subsystem().get_all_level_actors():
            try:
                if isinstance(a, cls):
                    return a, str(a.get_actor_label())
            except Exception:
                continue
    return None, None


def apply_props(obj, prop_list, context):
    """[(name_or_candidates, value), ...] -> (ok_count, failed_names)."""
    ok, failed = 0, []
    for names, value in prop_list:
        if not isinstance(names, (list, tuple)):
            names = [names]
        if set_first_prop(obj, names, value, context):
            ok += 1
        else:
            failed.append(names[0])
    return ok, failed


def _atmo_keylight(results):
    actor, label = find_rig_actor(("keylight", "directionallight", "directional_light"),
                                  unreal.DirectionalLight)
    if actor is None:
        results.append("KeyLight NOT FOUND")
        return
    try:
        actor.set_actor_rotation(
            unreal.Rotator(roll=0.0, pitch=-25.0, yaw=155.0), False)
    except Exception:
        # older arity without teleport flag
        actor.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-25.0, yaw=155.0))
    comp = actor.get_component_by_class(unreal.DirectionalLightComponent)
    if comp is None:
        results.append("KeyLight('%s') has no DirectionalLightComponent" % label)
        return
    # bloom_tint is an FColor on the component; try Color then LinearColor.
    tint_ok = set_first_prop(comp, ["bloom_tint"],
                             unreal.Color(r=255, g=158, b=97, a=255), "KeyLight")
    if not tint_ok:
        tint_ok = set_first_prop(comp, ["bloom_tint"],
                                 unreal.LinearColor(1.0, 0.62, 0.38, 1.0), "KeyLight")
    ok, failed = apply_props(comp, [
        ("intensity", 3.5),                       # lux
        ("use_temperature", True),
        ("temperature", 4250.0),
        ("enable_light_shaft_bloom", True),       # the cheap god-ray (~0.1-0.2 ms)
        ("bloom_scale", 0.25),
        ("bloom_threshold", 8.0),                 # only the sun disk blooms
        ("bloom_max_brightness", 2.0),
        ("enable_light_shaft_occlusion", True),
        ("occlusion_mask_darkness", 0.3),
        ("occlusion_depth_range", 20000.0),
    ], "KeyLight")
    results.append("KeyLight('%s'): rot -25/155, %d props%s%s"
                   % (label, ok + (1 if tint_ok else 0),
                      "" if not failed else " FAILED:" + ",".join(failed),
                      "" if tint_ok else " (+bloom_tint FAILED)"))


def _atmo_sky_atmosphere(results):
    actor, label = find_rig_actor(("skyatmosphere", "sky_atmosphere", "atmosphere"),
                                  unreal.SkyAtmosphere)
    if actor is None:
        results.append("SkyAtmosphere NOT FOUND")
        return
    comp = actor.get_component_by_class(unreal.SkyAtmosphereComponent)
    if comp is None:
        results.append("SkyAtmosphere('%s') has no component" % label)
        return
    ok, failed = apply_props(comp, [
        ("rayleigh_scattering_scale", 0.052),   # deeper/colder sky -> colder RTC skylight
        ("mie_scattering_scale", 0.0085),
        ("mie_anisotropy", 0.88),               # hazy halo hugging the low sun
        ("mie_absorption_scale", 0.0007),
    ], "SkyAtmosphere")
    results.append("SkyAtmosphere('%s'): %d/4 props%s"
                   % (label, ok, "" if not failed else " FAILED:" + ",".join(failed)))


def _atmo_skylight(results):
    actor, label = find_rig_actor(("skylight", "sky_light"), unreal.SkyLight)
    if actor is None:
        results.append("SkyLight NOT FOUND")
        return
    comp = actor.get_component_by_class(unreal.SkyLightComponent)
    if comp is None:
        results.append("SkyLight('%s') has no component" % label)
        return
    # Keep Movable + Real Time Capture (it inherits the colder atmosphere);
    # do NOT assign the HDR_ParagonSample cubemap (plan A verdict).
    ok = set_first_prop(comp, ["intensity_scale", "intensity"], 0.85, "SkyLight")
    results.append("SkyLight('%s'): intensity 0.85 %s (RTC kept, no HDRI)"
                   % (label, "OK" if ok else "FAILED"))


def _atmo_fog(results):
    actor, label = find_rig_actor(("heightfog", "height_fog", "fog"),
                                  unreal.ExponentialHeightFog)
    if actor is None:
        results.append("HeightFog NOT FOUND")
        return
    comp = actor.get_component_by_class(unreal.ExponentialHeightFogComponent)
    if comp is None:
        results.append("HeightFog('%s') has no component" % label)
        return
    ok, failed = apply_props(comp, [
        ("fog_density", 0.028),
        ("fog_height_falloff", 0.35),           # fog pools in the crater bowl
        ("start_distance", 3000.0),             # LOAD-BEARING: fight floor stays clear
        ("fog_inscattering_luminance",
         unreal.LinearColor(0.055, 0.068, 0.092, 1.0)),  # cold blue-grey
        # warm counter-glow toward the low sun
        (["directional_inscattering_luminance", "directional_inscattering_color"],
         unreal.LinearColor(0.30, 0.16, 0.085, 1.0)),
        ("directional_inscattering_exponent", 16.0),
        ("directional_inscattering_start_distance", 8000.0),
        ("enable_volumetric_fog", False),       # plan A verdict: stays OFF
    ], "HeightFog")
    # Second fog layer: STRUCT property -- write back + RE-READ verify
    # (struct write-backs silently fail from python; hard project rule).
    second_ok = False
    try:
        data = comp.get_editor_property("second_fog_data")
        data.set_editor_property("fog_density", 0.032)
        data.set_editor_property("fog_height_falloff", 1.2)
        data.set_editor_property("fog_height_offset", -150.0)
        comp.set_editor_property("second_fog_data", data)
        reread = comp.get_editor_property("second_fog_data")
        second_ok = abs(float(reread.get_editor_property("fog_density")) - 0.032) < 1e-4
        if not second_ok:
            warn("second_fog_data write-back did NOT stick (re-read mismatch) -- "
                 "set the ground-haze layer manually on %s." % label)
    except Exception as exc:
        warn("second_fog_data unavailable (%s) -- set the ground-haze layer "
             "manually on %s." % (exc, label))
    results.append("HeightFog('%s'): %d/8 props, 2nd layer %s%s"
                   % (label, ok, "OK" if second_ok else "FAILED",
                      "" if not failed else " FAILED:" + ",".join(failed)))


def _atmo_postprocess(results):
    actor, label = find_rig_actor(("postprocess", "post_process"),
                                  unreal.PostProcessVolume)
    if actor is None:
        results.append("PostProcess NOT FOUND")
        return
    # FPostProcessSettings: struct COPY; every field needs its override_*
    # sibling True, then the struct is set back and RE-READ verified.
    settings = actor.get_editor_property("settings")
    pp_fields = [
        # exposure: scene got darker; provisional band, re-meter per visuals.md
        ("auto_exposure_min_brightness", 0.35),
        ("auto_exposure_max_brightness", 0.85),
        # grade: global cool bias so the 4250 K key pops
        ("color_saturation", unreal.Vector4(0.92, 0.92, 0.92, 1.0)),
        ("color_contrast", unreal.Vector4(1.08, 1.08, 1.08, 1.0)),
        ("white_temp", 6300.0),
        # split-tone: cool shadows / warm highlights
        ("color_gain_shadows", unreal.Vector4(0.97, 1.00, 1.06, 1.0)),
        ("color_gain_highlights", unreal.Vector4(1.06, 1.00, 0.94, 1.0)),
        ("color_saturation_shadows", unreal.Vector4(0.88, 0.88, 0.88, 1.0)),
        ("vignette_intensity", 0.35),
    ]
    ok, failed = 0, []
    for field, value in pp_fields:
        ok_v = set_prop_if_exists(settings, field, value, "PostProcessSettings")
        ok_o = set_prop_if_exists(settings, "override_" + field, True, "PostProcessSettings")
        if ok_v and ok_o:
            ok += 1
        else:
            failed.append(field)
    actor.set_editor_property("settings", settings)
    # verify the struct write-back stuck
    verified = False
    try:
        reread = actor.get_editor_property("settings")
        verified = abs(float(reread.get_editor_property("white_temp")) - 6300.0) < 1.0 \
            and bool(reread.get_editor_property("override_white_temp"))
    except Exception:
        pass
    if not verified:
        warn("PostProcess settings write-back could NOT be verified -- check "
             "'%s' manually (white_temp should read 6300)." % label)
    results.append("PostProcess('%s'): %d/%d fields, write-back %s%s"
                   % (label, ok, len(pp_fields), "VERIFIED" if verified else "UNVERIFIED",
                      "" if not failed else " FAILED:" + ",".join(failed)))


def step_atmosphere():
    # Verify the actual rig labels first -- full dump into the log.
    labels = []
    for a in get_actor_subsystem().get_all_level_actors():
        try:
            lbl = str(a.get_actor_label())
            if lbl.startswith("ARENA_") and not lbl.startswith(LABEL_PREFIX):
                labels.append(lbl)
        except Exception:
            continue
    log("ATMOSPHERE: %d ARENA_* rig/build actors in level: %s"
        % (len(labels), ", ".join(sorted(labels)[:40])))
    results = []
    for fn in (_atmo_keylight, _atmo_sky_atmosphere, _atmo_skylight,
               _atmo_fog, _atmo_postprocess):
        try:
            fn(results)
        except Exception as exc:
            results.append("%s CRASHED: %s" % (fn.__name__, exc))
            warn(traceback.format_exc())
    n_missing = sum(1 for r in results if "NOT FOUND" in r)
    for r in results:
        log("  atmo: %s" % r)
    record("2 atmosphere", "FAIL" if n_missing >= 5 else "PASS",
           "%d/5 rig actors updated; re-meter exposure per visuals.md "
           "(HDR Eye Adaptation) after this pass" % (5 - n_missing))


# ---------------------------------------------------------------------------
# Step 3: Blender meshes -- import + place (floor ring / mountain backdrop)
# ---------------------------------------------------------------------------

def import_fbx_static_mesh(name):
    """build_arena_level step-1 import settings, but Nanite OFF at import
    (crash-resistance default; the DO_NANITE pass flips PLACED meshes later).
    Returns (mesh_or_None, detail)."""
    asset_path = "%s/%s" % (MESH_DIR, name)
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        return load_mesh(asset_path), "pre-existing"
    fbx = os.path.join(SOURCE_ARENA_DIR, name + ".fbx")
    if not os.path.isfile(fbx):
        return None, "%s not exported yet" % fbx
    ui = unreal.FbxImportUI()
    ui.set_editor_property("import_mesh", True)
    ui.set_editor_property("import_as_skeletal", False)
    ui.set_editor_property("import_animations", False)
    ui.set_editor_property("import_materials", False)
    ui.set_editor_property("import_textures", False)
    ui.set_editor_property("create_physics_asset", False)
    set_prop_if_exists(ui, "mesh_type_to_import",
                       unreal.FBXImportType.FBXIT_STATIC_MESH, "FbxImportUI")
    smd = ui.static_mesh_import_data
    smd.set_editor_property("combine_meshes", True)
    smd.set_editor_property("generate_lightmap_u_vs", False)
    smd.set_editor_property("auto_generate_collision", False)
    smd.set_editor_property("import_uniform_scale", 1.0)
    set_prop_if_exists(smd, "build_nanite", False, "static_mesh_import_data")
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", fbx)
    task.set_editor_property("destination_path", MESH_DIR)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", False)
    task.set_editor_property("options", ui)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    if not unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        return None, "import produced no asset (check Output Log FBX section)"
    return load_mesh(asset_path), "imported"


def build_floor_ring_material():
    """NEW M_FloorRing via the PROVEN fallback-material pattern (M_Terrain
    would slope-blend the carve away; the plan's full vertex-color/triplanar
    graph is hand work -- this gets the RockyPath stone read in place).
    Returns the material or None; on None the caller assigns M_Terrain."""
    mat_path = "%s/M_FloorRing" % MAT_DIR
    try:
        mel = unreal.MaterialEditingLibrary
        tex_d = unreal.EditorAssetLibrary.load_asset(RING_TEX_D)
        tex_n = unreal.EditorAssetLibrary.load_asset(RING_TEX_N)
        if tex_d is None:
            raise RuntimeError("RockyPath diffuse missing: %s" % RING_TEX_D)
        if unreal.EditorAssetLibrary.does_asset_exist(mat_path):
            log("M_FloorRing exists -- rebuilding its graph in place.")
            mat = unreal.EditorAssetLibrary.load_asset(mat_path)
        else:
            mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                "M_FloorRing", MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
        if mat is None:
            raise RuntimeError("could not create/load %s" % mat_path)
        mel.delete_all_material_expressions(mat)

        def connect(frm, outs, to, ins, what):
            for o in outs:
                for i in ins:
                    try:
                        if mel.connect_material_expressions(frm, o, to, i):
                            return
                    except Exception:
                        continue
            raise RuntimeError("connect failed: %s" % what)

        def connect_prop(frm, outs, prop, what):
            for o in outs:
                try:
                    if mel.connect_material_property(frm, o, prop):
                        return
                except Exception:
                    continue
            raise RuntimeError("property connect failed: %s" % what)

        wpos = mel.create_material_expression(
            mat, unreal.MaterialExpressionWorldPosition, -1200, 0)
        mask_rg = mel.create_material_expression(
            mat, unreal.MaterialExpressionComponentMask, -1000, 0)
        mask_rg.set_editor_property("r", True)
        mask_rg.set_editor_property("g", True)
        mask_rg.set_editor_property("b", False)
        mask_rg.set_editor_property("a", False)
        divide = mel.create_material_expression(
            mat, unreal.MaterialExpressionDivide, -800, 0)
        divide.set_editor_property("const_b", RING_TEX_SIZE_UU)
        connect(wpos, [""], mask_rg, ["", "Input"], "ring.mask")
        connect(mask_rg, [""], divide, ["A", ""], "ring.divide")

        samp_d = mel.create_material_expression(
            mat, unreal.MaterialExpressionTextureSample, -500, -200)
        samp_d.set_editor_property("texture", tex_d)
        connect(divide, [""], samp_d, ["UVs", "Coordinates", ""], "ring.uv.d")
        connect_prop(samp_d, [""], unreal.MaterialProperty.MP_BASE_COLOR, "ring.BaseColor")
        # D_CC_R convention: roughness rides in alpha -- wire if it connects.
        try:
            connect_prop(samp_d, ["A"], unreal.MaterialProperty.MP_ROUGHNESS, "ring.Rough")
        except Exception:
            log("M_FloorRing: alpha->roughness not wired (default roughness kept)")
        if tex_n is not None:
            samp_n = mel.create_material_expression(
                mat, unreal.MaterialExpressionTextureSample, -500, 200)
            samp_n.set_editor_property("texture", tex_n)
            set_prop_if_exists(samp_n, "sampler_type",
                               unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, "ring.N")
            connect(divide, [""], samp_n, ["UVs", "Coordinates", ""], "ring.uv.n")
            connect_prop(samp_n, [""], unreal.MaterialProperty.MP_NORMAL, "ring.Normal")
        mel.recompile_material(mat)
        force_save_asset(mat)
        return mat
    except Exception as exc:
        warn("M_FloorRing build failed (%s) -- floor ring falls back to "
             "M_Terrain. Rebuild the carve material by hand (plan B.1)." % exc)
        warn(traceback.format_exc())
        return None


def _no_collision(actor, label):
    """Collision NoCollision -- MANDATORY on the floor ring (root-motion
    contract: nothing may bump the fight floor) and on the backdrop
    (unreachable; ARENA_BV_* already fences play space)."""
    try:
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp is None:
            raise RuntimeError("no StaticMeshComponent")
        try:
            comp.set_collision_profile_name("NoCollision")
        except Exception:
            pass
        comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
        return True
    except Exception as exc:
        warn("Could NOT disable collision on %s (%s) -- fix manually; the "
             "floor ring MUST NOT collide (root-motion contract)." % (label, exc))
        return False


def _place_blender_mesh(name, label_suffix, material, detail_out):
    """Spawn at origin (authored world-space, like SM_ArenaTerrain)."""
    mesh, how = import_fbx_static_mesh(name)
    if mesh is None:
        detail_out.append("%s: SKIP (%s)" % (name, how))
        return None
    label = LABEL_PREFIX + label_suffix
    actor = get_actor_subsystem().spawn_actor_from_object(
        mesh, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
    if actor is None:
        detail_out.append("%s: spawn FAILED" % name)
        return None
    actor.set_actor_label(label)
    try:
        comp = actor.get_component_by_class(unreal.StaticMeshComponent)
        if comp is not None:
            comp.set_mobility(unreal.ComponentMobility.STATIC)
            if material is not None:
                comp.set_material(0, material)
    except Exception as exc:
        warn("Could not set mobility/material on %s: %s" % (label, exc))
    coll_ok = _no_collision(actor, label)
    SPAWNED.append(actor)
    PLACED_MESHES["%s/%s" % (MESH_DIR, name)] = mesh
    ZONE_COUNTS["BLENDER"] = ZONE_COUNTS.get("BLENDER", 0) + 1
    detail_out.append("%s: %s, placed at origin, collision %s"
                      % (name, how, "OFF" if coll_ok else "STILL ON (fix!)"))
    return actor


def step_blender_meshes():
    details = []
    # Floor ring: NEW M_FloorRing (fallback: M_Terrain), NO collision.
    ring_mat = build_floor_ring_material()
    if ring_mat is None and unreal.EditorAssetLibrary.does_asset_exist(
            "%s/M_Terrain" % MAT_DIR):
        ring_mat = unreal.EditorAssetLibrary.load_asset("%s/M_Terrain" % MAT_DIR)
    ring = _place_blender_mesh(FLOOR_RING_NAME, "FLOORRING", ring_mat, details)
    # Backdrop: reuse M_Terrain (triplanar slope-blend reads as rock at range).
    terrain_mat = None
    if unreal.EditorAssetLibrary.does_asset_exist("%s/M_Terrain" % MAT_DIR):
        terrain_mat = unreal.EditorAssetLibrary.load_asset("%s/M_Terrain" % MAT_DIR)
    else:
        warn("M_Terrain missing -- backdrop keeps its default material.")
    backdrop = _place_blender_mesh(BACKDROP_NAME, "BACKDROP", terrain_mat, details)
    placed = sum(1 for a in (ring, backdrop) if a is not None)
    status = "PASS" if placed else ("SKIP" if all("SKIP" in d for d in details) else "FAIL")
    record("3 blender meshes", status, "; ".join(details) or "nothing to do")


# ---------------------------------------------------------------------------
# Step 4: BACKDROP RING (plan C: 20 pieces, r 9000-25000, outside zone rect)
# ---------------------------------------------------------------------------

def _backdrop_pos_ok(x, y):
    return (not in_zone_rect(x, y)
            and placement_forbidden(x, y) is None
            and math.hypot(x, y) >= BACKDROP_R[0])


def step_backdrop_ring():
    cliffs = valid_palette("backdrop_cliff")
    mountains = valid_palette("backdrop_mountain")
    volcanics = valid_palette("backdrop_volcanic")
    if not (cliffs or mountains or volcanics):
        record("4 backdrop ring", "SKIP", "no KiteDemo backdrop assets found")
        return
    placed, total = 0, 0
    # Cliff01 x4 at plan azimuths, scale 1.6-2.4, sunk 3-8 m, facing center +-20
    for i, az in enumerate((120.0, 165.0, 210.0, 280.0)):
        if not cliffs:
            break
        total += 1
        ang = math.radians(az + RNG.uniform(-6.0, 6.0))
        r = RNG.uniform(11000.0, 16000.0)
        x, y = r * math.cos(ang), r * math.sin(ang)
        yaw = math.degrees(math.atan2(-y, -x)) + RNG.uniform(-20.0, 20.0)
        if spawn_piece(cliffs[0], x, y, yaw, RNG.uniform(1.6, 2.4),
                       "%sBACKRING_CLIFF_%02d" % (LABEL_PREFIX, i),
                       sink_cm=(300.0, 800.0)):
            placed += 1
    # MountainRock (+_Closed) x8 at r 11000-18000, scale 1.0-1.8
    for i in range(8):
        if not mountains:
            break
        total += 1
        for _try in range(20):
            ang = math.radians(RNG.uniform(0.0, 360.0))
            r = RNG.uniform(11000.0, 18000.0)
            x, y = r * math.cos(ang), r * math.sin(ang)
            if _backdrop_pos_ok(x, y):
                break
        else:  # never spawn the last INVALID candidate (zone-rect contract)
            warn("SKIP %sBACKRING_MTN_%02d: no valid backdrop position in 20 tries"
                 % (LABEL_PREFIX, i))
            continue
        yaw = math.degrees(math.atan2(-y, -x)) + RNG.uniform(-25.0, 25.0)
        if spawn_piece(mountains[i % len(mountains)], x, y, yaw,
                       RNG.uniform(1.0, 1.8),
                       "%sBACKRING_MTN_%02d" % (LABEL_PREFIX, i),
                       sink_cm=(150.0, 500.0)):
            placed += 1
    # Large volcanic rocks x8, scale 1.2-2.0
    for i in range(8):
        if not volcanics:
            break
        total += 1
        for _try in range(20):
            ang = math.radians(RNG.uniform(0.0, 360.0))
            r = RNG.uniform(BACKDROP_R[0], 20000.0)
            x, y = r * math.cos(ang), r * math.sin(ang)
            if _backdrop_pos_ok(x, y):
                break
        else:  # never spawn the last INVALID candidate (zone-rect contract)
            warn("SKIP %sBACKRING_VOLC_%02d: no valid backdrop position in 20 tries"
                 % (LABEL_PREFIX, i))
            continue
        if spawn_piece(volcanics[i % len(volcanics)], x, y,
                       RNG.uniform(0.0, 360.0), RNG.uniform(1.2, 2.0),
                       "%sBACKRING_VOLC_%02d" % (LABEL_PREFIX, i),
                       sink_cm=(100.0, 400.0)):
            placed += 1
    record("4 backdrop ring", "PASS" if placed else "FAIL",
           "%d/%d backdrop silhouettes" % (placed, total))


# ---------------------------------------------------------------------------
# Step 5: RIM CROWN (plan C: 34 pieces, 11 clusters of 2-4)
# ---------------------------------------------------------------------------

def step_rim_crown():
    palette = valid_palette("rim")
    if not palette:
        record("5 rim crown", "SKIP", "no rim palette assets found")
        return
    target = 34
    placed = 0
    lo = ENTRANCE_HALF_ANGLE_DEG
    hi = 360.0 - ENTRANCE_HALF_ANGLE_DEG
    n_clusters = 11
    idx = 0
    for c in range(n_clusters):
        # cluster centers spread over the ring minus the entrance sector
        base_ang = lo + (hi - lo) * (c + 0.5) / n_clusters + RNG.uniform(-8.0, 8.0)
        k = RNG.randint(2, 4)
        if c == n_clusters - 1:
            k = max(1, target - placed)  # top up to the target on the last cluster
        for _ in range(k):
            if placed >= target:
                break
            ang = base_ang + RNG.uniform(-6.0, 6.0)
            rad = math.radians(ang)
            r = RNG.uniform(RIM_R[0], RIM_R[1])
            x, y = r * math.cos(rad), r * math.sin(rad)
            yaw = math.degrees(math.atan2(-y, -x)) + RNG.uniform(-15.0, 15.0)
            asset = RNG.choice(palette)
            # plan: SM_MountainRock_Closed joins the rim at 0.5-0.8
            scale = (RNG.uniform(0.5, 0.8) if asset.endswith("SM_MountainRock_Closed")
                     else RNG.uniform(0.9, 1.6))
            try:
                if spawn_piece(asset, x, y, yaw, scale,
                               "%sRIM_%02d" % (LABEL_PREFIX, idx)):
                    placed += 1
            except Exception as exc:
                warn("rim piece %d failed: %s" % (idx, exc))
            idx += 1
    record("5 rim crown", "PASS" if placed else "FAIL",
           "%d/%d silhouettes in %d clusters on the crest" % (placed, target, n_clusters))


# ---------------------------------------------------------------------------
# Step 6: BOWL INTERIOR (plan C ~170 -- v1 had ZERO here)
# ---------------------------------------------------------------------------

def _bowl_angle_ok(x, y):
    """Keep the bowl's +X walk line to the corridor mouth passable."""
    ang = math.degrees(math.atan2(y, x)) % 360.0
    return not (ang < ENTRANCE_HALF_ANGLE_DEG or ang > 360.0 - ENTRANCE_HALF_ANGLE_DEG)


def step_bowl_interior():
    scree = valid_palette("bowl_scree")
    rocks = valid_palette("bowl_rocks")
    grass = valid_palette("grass")
    heather = valid_palette("heather")
    ferns = valid_palette("ferns")
    if not (scree or rocks or grass):
        record("6 bowl interior", "SKIP", "no bowl palette assets found")
        return
    placed, total = 0, 0

    # Scree skirt: 26 pieces in 10 broken arcs hiding the floor->rim seam
    if scree:
        arcs = 10
        per_arc = [3, 3, 3, 3, 3, 3, 2, 2, 2, 2]  # = 26
        for a in range(arcs):
            base_ang = RNG.uniform(ENTRANCE_HALF_ANGLE_DEG,
                                   360.0 - ENTRANCE_HALF_ANGLE_DEG)
            r = RNG.uniform(SCREE_SKIRT_R[0], SCREE_SKIRT_R[1])
            for k in range(per_arc[a]):
                total += 1
                ang = math.radians(base_ang + k * RNG.uniform(2.0, 4.0))
                x, y = r * math.cos(ang), r * math.sin(ang)
                if not _bowl_angle_ok(x, y):
                    continue
                yaw = math.degrees(ang) + 90.0 + RNG.uniform(-15.0, 15.0)
                pitch, roll = slope_lean(x, y, yaw)
                if spawn_piece(RNG.choice(scree), x, y, yaw,
                               RNG.uniform(0.9, 1.4),
                               "%sBOWL_SCREE_%02d_%d" % (LABEL_PREFIX, a, k),
                               pitch=pitch, roll=roll, sink_cm=(5.0, 10.0)):
                    placed += 1

    # Half-buried rocks: 36, sink 25-40 %, nothing stands taller than 2 m
    if rocks:
        def bowl_center():
            for _try in range(20):
                ang = math.radians(RNG.uniform(0.0, 360.0))
                r = RNG.uniform(BOWL_ROCK_R[0], BOWL_ROCK_R[1])
                x, y = r * math.cos(ang), r * math.sin(ang)
                if _bowl_angle_ok(x, y):
                    return x, y
            return BOWL_ROCK_R[0], BOWL_ROCK_R[0]
        i = 0
        for x, y, _outlier in cluster_points(36, bowl_center):
            total += 1
            if math.hypot(x, y) < FIGHT_FLOOR_KEEPOUT_R or not _bowl_angle_ok(x, y):
                continue
            yaw = RNG.uniform(0.0, 360.0)
            pitch, roll = slope_lean(x, y, yaw)
            if spawn_piece(RNG.choice(rocks), x, y, yaw, RNG.uniform(0.7, 1.4),
                           "%sBOWL_ROCK_%02d" % (LABEL_PREFIX, i),
                           pitch=pitch, roll=roll, sink_frac=(0.25, 0.40),
                           max_stand_cm=BOWL_MAX_STAND_CM):
                placed += 1
            i += 1

    # Ground cover -- ALL CastShadow OFF (plan D: WPO grass invalidates VSM pages)
    def cover(palette_list, n, tag, region_fn, scale=(0.8, 1.2)):
        nonlocal placed, total
        if not palette_list:
            return
        i = 0
        for x, y, _outlier in cluster_points(n, region_fn, cluster_size=(3, 4),
                                             spread=(200.0, 500.0)):
            total += 1
            if math.hypot(x, y) < FIGHT_FLOOR_KEEPOUT_R:
                continue
            if spawn_piece(RNG.choice(palette_list), x, y, RNG.uniform(0.0, 360.0),
                           RNG.uniform(scale[0], scale[1]),
                           "%sBOWL_%s_%02d" % (LABEL_PREFIX, tag, i),
                           sink_cm=(2.0, 8.0), cast_shadow=False):
                placed += 1
            i += 1

    def anywhere_bowl():
        ang = math.radians(RNG.uniform(0.0, 360.0))
        r = RNG.uniform(BOWL_R[0] + 300.0, BOWL_R[1] - 200.0)
        return r * math.cos(ang), r * math.sin(ang)

    def north_slope():  # north = +Y, the shade side of the -25/155 sun
        ang = math.radians(RNG.uniform(35.0, 145.0))
        r = RNG.uniform(BOWL_R[0] + 300.0, BOWL_R[1] - 200.0)
        return r * math.cos(ang), r * math.sin(ang)

    cover(grass, 60, "GRASS", anywhere_bowl)
    cover(heather, 25, "HEATHER", anywhere_bowl)
    cover(ferns, 20, "FERN", north_slope)

    record("6 bowl interior", "PASS" if placed else "FAIL",
           "%d/%d (scree skirt + half-buried rocks + shadowless cover)" % (placed, total))


# ---------------------------------------------------------------------------
# Step 7: DECALS (fight floor cracks/wet + canyon lane scuffs; <= 16 total)
# ---------------------------------------------------------------------------

def spawn_decal(mat_path, x, y, size, yaw, label, elong=1.0):
    if COUNTS["decals"] >= DECAL_CAP:
        warn("SKIP %s: decal cap %d reached" % (label, DECAL_CAP))
        return None
    if not unreal.EditorAssetLibrary.does_asset_exist(mat_path):
        warn("Decal material missing: %s" % mat_path)
        return None
    mat = unreal.EditorAssetLibrary.load_asset(mat_path)
    if mat is None:
        return None
    gz = ground_z(x, y)
    # pitch -90: DecalComponent projects along +X -> point it at the ground
    actor = get_actor_subsystem().spawn_actor_from_class(
        unreal.DecalActor, unreal.Vector(x, y, gz + 20.0),
        unreal.Rotator(roll=0.0, pitch=-90.0, yaw=yaw))
    if actor is None:
        warn("DecalActor spawn failed for %s" % label)
        return None
    actor.set_actor_label(label)
    try:
        comp = actor.get_component_by_class(unreal.DecalComponent)
        if comp is None:
            raise RuntimeError("no DecalComponent")
        try:
            comp.set_decal_material(mat)
        except Exception:
            comp.set_editor_property("decal_material", mat)
        # X = projection depth; Y/Z = footprint half-sizes (elong along Y)
        comp.set_editor_property(
            "decal_size", unreal.Vector(256.0, size * elong / 2.0, size / 2.0))
    except Exception as exc:
        warn("Decal setup failed for %s: %s" % (label, exc))
    SPAWNED.append(actor)
    COUNTS["decals"] += 1
    ZONE_COUNTS["DECAL"] = ZONE_COUNTS.get("DECAL", 0) + 1
    log("  + %-34s %-46s (%.0f, %.0f) size %.0f" % (label, mat_path.rsplit("/", 1)[-1], x, y, size))
    return actor


def step_decals():
    crack_mats = [m for m in DECAL_CRACK_MATS
                  if unreal.EditorAssetLibrary.does_asset_exist(m)]
    placed, total = 0, 0
    # Fight floor: 8 crack/dirt decals r 300-1800 (opacity stays at the
    # material-instance default -- per-actor opacity would need MIC churn).
    for i in range(8):
        total += 1
        if not crack_mats:
            break
        ang = math.radians(RNG.uniform(0.0, 360.0))
        r = RNG.uniform(300.0, 1800.0)
        if spawn_decal(RNG.choice(crack_mats), r * math.cos(ang), r * math.sin(ang),
                       RNG.uniform(400.0, 900.0), RNG.uniform(0.0, 360.0),
                       "%sDECAL_FLOOR_%02d" % (LABEL_PREFIX, i)):
            placed += 1
    # 2 wet decals on the monolith side of the floor
    mono_ang = math.atan2(MONOLITH_XY[1], MONOLITH_XY[0])
    for i in range(2):
        total += 1
        ang = mono_ang + math.radians(RNG.uniform(-25.0, 25.0))
        r = RNG.uniform(1200.0, 1800.0)
        if spawn_decal(DECAL_WET_MAT, r * math.cos(ang), r * math.sin(ang),
                       RNG.uniform(500.0, 800.0), RNG.uniform(0.0, 360.0),
                       "%sDECAL_WET_%02d" % (LABEL_PREFIX, i)):
            placed += 1
    # Canyon lane scuffs: 5, elongated 2.5:1 along the lane (+X), |y| < 600
    for i in range(5):
        total += 1
        if not crack_mats:
            break
        x = RNG.uniform(CORRIDOR_X[0] + 400.0, CORRIDOR_X[1] - 400.0)
        y = RNG.uniform(-600.0, 600.0)
        if spawn_decal(RNG.choice(crack_mats), x, y,
                       RNG.uniform(350.0, 600.0), 0.0 + RNG.uniform(-8.0, 8.0),
                       "%sDECAL_LANE_%02d" % (LABEL_PREFIX, i), elong=2.5):
            placed += 1
    record("7 decals", "PASS" if placed else ("SKIP" if not crack_mats else "FAIL"),
           "%d/%d decals (cap %d; deferred decals are cheap at this count)"
           % (placed, total, DECAL_CAP))


# ---------------------------------------------------------------------------
# Step 8: MONOLITH COURT (v1 layout + plan C's +8 Ruins upgrade)
# ---------------------------------------------------------------------------

COURT_STATUE = _MC + "/Props/SM_Statue7"  # the stated centerpiece


def step_monolith_court():
    palette = valid_palette("court")
    if not palette:
        record("8 monolith court", "SKIP", "no court palette assets found")
        return
    mx, my = MONOLITH_XY
    placed, total = 0, 0
    statue_ok = False
    statue_xy = None
    others = palette
    if COURT_STATUE in palette:
        total += 1
        try:
            rad = math.radians(35.0)
            r = 800.0
            x, y = mx + r * math.cos(rad), my + r * math.sin(rad)
            yaw = math.degrees(math.atan2(my - y, mx - x))
            if spawn_piece(COURT_STATUE, x, y, yaw, 1.1,
                           "%sCOURT_STATUE" % LABEL_PREFIX):
                placed += 1
                statue_ok = True
                statue_xy = (x, y)
        except Exception as exc:
            warn("court statue centerpiece failed: %s" % exc)
        others = [p for p in palette if p != COURT_STATUE]
    else:
        warn("court centerpiece %s missing -- court runs statueless" % COURT_STATUE)
    n = RNG.randint(4, 6)
    for i in range(n):
        if not others:
            break
        total += 1
        try:
            ang = 360.0 * (i + 0.5) / n + RNG.uniform(-20.0, 20.0)
            rad = math.radians(ang)
            r = RNG.uniform(COURT_R[0], COURT_R[1])
            x, y = mx + r * math.cos(rad), my + r * math.sin(rad)
            yaw = math.degrees(math.atan2(my - y, mx - x)) + RNG.uniform(-10.0, 10.0)
            if spawn_piece(others[i % len(others)], x, y, yaw, RNG.uniform(0.9, 1.2),
                           "%sCOURT_%02d" % (LABEL_PREFIX, i)):
                placed += 1
        except Exception as exc:
            warn("court piece %d failed: %s" % (i, exc))
    # +8 upgrade: 3 pre-toppled pillar stacks, 3 trim stones, 2 dead-leaf piles
    pillars = valid_palette("court_add_pillars")
    trims = valid_palette("court_add_trims")
    leaves = valid_palette("dead_leaves")
    for i, asset in enumerate((pillars + trims)[:6]):
        total += 1
        ang = math.radians(RNG.uniform(0.0, 360.0))
        r = RNG.uniform(500.0, 1150.0)
        x, y = mx + r * math.cos(ang), my + r * math.sin(ang)
        yaw = RNG.uniform(0.0, 360.0)
        pitch, roll = slope_lean(x, y, yaw, max_deg=8.0)
        if spawn_piece(asset, x, y, yaw, RNG.uniform(0.9, 1.15),
                       "%sCOURT_RUIN_%02d" % (LABEL_PREFIX, i),
                       pitch=pitch, roll=roll):
            placed += 1
    if leaves:
        bx, by = statue_xy if statue_xy else (mx + 700.0, my + 500.0)
        for i in range(2):
            total += 1
            if spawn_piece(leaves[0], bx + RNG.uniform(-180.0, 180.0),
                           by + RNG.uniform(-180.0, 180.0),
                           RNG.uniform(0.0, 360.0), RNG.uniform(0.9, 1.2),
                           "%sCOURT_LEAVES_%02d" % (LABEL_PREFIX, i),
                           sink_cm=(2.0, 6.0), cast_shadow=False):
                placed += 1
    record("8 monolith court", "PASS" if placed else "FAIL",
           "%d/%d props (centerpiece statue: %s; +8 Ruins upgrade)"
           % (placed, total, "placed" if statue_ok else "NOT placed"))


# ---------------------------------------------------------------------------
# Step 9: CANYON (v1 flanks + vines/scree/rocks + Dusk Spire gate assembly)
# ---------------------------------------------------------------------------

def _canyon_flanks_v1():
    """v1's spike-tree clusters flanking the corridor -- kept per plan C."""
    trees = valid_palette("gate_trees")
    rocks = valid_palette("gate_rocks")
    placed, total = 0, 0
    for side in (1.0, -1.0):
        clusters = RNG.randint(2, 3)
        for c in range(clusters):
            cx = RNG.uniform(GATE_X[0] + 300.0, GATE_X[1] - 300.0)
            cy = side * RNG.uniform(GATE_ABS_Y[0] + 200.0, GATE_ABS_Y[1] - 100.0)
            n_trees = RNG.randint(2, 4) if trees else 0
            n_rocks = RNG.randint(1, 2) if rocks else 0
            for k in range(n_trees + n_rocks):
                total += 1
                try:
                    x = cx + RNG.uniform(-250.0, 250.0)
                    y = cy + side * RNG.uniform(-150.0, 250.0)
                    y = side * max(abs(y), GATE_ABS_Y[0])  # never into the lane
                    is_tree = k < n_trees
                    asset = RNG.choice(trees if is_tree else rocks)
                    yaw = RNG.uniform(0.0, 360.0)
                    lean = RNG.uniform(8.0, 18.0) if is_tree else 0.0
                    yaw_lean = 90.0 * side + RNG.uniform(-20.0, 20.0) if is_tree else yaw
                    if spawn_piece(asset, x, y, yaw_lean, RNG.uniform(0.9, 1.4),
                                   "%sGATE_%s%d_%02d" % (LABEL_PREFIX,
                                                         "N" if side > 0 else "S", c, k),
                                   pitch=-lean):
                        placed += 1
                except Exception as exc:
                    warn("gate piece failed: %s" % exc)
    return placed, total


def step_canyon():
    placed, total = _canyon_flanks_v1()
    # V2 additions: vines x7 at wall bases, scree x12, FS rocks x5
    vines = valid_palette("canyon_vines")
    scree = valid_palette("bowl_scree")
    rocks = valid_palette("gate_rocks")
    adds = ([(vines, 7, "VINE", (0.9, 1.3), (5.0, 15.0))] if vines else []) \
        + ([(scree, 12, "SCREE", (0.8, 1.3), (5.0, 10.0))] if scree else []) \
        + ([(rocks, 5, "ROCK", (0.8, 1.4), (10.0, 30.0))] if rocks else [])
    for pal, n, tag, scale, sink in adds:
        for i in range(n):
            total += 1
            side = 1.0 if RNG.random() < 0.5 else -1.0
            x = RNG.uniform(GATE_X[0] + 200.0, GATE_X[1] - 200.0)
            y = side * RNG.uniform(GATE_ABS_Y[0] + 50.0, GATE_ABS_Y[1] - 100.0)
            yaw = RNG.uniform(0.0, 360.0)
            pitch, roll = (slope_lean(x, y, yaw) if tag != "VINE" else (0.0, 0.0))
            if spawn_piece(RNG.choice(pal), x, y, yaw,
                           RNG.uniform(scale[0], scale[1]),
                           "%sCANYON_%s_%02d" % (LABEL_PREFIX, tag, i),
                           pitch=pitch, roll=roll, sink_cm=sink,
                           cast_shadow=(False if tag == "VINE" else None)):
                placed += 1
    # Dusk Spire gate assembly at x 13720-13900 (outside walkable keep-clear)
    gate_placed = 0
    gate_specs = [
        (DUSK_GATE["pillar_a"], 13760.0, +DUSK_GATE_PILLAR_Y, 180.0, "GATEP_A"),
        (DUSK_GATE["pillar_b"], 13760.0, -DUSK_GATE_PILLAR_Y, 180.0, "GATEP_B"),
        (DUSK_GATE["gate"], 13800.0, 0.0, 90.0, "GATE_SPAN"),
        (DUSK_GATE["top"], 13800.0, 0.0, 90.0, "GATE_TOP"),
        (DUSK_GATE["filler"], 13860.0, +900.0, 90.0, "GATE_FILL0"),
        (DUSK_GATE["filler"], 13860.0, -900.0, 90.0, "GATE_FILL1"),
    ]
    for asset, x, y, yaw, tag in gate_specs:
        total += 1
        if not unreal.EditorAssetLibrary.does_asset_exist(asset):
            warn("Dusk gate piece missing: %s" % asset)
            continue
        if spawn_piece(asset, x, y, yaw, 1.0,
                       "%sCANYON_%s" % (LABEL_PREFIX, tag), sink_cm=(0.0, 5.0)):
            gate_placed += 1
    placed += gate_placed
    if gate_placed:
        warn("MANUAL CHECK: verify >=600 UU vertical clearance over the lane "
             "under the Dusk_Spire_Gate span and that nav still links through "
             "the corridor (plan C gate contract).")
    record("9 canyon + gate", "PASS" if placed else "FAIL",
           "%d/%d flank+adds, gate assembly %d/6" % (placed, total, gate_placed))


# ---------------------------------------------------------------------------
# Step 10: PAD RUINS (plan C: 16 per pad -- Paragon Ruins upgrade)
# ---------------------------------------------------------------------------

def step_pad_ruins():
    walls = valid_palette("pad_walls")
    pillars = valid_palette("pad_pillars")
    rubble = valid_palette("pad_rubble")
    trims = valid_palette("pad_trims")
    landmarks = valid_palette("pad_landmarks")
    if not (walls or pillars or rubble or trims or landmarks):
        record("10 pad ruins", "SKIP", "no Ruins/MedCastle assets found")
        return
    placed, total = 0, 0
    for pi, (px, py) in enumerate(PAD_CENTERS):
        try:
            # 6 wall arcs on the ring with 2 gaps (8 slots, skip 2), tangent +-10
            slots = 8
            gap_slots = set(RNG.sample(range(slots), 2))
            start_ang = RNG.uniform(0.0, 360.0)
            wall_i = 0
            for s in range(slots):
                if s in gap_slots or not walls or wall_i >= 6:
                    continue
                total += 1
                ang = start_ang + 360.0 * s / slots + RNG.uniform(-8.0, 8.0)
                rad = math.radians(ang)
                r = RNG.uniform(PAD_WALL_R[0], PAD_WALL_R[1])
                x, y = px + r * math.cos(rad), py + r * math.sin(rad)
                yaw = ang + 90.0 + RNG.uniform(-10.0, 10.0)  # tangent-aligned
                if spawn_piece(RNG.choice(walls), x, y, yaw, RNG.uniform(0.95, 1.15),
                               "%sPAD%d_WALL_%02d" % (LABEL_PREFIX, pi, s)):
                    placed += 1
                wall_i += 1
            # 4 pillar blocks / toppled stacks inside
            for k in range(4 if pillars else 0):
                total += 1
                ang = math.radians(RNG.uniform(0.0, 360.0))
                r = RNG.uniform(PAD_CENTER_KEEPOUT + 200.0, PAD_WALL_R[0] - 250.0)
                x, y = px + r * math.cos(ang), py + r * math.sin(ang)
                if spawn_piece(RNG.choice(pillars), x, y, RNG.uniform(0.0, 360.0),
                               RNG.uniform(0.9, 1.1),
                               "%sPAD%d_PILLAR_%02d" % (LABEL_PREFIX, pi, k)):
                    placed += 1
            # 2 rubble piles
            for k in range(2 if rubble else 0):
                total += 1
                ang = math.radians(RNG.uniform(0.0, 360.0))
                r = RNG.uniform(PAD_CENTER_KEEPOUT + 150.0, PAD_WALL_R[0] - 300.0)
                x, y = px + r * math.cos(ang), py + r * math.sin(ang)
                if spawn_piece(rubble[0], x, y, RNG.uniform(0.0, 360.0),
                               RNG.uniform(0.85, 1.15),
                               "%sPAD%d_RUBBLE_%02d" % (LABEL_PREFIX, pi, k)):
                    placed += 1
            # 3 low trim connectors near the wall ring
            for k in range(3 if trims else 0):
                total += 1
                ang = start_ang + RNG.uniform(0.0, 360.0)
                rad = math.radians(ang)
                r = RNG.uniform(PAD_WALL_R[0] - 150.0, PAD_WALL_R[1])
                x, y = px + r * math.cos(rad), py + r * math.sin(rad)
                yaw = ang + 90.0 + RNG.uniform(-10.0, 10.0)
                if spawn_piece(RNG.choice(trims), x, y, yaw, RNG.uniform(0.95, 1.1),
                               "%sPAD%d_TRIM_%02d" % (LABEL_PREFIX, pi, k)):
                    placed += 1
            # 1 MedCastle tower landmark, kept from v1, OUTSIDE the ring
            if landmarks:
                total += 1
                ang = math.radians(start_ang + RNG.uniform(120.0, 240.0))
                r = PAD_WALL_R[1] + 250.0
                x, y = px + r * math.cos(ang), py + r * math.sin(ang)
                yaw = math.degrees(math.atan2(py - y, px - x))
                if spawn_piece(landmarks[pi % len(landmarks)], x, y, yaw, 1.0,
                               "%sPAD%d_LANDMARK" % (LABEL_PREFIX, pi)):
                    placed += 1
        except Exception as exc:
            warn("pad %d failed wholesale: %s" % (pi, exc))
            warn(traceback.format_exc())
    record("10 pad ruins", "PASS" if placed else "FAIL",
           "%d/%d pieces across %d pads (target 16 each)" % (placed, total, len(PAD_CENTERS)))


# ---------------------------------------------------------------------------
# Step 11: ZONE FIELD (plan C: 135 pieces in the rect interior, off-pads)
# ---------------------------------------------------------------------------

def _field_pos_ok(x, y):
    if not (ZONE_RECT[0] + 400.0 <= x <= ZONE_RECT[1] - 400.0
            and ZONE_RECT[2] + 400.0 <= y <= ZONE_RECT[3] - 400.0):
        return False
    if placement_forbidden(x, y) is not None:
        return False
    for px, py in PAD_CENTERS:
        if math.hypot(x - px, y - py) < 1900.0:  # off the encounter pads
            return False
    return True


def _field_center():
    for _try in range(30):
        x = RNG.uniform(ZONE_RECT[0] + 600.0, ZONE_RECT[1] - 600.0)
        y = RNG.uniform(ZONE_RECT[2] + 600.0, ZONE_RECT[3] - 600.0)
        if _field_pos_ok(x, y):
            return x, y
    return ZONE_RECT[1] - 2000.0, 0.0


def step_zone_field():
    groups = [
        # (palette key, n, tag, scale band, sink, cast_shadow, lean, vertical)
        ("field_rocks", 20, "ROCK", (0.8, 1.4), {"sink_frac": (0.15, 0.35)}, None, True),
        ("field_boulders", 12, "BOULDER", (0.8, 1.3), {"sink_frac": (0.15, 0.35)}, None, True),
        ("field_pines", 14, "PINE", (0.9, 1.2), {"sink_cm": (5.0, 15.0)}, True, False),
        ("field_hilltrees", 5, "HILLTREE", (0.9, 1.15), {"sink_cm": (5.0, 15.0)}, True, False),
        ("field_stumps", 5, "STUMP", (0.9, 1.3), {"sink_cm": (5.0, 15.0)}, None, False),
        ("field_bushes", 18, "BUSH", (0.8, 1.3), {"sink_cm": (3.0, 10.0)}, False, False),
        ("field_debris", 12, "DEBRIS", (0.8, 1.2), {"sink_cm": (2.0, 8.0)}, False, False),
    ]
    placed, total = 0, 0
    for key, n, tag, scale, sink_kw, shadow, lean in groups:
        pal = valid_palette(key)
        if not pal:
            continue
        i = 0
        for x, y, _outlier in cluster_points(n, _field_center):
            total += 1
            if not _field_pos_ok(x, y):
                continue
            yaw = RNG.uniform(0.0, 360.0)
            pitch, roll = slope_lean(x, y, yaw) if lean else (0.0, 0.0)
            if spawn_piece(RNG.choice(pal), x, y, yaw,
                           RNG.uniform(scale[0], scale[1]),
                           "%sFIELD_%s_%02d" % (LABEL_PREFIX, tag, i),
                           pitch=pitch, roll=roll, cast_shadow=shadow, **sink_kw):
                placed += 1
            i += 1
    # 45 grass patches along pad-to-pad desire lines (CastShadow OFF)
    grass = valid_palette("grass")
    if grass:
        pairs = [(0, 1), (1, 2), (0, 2)]
        for i in range(45):
            total += 1
            a, b = pairs[i % len(pairs)]
            t = RNG.uniform(0.12, 0.88)
            x = PAD_CENTERS[a][0] + t * (PAD_CENTERS[b][0] - PAD_CENTERS[a][0]) \
                + RNG.uniform(-600.0, 600.0)
            y = PAD_CENTERS[a][1] + t * (PAD_CENTERS[b][1] - PAD_CENTERS[a][1]) \
                + RNG.uniform(-600.0, 600.0)
            if placement_forbidden(x, y) is not None:
                continue
            if spawn_piece(grass[0], x, y, RNG.uniform(0.0, 360.0),
                           RNG.uniform(0.8, 1.2),
                           "%sFIELD_GRASS_%02d" % (LABEL_PREFIX, i),
                           sink_cm=(2.0, 8.0), cast_shadow=False):
                placed += 1
    # 4 flat dead-leaf piles under the canyon-side spike trees
    flat = valid_palette("dead_leaves_flat")
    if flat:
        for i in range(4):
            total += 1
            side = 1.0 if i % 2 == 0 else -1.0
            x = RNG.uniform(GATE_X[0] + 400.0, GATE_X[1] - 400.0)
            y = side * RNG.uniform(GATE_ABS_Y[0] + 100.0, GATE_ABS_Y[1] - 200.0)
            if spawn_piece(flat[0], x, y, RNG.uniform(0.0, 360.0),
                           RNG.uniform(0.9, 1.3),
                           "%sFIELD_LEAVES_%02d" % (LABEL_PREFIX, i),
                           sink_cm=(1.0, 4.0), cast_shadow=False):
                placed += 1
    record("11 zone field", "PASS" if placed else "FAIL",
           "%d/%d pieces (alive trees so far: %d/%d)"
           % (placed, total, COUNTS["alive_trees"], ALIVE_TREE_CAP))


# ---------------------------------------------------------------------------
# Step 12: ZONE PERIMETER (plan C: 28 pieces)
# ---------------------------------------------------------------------------

def step_zone_perimeter():
    walls = valid_palette("perimeter_walls")
    cliffs = valid_palette("perimeter_cliffs")
    trees = valid_palette("gate_trees")
    if not (walls or cliffs or trees):
        record("12 zone perimeter", "SKIP", "no perimeter assets found")
        return
    x_min, x_max, y_min, y_max = ZONE_RECT
    placed, total = 0, 0
    # 12 flat-top wall rocks along N/S/E edges, inset 200-600, tangent-aligned
    edges = ["north", "south", "east"]
    for i in range(12 if walls else 0):
        total += 1
        edge = edges[i % 3]
        inset = RNG.uniform(200.0, 600.0)
        if edge == "north":
            x, y, yaw = RNG.uniform(x_min + 1200.0, x_max - 1200.0), y_max - inset, 0.0
        elif edge == "south":
            x, y, yaw = RNG.uniform(x_min + 1200.0, x_max - 1200.0), y_min + inset, 0.0
        else:
            x, y, yaw = x_max - inset, RNG.uniform(y_min + 1200.0, y_max - 1200.0), 90.0
        if spawn_piece(RNG.choice(walls), x, y, yaw + RNG.uniform(-10.0, 10.0),
                       RNG.uniform(1.0, 1.4),
                       "%sPERIM_WALL_%02d" % (LABEL_PREFIX, i)):
            placed += 1
    # 6 cliffs at the rect corners, scale 1.3-1.9
    corners = [(x_min + 1500.0, y_max - 1200.0), (x_max - 1500.0, y_max - 1200.0),
               (x_min + 1500.0, y_min + 1200.0), (x_max - 1500.0, y_min + 1200.0),
               (x_max - 1200.0, y_max - 3500.0), (x_max - 1200.0, y_min + 3500.0)]
    for i, (cx, cy) in enumerate(corners if cliffs else []):
        total += 1
        if spawn_piece(cliffs[0], cx + RNG.uniform(-300.0, 300.0),
                       cy + RNG.uniform(-300.0, 300.0),
                       RNG.uniform(0.0, 360.0), RNG.uniform(1.3, 1.9),
                       "%sPERIM_CLIFF_%02d" % (LABEL_PREFIX, i),
                       sink_cm=(50.0, 200.0)):
            placed += 1
    # 10 spike trees along the edges
    for i in range(10 if trees else 0):
        total += 1
        edge = edges[i % 3]
        inset = RNG.uniform(300.0, 800.0)
        if edge == "north":
            x, y = RNG.uniform(x_min + 1000.0, x_max - 1000.0), y_max - inset
        elif edge == "south":
            x, y = RNG.uniform(x_min + 1000.0, x_max - 1000.0), y_min + inset
        else:
            x, y = x_max - inset, RNG.uniform(y_min + 1000.0, y_max - 1000.0)
        if spawn_piece(RNG.choice(trees), x, y, RNG.uniform(0.0, 360.0),
                       RNG.uniform(0.9, 1.3),
                       "%sPERIM_TREE_%02d" % (LABEL_PREFIX, i),
                       sink_cm=(5.0, 15.0)):
            placed += 1
    record("12 zone perimeter", "PASS" if placed else "FAIL",
           "%d/%d wall-rocks + corner cliffs + spikes" % (placed, total))


# ---------------------------------------------------------------------------
# Step 13: keep-clear guard (belt and braces on top of by-construction checks)
# ---------------------------------------------------------------------------

def step_keepclear_guard():
    actors = get_actor_subsystem()
    violators = 0
    for a in list(SPAWNED):
        try:
            if a is None:
                continue
            label = str(a.get_actor_label())
            if guard_exempt(label):
                continue  # decals / floor ring / backdrop: sanctioned + no-collision
            loc = a.get_actor_location()
            reason = placement_forbidden(loc.x, loc.y)
            if reason is not None:
                warn("GUARD destroying %s -- landed in %s" % (label, reason))
                actors.destroy_actor(a)
                SPAWNED.remove(a)
                violators += 1
        except Exception as exc:
            warn("guard check failed on an actor: %s" % exc)
    record("13 keep-clear guard", "PASS",
           "0 violations" if violators == 0 else "removed %d violators" % violators)


# ---------------------------------------------------------------------------
# Step 14: count budget (plan D guardrails)
# ---------------------------------------------------------------------------

def step_count_budget():
    n = len(SPAWNED)
    over_mesh = {p.rsplit("/", 1)[-1]: c for p, c in MESH_COUNTS.items()
                 if c > _per_mesh_cap_for(p)}
    for zone in sorted(ZONE_COUNTS):
        log("  zone %-10s %4d actors" % (zone, ZONE_COUNTS[zone]))
    log("  foliage-class %d/%d, alive trees %d/%d, decals %d/%d"
        % (COUNTS["foliage"], FOLIAGE_CAP, COUNTS["alive_trees"], ALIVE_TREE_CAP,
           COUNTS["decals"], DECAL_CAP))
    ok = n <= HARD_CAP and not over_mesh \
        and COUNTS["foliage"] <= FOLIAGE_CAP and COUNTS["alive_trees"] <= ALIVE_TREE_CAP
    record("14 count budget", "PASS" if ok else "FAIL",
           "%d/%d dress actors (plan lands ~470-530; band 300-600)%s"
           % (n, HARD_CAP, "" if not over_mesh else "; PER-MESH OVER: %s" % over_mesh))


# ---------------------------------------------------------------------------
# Step 15: Nanite on placed meshes (flag-gated; foliage/trees NEVER)
# ---------------------------------------------------------------------------

def _nanite_via_subsystem(mesh):
    if not hasattr(unreal, "StaticMeshEditorSubsystem"):
        return False
    sub = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if sub is None or not hasattr(sub, "get_nanite_settings") \
            or not hasattr(sub, "set_nanite_settings"):
        return False
    settings = sub.get_nanite_settings(mesh)
    if getattr(settings, "enabled", False):
        return True  # already on -- idempotent
    settings.enabled = True
    try:
        sub.set_nanite_settings(mesh, settings, True)
    except TypeError:
        sub.set_nanite_settings(mesh, settings)  # older arity
    return bool(getattr(sub.get_nanite_settings(mesh), "enabled", False))


def _nanite_via_property(mesh):
    settings = mesh.get_editor_property("nanite_settings")
    if getattr(settings, "enabled", False):
        return True
    settings.enabled = True
    mesh.set_editor_property("nanite_settings", settings)
    reread = mesh.get_editor_property("nanite_settings")
    return bool(getattr(reread, "enabled", False))


def step_nanite():
    if not PLACED_MESHES:
        record("15 nanite", "SKIP", "no meshes were placed")
        return
    ok, already, failed, excluded = 0, 0, 0, 0
    for path, mesh in sorted(PLACED_MESHES.items()):
        try:
            if any(m in path for m in NANITE_NEVER_MARKERS):
                excluded += 1
                log("  nanite EXCLUDED (foliage/tree shader): %s" % path)
                continue
            if not isinstance(mesh, unreal.StaticMesh):
                continue
            was_on = False
            try:
                was_on = bool(getattr(
                    mesh.get_editor_property("nanite_settings"), "enabled", False))
            except Exception:
                pass
            if was_on:
                already += 1
                continue
            enabled = _nanite_via_subsystem(mesh)
            if not enabled:
                enabled = _nanite_via_property(mesh)
            if not enabled:
                raise RuntimeError("both subsystem and property paths failed verification")
            force_save_asset(mesh)
            ok += 1
            log("  nanite ENABLED + saved: %s" % path)
        except Exception as exc:
            failed += 1
            warn("  nanite FAILED for %s: %s" % (path, exc))
    record("15 nanite", "FAIL" if (ok + already) == 0 else "PASS",
           "%d enabled, %d already on, %d failed, %d foliage-excluded (of %d placed)"
           % (ok, already, failed, excluded, len(PLACED_MESHES)))


# ---------------------------------------------------------------------------
# Step 16: save level + summary
# ---------------------------------------------------------------------------

def step_save_level():
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is not None and les.save_current_level():
            record("16 save level", "PASS", "current level saved")
            return
        raise RuntimeError("save_current_level returned False")
    except Exception as exc:
        record("16 save level", "FAIL", "save manually (Ctrl+S): %s" % exc)


def print_summary():
    log("=" * 72)
    log("SET-DRESSING V2 SUMMARY  (%d actors spawned)" % len(SPAWNED))
    for step, status, detail in STEP_RESULTS:
        log("  %-4s %-28s %s" % (status, step, detail))
    n_fail = sum(1 for _, s, _ in STEP_RESULTS if s == "FAIL")
    log("-" * 72)
    log("Fight floor (r<2000): floor ring + decals ONLY (flat, no collision).")
    log("Corridor (x 10000..13500, |y|<1200) kept walkable; Dusk gate at x>=13720.")
    log("ACCEPTANCE GATE (plan D): 'stat unit' during a full boss fight with")
    log("minions aggroed -- GPU <= 14 ms at r.ScreenPercentage 80. If over:")
    log("1st lever = backdrop texture cuts (more 1024), 2nd = rim thinning to 24;")
    log("NEVER the fog/exposure settings (they're the look). Run 'stat streaming'")
    log("too -- pool is 2200; drop more backdrop sets to 1024 if over budget.")
    log("Re-meter exposure per visuals.md (settled value +-0.5) after this pass.")
    if n_fail:
        warn("%d step(s) FAILED -- see warnings above." % n_fail)
    log("=" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_STEP_LABELS = (
    "0 pre-clean", "1 texture caps (pre-place)", "2 atmosphere",
    "3 blender meshes", "4 backdrop ring", "5 rim crown", "6 bowl interior",
    "7 decals", "8 monolith court", "9 canyon + gate", "10 pad ruins",
    "11 zone field", "12 zone perimeter", "13 keep-clear guard",
    "14 count budget", "15 nanite", "16 save level")


def main():
    log("Set-dressing BossArena V2 (seed 7, labels %s*, plan v2 A/C/D)" % LABEL_PREFIX)
    # BLOCKER guard: never touch (or SAVE) a world that is not BossArena.
    if not ensure_bossarena_open():
        for label in ALL_STEP_LABELS:
            record(label, "FAIL",
                   "wrong level open and %s could not be loaded -- NOTHING "
                   "was touched" % MAP_PATH)
        print_summary()
        return
    collect_trace_ignores()
    steps = [step_preclean,
             step_texture_caps,      # BEFORE placement -- plan D mandatory order
             step_atmosphere,
             step_blender_meshes,
             step_backdrop_ring,
             step_rim_crown,
             step_bowl_interior,
             step_decals,
             step_monolith_court,
             step_canyon,
             step_pad_ruins,
             step_zone_field,
             step_zone_perimeter,
             step_keepclear_guard,
             step_count_budget]
    if DO_NANITE:
        steps.append(step_nanite)
    else:
        record("15 nanite", "SKIP",
               "DO_NANITE=False (crash-resistance default). After a successful "
               "placement pass: flip DO_NANITE=True at the top and re-run -- "
               "pre-clean + re-place is cheap and the Nanite pass runs alone. "
               "Mandatory set: SM_Cliff01, SM_MountainRock*, both Blender "
               "meshes, Paragon Ruins walls (foliage/trees auto-excluded).")
    steps.append(step_save_level)
    for fn in steps:
        try:
            fn()
        except Exception as exc:
            record(fn.__name__, "FAIL", str(exc))
            warn(traceback.format_exc())
        gc_now()   # crash-resistance: free load churn between steps
    print_summary()


main()
