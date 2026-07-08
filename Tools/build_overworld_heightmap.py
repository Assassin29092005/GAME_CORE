"""
build_overworld_heightmap.py — procedural heightmap + weightmaps for
the Tier 4 open-world map (Phase A1 of the overworld feature).

Emits, into SourceArt/Overworld/Textures/:
  - T_Overworld_Heightmap.png              16-bit grayscale, 2049x2049
  - T_Overworld_Weight_Castle.png          16-bit
  - T_Overworld_Weight_Marsh.png           16-bit
  - T_Overworld_Weight_Desert.png          16-bit
  - T_Overworld_Weight_Mountains.png       16-bit
  - T_Overworld_Weight_Plains.png          16-bit
  - T_Overworld_ColorHillshade.png         8-bit RGBA, full-res preview
  - T_Overworld_ColorHillshade_Small.png   8-bit RGBA, 512x512 preview

Also produces the 3D-preview mesh + Cycles render at
  SourceArt/Overworld/Textures/T_Overworld_3DRender.png
and saves the reproducible project at
  SourceArt/Overworld/Overworld_Terrain.blend.

Run modes:
  - Via Blender's execute_blender_code MCP tool (interactive session)
  - Headless:  blender --background --python Tools/build_overworld_heightmap.py

Cardinal orientation:
  - Numpy row 0 → NORTH; row H-1 → SOUTH
  - PNG rendered "N up" (top edge = north)

Biome layout (matches the D&D-style reference overworld image):
  - Castle plateau: center, circular, moat around rim
  - Marsh: W band, mid-latitude, channel-noise carving
  - Desert: NE quadrant, gentle dunes
  - Mountains: SW corner, sharp ridges via 1 - |fbm|
  - Plains: fallback, fills whatever is not covered
"""
from __future__ import annotations
import os, math, time
import numpy as np
import bpy

# ─── Config ────────────────────────────────────────────────────────────────
W = H = 2049                     # 1 m per quad on 2 km world
OUT_DIR = r"D:\GAME_CORE 5.8\SourceArt\Overworld\Textures"
PROJECT_DIR = r"D:\GAME_CORE 5.8\SourceArt\Overworld"
BLEND_PATH = os.path.join(PROJECT_DIR, "Overworld_Terrain.blend")
SEED = 20260708

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(PROJECT_DIR, exist_ok=True)

# ─── FFT smoothed noise helpers ────────────────────────────────────────────
def _smoothed_noise(shape, sigma_px, seed_offset=0):
    local_rng = np.random.default_rng(SEED + seed_offset)
    n = local_rng.standard_normal(shape).astype(np.float32)
    ky = np.fft.fftfreq(shape[0]).reshape(-1, 1).astype(np.float32) * shape[0]
    kx = np.fft.fftfreq(shape[1]).reshape(1, -1).astype(np.float32) * shape[1]
    fx = kx / shape[1]; fy = ky / shape[0]
    filt = np.exp(-2 * (np.pi**2) * (sigma_px**2)
                  * (fx*fx + fy*fy) / (shape[0]/W)).astype(np.float32)
    s = np.real(np.fft.ifft2(np.fft.fft2(n) * filt)).astype(np.float32)
    s = s - s.mean()
    s /= (s.std() + 1e-8) * 3
    return np.clip(s, -1, 1)

def _fbm(shape, octaves=5, base_sigma=64.0, persistence=0.55, lacunarity=2.0,
         seed_offset=0):
    total = np.zeros(shape, dtype=np.float32)
    amp = 1.0; sigma = base_sigma; norm = 0.0
    for i in range(octaves):
        total += amp * _smoothed_noise(shape, sigma, seed_offset=seed_offset + i)
        norm += amp; amp *= persistence; sigma /= lacunarity
    return total / norm

def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0 + 1e-8), 0.0, 1.0)
    return t*t*(3.0 - 2.0*t)

# ─── Terrain generation ────────────────────────────────────────────────────
def build_terrain():
    u = np.linspace(0.0, 1.0, W, dtype=np.float32)
    v = np.linspace(0.0, 1.0, H, dtype=np.float32)
    U, V = np.meshgrid(u, v, indexing="xy")

    r_center = np.hypot(U - 0.5, V - 0.5)
    mask_castle = 1.0 - _smoothstep(0.14, 0.22, r_center)
    mask_moat   = _smoothstep(0.155, 0.185, r_center) \
                * (1.0 - _smoothstep(0.185, 0.22, r_center))

    mask_marsh  = _smoothstep(0.52, 0.25, U) \
                * _smoothstep(0.10, 0.32, V) \
                * _smoothstep(0.82, 0.58, V)

    mask_desert = _smoothstep(0.42, 0.65, U) \
                * _smoothstep(0.60, 0.35, V)

    mask_mtn_peak = _smoothstep(0.30, 0.15, U) * _smoothstep(0.65, 0.82, V)
    mask_mtn_foot = _smoothstep(0.42, 0.22, U) * _smoothstep(0.55, 0.76, V) * 0.5

    others = np.clip(mask_castle + mask_marsh + mask_desert
                     + mask_mtn_peak + mask_mtn_foot, 0.0, 1.0)
    mask_plains = 1.0 - others

    noise_fine  = _fbm((H, W), octaves=6, base_sigma=48,  persistence=0.5,  seed_offset=100)
    noise_med   = _fbm((H, W), octaves=4, base_sigma=180, persistence=0.55, seed_offset=200)
    noise_ridge = 1.0 - np.abs(_fbm((H, W), octaves=5, base_sigma=90,  persistence=0.55, seed_offset=300))
    noise_marsh = _fbm((H, W), octaves=6, base_sigma=32,  persistence=0.6,  seed_offset=400)
    noise_plaza = _fbm((H, W), octaves=4, base_sigma=20,  persistence=0.4,  seed_offset=500)

    height = np.full((H, W), 0.38, dtype=np.float32)
    height += mask_castle * 0.22
    height -= mask_moat   * 0.10
    height += mask_mtn_peak * (0.34 + noise_ridge * 0.22)
    height += mask_mtn_foot * (0.08 + noise_med * 0.06)
    height -= mask_marsh    * (0.10 + np.clip(noise_marsh, 0, 1) * 0.06)
    height += mask_desert   * (0.04 + noise_med * 0.03)
    height += mask_plains   * (0.07 + noise_med * 0.05)
    height += noise_fine * 0.018

    plateau_core = 1.0 - _smoothstep(0.075, 0.11, r_center)
    plaza_h = 0.38 + 0.22 + noise_plaza * 0.005
    height = np.where(plateau_core > 0.5, plaza_h, height)
    height = np.clip(height, 0.0, 1.0)

    mask_mtn_combined = np.clip(mask_mtn_peak + mask_mtn_foot, 0.0, 1.0)
    biomes = {"Castle": mask_castle, "Marsh": mask_marsh, "Desert": mask_desert,
              "Mountains": mask_mtn_combined, "Plains": mask_plains}
    tot = sum(biomes.values()) + 1e-6
    weights = {n: (m / tot).astype(np.float32) for n, m in biomes.items()}

    return height, weights

# ─── PNG save via Blender image API (16-bit BW / 8-bit RGBA) ───────────────
def _save_gray16(arr, name, fname):
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '16'
    scene.render.image_settings.color_mode = 'BW'
    scene.render.image_settings.compression = 15
    a = np.clip(arr, 0.0, 1.0).astype(np.float32)
    a_b = np.flipud(a)                                  # Blender is bottom-row-first
    rgba = np.stack([a_b]*3 + [np.ones_like(a_b)], axis=-1)
    img = bpy.data.images.get(name)
    if img: bpy.data.images.remove(img)
    img = bpy.data.images.new(name, width=a.shape[1], height=a.shape[0],
                              alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    img.pixels.foreach_set(rgba.ravel())
    fp = os.path.join(OUT_DIR, fname)
    img.file_format = 'PNG'
    img.save_render(filepath=fp, scene=scene)
    return fp

def _save_color8(a, name, fname):
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.color_mode = 'RGBA'
    a_b = np.flipud(a).astype(np.float32)
    rgba = np.concatenate([a_b, np.ones((*a_b.shape[:2], 1), dtype=np.float32)], axis=-1)
    img = bpy.data.images.get(name)
    if img: bpy.data.images.remove(img)
    img = bpy.data.images.new(name, width=a.shape[1], height=a.shape[0],
                              alpha=True, float_buffer=True)
    img.pixels.foreach_set(rgba.ravel())
    fp = os.path.join(OUT_DIR, fname)
    img.file_format = 'PNG'
    img.save_render(filepath=fp, scene=scene)
    return fp

# ─── Colored hillshade preview ─────────────────────────────────────────────
BIOME_COLORS = {"Castle":    (0.62, 0.57, 0.52),
                "Marsh":     (0.15, 0.36, 0.32),
                "Desert":    (0.87, 0.76, 0.46),
                "Mountains": (0.36, 0.33, 0.31),
                "Plains":    (0.36, 0.55, 0.24)}

def color_hillshade(height, weights):
    color = np.zeros((*height.shape, 3), dtype=np.float32)
    for name, w in weights.items():
        col = np.array(BIOME_COLORS[name], dtype=np.float32)
        color += w[..., None] * col[None, None, :]
    gy, gx = np.gradient(height * 200.0)
    n_len = np.sqrt(gx*gx + gy*gy + 1.0)
    nx, ny, nz = -gx/n_len, -gy/n_len, 1.0/n_len
    shade = np.clip(nx*(-0.4) + ny*(-0.4) + nz*0.85, 0.22, 1.0).astype(np.float32)
    return np.clip(color * shade[..., None], 0.0, 1.0)

# ─── Blender 3D-preview mesh + Cycles render ───────────────────────────────
def build_preview_mesh_and_render(heightmap_path):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for m in list(bpy.data.meshes):    bpy.data.meshes.remove(m)
    for m in list(bpy.data.materials): bpy.data.materials.remove(m)
    for m in list(bpy.data.textures):  bpy.data.textures.remove(m)

    bpy.ops.mesh.primitive_plane_add(size=2000.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object
    plane.name = "OverworldTerrain"
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=399)
    bpy.ops.object.mode_set(mode='OBJECT')

    h_img = bpy.data.images.load(heightmap_path, check_existing=False)
    h_img.colorspace_settings.name = 'Non-Color'
    h_tex = bpy.data.textures.new("HeightmapTex", 'IMAGE')
    h_tex.image = h_img
    h_tex.extension = 'EXTEND'
    disp = plane.modifiers.new("Heightmap", 'DISPLACE')
    disp.texture = h_tex
    disp.texture_coords = 'UV'
    disp.strength = 300.0
    disp.mid_level = 0.0

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66))
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.modifier_apply(modifier="Heightmap")

    mat = bpy.data.materials.new("M_OverworldPreview")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    prin  = nt.nodes.new("ShaderNodeBsdfPrincipled")
    prin.inputs["Roughness"].default_value = 0.8
    prin.inputs["Specular IOR Level"].default_value = 0.15
    nt.links.new(prin.outputs["BSDF"], out_n.inputs["Surface"])
    uv_map = nt.nodes.new("ShaderNodeUVMap")
    uv_map.uv_map = plane.data.uv_layers.active.name

    accum = nt.nodes.new("ShaderNodeRGB")
    accum.outputs[0].default_value = (0, 0, 0, 1)
    last = accum.outputs[0]
    for n_name, col in BIOME_COLORS.items():
        wpath = os.path.join(OUT_DIR, f"T_Overworld_Weight_{n_name}.png")
        w_img = bpy.data.images.load(wpath, check_existing=False)
        w_img.colorspace_settings.name = 'Non-Color'
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = w_img
        tex.interpolation = 'Cubic'
        nt.links.new(uv_map.outputs["UV"], tex.inputs["Vector"])
        col_rgb = nt.nodes.new("ShaderNodeRGB")
        col_rgb.outputs[0].default_value = (*col, 1)
        mult = nt.nodes.new("ShaderNodeMixRGB")
        mult.blend_type = 'MULTIPLY'; mult.inputs["Fac"].default_value = 1.0
        nt.links.new(tex.outputs["Color"], mult.inputs["Color1"])
        nt.links.new(col_rgb.outputs[0], mult.inputs["Color2"])
        add = nt.nodes.new("ShaderNodeMixRGB")
        add.blend_type = 'ADD'; add.inputs["Fac"].default_value = 1.0
        nt.links.new(last, add.inputs["Color1"])
        nt.links.new(mult.outputs["Color"], add.inputs["Color2"])
        last = add.outputs["Color"]
    nt.links.new(last, prin.inputs["Base Color"])
    plane.data.materials.append(mat)

    sun_data = bpy.data.lights.new("Sun", 'SUN')
    sun_data.energy = 4.0
    sun_data.color = (1.0, 0.95, 0.85)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.collection.objects.link(sun)
    sun.location = (0, 0, 1000)
    sun.rotation_euler = (math.radians(50), 0, math.radians(-40))

    world = bpy.data.worlds.new("PreviewWorld") if "PreviewWorld" not in bpy.data.worlds \
            else bpy.data.worlds["PreviewWorld"]
    world.use_nodes = True
    wnt = world.node_tree
    for n in list(wnt.nodes): wnt.nodes.remove(n)
    wout = wnt.nodes.new("ShaderNodeOutputWorld")
    wbg  = wnt.nodes.new("ShaderNodeBackground")
    wbg.inputs["Color"].default_value = (0.6, 0.75, 0.90, 1.0)
    wbg.inputs["Strength"].default_value = 0.8
    wnt.links.new(wbg.outputs["Background"], wout.inputs["Surface"])
    bpy.context.scene.world = world

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 35
    cam_data.clip_end = 10000
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (1600, -1600, 1200)
    cam.rotation_euler = (math.radians(55), 0, math.radians(45))
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 64
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.color_mode = 'RGBA'

    scene.render.filepath = os.path.join(OUT_DIR, "T_Overworld_3DRender.png")
    bpy.ops.render.render(write_still=True)

# ─── Main ─────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    height, weights = build_terrain()
    print(f"height: [{height.min():.3f}, {height.max():.3f}] "
          f"mean={height.mean():.3f}")

    _save_gray16(height, "OverworldHeightmap", "T_Overworld_Heightmap.png")
    for name, w in weights.items():
        _save_gray16(w, f"OverworldWeight_{name}", f"T_Overworld_Weight_{name}.png")

    lit = color_hillshade(height, weights)
    _save_color8(lit,       "OverworldColorHillshade",       "T_Overworld_ColorHillshade.png")
    _save_color8(lit[::4, ::4], "OverworldColorHillshadeSmall", "T_Overworld_ColorHillshade_Small.png")

    build_preview_mesh_and_render(os.path.join(OUT_DIR, "T_Overworld_Heightmap.png"))
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    print(f"DONE in {time.time()-t0:.1f}s. Blend saved to {BLEND_PATH}")

if __name__ == "__main__":
    main()
