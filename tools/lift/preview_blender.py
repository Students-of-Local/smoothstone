"""Headless Blender preview: three clay views (front, 3/4, side) in one PNG.

blender -b --factory-startup -P preview_blender.py -- mesh.(glb|stl) out.png
"""

import math
import sys

import bpy
from mathutils import Vector

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]

bpy.ops.wm.read_factory_settings(use_empty=True)
if src.lower().endswith(".stl"):
    bpy.ops.wm.stl_import(filepath=src)  # STL is Z-up already
else:
    bpy.ops.import_scene.gltf(filepath=src)  # glTF importer converts Y-up to Z-up

objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2
radius = (hi - lo).length / 2

mat = bpy.data.materials.new("clay")
mat.diffuse_color = (0.78, 0.76, 0.72, 1)
for o in objs:
    o.data.materials.clear()
    o.data.materials.append(mat)
    for p in o.data.polygons:
        p.use_smooth = False

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_cavity = True
scene.render.film_transparent = False
scene.world = bpy.data.worlds.new("w")
scene.world.color = (1, 1, 1)
scene.view_settings.view_transform = "Standard"
size = 640
scene.render.resolution_x = size
scene.render.resolution_y = size

# Render three views with one ortho camera, then stitch them side by side.
cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam_data.ortho_scale = radius * 2.1
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

# Subject faces -Y after glTF import (front view of the input image).
views = [("front", 0), ("three_quarter", 45), ("side", 90)]
tiles = []
for name, deg in views:
    a = math.radians(deg)
    d = radius * 4
    cam.location = center + Vector((d * math.sin(a), -d * math.cos(a), 0))
    direction = center - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    path = f"{dst}.{name}.png"
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    tiles.append(path)

# Stitch with Blender's image API so no extra deps are needed.
import os

imgs = [bpy.data.images.load(p) for p in tiles]
w, h = imgs[0].size
out = bpy.data.images.new("sheet", width=w * 3, height=h, alpha=False)
px = [0.0] * (w * 3 * h * 4)
for i, im in enumerate(imgs):
    src_px = list(im.pixels)
    for y in range(h):
        row = src_px[y * w * 4:(y + 1) * w * 4]
        start = (y * w * 3 + i * w) * 4
        px[start:start + w * 4] = row
out.pixels = px
out.filepath_raw = dst
out.file_format = "PNG"
out.save()
for p in tiles:
    os.remove(p)
