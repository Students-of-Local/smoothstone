"""Render the photo-like ruler fixture for tests/test_measure.py.

blender -b --python tests/fixtures/measure/render_blender.py

A 200 x 30 mm yellow mm ruler and a dark 60 x 35 x 4 mm block with rounded edges lie on light paper.
The camera is a 50 mm perspective lens 350 mm away, tilted 14 deg off straight down, with a soft
area light and a little ambient light. Writes blender_ruler.jpg next to this file.
"""

import math
from pathlib import Path

import bpy
import numpy as np

HERE = Path(__file__).resolve().parent
MM = 0.001
TEX_PX_MM = 20


def ruler_texture() -> bpy.types.Image:
    w, h = 200 * TEX_PX_MM, 30 * TEX_PX_MM
    a = np.zeros((h, w, 4), np.float32)
    a[...] = (0.93, 0.74, 0.18, 1.0)  # linear yellow
    ink = (0.015, 0.015, 0.015, 1.0)

    def rect(x0, y0, x1, y1):  # mm, y from the top edge
        a[int(y0 * TEX_PX_MM): int(y1 * TEX_PX_MM), int(x0 * TEX_PX_MM): int(x1 * TEX_PX_MM)] = ink

    seg = {  # seven segment digits, 3 x 5 mm
        "a": (0, 0, 3, 0.5), "b": (2.5, 0, 3, 2.5), "c": (2.5, 2.5, 3, 5), "d": (0, 4.5, 3, 5),
        "e": (0, 2.5, 0.5, 5), "f": (0, 0, 0.5, 2.5), "g": (0, 2.25, 3, 2.75),
    }
    digits = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
              "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}
    for i in range(0, 191):
        x = 5 + i
        ln = 7.0 if i % 10 == 0 else 5.0 if i % 5 == 0 else 3.2
        rect(x - 0.1, 0, x + 0.1, ln)
        if i % 10 == 0:
            text = str(i // 10)
            x0 = x - 1.8 * len(text) + 0.3
            for ch in text:
                for s in digits[ch]:
                    sx0, sy0, sx1, sy1 = seg[s]
                    rect(x0 + sx0, 9 + sy0, x0 + sx1, 9 + sy1)
                x0 += 3.6
    img = bpy.data.images.new("ruler", w, h, alpha=True, float_buffer=True)
    img.pixels.foreach_set(a[::-1].ravel())  # Blender rows go bottom up
    img.pack()
    return img


def material(name, color, rough=0.6, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = rough
    if image is not None:
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = image
        t.interpolation = "Cubic"
        m.node_tree.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    return m


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    # paper
    bpy.ops.mesh.primitive_plane_add(size=0.6)
    paper = bpy.context.object
    pm = material("paper", (0.72, 0.70, 0.66, 1), rough=0.9)
    nt = pm.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 400
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.68, 0.66, 0.62, 1)
    ramp.color_ramp.elements[1].color = (0.75, 0.73, 0.69, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    paper.data.materials.append(pm)

    # ruler: a 1.5 mm thick yellow bar with the printed face on top
    rot = math.radians(-12)
    rc = (0.0, 0.045)
    bpy.ops.mesh.primitive_cube_add(size=1)
    body = bpy.context.object
    body.scale = (200 * MM, 30 * MM, 1.5 * MM)
    body.location = (rc[0], rc[1], 0.75 * MM)
    body.rotation_euler[2] = rot
    body.data.materials.append(material("ruler_body", (0.93, 0.74, 0.18, 1), rough=0.4))
    bpy.ops.mesh.primitive_plane_add(size=1)
    face = bpy.context.object
    face.scale = (200 * MM, 30 * MM, 1)
    face.location = (rc[0], rc[1], 1.51 * MM)
    face.rotation_euler[2] = rot
    face.data.materials.append(material("ruler_face", (1, 1, 1, 1), rough=0.35, image=ruler_texture()))

    # the object: 60 x 35 x 4 mm dark block, rounded edges
    bpy.ops.mesh.primitive_cube_add(size=1)
    blk = bpy.context.object
    blk.scale = (60 * MM, 35 * MM, 4 * MM)
    blk.location = (0.02, -0.04, 2 * MM)
    blk.rotation_euler[2] = math.radians(25)
    bpy.ops.object.transform_apply(scale=True)
    bev = blk.modifiers.new("bevel", "BEVEL")
    bev.width = 1.0 * MM
    bev.segments = 4
    blk.data.materials.append(material("block", (0.03, 0.03, 0.04, 1), rough=0.5))

    # camera: 350 mm up, tilted 14 deg
    tilt = math.radians(14)
    dist = 0.35
    bpy.ops.object.camera_add(location=(0.0, -dist * math.sin(tilt), dist * math.cos(tilt)))
    cam = bpy.context.object
    cam.rotation_euler = (tilt, 0, 0)
    cam.data.lens = 50
    cam.data.sensor_width = 36
    sc.camera = cam

    # light: a big soft area light off to one side, and a dim world
    bpy.ops.object.light_add(type="AREA", location=(0.25, -0.15, 0.6))
    lamp = bpy.context.object
    lamp.data.size = 0.5
    lamp.data.energy = 6
    lamp.rotation_euler = (math.radians(20), math.radians(22), 0)
    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25
    sc.world = world

    sc.render.engine = "CYCLES"
    sc.cycles.samples = 48
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 1600
    sc.render.resolution_y = 1200
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 90
    sc.view_settings.view_transform = "Standard"
    sc.render.filepath = str(HERE / "blender_ruler.jpg")
    bpy.ops.render.render(write_still=True)


main()
