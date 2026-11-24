"""Blender side of stone timelapse: render the frames of a predicted print timelapse.

blender -b --factory-startup --python timelapse_blender.py -- <scene.npz> <frames.json> <out dir>

scene.npz (timelapse.write_scene) holds V (n, 3) mm and Q (m, 4) quads of every printed line as a
flat ribbon, line width x layer height, in print order; lv and lq, each layer's first vertex and
first quad (one more entry than layers); bed (2,) mm; rgb (3,) the filament color 0..255.
frames.json holds the camera, the image size, the head size, and per frame: "full" (layers shown
whole), "part" ([layer, lines] of the layer in progress, or null), "head" ([x, y, z] mm of the
nozzle, or null when the head is parked out of view), "shift" (mm the camera moves in the bed's frame, for a
printer that moves its bed) and "extras" (an npz of extra geometry for this
frame, or null: V0 F0 C0, V1 F1 C1 ... meshes with their colors, added by stone timelapse --fail).
Writes f_0000.png ... in frame order.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
d = np.load(argv[0])
cfg = json.loads(Path(argv[1]).read_text())
out = Path(argv[2])
out.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
M = 0.001  # mm to m


def srgb_to_linear(c):
    c = np.asarray(c, float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def material(name, rgb, rough=0.5):
    m = bpy.data.materials.new(name)
    lin = srgb_to_linear(rgb)
    m.diffuse_color = (*lin.tolist(), 1.0)
    m.roughness = rough
    return m


def mesh(name, V, F, mat):
    me = bpy.data.meshes.new(name)
    k = F.shape[1]
    me.vertices.add(len(V))
    me.vertices.foreach_set("co", (np.asarray(V, np.float32) * M).ravel())
    me.loops.add(F.size)
    me.loops.foreach_set("vertex_index", F.astype(np.int32).ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set("loop_start", np.arange(0, F.size, k, dtype=np.int32))
    if bpy.app.version < (3, 6, 0):  # older ones do not work it out from loop_start
        me.polygons.foreach_set("loop_total", np.full(len(F), k, np.int32))
    me.polygons.foreach_set("use_smooth", np.zeros(len(F), bool))  # flat faces: Blender 4.1 and later start out smooth
    me.update(calc_edges=True)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob


V, Q, lv, lq = d["V"], d["Q"], d["lv"], d["lq"]
plastic = material("filament", d["rgb"], 0.45)
layers = []
for i in range(len(lv) - 1):
    if lq[i + 1] > lq[i]:
        layers.append(mesh(f"layer_{i:04d}", V[lv[i]:lv[i + 1]], Q[lq[i]:lq[i + 1]] - lv[i], plastic))
    else:
        layers.append(None)

bx, by = (float(v) for v in d["bed"])
bed_v = np.array([[x, y, z] for z in (-4.0, 0.0) for y in (0, by) for x in (0, bx)], float)
bed_f = np.array([[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [1, 5, 7, 3], [3, 7, 6, 2], [2, 6, 4, 0]])
mesh("bed", bed_v, bed_f, material("bed", cfg.get("bed_rgb", (40, 40, 42)), 0.8))

hs = cfg.get("head_mm", [40.0, 40.0, 50.0])
ns = float(cfg.get("nozzle_mm", 12.0))
hv = np.array([[x, y, z] for z in (ns, ns + hs[2]) for y in (-hs[1] / 2, hs[1] / 2) for x in (-hs[0] / 2, hs[0] / 2)], float)
nz = np.array([[x, y, z] for z in (0.0, ns) for y in (-4.0, 4.0) for x in (-4.0, 4.0)], float)
head = mesh("head", np.vstack([hv, nz]), np.vstack([bed_f, bed_f + 8]), material("head", cfg.get("head_rgb", (70, 72, 76)), 0.6))

cam_d = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_d)
scene.collection.objects.link(cam)
scene.camera = cam
c = cfg["camera"]
cam_d.sensor_fit = "HORIZONTAL"
cam_d.angle = math.radians(c["hfov_deg"])
cam_d.clip_start, cam_d.clip_end = 0.002, 20.0
pos = Vector([v * M for v in c["pos_mm"]])
if c.get("rot"):  # columns: the camera's right, up and back axes in world space (Blender's convention)
    R = Matrix([list(r) for r in c["rot"]])
    cam.matrix_world = Matrix.Translation(pos) @ R.to_4x4()
else:
    cam.location = pos
    cam.rotation_euler = (Vector([v * M for v in c["look_at_mm"]]) - pos).to_track_quat("-Z", "Y").to_euler()

world = bpy.data.worlds.new("world")
world.color = tuple(srgb_to_linear(cfg.get("background_rgb", (18, 18, 20))).tolist())
scene.world = world
scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading
sh.light = "STUDIO"
sh.color_type = "MATERIAL"
sh.show_shadows = True
sh.shadow_intensity = 0.35
sh.show_cavity = True
sh.cavity_type = "WORLD"
scene.display.render_aa = cfg.get("aa", "8")
scene.render.resolution_x, scene.render.resolution_y = cfg["size"]
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"

shown = -1
for k, fr in enumerate(cfg["frames"]):
    full = fr["full"]
    if full != shown:
        for i, ob in enumerate(layers):
            if ob is not None:
                ob.hide_render = i >= full
        shown = full
    temp = []
    if fr.get("part"):
        i, lines = fr["part"]
        if lines > 0:
            a = lv[i]
            temp.append(mesh("part", V[a:a + 8 * lines], Q[lq[i]:lq[i] + 5 * lines] - a, plastic))
    if fr.get("extras"):
        e = np.load(fr["extras"])
        j = 0
        while f"V{j}" in e:
            temp.append(mesh(f"extra{j}", e[f"V{j}"], e[f"F{j}"], material(f"extra{j}", e[f"C{j}"], 0.5)))
            j += 1
    head.hide_render = fr.get("head") is None
    if fr.get("head") is not None:
        head.location = Vector([v * M for v in fr["head"]])
    cam.location = pos + Vector([v * M for v in fr.get("shift", (0, 0, 0))])
    scene.render.filepath = str(out / f"f_{k:04d}.png")
    bpy.ops.render.render(write_still=True)
    for ob in temp:
        me = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
print("rendered", len(cfg["frames"]))
