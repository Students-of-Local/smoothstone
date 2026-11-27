"""Two stills of the snap case: closed (body + cover snapped on) and exploded (cover lifted off).

blender -b --python tools/case_still.py -- <body.stl> <cover.stl> <out.png> <closed|exploded> [color] [res]

The body sits on the bed at z = 0. Closed: the cover drops onto the front, its plate flush with the
body's front rim. Exploded: the cover lifts straight up the body's axis by 40 mm so the rim hooks and
the catch pockets show. Cycles on the CPU, denoised, same look as tools/still.py.
"""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
BODY, COVER, OUT, MODE = Path(argv[0]), Path(argv[1]), Path(argv[2]), argv[3]
COLORS = {"orange": (0.93, 0.30, 0.05), "teal": (0.02, 0.42, 0.42), "white": (0.80, 0.80, 0.78),
          "red": (0.70, 0.04, 0.04), "blue": (0.05, 0.18, 0.62), "green": (0.10, 0.45, 0.12),
          "gray": (0.30, 0.31, 0.33)}
PLA = COLORS[argv[4] if len(argv) > 4 else "orange"]
RES = int(argv[5]) if len(argv) > 5 else 1400

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 96
scene.cycles.use_denoising = True
scene.render.resolution_x = RES
scene.render.resolution_y = RES
scene.render.film_transparent = True


def load(path, z_off=0.0):
    bpy.ops.wm.stl_import(filepath=str(path))
    ob = bpy.context.selected_objects[0]
    ob.location.z += z_off
    mat = bpy.data.materials.new("pla")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*PLA, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.55
    ob.data.materials.append(mat)
    return ob


body = load(BODY)
if MODE == "closed":
    # the cover prints plate-down; to assemble it, flip it over and drop its rim into the case's
    # open top, so the plate rests on the case's front rim (z = h .. h + cover_t, defaults 30 + 2.5)
    cover = load(COVER)
    cover.rotation_euler = (3.141592653589793, 0.0, 0.0)
    cover.location = (0.0, 0.0, 32.5)
else:
    # exploded: the cover lifts straight up off the front, rim and hooks showing
    cover = load(COVER, z_off=0.0)
    cover.rotation_euler = (3.141592653589793, 0.0, 0.0)
    cover.location = (0.0, 0.0, 75.0)

# frame the union of both parts
pts = []
for ob in (body, cover):
    for c in ob.bound_box:
        pts.append(ob.matrix_world @ Vector(c))
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2
size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)

# camera: three-quarter view from the front-left, above
cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = center + Vector((-1.15, -1.45, 0.95)) * size
direction = center - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
cam_data.lens = 55

# a key light and a soft fill so the hooks read
key = bpy.data.lights.new("key", "AREA")
key.energy = size * size * 14
key.size = size
key_ob = bpy.data.objects.new("key", key)
key_ob.location = center + Vector((-1.2, -1.4, 2.2)) * size
key_ob.rotation_euler = (center - key_ob.location).to_track_quat("-Z", "Y").to_euler()
scene.collection.objects.link(key_ob)

fill = bpy.data.lights.new("fill", "AREA")
fill.energy = size * size * 5
fill.size = size * 1.5
fill_ob = bpy.data.objects.new("fill", fill)
fill_ob.location = center + Vector((1.6, -0.6, 0.8)) * size
fill_ob.rotation_euler = (center - fill_ob.location).to_track_quat("-Z", "Y").to_euler()
scene.collection.objects.link(fill_ob)

scene.world = bpy.data.worlds.new("w")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.9, 0.9, 0.92, 1)
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6

scene.render.filepath = str(OUT)
bpy.ops.render.render(write_still=True)
print("wrote", OUT)
