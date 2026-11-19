"""Blender side of stone video: render a painted figure turning, from the 3MF's own paint.

blender -b --factory-startup --python turntable_blender.py -- <mesh.npz> <out dir> <frames> <w> <h> [first last]

mesh.npz (video.paint_npz) holds V (n, 3) in mm, F (m, 3), fil (m,) the filament of each face, and
rgb (k, 3) each filament's color (0..255). Each filament is one plastic material, and each face takes
its own filament's material, so the paint seen is exactly the paint in the file. The light is smooth
below 60 degrees, as on the print; nothing is added to the shape. Frame i shows the figure turned by
360 * i / frames degrees, front first. Writes f_0000.png ... with a transparent background.
"""
import math
import sys
from pathlib import Path

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
npz, out, frames, w, h = argv[0], Path(argv[1]), int(argv[2]), int(argv[3]), int(argv[4])
first, last = (int(argv[5]), int(argv[6])) if len(argv) > 6 else (0, frames - 1)
out.mkdir(parents=True, exist_ok=True)

d = np.load(npz)
V, F, fil, rgb = d["V"], d["F"], d["fil"], d["rgb"]

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

mesh = bpy.data.meshes.new("figure")
mesh.from_pydata((V / 1000.0).tolist(), [], F.tolist())  # mm to m: Blender's light falls off in metres
mesh.update()
obj = bpy.data.objects.new("figure", mesh)
scene.collection.objects.link(obj)


def srgb_to_linear(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


for k in range(len(rgb)):
    m = bpy.data.materials.new(f"filament_{k + 1}")
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    lin = srgb_to_linear(np.asarray(rgb[k], float))
    p.inputs["Base Color"].default_value = (*lin.tolist(), 1.0)
    p.inputs["Roughness"].default_value = 0.42  # matte PLA with a soft sheen
    obj.data.materials.append(m)
mesh.polygons.foreach_set("material_index", (fil - 1).astype(np.int32))
mesh.update()

bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(60))

# turn about the figure's own vertical axis: a parent empty at the center of its footprint
lo, hi = V.min(0) / 1000.0, V.max(0) / 1000.0
ctr = (lo + hi) / 2
pivot = bpy.data.objects.new("pivot", None)
scene.collection.objects.link(pivot)
pivot.location = (ctr[0], ctr[1], 0.0)
obj.parent = pivot
obj.location = (-ctr[0], -ctr[1], 0.0)

height = hi[2] - lo[2]
cam_d = bpy.data.cameras.new("cam")
cam_d.lens = 85
cam = bpy.data.objects.new("cam", cam_d)
scene.collection.objects.link(cam)
scene.camera = cam
aspect = w / h
# fit the figure's height (and its width, turned) into the frame with a margin
fit = max(height, (hi[0] - lo[0]) * 1.15 / aspect, (hi[1] - lo[1]) * 1.15 / aspect) * 1.15
cam_d.sensor_fit = "VERTICAL"
cam_d.sensor_height = 24.0
dist = fit / 2 / math.tan(math.atan(cam_d.sensor_height / 2 / cam_d.lens))
elev = math.radians(12)
look = (ctr[0], ctr[1], lo[2] + height * 0.47)
cam.location = (look[0], look[1] - dist * math.cos(elev), look[2] + dist * math.sin(elev))
cam.rotation_euler = (math.pi / 2 - elev, 0, 0)


def area(name, loc, energy, size, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = energy
    ld.size = size
    ld.color = color
    lo_ = bpy.data.objects.new(name, ld)
    scene.collection.objects.link(lo_)
    lo_.location = loc
    direction = np.array(look) - np.array(loc)
    lo_.rotation_euler = direction_to_euler(direction)


def direction_to_euler(v):
    from mathutils import Vector
    return Vector(v).to_track_quat("-Z", "Y").to_euler()


s = dist
area("key", (look[0] - 0.6 * s, look[1] - 0.8 * s, look[2] + 0.7 * s), 30 * s * s, 0.6 * s, (1.0, 0.97, 0.93))
area("fill", (look[0] + 0.9 * s, look[1] - 0.5 * s, look[2] + 0.2 * s), 12 * s * s, 0.8 * s, (0.9, 0.93, 1.0))
area("rim", (look[0] + 0.2 * s, look[1] + 0.9 * s, look[2] + 0.8 * s), 26 * s * s, 0.5 * s, (0.75, 0.82, 1.0))

world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.03, 0.035, 0.05, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
scene.world = world

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 64
scene.cycles.use_denoising = True
scene.render.film_transparent = True
scene.render.resolution_x, scene.render.resolution_y = w, h
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"

for i in range(first, last + 1):
    pivot.rotation_euler = (0, 0, 2 * math.pi * i / frames)
    scene.render.filepath = str(out / f"f_{i:04d}.png")
    bpy.ops.render.render(write_still=True)
print("rendered", first, last)
