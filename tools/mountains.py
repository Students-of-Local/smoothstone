"""The mountain picture in examples/images, made here so its rights are ours.

blender -b -t 8 --python tools/mountains.py -- <out.png> [width] [samples]
"""
import math
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
W = int(argv[1]) if len(argv) > 1 else 900
SAMPLES = int(argv[2]) if len(argv) > 2 else 32

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = W, int(W * 2 / 3)
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - High Contrast"

# terrain: a far range of big ridges and a low near shore, each a subdivided plane pushed up by noise
lands = []
for loc, size, scale, strength in (((0, 340, -10), 480, 60, 170), ((0, 40, 0), 160, 14, 11)):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
    land = bpy.context.active_object
    sub = land.modifiers.new("sub", "SUBSURF")
    sub.subdivision_type = "SIMPLE"
    sub.levels = sub.render_levels = 9
    for name, sc, st, depth in (("ridges", scale, strength, 6), ("rocks", scale / 12, strength / 14, 2)):
        tex = bpy.data.textures.new(name, "CLOUDS")
        tex.noise_scale = sc
        tex.noise_depth = depth
        d = land.modifiers.new(name, "DISPLACE")
        d.texture = tex
        d.strength = st
        d.mid_level = 0.35
        d.texture_coords = "GLOBAL"
    lands.append(land)
mat = bpy.data.materials.new("rock")
mat.use_nodes = True
b = mat.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.22, 0.22, 0.23, 1)
b.inputs["Roughness"].default_value = 0.9
for land in lands:
    land.data.materials.append(mat)

# lake in the valley
bpy.ops.mesh.primitive_plane_add(size=900, location=(0, 200, 4))
water = bpy.data.materials.new("water")
water.use_nodes = True
wb = water.node_tree.nodes["Principled BSDF"]
wb.inputs["Base Color"].default_value = (0.05, 0.06, 0.08, 1)
wb.inputs["Roughness"].default_value = 0.05
bpy.context.active_object.data.materials.append(water)

world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
sky.sun_elevation = math.radians(9)
sky.sun_rotation = math.radians(180)
world.node_tree.links.new(sky.outputs[0], world.node_tree.nodes["Background"].inputs[0])
world.node_tree.nodes["Background"].inputs[1].default_value = 0.25

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 2.5
sun.data.angle = math.radians(2)
sun.rotation_euler = (math.radians(81), 0, math.radians(180))
scene.collection.objects.link(sun)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.lens = 40
cam.location = (0, -40, 22)
cam.rotation_euler = (math.radians(86), 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "BW"
scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)
