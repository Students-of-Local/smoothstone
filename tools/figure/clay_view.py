"""An orthographic clay render of a unit-height figure, straight from the front or the back, on white.

blender -b --python tools/figure/clay_view.py -- <figure.stl> <out.png> front|back [width] [height]

The style model paints this picture, so the colors it draws sit exactly on the mesh: the
picture is of the mesh itself, not of a drawing the lift model only approximated.
The figure is Z up and faces -Y (src/smoothstone/figure.py repair).
"""
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
STL, OUT, SIDE = argv[0], argv[1], argv[2]
W = int(argv[3]) if len(argv) > 3 else 768
H = int(argv[4]) if len(argv) > 4 else 1024

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = W, H
scene.render.film_transparent = True  # composited onto pure white below
scene.render.image_settings.color_mode = "RGBA"
scene.view_settings.view_transform = "Standard"

bpy.ops.wm.stl_import(filepath=STL)
obj = bpy.context.selected_objects[0]
bpy.ops.object.shade_smooth()
mat = bpy.data.materials.new("clay")
mat.use_nodes = True
b = mat.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.72, 0.72, 0.72, 1)
b.inputs["Roughness"].default_value = 0.6
obj.data.materials.append(mat)

world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.55

lo = Vector([min(v.co[i] for v in obj.data.vertices) for i in range(3)])
hi = Vector([max(v.co[i] for v in obj.data.vertices) for i in range(3)])
c = (lo + hi) / 2
size = hi - lo
sign = -1 if SIDE == "front" else 1

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
# portrait frame: ortho_scale spans the height; full figure with a margin, wide figures fit too
cam_data.sensor_fit = "VERTICAL"
cam_data.ortho_scale = max(size.z, size.x * H / W) * 1.12
cam = bpy.data.objects.new("cam", cam_data)
bpy.context.collection.objects.link(cam)
cam.location = (c.x, c.y + sign * 5 * size.z, c.z)
cam.rotation_euler = (1.5708, 0, 0 if SIDE == "front" else 3.14159)
scene.camera = cam

key = bpy.data.lights.new("key", "SUN")
key.energy = 3.0
k = bpy.data.objects.new("key", key)
bpy.context.collection.objects.link(k)
k.rotation_euler = (0.9, 0.35, 0.4 + (0 if SIDE == "front" else 3.14159))  # key light turns with the camera

scene.render.filepath = OUT
bpy.ops.render.render(write_still=True)

# flatten onto pure white so the style model sees a clean sheet
img = bpy.data.images.load(OUT)
px = list(img.pixels)
for i in range(0, len(px), 4):
    a = px[i + 3]
    for j in range(3):
        px[i + j] = px[i + j] * a + (1 - a)
    px[i + 3] = 1.0
img.pixels[:] = px
img.filepath_raw = OUT
img.file_format = "PNG"
img.save()
