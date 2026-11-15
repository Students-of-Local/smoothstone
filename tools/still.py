"""One product still of a finished part, for the README.

blender -b --python tools/still.py -- <part.stl> <out.png> [color] [res] [samples]

color is a PLA name from COLORS. STILL_BACKLIT=1 is for lithophanes: thin white PLA lit from behind,
seen from the front. The mesh is the STL as written; it is only centered on the bed
and framed by its own size. Cycles on the CPU (set STILL_GPU=1 for OptiX), denoised.
"""
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
STL, OUT = argv[0], Path(argv[1])
COLORS = {"orange": (0.93, 0.30, 0.05), "teal": (0.02, 0.42, 0.42), "white": (0.80, 0.80, 0.78),
          "red": (0.70, 0.04, 0.04), "blue": (0.05, 0.18, 0.62), "green": (0.10, 0.45, 0.12),
          "black": (0.03, 0.03, 0.035), "yellow": (0.95, 0.62, 0.02), "purple": (0.30, 0.10, 0.55),
          "gray": (0.30, 0.31, 0.33)}
PLA = COLORS[argv[2] if len(argv) > 2 else "orange"]
RES = int(argv[3]) if len(argv) > 3 else 1200
SAMPLES = int(argv[4]) if len(argv) > 4 else 96
BACKLIT = bool(os.environ.get("STILL_BACKLIT"))
TURN = int(os.environ.get("STILL_TURN", "0"))
SPAN = float(os.environ.get("STILL_SPAN", "1"))

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
if os.environ.get("STILL_GPU"):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    scene.cycles.device = "GPU"
else:
    scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
scene.render.resolution_x = scene.render.resolution_y = RES
scene.render.image_settings.file_format = "PNG"
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Medium High Contrast"

world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.045, 0.05, 0.085, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.35


def nodes_of(m):
    m.use_nodes = True
    return m.node_tree.nodes, m.node_tree.links


def pla_material():
    m = bpy.data.materials.new("pla")
    n, l = nodes_of(m)
    b = n["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*PLA, 1)
    b.inputs["Roughness"].default_value = 0.45
    b.inputs["Subsurface Weight"].default_value = 1.0 if BACKLIT else 0.06
    b.inputs["Subsurface Radius"].default_value = (1.0, 0.85, 0.6) if BACKLIT else (1.0, 0.4, 0.2)
    b.inputs["Subsurface Scale"].default_value = 0.5 if BACKLIT else 0.6
    if BACKLIT:  # frosted plastic that absorbs and scatters per millimeter, so thick areas go dark (cool LED look)
        b.inputs["Transmission Weight"].default_value = 1.0
        b.inputs["Roughness"].default_value = 0.7
        b.inputs["Subsurface Weight"].default_value = 0.0
        vol = n.new("ShaderNodeVolumePrincipled")
        vol.inputs["Color"].default_value = (1.0, 0.82, 0.6, 1)
        vol.inputs["Density"].default_value = 1.4
        vol.inputs["Anisotropy"].default_value = 0.5
        vol.inputs["Absorption Color"].default_value = (0.22, 0.5, 0.85, 1)
        l.new(vol.outputs[0], n["Material Output"].inputs["Volume"])
    bev = n.new("ShaderNodeBevel")  # shading only: the mesh is not changed
    bev.inputs["Radius"].default_value = 0.3
    l.new(bev.outputs["Normal"], b.inputs["Normal"])
    return m


def bed_material():
    m = bpy.data.materials.new("bed")
    n, l = nodes_of(m)
    b = n["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.022, 0.021, 0.024, 1)
    b.inputs["Roughness"].default_value = 0.78
    b.inputs["Specular IOR Level"].default_value = 0.3
    tc = n.new("ShaderNodeTexCoord")
    noise = n.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 90.0
    noise.inputs["Detail"].default_value = 8
    l.new(tc.outputs["Object"], noise.inputs["Vector"])
    bump = n.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    bump.inputs["Distance"].default_value = 0.08
    l.new(noise.outputs["Fac"], bump.inputs["Height"])
    l.new(bump.outputs["Normal"], b.inputs["Normal"])
    # radial fade so the bed ends in the background, not on an edge
    sep = n.new("ShaderNodeSeparateXYZ")
    l.new(tc.outputs["Object"], sep.inputs[0])
    comb = n.new("ShaderNodeCombineXYZ")
    l.new(sep.outputs["X"], comb.inputs["X"])
    l.new(sep.outputs["Y"], comb.inputs["Y"])
    vlen = n.new("ShaderNodeVectorMath")
    vlen.operation = "LENGTH"
    l.new(comb.outputs[0], vlen.inputs[0])
    ramp = n.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.42
    ramp.inputs["From Max"].default_value = 1.0
    ramp.inputs["To Min"].default_value = 1.0
    ramp.inputs["To Max"].default_value = 0.0
    ramp.interpolation_type = "SMOOTHSTEP"
    l.new(vlen.outputs["Value"], ramp.inputs["Value"])
    mix = n.new("ShaderNodeMixShader")
    bg = n.new("ShaderNodeBsdfTransparent")
    l.new(ramp.outputs["Result"], mix.inputs["Fac"])
    l.new(bg.outputs[0], mix.inputs[1])
    l.new(b.outputs[0], mix.inputs[2])
    l.new(mix.outputs[0], n["Material Output"].inputs["Surface"])
    return m


bpy.ops.wm.stl_import(filepath=STL)
obj = bpy.context.selected_objects[0]
obj.data.materials.clear()
obj.data.materials.append(pla_material())
lo = Vector([min(v.co[i] for v in obj.data.vertices) for i in range(3)])
hi = Vector([max(v.co[i] for v in obj.data.vertices) for i in range(3)])
size = hi - lo
obj.location = (-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)  # centered, standing on the bed
S = max(size.x, size.y, size.z * 1.3)

R_BED = S * 1.1
bpy.ops.mesh.primitive_cylinder_add(vertices=192, radius=1.0, depth=0.02, location=(0, 0, -0.011 * R_BED))
bed = bpy.context.active_object
bed.scale = (R_BED, R_BED, R_BED)
bed.data.materials.append(bed_material())

cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 85
cam_data.sensor_width = 36
cam_data.clip_start = 1
cam_data.clip_end = 100000
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
el, az = (math.radians(10), math.radians(-18)) if BACKLIT else (math.radians(30), math.radians(-35))
dist = S * 3.3
target = Vector((0, 0, size.z * 0.42))
cam.location = target + Vector((dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az), dist * math.sin(el)))
cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = cam
cam_data.dof.use_dof = True
cam_data.dof.focus_distance = (target - cam.location).length
cam_data.dof.aperture_fstop = 5.6


def light(name, energy, loc, sz, color):
    d = bpy.data.lights.new(name, "AREA")
    d.energy = energy
    d.color = color
    d.size = sz
    o = bpy.data.objects.new(name, d)
    o.location = loc
    scene.collection.objects.link(o)
    o.rotation_euler = (Vector((0, 0, 0)) - o.location).to_track_quat("-Z", "Y").to_euler()


k = S / 120.0
if BACKLIT:  # a warm panel behind the picture, the room nearly dark
    light("back", 8.0e5 * k * k, (0, S * 0.5, size.z * 0.5), S * 0.6, (1.0, 0.86, 0.66))
    k *= 0.08
light("key", 1.9e6 * k * k, (-S * 2.0, -S * 2.2, S * 3.0), S * 2.4, (1.0, 0.96, 0.9))
light("fill", 0.6e6 * k * k, (S * 2.6, -S * 1.6, S * 1.4), S * 2.5, (0.75, 0.82, 1.0))
light("rim", 3.0e6 * k * k, (S * 0.6, S * 2.6, S * 1.6), S * 1.4, (0.55, 0.68, 1.0))

if TURN:
    pivot = bpy.data.objects.new("pivot", None)
    scene.collection.objects.link(pivot)
    obj.parent = pivot
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", index=2, frame=0)
    pivot.rotation_euler = (0, 0, 2 * math.pi * SPAN)
    pivot.keyframe_insert("rotation_euler", index=2, frame=TURN)
    for kp in pivot.animation_data.action.layers[0].strips[0].channelbags[0].fcurves[0].keyframe_points \
            if hasattr(pivot.animation_data.action, "layers") else pivot.animation_data.action.fcurves[0].keyframe_points:
        kp.interpolation = "LINEAR"
    OUT.mkdir(parents=True, exist_ok=True)
    for f in range(TURN):
        scene.frame_set(f)
        scene.render.filepath = str(OUT / f"f_{f:04d}.png")
        bpy.ops.render.render(write_still=True)
else:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(OUT)
    bpy.ops.render.render(write_still=True)
