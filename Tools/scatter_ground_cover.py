"""LEVER 2 -- mass ground cover via HISM for /Game/Maps/BossArena.

Run headlessly (proven pattern -- in-editor python crashes this machine):
  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"
      "D:/GAME_CORE 5.8/GAME_CORE.uproject"
      -ExecutePythonScript="D:/GAME_CORE 5.8/Tools/scatter_ground_cover.py"

ADDITIVE pass: the 508 ARENA_DRESS_* actors are NEVER touched. This script
owns ONLY the ARENA_AAA_GC_* label family (its own pre-clean destroys just
those, so re-runs are idempotent and other ARENA_AAA_* levers are safe).

LEVEL GUARD: verifies the open level is /Game/Maps/BossArena (dress_arena
ensure_bossarena_open pattern); loads it if needed; if THAT fails every step
records FAIL and the script exits without spawning or saving anything.

What it does (each step isolated; one failure never aborts the rest):
  0. Pre-clean: destroy every ARENA_AAA_GC_* actor.
  1. MIC prep: dead-tint MICs for grass (parent M_FieldGrass_Inst_01, tint
     0.30/0.26/0.17) and ferns (parent M_Fern_01_Inst, tint 0.22/0.20/0.12)
     via vector-param-name discovery on the master materials (param dump is
     logged; no color-ish param = SKIP tint, stock material used). Heather
     uses the pack's own existing dead variant
     M_HeatherPatches_Inst2_BrownPinkVairience_NoWind (no new MIC). Dead
     leaves stay stock. MIC writes are re-read verified + force-saved with
     the on-disk-mtime check.
  2-6. Five regions, one step each -- zone field / zone fringe / bowl outer
     slopes / canyon banks / pads. Per region x cover type: ONE actor with
     one HISM component per mesh (ferns fan out over SM_Fern_01/02/03),
     mobility STATIC, cast_shadow=False (plan-D ground-cover rule),
     NoCollision, no-nav, per-tier cull distances (grass/leaves 2500/5000,
     heather/fern 4000/8000). Instances are added in CHUNKS of 500 with
     collect_garbage every 5000 instances (16 GB box), then the component
     instance count is RE-READ and verified against the planned count.
     HISM components are created with CreationMethod=Instance (Subobject
     DataSubsystem primary; add_component_by_class + creation_method=
     INSTANCE re-read-verified fallback) -- add_component_by_class alone
     marks them UserConstructionScript and RerunConstructionScripts would
     silently destroy every one of them on the next editor load. If
     neither Instance path can be verified the region step FAILS loudly
     instead of building doomed components.
  7. Budget log: per-region / per-type totals vs the 24 500 plan.
  8. Save level.
  9. Reload verify: load /Game/Maps/BossArena AGAIN from disk and re-count
     every ARENA_AAA_GC_* HISM instance -- the only re-read that can catch
     UserConstructionScript-style silent component loss (in-session counts
     pass even on doomed components). Then the PASS/FAIL/SKIP summary.

Counts (THE FOUR-LEVER SPEC, exact):
    region        grass  heather  fern  leaves   total
    zone field    12000    2500   1000     500   16000
    zone fringe    2200     800      -       -    3000
    bowl slopes    2000     600    400     200    3200
    canyon banks    500       -    200     100     800
    pads (3x)       900     300    200     100    1500
                                                 24500

Masks / keep-clears (all enforced per candidate):
  - value-noise clustering: accept iff hash(floor(x/600), floor(y/600))*0.5
    + rng*0.5 > 0.45  (meadow patches, not carpet)
  - fight floor r < 2200 (flat contract: NO foliage), entrance corridor
    x 9800..13700 |y| < 1300, pad centers r < 400 (minion spawns)
  - pad-to-pad desire lines: segment distance < 300 UU rejected
  - slope > 35 deg rejected (ground_z probes)
  - ground snap: ground_z - sink 2..6 cm; yaw 0..360; scale 0.8..1.3
Placement is deterministic: per-(region, type) RNG seeded by crc32, cell
noise seeded independently -- re-runs produce identical layouts.
ground_z ignores the invisible ARENA_BV_* blocking volumes AND everything
this run spawns.
"""

import math
import os
import random
import traceback
import zlib

import unreal

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

TAG = "[GroundCover]"
LABEL_PREFIX = "ARENA_AAA_GC_"          # own label family; own pre-clean
MAP_PATH = "/Game/Maps/BossArena"
MAT_DIR = "/Game/Arena/Materials"
SEED_TEXT = "scatter_ground_cover_v1"   # deterministic layout namespace

# Map geometry (UU) -- CLAUDE.md / dress_arena.py contract
FIGHT_FLOOR_KEEPOUT_R = 2200.0          # flat contract: NO foliage inside
CORRIDOR_X = (9800.0, 13700.0)          # walkable lane keep-out (+margin)
CORRIDOR_HALF_Y = 1300.0
PAD_CENTERS = [(17000.0, -4000.0), (22000.0, 3500.0), (29000.0, -1500.0)]
PAD_CENTER_KEEPOUT = 400.0
PAD_R = 1800.0
ZONE_RECT = (10000.0, 35000.0, -8500.0, 8500.0)  # x_min, x_max, y_min, y_max
FRINGE_BAND = 600.0                     # zone perimeter fringe width
BOWL_R = (2400.0, 6800.0)               # bowl outer slopes
CANYON_X = (9800.0, 13700.0)
CANYON_ABS_Y = (1300.0, 2200.0)
DESIRE_LINE_HALF_WIDTH = 300.0          # pad-to-pad walking lanes stay clear
MAX_SLOPE_DEG = 35.0
SLOPE_PROBE_UU = 120.0

# Value-noise clustering (spec): cell 600 UU, threshold 0.45
NOISE_CELL = 600.0
NOISE_THRESHOLD = 0.45

SINK_CM = (2.0, 6.0)
SCALE_RANGE = (0.8, 1.3)

CHUNK_SIZE = 500                        # add_instances batch size
GC_EVERY_INSTANCES = 5000               # collect_garbage cadence (16 GB box)
ATTEMPTS_PER_TARGET = 30                # candidate budget per wanted instance

TRACE_TOP_Z = 20000.0
TRACE_BOTTOM_Z = -5000.0

_KD = "/Game/KiteDemo/Environments/Foliage"

MESH_GRASS = _KD + "/Grass/FieldGrass/SM_FieldGrass_01"
MESH_HEATHER = _KD + "/Flowers/Heather/SM_Heather_Mesh_Clumps2"
MESH_FERNS = [_KD + "/Ferns/SM_Fern_01",
              _KD + "/Ferns/SM_Fern_02",
              _KD + "/Ferns/SM_Fern_03"]
MESH_LEAVES = _KD + "/Leaves/SM_DeadLeaves_Flat"

GRASS_MASTER = _KD + "/Grass/FieldGrass/M_FieldGrass_01"
GRASS_PARENT = _KD + "/Grass/FieldGrass/M_FieldGrass_Inst_01"
FERN_MASTER = _KD + "/Ferns/M_Fern_01"
FERN_PARENT = _KD + "/Ferns/M_Fern_01_Inst"
HEATHER_DEAD_MI = (_KD + "/Flowers/Heather/"
                   "M_HeatherPatches_Inst2_BrownPinkVairience_NoWind")

MIC_GRASS_NAME = "MIC_GC_FieldGrass_Dead"
MIC_FERN_NAME = "MIC_GC_Fern_Dead"
GRASS_TINT = unreal.LinearColor(0.30, 0.26, 0.17, 1.0)   # x0.75 desat baked in
FERN_TINT = unreal.LinearColor(0.22, 0.20, 0.12, 1.0)

# Cover types: meshes, cull tier, material override key
#   tier "near" (grass/leaves): cull 2500/5000; tier "far" (heather/fern):
#   4000/8000 -- THE FOUR-LEVER SPEC per-type settings.
CULL_TIERS = {"near": (2500.0, 5000.0), "far": (4000.0, 8000.0)}
COVER_TYPES = {
    "grass":   {"meshes": [MESH_GRASS],   "tier": "near", "mic": "grass"},
    "heather": {"meshes": [MESH_HEATHER], "tier": "far",  "mic": "heather"},
    "fern":    {"meshes": MESH_FERNS,     "tier": "far",  "mic": "fern"},
    "leaves":  {"meshes": [MESH_LEAVES],  "tier": "near", "mic": None},
}
TYPE_ORDER = ("grass", "heather", "fern", "leaves")

# region key -> {type: count}; samplers attached in REGION_SAMPLERS below
REGION_COUNTS = [
    ("zonefield", {"grass": 12000, "heather": 2500, "fern": 1000, "leaves": 500}),
    ("fringe",    {"grass": 2200,  "heather": 800}),
    ("bowl",      {"grass": 2000,  "heather": 600,  "fern": 400,  "leaves": 200}),
    ("canyon",    {"grass": 500,   "fern": 200,     "leaves": 100}),
    ("pads",      {"grass": 900,   "heather": 300,  "fern": 200,  "leaves": 100}),
]
PLANNED_TOTAL = sum(sum(c.values()) for _, c in REGION_COUNTS)  # 24500

STEP_RESULTS = []   # (step label, PASS/FAIL/SKIP, detail)
SPAWNED = []        # actors created this run (trace ignore list)
IGNORE_ACTORS = []  # ARENA_BV_* invisible blocking volumes
CTX = {"trace_ok": True}
MICS = {}           # "grass"/"fern"/"heather" -> MaterialInterface or None
MESH_CACHE = {}
PLACED = {}         # (region, type) -> instances actually added
_HISM_PROP_STATS = {"components": 0, "failed": []}  # cast_shadow/cull re-read verify
_INSTANCE_GC = [0]
_SAVE_COUNT = [0]
GC_EVERY_SAVES = 12


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
    log("%-26s %-4s %s" % (step, status, detail))


# ---------------------------------------------------------------------------
# Editor helpers (dress_arena.py / build_arena_level.py proven patterns)
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
    """BLOCKER guard (dress_arena pattern): only ever touch BossArena."""
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
    """ARENA_BV_* invisible BlockAll cubes -- never a ground-snap surface."""
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
        warn("Could not collect ARENA_BV_* trace ignores (%s)" % exc)


def _analytic_ground_z_uu(x_uu, y_uu):
    """Terrain height at (x,y) UU from the EXACT closed-form formula the
    Blender builders used (same seeds/octaves) — the mesh IS this function
    sampled on a 0.4 m grid, so this is trace-free ground truth to within
    interpolation error. Piecewise: arena mesh spans x<=100 m, patrol zone
    x>=100 m (zone = arena base + zone features, matching the seam)."""
    xm, ym = x_uu / 100.0, y_uu / 100.0

    def _h(ix, iy, seed):
        h = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453123
        return h - math.floor(h)

    def _vn(px, py, seed):
        ix, iy = math.floor(px), math.floor(py)
        fx, fy = px - ix, py - iy
        u = fx * fx * (3.0 - 2.0 * fx)
        v = fy * fy * (3.0 - 2.0 * fy)
        a = _h(ix, iy, seed); b = _h(ix + 1, iy, seed)
        c = _h(ix, iy + 1, seed); d = _h(ix + 1, iy + 1, seed)
        return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v

    def _fbm(px, py, seed, octaves):
        val, amp, freq, tot = 0.0, 1.0, 1.0, 0.0
        for i in range(octaves):
            val += amp * _vn(px * freq, py * freq, seed + i * 17.31)
            tot += amp; amp *= 0.5; freq *= 2.0
        return val / tot - 0.5

    def _ss(e0, e1, v):
        t = max(0.0, min(1.0, (v - e0) / (e1 - e0)))
        return t * t * (3.0 - 2.0 * t)

    r = math.hypot(xm, ym)
    th = math.degrees(math.atan2(ym, xm))
    roll = _fbm(xm / 26.0, ym / 26.0, 3.1, 4)
    med = _fbm(xm / 7.0, ym / 7.0, 7.7, 3)
    mic = _fbm(xm / 1.7, ym / 1.7, 11.3, 2)
    jag = _fbm(xm / 13.0, ym / 13.0, 23.9, 4)
    fa = _ss(14, 40, r)
    z = (1.3 * _ss(20, 44, r) + roll * 2.6 * fa
         + med * (0.9 * fa + 0.06) + mic * (0.14 * fa + 0.05))
    rim = (15.0 * _ss(68, 82, r) - 2.0 * _ss(84, 92, r)
           - 5.0 * _ss(92, 100, r) - 6.0 * _ss(100, 140, r))
    z += (rim + jag * 4.0 * _ss(64, 78, r)) * (1.0 - 0.96 * math.exp(-(th / 8.0) ** 2))
    if xm >= 100.0:  # patrol-zone overlays (zone mesh replaces arena east of the seam)
        z += _ss(112, 150, xm) * (1.1 + _fbm(xm / 22.0, ym / 22.0, 41.7, 4) * 2.2)
        d_edge = min(350.0 - xm, min(85.0 - ym, 85.0 + ym))
        z += ((14.0 * (1.0 - _ss(2.0, 12.0, d_edge))
               + jag * 3.0 * (1.0 - _ss(4.0, 16.0, d_edge))) * _ss(100, 112, xm))
        z += 11.0 * _ss(101, 109, xm) * (1.0 - _ss(112, 122, xm)) * _ss(14, 26, abs(ym))
        for px_, py_ in ((170.0, -40.0), (220.0, 35.0), (290.0, -15.0)):
            d = math.hypot(xm - px_, ym - py_)
            mk = 0.9 * math.exp(-((d / 18.0) ** 4))
            z = z * (1 - mk) + 2.4 * mk
    return z * 100.0


def _hit_result_z(hit):
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
    raise AttributeError("no location-like field on HitResult")


def ground_z(x, y, default_z=None):
    """Terrain Z at (x, y): line-trace when the API cooperates, else the
    analytic Blender-formula port (ground truth for the terrain meshes;
    dressing props on top are not accounted, which is fine for cover)."""
    if CTX.get("use_analytic"):
        return _analytic_ground_z_uu(x, y)
    if not CTX["trace_ok"]:
        return _analytic_ground_z_uu(x, y)
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
        if not CTX.get("use_analytic"):
            warn("Ground trace unavailable (%s) -- switching to the ANALYTIC "
                 "terrain height (Blender formula port); slope mask stays ON."
                 % exc)
            CTX["use_analytic"] = True
        return _analytic_ground_z_uu(x, y)


def slope_too_steep(x, y, z0):
    """True when local slope exceeds MAX_SLOPE_DEG (two ground_z probes)."""
    if not CTX["trace_ok"]:
        return False
    # explicit None default: a probe miss must return None (not z0) so the
    # edge rejection below actually fires -- default_z=z0 read edge-of-mesh
    # candidates as perfectly flat and planted them past the 35-deg mask
    zx = ground_z(x + SLOPE_PROBE_UU, y, None)
    zy = ground_z(x, y + SLOPE_PROBE_UU, None)
    if zx is None or zy is None:
        return True  # probe fell off the mesh edge -- don't plant there
    sx = math.degrees(math.atan2(abs(zx - z0), SLOPE_PROBE_UU))
    sy = math.degrees(math.atan2(abs(zy - z0), SLOPE_PROBE_UU))
    return max(sx, sy) > MAX_SLOPE_DEG


def load_mesh(path):
    if path in MESH_CACHE:
        return MESH_CACHE[path]
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        warn("Mesh missing on disk: %s" % path)
        MESH_CACHE[path] = None
        return None
    asset = unreal.EditorAssetLibrary.load_asset(path)
    if not isinstance(asset, unreal.StaticMesh):
        warn("Not a StaticMesh (skipped): %s" % path)
        asset = None
    MESH_CACHE[path] = asset
    return asset


def force_save_asset(asset):
    """dirty -> save(only_if_is_dirty=False) -> verify on-disk mtime advanced
    (dirty-gated saves silently wrote NOTHING in earlier passes)."""
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
# Determinism helpers
# ---------------------------------------------------------------------------

def _crc_float(text):
    """Deterministic [0, 1) from a string (builtin hash() is salted per run)."""
    return (zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF) / 4294967296.0


def cell_noise(x, y):
    cx = int(math.floor(x / NOISE_CELL))
    cy = int(math.floor(y / NOISE_CELL))
    return _crc_float("%s:cell:%d:%d" % (SEED_TEXT, cx, cy))


def region_rng(region, cover):
    return random.Random(zlib.crc32(
        ("%s:%s:%s" % (SEED_TEXT, region, cover)).encode("utf-8")))


# ---------------------------------------------------------------------------
# Keep-clear contract
# ---------------------------------------------------------------------------

def _dist_point_segment(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    vv = vx * vx + vy * vy
    t = 0.0 if vv <= 0.0 else max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    dx, dy = px - (ax + t * vx), py - (ay + t * vy)
    return math.hypot(dx, dy)


DESIRE_LINES = [(PAD_CENTERS[i], PAD_CENTERS[j])
                for i in range(len(PAD_CENTERS))
                for j in range(i + 1, len(PAD_CENTERS))]


def placement_forbidden(x, y):
    """Reason string when (x, y) violates the keep-clear contract, else None."""
    if math.hypot(x, y) < FIGHT_FLOOR_KEEPOUT_R:
        return "fight floor"
    if CORRIDOR_X[0] <= x <= CORRIDOR_X[1] and abs(y) < CORRIDOR_HALF_Y:
        return "entrance corridor"
    for px, py in PAD_CENTERS:
        if math.hypot(x - px, y - py) < PAD_CENTER_KEEPOUT:
            return "pad center"
    for (ax, ay), (bx, by) in DESIRE_LINES:
        if _dist_point_segment(x, y, ax, ay, bx, by) < DESIRE_LINE_HALF_WIDTH:
            return "desire line"
    return None


# ---------------------------------------------------------------------------
# Region samplers -- each returns a candidate (x, y)
# ---------------------------------------------------------------------------

def sample_zonefield(rng):
    return (rng.uniform(ZONE_RECT[0] + 300.0, ZONE_RECT[1] - 300.0),
            rng.uniform(ZONE_RECT[2] + 300.0, ZONE_RECT[3] - 300.0))


_FRINGE_BANDS = None


def _fringe_bands():
    """(x_min, x_max, y_min, y_max, area) for the four inner border bands."""
    global _FRINGE_BANDS
    if _FRINGE_BANDS is None:
        x0, x1, y0, y1 = ZONE_RECT
        b = FRINGE_BAND
        bands = [
            (x0, x1, y1 - b, y1),      # north
            (x0, x1, y0, y0 + b),      # south
            (x1 - b, x1, y0 + b, y1 - b),  # east (minus corners)
            (x0, x0 + b, y0 + b, y1 - b),  # west
        ]
        _FRINGE_BANDS = [(bx0, bx1, by0, by1, (bx1 - bx0) * (by1 - by0))
                         for bx0, bx1, by0, by1 in bands]
    return _FRINGE_BANDS


def sample_fringe(rng):
    bands = _fringe_bands()
    total = sum(b[4] for b in bands)
    pick = rng.uniform(0.0, total)
    for bx0, bx1, by0, by1, area in bands:
        if pick <= area:
            return rng.uniform(bx0, bx1), rng.uniform(by0, by1)
        pick -= area
    bx0, bx1, by0, by1, _ = bands[-1]
    return rng.uniform(bx0, bx1), rng.uniform(by0, by1)


def sample_bowl(rng):
    # sqrt for area-uniform radial distribution
    r = math.sqrt(rng.uniform(BOWL_R[0] ** 2, BOWL_R[1] ** 2))
    a = rng.uniform(0.0, 2.0 * math.pi)
    return r * math.cos(a), r * math.sin(a)


def sample_canyon(rng):
    x = rng.uniform(CANYON_X[0], CANYON_X[1])
    y = rng.uniform(CANYON_ABS_Y[0], CANYON_ABS_Y[1])
    return x, y if rng.random() < 0.5 else -y


def sample_pads(rng):
    px, py = PAD_CENTERS[rng.randrange(len(PAD_CENTERS))]
    r = math.sqrt(rng.uniform((PAD_CENTER_KEEPOUT + 20.0) ** 2,
                              (PAD_R - 20.0) ** 2))
    a = rng.uniform(0.0, 2.0 * math.pi)
    return px + r * math.cos(a), py + r * math.sin(a)


REGION_SAMPLERS = {
    "zonefield": sample_zonefield,
    "fringe": sample_fringe,
    "bowl": sample_bowl,
    "canyon": sample_canyon,
    "pads": sample_pads,
}


# ---------------------------------------------------------------------------
# Step 0: pre-clean (own label family ONLY -- this pass is additive)
# ---------------------------------------------------------------------------

def step_preclean():
    actors = get_actor_subsystem()
    doomed = [a for a in actors.get_all_level_actors()
              if a is not None and str(a.get_actor_label()).startswith(LABEL_PREFIX)]
    killed = 0
    for a in doomed:
        try:
            actors.destroy_actor(a)
            killed += 1
        except Exception as exc:
            warn("Could not destroy %s: %s" % (a.get_actor_label(), exc))
    record("0 pre-clean", "PASS", "destroyed %d %s* actors" % (killed, LABEL_PREFIX))


# ---------------------------------------------------------------------------
# Step 1: MIC prep (tint overrides)
# ---------------------------------------------------------------------------

MEL = unreal.MaterialEditingLibrary


def _vector_param_names(material_paths):
    """Dump + return vector parameter names from the first loadable material."""
    for path in material_paths:
        try:
            mat = unreal.EditorAssetLibrary.load_asset(path)
            if mat is None:
                continue
            base = mat
            try:  # MI parent -> walk to the master for the param dump
                if isinstance(mat, unreal.MaterialInstance):
                    base = mat.get_base_material()
            except Exception:
                pass
            names = [str(n) for n in (MEL.get_vector_parameter_names(base) or [])]
            log("  vector params on %s: %s" % (path.rsplit("/", 1)[-1], names))
            if names:
                return names
        except Exception as exc:
            warn("  param dump failed for %s: %s" % (path, exc))
    return []


def _pick_tint_param(names):
    for n in names:
        ln = n.lower()
        if "color" in ln or "tint" in ln:
            return n
    return names[0] if len(names) == 1 else None


def _create_mic(name, parent):
    dest = "%s/%s" % (MAT_DIR, name)
    if unreal.EditorAssetLibrary.does_asset_exist(dest):
        mic = unreal.EditorAssetLibrary.load_asset(dest)
        if isinstance(mic, unreal.MaterialInstanceConstant):
            log("  MIC exists, re-using: %s" % dest)
            return mic
        raise RuntimeError("%s exists but is not a MaterialInstanceConstant" % dest)
    if hasattr(MEL, "create_material_instance_asset"):
        try:
            mic = MEL.create_material_instance_asset(name, MAT_DIR, parent)
            if mic is not None:
                return mic
        except Exception as exc:
            warn("  create_material_instance_asset failed (%s) -- factory path." % exc)
    factory = unreal.MaterialInstanceConstantFactoryNew()
    try:
        factory.set_editor_property("initial_parent", parent)
    except Exception:
        pass
    mic = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, MAT_DIR, unreal.MaterialInstanceConstant, factory)
    if mic is None:
        raise RuntimeError("could not create MIC %s" % dest)
    try:
        if hasattr(MEL, "set_material_instance_parent"):
            MEL.set_material_instance_parent(mic, parent)
        else:
            mic.set_editor_property("parent", parent)
    except Exception as exc:
        raise RuntimeError("could not set parent on %s: %s" % (dest, exc))
    return mic


def _colors_close(a, b, tol=0.01):
    try:
        return (abs(float(a.r) - float(b.r)) < tol
                and abs(float(a.g) - float(b.g)) < tol
                and abs(float(a.b) - float(b.b)) < tol)
    except Exception:
        return False


def _make_tint_mic(key, mic_name, parent_path, master_path, tint):
    """One MIC, isolated: any failure -> MICS[key]=None (stock material)."""
    if not unreal.EditorAssetLibrary.does_asset_exist(parent_path):
        warn("MIC[%s]: parent missing (%s) -- stock material." % (key, parent_path))
        return None
    parent = unreal.EditorAssetLibrary.load_asset(parent_path)
    names = _vector_param_names([master_path, parent_path])
    pname = _pick_tint_param(names)
    if pname is None:
        warn("MIC[%s]: no color/tint vector param among %s -- stock material "
             "(mesh is already straw-dead; acceptable)." % (key, names))
        return None
    mic = _create_mic(mic_name, parent)
    if not MEL.set_material_instance_vector_parameter_value(mic, pname, tint):
        raise RuntimeError("set_material_instance_vector_parameter_value('%s') "
                           "returned False" % pname)
    got = MEL.get_material_instance_vector_parameter_value(mic, pname)
    if not _colors_close(got, tint):
        raise RuntimeError("re-read of '%s' does not match the written tint "
                           "(struct write-back silently failed?)" % pname)
    try:
        MEL.update_material_instance(mic)
    except Exception:
        pass
    force_save_asset(mic)
    log("  MIC[%s] ready: %s/%s (param '%s')" % (key, MAT_DIR, mic_name, pname))
    return mic


def step_mics():
    made, failed = [], []
    # grass tint MIC
    try:
        MICS["grass"] = _make_tint_mic("grass", MIC_GRASS_NAME, GRASS_PARENT,
                                       GRASS_MASTER, GRASS_TINT)
        made.append("grass" if MICS["grass"] else "grass(stock)")
    except Exception as exc:
        warn("MIC[grass] FAILED (%s) -- stock material." % exc)
        warn(traceback.format_exc())
        MICS["grass"] = None
        failed.append("grass")
    # fern tint MIC
    try:
        MICS["fern"] = _make_tint_mic("fern", MIC_FERN_NAME, FERN_PARENT,
                                      FERN_MASTER, FERN_TINT)
        made.append("fern" if MICS["fern"] else "fern(stock)")
    except Exception as exc:
        warn("MIC[fern] FAILED (%s) -- stock material." % exc)
        warn(traceback.format_exc())
        MICS["fern"] = None
        failed.append("fern")
    # heather: the pack's own dead/no-wind variant, no new MIC needed
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(HEATHER_DEAD_MI):
            MICS["heather"] = unreal.EditorAssetLibrary.load_asset(HEATHER_DEAD_MI)
            made.append("heather(pack)")
        else:
            warn("Heather dead variant missing: %s -- stock material." % HEATHER_DEAD_MI)
            MICS["heather"] = None
            failed.append("heather")
    except Exception as exc:
        warn("Heather MI load FAILED (%s) -- stock material." % exc)
        MICS["heather"] = None
        failed.append("heather")
    status = "FAIL" if len(failed) == 3 else "PASS"
    record("1 MIC prep", status,
           "ready: %s%s" % (", ".join(made) or "none",
                            ("; FAILED: " + ", ".join(failed)) if failed else ""))
    gc_now()


# ---------------------------------------------------------------------------
# HISM plumbing
# ---------------------------------------------------------------------------

def _make_transform(x, y, z, yaw, scale):
    try:
        return unreal.Transform(
            location=unreal.Vector(x, y, z),
            rotation=unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw),
            scale=unreal.Vector(scale, scale, scale))
    except Exception:
        t = unreal.Transform()
        t.set_editor_property("translation", unreal.Vector(x, y, z))
        t.set_editor_property(
            "rotation", unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw).quaternion())
        t.set_editor_property("scale3d", unreal.Vector(scale, scale, scale))
        return t


def _add_hism_component_raw(actor, context):
    """AActor.add_component_by_class, tolerant of 5.x arg-shape drift.
    NOTE: components created this way come back CreationMethod=
    UserConstructionScript -- the caller MUST force creation_method=INSTANCE
    afterwards or RerunConstructionScripts destroys them on the next load."""
    cls = unreal.HierarchicalInstancedStaticMeshComponent
    attempts = (
        lambda: actor.add_component_by_class(cls, False, unreal.Transform(), False),
        lambda: actor.add_component_by_class(cls, False, unreal.Transform(), True),
        lambda: actor.add_component_by_class(cls),
    )
    last = None
    for fn in attempts:
        try:
            comp = fn()
            if comp is not None:
                return comp
        except Exception as exc:
            last = exc
    raise RuntimeError("add_component_by_class(HISM) failed on %s: %s" % (context, last))


def _resolve_subobject_component(sds, handle):
    """SubobjectDataHandle -> live HISM component (5.x API-shape tolerant)."""
    data = None
    for fn_name in ("k2_find_subobject_data_from_handle",
                    "find_subobject_data_from_handle"):
        fn = getattr(sds, fn_name, None)
        if fn is None:
            continue
        try:
            data = fn(handle)
            break
        except Exception:
            continue
    if data is None:
        return None
    lib = getattr(unreal, "SubobjectDataBlueprintFunctionLibrary", None)
    if lib is None:
        return None
    for fn_name in ("get_object", "get_object_for_blueprint"):
        fn = getattr(lib, fn_name, None)
        if fn is None:
            continue
        try:
            obj = fn(data)
            if isinstance(obj, unreal.HierarchicalInstancedStaticMeshComponent):
                return obj
        except Exception:
            continue
    return None


def _creation_method_is_instance(comp):
    """True/False from the enum VALUE (5.8 python does not export the
    unreal.ComponentCreationMethod enum CLASS — compare by name-string or
    raw int instead). None = unreadable."""
    try:
        got = comp.get_editor_property("creation_method")
    except Exception:
        return None
    if isinstance(got, int):
        return got == 3  # EComponentCreationMethod::Instance
    return "INSTANCE" in str(got).upper()


def _ensure_instance_creation_method(comp, context, via_subsystem=False):
    """Verify (and where possible force) CreationMethod=Instance so the
    component survives RerunConstructionScripts on the next editor open.
    5.8: the enum class is not exposed to python, so verification is by
    value-string/int; writes try enum (if present), name-string, then int.
    Components added via SubobjectDataSubsystem on a level-actor instance
    are created as Instance by the subsystem itself — when the property is
    unreadable we trust that path (step 9's reload-verify backstops)."""
    if _creation_method_is_instance(comp) is True:
        return True, "already Instance"
    enum_cls = None
    for name in ("ComponentCreationMethod", "EComponentCreationMethod"):
        cand = getattr(unreal, name, None)
        if cand is not None and hasattr(cand, "INSTANCE"):
            enum_cls = cand
            break
    candidates = ([enum_cls.INSTANCE] if enum_cls else []) + ["Instance", 3]
    for value in candidates:
        try:
            comp.set_editor_property("creation_method", value)
        except Exception:
            continue
        if _creation_method_is_instance(comp) is True:
            return True, "forced to Instance (re-read verified)"
    status = _creation_method_is_instance(comp)
    if status is True:
        return True, "Instance (verified)"
    if via_subsystem and status is None:
        return True, ("creation_method unreadable in this python surface; "
                      "trusting the SubobjectDataSubsystem instance-add "
                      "(step 9 reload-verify backstops)")
    if via_subsystem and status is False:
        return True, ("creation_method reads non-Instance but the component "
                      "came from SubobjectDataSubsystem's instance path; "
                      "step 9 reload-verify is the arbiter -- WATCH IT")
    return False, "creation_method could not be verified or forced (raw add path)"


def _add_hism_component(actor, context):
    """Create ONE HISM that SURVIVES the next editor load of BossArena.

    add_component_by_class routes through PostCreateBlueprintComponent and
    marks the component UserConstructionScript; every editor level load runs
    RerunConstructionScripts -> DestroyConstructedComponents, which destroys
    every such component, and a plain native unreal.Actor has no UCS to
    rebuild them -- all 24 500 instances would silently vanish on the NEXT
    open (and the loss would be baked in by any later save).
      primary : SubobjectDataSubsystem.add_new_subobject -> per-instance
                component (CreationMethod=Instance, serialized with actor)
      fallback: raw add_component_by_class + creation_method=INSTANCE,
                re-read verified
      neither : raise -> the region step FAILS loudly rather than building
                doomed components.
    """
    comp, how = None, None
    sds = None
    if hasattr(unreal, "SubobjectDataSubsystem"):
        try:
            sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
        except Exception:
            sds = None
    if sds is not None and hasattr(unreal, "AddNewSubobjectParams"):
        try:
            handles = list(sds.k2_gather_subobject_data_for_instance(actor) or [])
            if handles:
                params = unreal.AddNewSubobjectParams(
                    parent_handle=handles[0],
                    new_class=unreal.HierarchicalInstancedStaticMeshComponent)
                result = sds.add_new_subobject(params)
                handle = result[0] if isinstance(result, tuple) else result
                comp = _resolve_subobject_component(sds, handle)
                if comp is not None:
                    how = "SubobjectDataSubsystem"
        except Exception as exc:
            warn("  SubobjectDataSubsystem path failed on %s (%s) -- "
                 "creation_method=INSTANCE fallback." % (context, exc))
            comp = None
    if comp is None:
        comp = _add_hism_component_raw(actor, context)
        how = "add_component_by_class"
    ok, detail = _ensure_instance_creation_method(
        comp, context, via_subsystem=(how == "SubobjectDataSubsystem"))
    if not ok:
        raise RuntimeError(
            "%s: HISM would NOT survive a level reload (%s; via %s) -- "
            "refusing to build doomed components" % (context, detail, how))
    return comp


def _configure_hism(comp, mesh, tier, mic, context):
    if not comp.set_static_mesh(mesh):
        raise RuntimeError("set_static_mesh failed on %s" % context)
    try:
        comp.set_mobility(unreal.ComponentMobility.STATIC)
    except Exception:
        try:
            comp.set_editor_property("mobility", unreal.ComponentMobility.STATIC)
        except Exception as exc:
            warn("  mobility STATIC did not stick on %s: %s" % (context, exc))
    start, end = CULL_TIERS[tier]
    try:
        comp.set_cull_distances(int(start), int(end))
    except Exception:
        ok1 = ok2 = False
        try:
            comp.set_editor_property("instance_start_cull_distance", int(start))
            ok1 = True
            comp.set_editor_property("instance_end_cull_distance", int(end))
            ok2 = True
        except Exception:
            pass
        if not (ok1 and ok2):
            warn("  cull distances did not stick on %s" % context)
    try:
        comp.set_editor_property("cast_shadow", False)  # plan-D ground-cover rule
    except Exception as exc:
        warn("  cast_shadow=False did not stick on %s: %s" % (context, exc))
    try:
        comp.set_can_ever_affect_navigation(False)
    except Exception:
        try:
            comp.set_editor_property("can_ever_affect_navigation", False)
        except Exception:
            pass
    try:
        comp.set_collision_profile_name("NoCollision")
    except Exception:
        pass
    if mic is not None:
        try:
            comp.set_material(0, mic)
        except Exception as exc:
            warn("  material override did not stick on %s: %s" % (context, exc))
    # RE-READ verify the hard-rule properties (blanket write-back rule):
    # cast_shadow OFF + both cull distances must be PROVABLY set, or the
    # summary must say so instead of asserting them unconditionally.
    _HISM_PROP_STATS["components"] += 1
    bad = []
    for name, want in (("cast_shadow", False),
                       ("instance_start_cull_distance", int(start)),
                       ("instance_end_cull_distance", int(end))):
        try:
            got = comp.get_editor_property(name)
            mismatch = (bool(got) != want) if isinstance(want, bool) \
                else (int(got) != want)
            if mismatch:
                bad.append("%s=%s (wanted %s)" % (name, got, want))
        except Exception as exc:
            bad.append("%s unreadable (%s)" % (name, exc))
    if bad:
        _HISM_PROP_STATS["failed"].append("%s: %s" % (context, ", ".join(bad)))
        warn("  HISM prop verify FAILED on %s: %s" % (context, ", ".join(bad)))


def _add_instances_chunked(comp, transforms, context):
    """Chunks of 500; GC every 5000 instances; RE-READ count verified."""
    added = 0
    for i in range(0, len(transforms), CHUNK_SIZE):
        chunk = transforms[i:i + CHUNK_SIZE]
        try:
            comp.add_instances(chunk, False)
        except Exception:
            # arg-shape drift fallback: (transforms, return_indices, world_space)
            comp.add_instances(chunk, False, False)
        added += len(chunk)
        _INSTANCE_GC[0] += len(chunk)
        if _INSTANCE_GC[0] >= GC_EVERY_INSTANCES:
            _INSTANCE_GC[0] = 0
            gc_now()
    got = int(comp.get_instance_count())
    if got != len(transforms):
        raise RuntimeError("%s: instance count re-read %d != planned %d"
                           % (context, got, len(transforms)))
    return added


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def generate_points(region, cover, target):
    """Deterministic accepted (x, y, z) list for one (region, type)."""
    rng = region_rng(region, cover)
    sampler = REGION_SAMPLERS[region]
    pts = []
    attempts = 0
    budget = target * ATTEMPTS_PER_TARGET
    rejected = {"forbidden": 0, "noise": 0, "slope": 0, "no_ground": 0}
    while len(pts) < target and attempts < budget:
        attempts += 1
        x, y = sampler(rng)
        # value-noise clustering FIRST (cheap): meadow patches, not carpet
        if cell_noise(x, y) * 0.5 + rng.random() * 0.5 <= NOISE_THRESHOLD:
            rejected["noise"] += 1
            continue
        if placement_forbidden(x, y) is not None:
            rejected["forbidden"] += 1
            continue
        z = ground_z(x, y)
        if z is None:
            rejected["no_ground"] += 1
            continue
        if slope_too_steep(x, y, z):
            rejected["slope"] += 1
            continue
        pts.append((x, y, z))
    if len(pts) < target:
        warn("  %s/%s: only %d/%d accepted after %d attempts (rejects: %s)"
             % (region, cover, len(pts), target, attempts, rejected))
    return pts


# ---------------------------------------------------------------------------
# Region build steps
# ---------------------------------------------------------------------------

def build_region(step_label, region, counts):
    """One step per region; each (type) isolated inside it."""
    built, failed, skipped = [], [], []
    for cover in TYPE_ORDER:
        target = counts.get(cover, 0)
        if target <= 0:
            continue
        try:
            n = _build_cover(region, cover, target)
            if n == 0:
                skipped.append(cover)
            else:
                built.append("%s:%d" % (cover, n))
        except Exception as exc:
            failed.append(cover)
            warn("%s/%s FAILED: %s" % (region, cover, exc))
            warn(traceback.format_exc())
        gc_now()
    if not built and failed:
        record(step_label, "FAIL", "all types failed: %s" % ", ".join(failed))
    elif not built and skipped:
        record(step_label, "SKIP", "no meshes available (%s)" % ", ".join(skipped))
    else:
        record(step_label, "PASS",
               "%s%s%s" % (", ".join(built),
                           ("; FAILED " + ",".join(failed)) if failed else "",
                           ("; SKIP " + ",".join(skipped)) if skipped else ""))


def _build_cover(region, cover, target):
    spec = COVER_TYPES[cover]
    meshes = [m for m in (load_mesh(p) for p in spec["meshes"]) if m is not None]
    if not meshes:
        warn("%s/%s: no meshes on disk -- skipped." % (region, cover))
        return 0
    pts = generate_points(region, cover, target)
    if not pts:
        warn("%s/%s: zero accepted candidates -- skipped." % (region, cover))
        return 0
    rng = region_rng(region, cover + ":xform")
    # fan points over the meshes (ferns: 3 HISMs; others: 1)
    per_mesh = [[] for _ in meshes]
    for idx, (x, y, z) in enumerate(pts):
        yaw = rng.uniform(0.0, 360.0)
        scale = rng.uniform(SCALE_RANGE[0], SCALE_RANGE[1])
        sink = rng.uniform(SINK_CM[0], SINK_CM[1])
        per_mesh[idx % len(meshes)].append(
            _make_transform(x, y, z - sink, yaw, scale))

    label = "%s%s_%s" % (LABEL_PREFIX, region, cover)
    actor = get_actor_subsystem().spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0.0, 0.0, 0.0),
        unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0))
    if actor is None:
        raise RuntimeError("spawn_actor_from_class(Actor) returned None for %s" % label)
    actor.set_actor_label(label)
    SPAWNED.append(actor)

    total = 0
    mic = MICS.get(spec["mic"]) if spec["mic"] else None
    try:
        for mesh, transforms in zip(meshes, per_mesh):
            if not transforms:
                continue
            context = "%s[%s]" % (label, mesh.get_name())
            comp = _add_hism_component(actor, context)
            _configure_hism(comp, mesh, spec["tier"], mic, context)
            total += _add_instances_chunked(comp, transforms, context)
        # write-back verification: components + counts re-read from the actor
        comps = actor.get_components_by_class(
            unreal.HierarchicalInstancedStaticMeshComponent)
        got = sum(int(c.get_instance_count()) for c in comps)
        if got != total:
            raise RuntimeError("%s: actor re-read %d instances != %d added"
                               % (label, got, total))
    except Exception:
        # per-item isolation: never leave a half-built cover actor behind
        try:
            get_actor_subsystem().destroy_actor(actor)
            SPAWNED.remove(actor)
        except Exception:
            pass
        raise
    PLACED[(region, cover)] = total
    log("  + %-34s %d instances over %d HISM (tier %s, mic %s)"
        % (label, total, len([t for t in per_mesh if t]), spec["tier"],
           "yes" if mic is not None else "stock"))
    return total


# ---------------------------------------------------------------------------
# Step 7: budget log
# ---------------------------------------------------------------------------

def step_budget():
    total = sum(PLACED.values())
    by_type = {}
    for (region, cover), n in PLACED.items():
        by_type[cover] = by_type.get(cover, 0) + n
    for region, counts in REGION_COUNTS:
        placed = sum(PLACED.get((region, c), 0) for c in counts)
        planned = sum(counts.values())
        log("  region %-10s %6d / %6d planned" % (region, placed, planned))
    log("  by type: %s" % ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(by_type.items())))
    status = "PASS" if total > 0 else "FAIL"
    if total > PLANNED_TOTAL:
        status = "FAIL"  # impossible by construction; belt-and-braces
    record("7 budget", status, "%d / %d planned instances" % (total, PLANNED_TOTAL))


# ---------------------------------------------------------------------------
# Step 8: save level
# ---------------------------------------------------------------------------

def step_save_level():
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is not None and les.save_current_level():
            record("8 save level", "PASS", "current level saved")
            return
        raise RuntimeError("save_current_level returned False")
    except Exception as exc:
        record("8 save level", "FAIL", "save manually (Ctrl+S): %s" % exc)


# ---------------------------------------------------------------------------
# Step 9: reload verify -- the ONLY re-read that catches component loss
# ---------------------------------------------------------------------------

def step_reload_verify():
    """Round-trip /Game/Maps/BossArena through disk and re-count every
    ARENA_AAA_GC_* HISM instance. In-session count re-reads all PASS even
    when the components are doomed (UserConstructionScript creation method:
    they serialize fine and only vanish on the NEXT editor open) -- this
    save->load->recount is the only verification that catches that class of
    silent loss."""
    if not PLACED or sum(PLACED.values()) == 0:
        record("9 reload verify", "SKIP", "nothing was placed this run")
        return
    save_status = next((s for step, s, _ in STEP_RESULTS
                        if step == "8 save level"), None)
    if save_status != "PASS":
        record("9 reload verify", "SKIP",
               "level save did not PASS -- reloading now would discard the "
               "in-memory instances and test stale on-disk data")
        return
    expected = {"%s%s_%s" % (LABEL_PREFIX, region, cover): n
                for (region, cover), n in PLACED.items() if n > 0}
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les is None:
            raise RuntimeError("LevelEditorSubsystem unavailable")
        if not les.load_level(MAP_PATH):
            raise RuntimeError("load_level returned False")
    except Exception as exc:
        record("9 reload verify", "FAIL",
               "could not round-trip the level: %s" % exc)
        return
    gc_now()
    found = {}
    try:
        for a in get_actor_subsystem().get_all_level_actors():
            try:
                label = str(a.get_actor_label())
            except Exception:
                continue
            if not label.startswith(LABEL_PREFIX):
                continue
            try:
                comps = a.get_components_by_class(
                    unreal.HierarchicalInstancedStaticMeshComponent)
                found[label] = sum(int(c.get_instance_count()) for c in comps)
            except Exception:
                found[label] = -1
    except Exception as exc:
        record("9 reload verify", "FAIL", "post-reload actor scan failed: %s" % exc)
        return
    lost = ["%s %d->%d" % (label, want, found.get(label, 0))
            for label, want in sorted(expected.items())
            if found.get(label, 0) != want]
    total_want = sum(expected.values())
    total_got = sum(max(found.get(label, 0), 0) for label in expected)
    if lost:
        record("9 reload verify", "FAIL",
               "instances did NOT survive the save->reload round-trip "
               "(%d/%d): %s -- CreationMethod regression (components must be "
               "Instance, not UserConstructionScript)"
               % (total_got, total_want, "; ".join(lost[:8])))
    else:
        record("9 reload verify", "PASS",
               "%d actors / %d instances survived a full save->reload "
               "round-trip" % (len(expected), total_want))


def print_summary():
    log("=" * 72)
    log("GROUND-COVER (LEVER 2) SUMMARY  (%d HISM actors, %d instances)"
        % (len(SPAWNED), sum(PLACED.values())))
    for step, status, detail in STEP_RESULTS:
        log("  %-4s %-26s %s" % (status, step, detail))
    n_fail = sum(1 for _, s, _ in STEP_RESULTS if s == "FAIL")
    log("-" * 72)
    log("Fight floor r<2200 / corridor / pad centers / desire lines kept clear.")
    n_comp = _HISM_PROP_STATS["components"]
    n_bad = len(_HISM_PROP_STATS["failed"])
    if n_comp and not n_bad:
        log("Re-read verified on all %d HISM components: cast_shadow OFF, cull"
            % n_comp)
        log("grass+leaves 2500/5000, heather+fern 4000/8000. (NoCollision and")
        log("no-nav remain warn-only -- any misses appear as warnings above.)")
    else:
        warn("cast_shadow/cull verified on %d/%d HISM components; %d FAILED "
             "-- the 'grass shadows OFF' rule is NOT proven; see warnings "
             "above." % (n_comp - n_bad, n_comp, n_bad))
    log("PERF GATE (spec): 'stat unit' mid-fight, GPU <= 14 ms @ SP 80. Dial")
    log("order: zone grass 12000->6000, then cull 2500/5000->1800/3500. Never")
    log("touch the dress_arena atmosphere numbers or r.Streaming.PoolSize.")
    if n_fail:
        warn("%d step(s) FAILED -- see warnings above." % n_fail)
    log("=" * 72)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_STEP_LABELS = (
    "0 pre-clean", "1 MIC prep", "2 zone field", "3 zone fringe",
    "4 bowl slopes", "5 canyon banks", "6 pads", "7 budget", "8 save level",
    "9 reload verify")

REGION_STEP_LABELS = {
    "zonefield": "2 zone field",
    "fringe": "3 zone fringe",
    "bowl": "4 bowl slopes",
    "canyon": "5 canyon banks",
    "pads": "6 pads",
}


def main():
    log("Ground-cover scatter (LEVER 2, deterministic '%s', labels %s*)"
        % (SEED_TEXT, LABEL_PREFIX))
    if not ensure_bossarena_open():
        for label in ALL_STEP_LABELS:
            record(label, "FAIL",
                   "wrong level open and %s could not be loaded -- NOTHING "
                   "was touched" % MAP_PATH)
        print_summary()
        return
    collect_trace_ignores()

    steps = [step_preclean, step_mics]
    for region, counts in REGION_COUNTS:
        steps.append(lambda r=region, c=counts:
                     build_region(REGION_STEP_LABELS[r], r, c))
    steps.extend([step_budget, step_save_level, step_reload_verify])

    for fn in steps:
        try:
            fn()
        except Exception as exc:
            record(getattr(fn, "__name__", "step"), "FAIL", str(exc))
            warn(traceback.format_exc())
        gc_now()   # crash resistance between steps (16 GB box)
    print_summary()


main()
