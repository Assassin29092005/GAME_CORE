"""
build_beauty_meshes.py -- headless Blender builder for the two BossArena
beautification meshes (art plan v2, section B):

  1. SM_ArenaFloorRing     carved stone inlay annulus (r 2.5..19 m) for the
                           fight floor. Top +1 cm, grooves carved DOWN 3.5 cm
                           (10 cm wide, 45 deg bevel), total relief <= 5 cm.
                           4 concentric groove rings (r 6/10/14/18 m) + 16
                           radial rune-grooves (22.5 deg spacing, r 10..18 m).
                           Vertex colors: R dirt/wear (r<10 m combat zone),
                           G moss patches, B rune-emissive mask (groove
                           interiors). Budget <= 60k tris. No UVs (triplanar).
  2. SM_MountainBackdrop   silhouette ridge ring. Near-ring footprint base
                           radius 300..420 m; bulge sector |azimuth| <= 20 deg
                           of +X pushed to base radius 470..500 m (wraps
                           BEHIND the patrol zone); full opening of the near
                           ring over azimuth 342..18 deg (canyon mouth).
                           Crests 45..90 m noise-varied, tall shoulders
                           85..90 m at az 90/200/270 deg, sunset dip
                           28..35 m over az 312..342 deg (sun az 335 sits in
                           the notch). Base skirt sinks 10 m below grade.
                           Budget <= 80k tris (target ~70k).

Authoring convention (empirically matched against SM_PatrolZone.fbx, the
proven Blender->UE pipeline: its y-asymmetric flattened pads sit at the
UNmirrored positions in raw file geometry):
  * world-space METERS, Blender Z-up, pivot/object at world origin;
  * Blender +X == UE +X, Blender +Y == UE +Y (x100 UU);
  * azimuth 0 deg = +X (canyon axis), CCW toward +Y -- same as the art plan;
  * export with vanilla Blender FBX defaults (apply_unit_scale=True,
    FBX_SCALE_NONE, axis -Z forward / Y up) => same Model(-90 deg X rot,
    scale 100) signature as SM_ArenaTerrain / SM_PatrolZone, which
    build_arena_level.py imports at import_uniform_scale 1.0.

UE-side import notes (handled by the level/dressing scripts, NOT here):
  * both meshes: Nanite ON at import, collision NoCollision (mandatory --
    floor ring must not shadow the terrain walk surface / root-motion
    contract; backdrop is unreachable).
  * SM_ArenaFloorRing -> NEW M_FloorRing (world-aligned RockyPath @300 +
    vertex-color dirt/moss/rune-emissive, EmissiveIntensity default 0).
  * SM_MountainBackdrop -> existing M_Terrain (triplanar slope blend).

Run headless (standalone; builds its own empty .blend in memory -- does NOT
touch arena_source.blend):

  "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" -b -P "D:\\GAME_CORE 5.8\\Tools\\build_beauty_meshes.py"

Dry-run the numpy geometry + spec checks WITHOUT Blender (project venv):

  "D:\\GAME_CORE 5.8\\Python\\venv\\Scripts\\python.exe" "D:\\GAME_CORE 5.8\\Tools\\build_beauty_meshes.py"

Deterministic: fixed seeds (floor 71, mountain 72), no bpy.ops geometry --
pure bpy.data mesh construction; the only ops are read_factory_settings and
the FBX export.
"""

import math
import os

import numpy as np

try:
    import bpy  # noqa: F401
    IN_BLENDER = True
except ImportError:
    IN_BLENDER = False

OUT_DIR = r"D:\GAME_CORE 5.8\SourceArt\Arena"
TWO_PI = 2.0 * math.pi

# ---------------------------------------------------------------------------
# Floor ring spec (meters)
FR_R_IN, FR_R_OUT = 2.5, 19.0
FR_TOP_Z = 0.010            # +1 cm above fight-floor Z (kills z-fighting)
FR_GROOVE_DEPTH = 0.035     # carved DOWN 3.5 cm from the top surface
FR_HALF_TOP = 0.050         # groove half-width at the top (10 cm total)
FR_HALF_BOT = 0.015         # half-width at the bottom (45 deg bevel: 5-1.5=3.5)
FR_BOTTOM_Z = -0.040        # hidden skirt/underside; total envelope = 5.0 cm
FR_CONC_R = (6.0, 10.0, 14.0, 18.0)
FR_N_RADIAL = 16            # rune-grooves every 22.5 deg
FR_RAD_R0, FR_RAD_R1 = 10.0, 18.0
FR_TRI_BUDGET = 60000

# Mountain backdrop spec (meters)
MT_N_AZ = 1400
MT_N_ROWS = 24
MT_SKIRT_Z = -10.0
MT_BASE_IN_LO, MT_BASE_IN_HI = 300.0, 320.0     # near-ring inner base
MT_BASE_OUT_LO, MT_BASE_OUT_HI = 400.0, 420.0   # near-ring outer base
MT_BULGE_IN_LO, MT_BULGE_IN_HI = 470.0, 500.0   # bulge base radius band
MT_GAP_DEG = 18.0           # full opening of the near ring: az 342..18
MT_BULGE_DEG = 20.0         # bulge confined within +-20 deg of +X
MT_H_LO, MT_H_HI = 45.0, 90.0
MT_SHOULDERS_DEG = (90.0, 200.0, 270.0)         # pushed to 85..90 m
MT_SHOULDER_SIGMA = 9.0
MT_DIP_LO_DEG, MT_DIP_HI_DEG = 312.0, 342.0     # sunset dip: crest 28..35 m
MT_DIP_FEATHER = 6.0
MT_TRI_BUDGET = 80000


def log(msg):
    print("[BeautyMesh] %s" % msg, flush=True)


# ---------------------------------------------------------------------------
# Deterministic periodic value noise (numpy only)

def pnoise1(theta, n_ctrl, rng):
    """Periodic 1D value noise over theta in [0, 2pi), smoothstep interp."""
    vals = rng.random(n_ctrl)
    x = (np.asarray(theta) / TWO_PI) * n_ctrl
    i0 = np.floor(x).astype(np.int64) % n_ctrl
    i1 = (i0 + 1) % n_ctrl
    f = x - np.floor(x)
    s = f * f * (3.0 - 2.0 * f)
    return vals[i0] * (1.0 - s) + vals[i1] * s


def octnoise1(theta, base_ctrl, rng, octaves=2, gain=0.5):
    total = np.zeros_like(np.asarray(theta, dtype=np.float64))
    amp, norm, c = 1.0, 0.0, int(base_ctrl)
    for _ in range(octaves):
        total += amp * pnoise1(theta, c, rng)
        norm += amp
        amp *= gain
        c *= 2
    return total / norm


def pnoise2(xg, yg, nx, ny, rng):
    """2D value noise: periodic in x (angle 0..2pi), clamped in y (0..1)."""
    vals = rng.random((nx, ny + 1))
    x = (np.asarray(xg) / TWO_PI) * nx
    ix0 = np.floor(x).astype(np.int64) % nx
    ix1 = (ix0 + 1) % nx
    fx = x - np.floor(x)
    y = np.clip(np.asarray(yg), 0.0, 1.0) * ny
    iy0 = np.minimum(np.floor(y).astype(np.int64), ny - 1)
    iy1 = iy0 + 1
    fy = np.clip(y - iy0, 0.0, 1.0)
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    return (vals[ix0, iy0] * (1 - sx) * (1 - sy)
            + vals[ix1, iy0] * sx * (1 - sy)
            + vals[ix0, iy1] * (1 - sx) * sy
            + vals[ix1, iy1] * sx * sy)


def smoothstep01(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def tri_count(faces):
    return sum(len(f) - 2 for f in faces)


# ---------------------------------------------------------------------------
# Mesh 1: SM_ArenaFloorRing

def _floor_r_samples():
    """Non-uniform radial samples: exact groove feature edges + coarse fill."""
    rs = [2.5, 3.1, 3.7, 4.3, 4.9, 5.5]
    fills = ([7.0, 8.0, 9.0], [11.0, 12.0, 13.0], [15.0, 16.0, 17.0],
             [18.5, 19.0])
    for ring_r, fill in zip(FR_CONC_R, fills):
        rs += [ring_r - FR_HALF_TOP, ring_r - FR_HALF_BOT,
               ring_r + FR_HALF_BOT, ring_r + FR_HALF_TOP]
        rs += fill
    return np.asarray(rs, dtype=np.float64)


def _floor_theta_samples():
    """Per 22.5-deg sector: a cluster of samples resolving the radial groove
    walls at r=10/14/18 (edges at half-width/r radians) + coarse fill."""
    sector = TWO_PI / FR_N_RADIAL
    offs = sorted({w / r for w in (FR_HALF_BOT, FR_HALF_TOP)
                   for r in (10.0, 14.0, 18.0)} | {0.008, 0.011})
    cluster = [-o for o in reversed(offs)] + [0.0] + list(offs)  # 17 samples
    fill = np.linspace(0.011, sector - 0.011, 20)[1:-1]          # 18 samples
    pattern = np.asarray(cluster + list(fill), dtype=np.float64)
    thetas = np.concatenate([k * sector + pattern for k in range(FR_N_RADIAL)])
    if not np.all(np.diff(thetas) > 0):
        raise AssertionError("floor theta samples not strictly increasing")
    return thetas


def _floor_depth(rr, th):
    """Carve depth (>=0) at (r, theta): union of concentric + radial grooves,
    45-deg bevel walls (slope 1:1), flat bottom at FR_GROOVE_DEPTH."""
    d_conc = np.full_like(rr, 1e9)
    for ring_r in FR_CONC_R:
        d_conc = np.minimum(d_conc, np.abs(rr - ring_r))
    carve_c = np.clip(FR_HALF_TOP - d_conc, 0.0, FR_GROOVE_DEPTH)

    half_sector = math.pi / FR_N_RADIAL
    dth = np.abs(((th + half_sector) % (2.0 * half_sector)) - half_sector)
    arc = rr * dth                                   # ~perpendicular distance
    outside = np.maximum(0.0, np.maximum(FR_RAD_R0 - rr, rr - FR_RAD_R1))
    carve_r = np.clip(FR_HALF_TOP - arc, 0.0, FR_GROOVE_DEPTH) - outside
    carve_r = np.clip(carve_r, 0.0, FR_GROOVE_DEPTH)
    return np.maximum(carve_c, carve_r)


def build_floor_ring():
    rng = np.random.default_rng(71)
    rs = _floor_r_samples()
    thetas = _floor_theta_samples()
    nr, nt = len(rs), len(thetas)

    th, rr = np.meshgrid(thetas, rs, indexing="ij")   # (nt, nr)
    depth = _floor_depth(rr, th)
    z = FR_TOP_Z - depth
    x = rr * np.cos(th)
    y = rr * np.sin(th)
    top = np.stack([x, y, z], axis=-1).reshape(-1, 3)

    # Hidden skirt: outer wall, flat underside, inner wall (watertight-ish).
    cs, sn = np.cos(thetas), np.sin(thetas)
    bot_out = np.stack([FR_R_OUT * cs, FR_R_OUT * sn,
                        np.full(nt, FR_BOTTOM_Z)], axis=-1)
    bot_in = np.stack([FR_R_IN * cs, FR_R_IN * sn,
                       np.full(nt, FR_BOTTOM_Z)], axis=-1)
    verts = np.concatenate([top, bot_out, bot_in], axis=0)

    # Vertex colors (POINT domain RGBA): R dirt, G moss, B rune mask.
    u_rad = (rr - FR_R_IN) / (FR_R_OUT - FR_R_IN)
    n_a = pnoise2(th, u_rad, 40, 6, rng)
    n_b = pnoise2(th, u_rad, 90, 12, rng)
    n_mix = 0.65 * n_a + 0.35 * n_b
    col_r = np.clip((10.0 - rr) / 1.2, 0.0, 1.0) * (0.75 + 0.25 * n_mix)
    col_g = np.clip((n_mix - 0.52) * 3.0, 0.0, 1.0) * 0.75
    col_g = np.maximum(col_g, (depth / FR_GROOVE_DEPTH) * 0.35 * n_mix)
    col_b = depth / FR_GROOVE_DEPTH
    cols_top = np.stack([col_r, col_g, col_b, np.ones_like(col_r)],
                        axis=-1).reshape(-1, 4)
    cols_skirt = np.zeros((2 * nt, 4))
    cols_skirt[:, 3] = 1.0
    colors = np.concatenate([cols_top, cols_skirt], axis=0)

    faces = []
    vid = lambda t, r: t * nr + r
    ob0, ib0 = nt * nr, nt * nr + nt
    for t in range(nt):
        t1 = (t + 1) % nt
        for r in range(nr - 1):                       # top surface (+Z)
            faces.append([vid(t, r), vid(t, r + 1),
                          vid(t1, r + 1), vid(t1, r)])
        faces.append([vid(t, nr - 1), ob0 + t,        # outer wall (+r)
                      ob0 + t1, vid(t1, nr - 1)])
        faces.append([ob0 + t, ib0 + t,               # underside (-Z)
                      ib0 + t1, ob0 + t1])
        faces.append([ib0 + t, vid(t, 0),             # inner wall (-r)
                      vid(t1, 0), ib0 + t1])
    return {"name": "SM_ArenaFloorRing", "verts": verts, "faces": faces,
            "colors": colors, "material": "M_FloorRing",
            "grid_z": z, "depth": depth, "nt": nt, "nr": nr}


# ---------------------------------------------------------------------------
# Mesh 2: SM_MountainBackdrop

def _wrapped_deg(a_deg, b_deg):
    return np.abs(((a_deg - b_deg + 180.0) % 360.0) - 180.0)


def build_mountain_backdrop():
    rng = np.random.default_rng(72)
    az = np.linspace(0.0, TWO_PI, MT_N_AZ, endpoint=False)
    azd = np.degrees(az)

    # --- footprint radii ---------------------------------------------------
    n_in = octnoise1(az, 20, rng)
    n_out = octnoise1(az, 20, rng)
    r_in_near = MT_BASE_IN_LO + (MT_BASE_IN_HI - MT_BASE_IN_LO) * n_in
    r_out_near = MT_BASE_OUT_HI - (MT_BASE_OUT_HI - MT_BASE_OUT_LO) * n_out
    n_bulge = octnoise1(az, 12, rng)
    r_in_bulge = MT_BULGE_IN_LO + (MT_BULGE_IN_HI - MT_BULGE_IN_LO) * n_bulge
    r_out_bulge = r_in_bulge + (r_out_near - r_in_near)  # width preserved

    # bulge weight: 1 inside +-18 deg (gap fully open -> far wall only),
    # 0 outside +-20 deg (bulge confined per plan).
    adeg = _wrapped_deg(azd, 0.0)
    wb = 1.0 - smoothstep01((adeg - MT_GAP_DEG) / (MT_BULGE_DEG - MT_GAP_DEG))
    r_in = r_in_near * (1.0 - wb) + r_in_bulge * wb
    r_out = r_out_near * (1.0 - wb) + r_out_bulge * wb
    width = r_out - r_in
    n_crest_pos = octnoise1(az, 28, rng)
    r_crest = r_in + width * (0.40 + 0.10 * (n_crest_pos - 0.5))

    # --- crest heights -----------------------------------------------------
    n_h = octnoise1(az, 36, rng, octaves=2)
    crest = MT_H_LO + (MT_H_HI - MT_H_LO) * n_h                 # 45..90
    for c_deg in MT_SHOULDERS_DEG:                              # 85..90
        target = 85.0 + 5.0 * rng.random()
        gauss = np.exp(-0.5 * (_wrapped_deg(azd, c_deg) / MT_SHOULDER_SIGMA) ** 2)
        crest = np.maximum(crest, target * gauss)
    n_dip = octnoise1(az, 24, rng)
    dip_h = 28.0 + 7.0 * n_dip                                  # 28..35
    dd = np.maximum(0.0, np.maximum(MT_DIP_LO_DEG - azd, azd - MT_DIP_HI_DEG))
    w_dip = 1.0 - smoothstep01(dd / MT_DIP_FEATHER)             # 1 across band
    crest = crest * (1.0 - w_dip) + dip_h * w_dip

    # --- swept cross-section with crag noise -------------------------------
    u = np.linspace(-1.0, 1.0, MT_N_ROWS)
    t = np.sign(u) * np.abs(u) ** 1.3                 # denser near the crest
    tg = np.broadcast_to(t, (MT_N_AZ, MT_N_ROWS))
    azg = np.broadcast_to(az[:, None], (MT_N_AZ, MT_N_ROWS))

    inner = tg < 0.0
    rg = np.where(inner,
                  r_crest[:, None] + tg * (r_crest - r_in)[:, None],
                  r_crest[:, None] + tg * (r_out - r_crest)[:, None])
    shape = np.cos(tg * (math.pi / 2.0)) ** 1.4
    zg = MT_SKIRT_Z + (crest[:, None] - MT_SKIRT_Z) * shape

    yg01 = (tg + 1.0) * 0.5
    n2 = 0.7 * pnoise2(azg, yg01, 160, 8, rng) + 0.3 * pnoise2(azg, yg01, 360, 16, rng)
    amp = crest[:, None] * 0.14 * (1.0 - tg ** 2) * np.abs(tg) ** 0.6
    zg = np.maximum(zg + (n2 - 0.5) * 2.0 * amp, MT_SKIRT_Z)
    n3 = pnoise2(azg, yg01, 120, 6, rng)
    rg = rg + (n3 - 0.5) * 2.0 * 0.08 * width[:, None] * (1.0 - np.abs(tg))

    xg = rg * np.cos(azg)
    yg = rg * np.sin(azg)
    verts = np.stack([xg, yg, zg], axis=-1).reshape(-1, 3)

    faces = []
    vid = lambda i, j: i * MT_N_ROWS + j
    for i in range(MT_N_AZ):
        i1 = (i + 1) % MT_N_AZ
        for j in range(MT_N_ROWS - 1):                # flanks + crest
            faces.append([vid(i, j), vid(i, j + 1),
                          vid(i1, j + 1), vid(i1, j)])
        faces.append([vid(i, MT_N_ROWS - 1), vid(i, 0),   # buried underside
                      vid(i1, 0), vid(i1, MT_N_ROWS - 1)])
    return {"name": "SM_MountainBackdrop", "verts": verts, "faces": faces,
            "colors": None, "material": "M_Terrain",
            "crest_field": crest, "azd": azd, "zg": zg, "rg": rg,
            "r_in": r_in, "r_out": r_out}


# ---------------------------------------------------------------------------
# Spec validation (runs in the dry-run AND before export in Blender)

def _quad_normals(verts, faces, sample):
    f = np.asarray([faces[i] for i in sample])
    v0, v1, v2, v3 = (verts[f[:, k]] for k in range(4))
    n = np.cross(v2 - v0, v3 - v1)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def validate(floor, mtn):
    ok = True

    def check(cond, msg):
        nonlocal ok
        print("[BeautyMesh][check] %s %s" % ("PASS" if cond else "FAIL", msg),
              flush=True)
        ok = ok and bool(cond)

    # ---- floor ring ----
    v, fc = floor["verts"], floor["faces"]
    tris = tri_count(fc)
    gz, dep = floor["grid_z"], floor["depth"]
    r_all = np.hypot(v[:, 0], v[:, 1])
    check(tris <= FR_TRI_BUDGET,
          "floor tris %d <= %d" % (tris, FR_TRI_BUDGET))
    check(abs(gz.max() - FR_TOP_Z) < 1e-9 and abs(gz.min() - (FR_TOP_Z - FR_GROOVE_DEPTH)) < 1e-9,
          "floor top surface z in [%.4f, %.4f] m (relief %.1f cm carved down)"
          % (gz.min(), gz.max(), (gz.max() - gz.min()) * 100))
    check(v[:, 2].max() - v[:, 2].min() <= 0.05 + 1e-9,
          "floor total envelope %.1f cm <= 5 cm, nothing above +1 cm"
          % ((v[:, 2].max() - v[:, 2].min()) * 100))
    check(abs(dep.max() - FR_GROOVE_DEPTH) < 1e-9,
          "floor max carve depth %.1f cm == 3.5 cm" % (dep.max() * 100))
    check(abs(r_all.min() - FR_R_IN) < 1e-6 and abs(r_all.max() - FR_R_OUT) < 1e-6,
          "floor annulus r %.2f..%.2f m" % (r_all.min(), r_all.max()))
    # groove present at each concentric ring + between-rings top is clean
    nt, nr = floor["nt"], floor["nr"]
    mid_t = nt // 32  # between spoke 0 and spoke 1 clusters
    rline = np.hypot(v[:nt * nr, 0], v[:nt * nr, 1]).reshape(nt, nr)[mid_t]
    zline = gz[mid_t]
    for ring_r in FR_CONC_R:
        at = np.argmin(np.abs(rline - ring_r))
        check(zline[at] <= FR_TOP_Z - FR_GROOVE_DEPTH + 1e-9,
              "concentric groove @ r=%.0f m carved to %.1f cm" % (ring_r, -zline[at] * 100 + 1))
    # per-theta face block = (nr-1) top faces + 3 skirt faces; sample tops only
    top_ids = [t * (nr + 2) + j for t in range(0, nt, 11)
               for j in (0, nr // 2, nr - 2)]
    nrm = _quad_normals(v, fc, top_ids)
    check(float(nrm[:, 2].mean()) > 0.9, "floor top faces wind +Z (mean nz %.3f)" % nrm[:, 2].mean())

    # ---- mountain ----
    v2, fc2 = mtn["verts"], mtn["faces"]
    tris2 = tri_count(fc2)
    crest_mesh = mtn["zg"].max(axis=1)
    azd = mtn["azd"]
    r_in, r_out = mtn["r_in"], mtn["r_out"]
    adeg = _wrapped_deg(azd, 0.0)
    check(tris2 <= MT_TRI_BUDGET,
          "mountain tris %d <= %d (target ~70k)" % (tris2, MT_TRI_BUDGET))
    check(abs(v2[:, 2].min() - MT_SKIRT_Z) < 1e-6,
          "mountain skirt base z = %.1f m (10 m below grade)" % v2[:, 2].min())
    check(v2[:, 2].max() <= MT_H_HI + 0.6,
          "mountain max crest %.1f m <= 90 m" % v2[:, 2].max())
    near = adeg >= MT_BULGE_DEG + 1.0
    check(r_in[near].min() >= MT_BASE_IN_LO - 1e-6 and r_out[near].max() <= MT_BASE_OUT_HI + 1e-6,
          "near-ring footprint %.0f..%.0f m within 300..420" % (r_in[near].min(), r_out[near].max()))
    gap = adeg <= MT_GAP_DEG
    check(r_in[gap].min() >= MT_BULGE_IN_LO - 1e-6 and r_in[gap].max() <= MT_BULGE_IN_HI + 1e-6,
          "gap sector (az 342..18) near ring OPEN: base radius %.0f..%.0f m in 470..500"
          % (r_in[gap].min(), r_in[gap].max()))
    behind = adeg <= 16.0
    check(r_in[behind].min() >= 430.0,
          "bulge wraps BEHIND patrol zone (inner base >= %.0f m for |az|<=16)"
          % r_in[behind].min())
    dip = (azd >= MT_DIP_LO_DEG + 1.0) & (azd <= MT_DIP_HI_DEG - 1.0)
    check(27.5 <= crest_mesh[dip].min() and crest_mesh[dip].max() <= 35.5,
          "sunset dip az 312..342: crest %.1f..%.1f m in 28..35 (sun az 335 in notch)"
          % (crest_mesh[dip].min(), crest_mesh[dip].max()))
    for c_deg in MT_SHOULDERS_DEG:
        m = _wrapped_deg(azd, c_deg) <= 2.0
        check(crest_mesh[m].max() >= 82.5,
              "shoulder @ az %.0f deg: crest %.1f m (~85..90)" % (c_deg, crest_mesh[m].max()))
    outside_dip = (dd_out := _wrapped_deg(azd, (MT_DIP_LO_DEG + MT_DIP_HI_DEG) / 2.0)) > (MT_DIP_HI_DEG - MT_DIP_LO_DEG) / 2.0 + MT_DIP_FEATHER + 1.0
    check(crest_mesh[outside_dip].min() >= MT_H_LO - 1.5,
          "crest outside dip stays %.1f..%.1f m (spec 45..90)"
          % (crest_mesh[outside_dip].min(), crest_mesh[outside_dip].max()))
    nrm2 = _quad_normals(v2, fc2, range(0, MT_N_AZ * (MT_N_ROWS - 1), 211))
    check(float(nrm2[:, 2].mean()) > 0.2, "mountain flank faces wind outward/up (mean nz %.3f)" % nrm2[:, 2].mean())

    if not ok:
        raise AssertionError("spec validation FAILED -- see FAIL lines above")
    log("all spec checks passed (floor %d tris, mountain %d tris)" % (tris, tris2))
    return tris, tris2


# ---------------------------------------------------------------------------
# Blender side

def _make_object(build):
    mesh = bpy.data.meshes.new(build["name"])
    mesh.from_pydata(build["verts"].tolist(), [], build["faces"])
    mesh.validate(verbose=False)
    mesh.polygons.foreach_set("use_smooth",
                              np.ones(len(mesh.polygons), dtype=bool))
    if hasattr(mesh, "set_sharp_from_angle"):
        mesh.set_sharp_from_angle(angle=math.radians(50.0))
    if build["colors"] is not None:
        ca = mesh.color_attributes.new(name="Col", type="BYTE_COLOR",
                                       domain="POINT")
        ca.data.foreach_set(
            "color_srgb",
            build["colors"].astype(np.float32).ravel())
    mat = (bpy.data.materials.get(build["material"])
           or bpy.data.materials.new(build["material"]))
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(build["name"], mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (0.0, 0.0, 0.0)  # pivot at world origin, world-space verts
    return obj


def _export_fbx(obj, path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # Vanilla axis/scale defaults on purpose: matches the proven
    # SM_ArenaTerrain / SM_PatrolZone signature (Model rot -90X, scale 100,
    # raw Blender-space meter geometry) that build_arena_level.py imports
    # at import_uniform_scale 1.0 (200 m -> 20000 UU assert passes).
    bpy.ops.export_scene.fbx(
        filepath=path,
        use_selection=True,
        object_types={"MESH"},
        use_mesh_modifiers=False,
        mesh_smooth_type="OFF",       # export split normals (sharp bevels)
        use_triangles=True,
        add_leaf_bones=False,
        bake_anim=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_NONE",
        global_scale=1.0,
        axis_forward="-Z",
        axis_up="Y",
        path_mode="AUTO",
        colors_type="SRGB",
    )


def blender_main():
    log("Blender %s headless build starting (fresh empty file; "
        "arena_source.blend untouched)" % ".".join(map(str, bpy.app.version)))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    log("building SM_ArenaFloorRing geometry (numpy)...")
    floor = build_floor_ring()
    log("building SM_MountainBackdrop geometry (numpy)...")
    mtn = build_mountain_backdrop()
    log("validating against art-plan section B specs...")
    tris_f, tris_m = validate(floor, mtn)

    results = []
    for build, tris in ((floor, tris_f), (mtn, tris_m)):
        log("meshing %s (%d verts, %d quads -> %d export tris)"
            % (build["name"], len(build["verts"]), len(build["faces"]), tris))
        obj = _make_object(build)
        path = os.path.join(OUT_DIR, build["name"] + ".fbx")
        log("exporting %s ..." % path)
        _export_fbx(obj, path)
        results.append((build["name"], tris, path, os.path.getsize(path)))

    log("---- done ----")
    for name, tris, path, size in results:
        log("%s: %d tris, %s (%.2f MB)" % (name, tris, path, size / 1e6))
    log("UE import notes: Nanite ON, collision NoCollision (both), "
        "M_FloorRing (new, vertex-color R dirt/G moss/B rune emissive "
        "default 0) on the ring, M_Terrain on the backdrop.")


def dry_run():
    log("dry-run (no bpy): building geometry with numpy and checking specs")
    floor = build_floor_ring()
    mtn = build_mountain_backdrop()
    tris_f, tris_m = validate(floor, mtn)
    log("DRY-RUN PASS: floor %d verts / %d tris (budget 60k), "
        "mountain %d verts / %d tris (budget 80k, target ~70k)"
        % (len(floor["verts"]), tris_f, len(mtn["verts"]), tris_m))


if __name__ == "__main__":
    if IN_BLENDER:
        blender_main()
    else:
        dry_run()
