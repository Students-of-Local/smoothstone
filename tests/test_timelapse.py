"""stone timelapse: the G-code reader and time model (gcode.py), generated toolpaths (toolpaths.py),
frames, the camera fit and the Blender render (timelapse.py)."""

import gzip
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, gcode, timelapse, toolpaths

from test_slicer import _box, _union

FIX = Path(__file__).parent / "fixtures" / "gcode"
GCODES = sorted(FIX.glob("*.gcode.gz"))


def _layer_zs(text: str) -> list[float]:
    """Each layer's z as the file says it, read without gcode.py: the ;Z: (or ; Z_HEIGHT:) comment
    after each ;LAYER_CHANGE."""
    zs, want = [], False
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r";\s*(LAYER_CHANGE|CHANGE_LAYER)", s):
            want = True
        elif want and re.match(r";\s*(Z|Z_HEIGHT):", s):
            zs.append(float(s.split(":", 1)[1]))
            want = False
    return zs


@pytest.mark.parametrize("path", GCODES, ids=lambda p: p.name.split(".")[0])
def test_every_frame_is_its_layers_gcode_z(path):
    """(a) One frame per layer, each at that layer's z from the file, exactly."""
    want = _layer_zs(gzip.decompress(path.read_bytes()).decode(errors="replace"))
    tp = gcode.load(path)
    frs = timelapse.frames(tp, "per-layer")
    assert len(want) > 3
    assert [f["z_mm"] for f in frs] == want
    assert [f["layer"] for f in frs] == list(range(len(want)))
    if tp.header_layers:
        assert len(frs) == tp.header_layers
    assert all(b["t_s"] > a["t_s"] for a, b in zip(frs, frs[1:]))


@pytest.mark.parametrize("path", GCODES, ids=lambda p: p.name.split(".")[0])
def test_print_time_is_within_10_percent_of_the_slicers_estimate(path):
    """(b) Measured: screw (PrusaSlicer) +4.1%, washer (Creality Print) +1.2%, cube (OrcaSlicer) +0.4%."""
    tp = gcode.load(path)
    assert tp.estimate_s
    assert tp.total_s() == pytest.approx(tp.estimate_s, rel=0.10)


def test_trapezoid_and_triangle_moves_take_their_textbook_time():
    text = "M205 X0 Y0 Z0 E0\nM204 S1000\nG21\nG90\nM83\nG1 X100 F6000\nG1 X98\n"
    tp = gcode.plan(gcode.parse(text))
    # 100 mm at 100 mm/s, 1000 mm/s2, from rest and back to rest (no jerk, then a reversal)
    assert tp.t1[0] - tp.t0[0] == pytest.approx(1.1, abs=1e-6)
    # 2 mm back never reaches 100 mm/s: up to sqrt(a d) and down again
    assert tp.t1[1] - tp.t0[1] == pytest.approx(2 * math.sqrt(1000 * 2) / 1000, abs=1e-6)


CURA = """;FLAVOR:Marlin
;TIME:100
;LAYER_COUNT:2
M82
G92 E0
;LAYER:0
G0 F6000 X10 Y10 Z0.3
;TYPE:WALL-OUTER
G1 F1800 X20 Y10 E1
G1 X20 Y20 E2
;TYPE:FILL
G1 X10 Y20 E3
;LAYER:1
G0 X10 Y10 Z0.5
G92 E0
;TYPE:SKIN
G1 X20 Y10 E1
G91
G1 X0 Y10 E1
G90
"""

BAMBU = """; HEADER_BLOCK_START
; model printing time: 1m 40s; total estimated time: 2m 0s
; total layer number: 2
; HEADER_BLOCK_END
M83
SET_VELOCITY_LIMIT ACCEL=5000
; CHANGE_LAYER
; Z_HEIGHT: 0.2
; LAYER_HEIGHT: 0.2
; FEATURE: Outer wall
; LINE_WIDTH: 0.42
G1 X10 Y10 Z0.2 F3000
G1 X20 Y10 E0.5
G3 X20 Y20 I0 J5 E0.8
; CHANGE_LAYER
; Z_HEIGHT: 0.4
; FEATURE: Sparse infill
G1 Z0.4
G1 X10 Y20 E0.5
"""


def test_cura_layers_features_and_relative_moves():
    tp = gcode.load(CURA)
    assert tp.layer_z == [0.3, 0.5]  # Cura writes no ;Z:, so each layer's first extrusion height
    assert tp.estimate_s == 100
    ext = tp.extruding()
    names = [gcode.FEATURES[k] for k in tp.feature[ext]]
    assert names == ["outer wall", "outer wall", "sparse infill", "solid infill", "solid infill"]
    assert tp.p1[ext][-1, :2].tolist() == [20.0, 20.0]  # G91 moved 10 mm from 20,10
    assert tp.p1[ext][3, 3] - tp.p0[ext][3, 3] == pytest.approx(1.0)  # G92 E0 restarted absolute E


def test_bambu_layers_features_arcs_and_accel():
    tp = gcode.load(BAMBU)
    assert tp.layer_z == [0.2, 0.4]
    ext = tp.extruding()
    assert set(gcode.FEATURES[k] for k in tp.feature[ext & (tp.layer == 0)]) == {"outer wall"}
    assert gcode.FEATURES[tp.feature[ext][-1]] == "sparse infill"
    assert np.all(tp.width[ext & (tp.layer == 0)] == 0.42)
    arc = ext & (tp.layer == 0) & (tp.p0[:, 1] >= 10) & (tp.p1[:, 1] > 10)
    assert arc.sum() > 10  # the half circle is cut into short chords
    length = np.hypot(*(tp.p1[arc, :2] - tp.p0[arc, :2]).T).sum()
    assert length == pytest.approx(math.pi * 5, rel=0.01)
    assert np.all(tp.accel[ext] == 5000)
    assert tp.estimate_s == 120


def _k2():
    return timelapse.slicing(timelapse.builtin_k2())


@pytest.mark.parametrize("shape", ["box", "cylinder", "t_supported"])
def test_generated_volume_matches_the_model_per_layer(shape):
    """(d) Each layer's generated lines lay within 15% of the modeled plastic: walls and solid
    infill fill their area, the grid its density, supports their spacing. Features here are 12 mm
    or more across; narrower ones quantize (a 6 mm support strip at 2.5 mm spacing holds 2 lines
    where the fill asks for 2.4, and the 6 mm T of test_supports comes out 15% low)."""
    from smoothstone import supports

    if shape == "box":
        mesh, sup = trimesh.creation.box((20, 20, 6)), None
    elif shape == "cylinder":
        mesh, sup = trimesh.creation.cylinder(radius=12, height=6, sections=128), None
    else:
        mesh = _union(_box((10, 12, 10), (15, 0, 0)), _box((40, 12, 3), (0, 0, 10)))
        sup = supports.analyze(mesh, columns=True)
    tp = toolpaths.generate(mesh, _k2(), 0.2, sup, (130, 130))
    exp, got = tp.volumes["expected"], tp.volumes["generated"]
    big = exp > 20 * 0.2 * 0.15  # layers with at least 20 mm2 of part at the sparsest fill
    assert big.sum() >= 0.8 * len(exp)
    ratio = got[big] / exp[big]
    assert ratio.min() > 0.85 and ratio.max() < 1.15, np.round(ratio, 3)
    if sup:
        support = tp.feature == gcode.FEATURES.index("support")
        assert support.any() and tp.p1[support, 2].max() <= 10.0 - 0.2 + 1e-6  # stops a gap below the arm


def test_generated_layers_take_orcas_time_for_the_same_plate():
    """OrcaSlicer's cube fixture is a 35 mm square plate, 4 layers. stone's own toolpaths for that
    plate with that file's settings take within 10% of Orca's lines on layers 1 to 3 (both timed by
    gcode.plan, which matches Orca's own estimate to 0.4%; layer 4 is left out, Orca irons it).
    Measured: 90.0 s against 93.9 s, -4.2%."""
    orca = gcode.load(FIX / "orca_cube.gcode.gz")
    e = orca.extruding()
    x, y = orca.p1[e, 0], orca.p1[e, 1]
    side = float(x.max() - x.min()) + 0.5  # the first layer's outer wall is 0.5 mm wide
    prof = {"widths": {"outer_wall": .42, "inner_wall": .45, "solid_infill": .42, "top_surface": .42, "first_layer": .5, "sparse_infill": .45},
            "speeds": {"outer_wall": 120, "inner_wall": 200, "solid_infill": 250, "top_surface": 200, "first_layer": 50,
                       "first_layer_infill": 105, "sparse_infill": 200, "travel": 500, "support": 150},
            "accels": {"default": 10000, "outer_wall": 5000, "inner_wall": 10000, "top_surface": 2000, "travel": 10000,
                       "first_layer": 500, "solid_infill": 10000, "sparse_infill": 10000},
            "shells": {"wall_loops": 3, "bottom_shell_layers": 5, "top_shell_layers": 6, "sparse_infill_density": 12},
            "support": {"line_width": .42, "base_pattern_spacing": 2.5, "top_z_distance": .2, "object_xy_distance": .35},
            "jerk": 9.0, "max_feed": orca.max_feed, "max_accel": orca.max_accel}
    ours = toolpaths.generate(trimesh.creation.box((side, side, 0.8)), prof, 0.2, None,
                              ((x.min() + x.max()) / 2, (y.min() + y.max()) / 2))
    assert ours.layer_z == orca.layer_z

    def first3(tp):
        dt = tp.t1 - tp.t0
        return float(dt[(tp.layer >= 0) & (tp.layer < 3)].sum())

    assert first3(ours) == pytest.approx(first3(orca), rel=0.10)


def test_realtime_frames_step_evenly_and_show_part_of_a_layer():
    tp = gcode.load(FIX / "creality_washer.gcode.gz")
    frs = timelapse.frames(tp, "realtime", seconds=2, fps=30)
    assert len(frs) == 60
    dt = np.diff([f["t_s"] for f in frs])
    assert np.allclose(dt, tp.total_s() / 60)
    layers = [f["layer"] for f in frs]
    assert layers == sorted(layers)
    assert any(0 < f["part"][1] for f in frs)


def test_ribbons_are_line_width_by_layer_height():
    V, Q = timelapse.ribbons(np.array([[0.0, 0, 0.2]]), np.array([[10.0, 0, 0.2]]), np.array([0.4]), np.array([0.2]))
    assert V.shape == (8, 3) and Q.shape == (5, 4)
    assert V[:, 0].min() == pytest.approx(-0.2) and V[:, 0].max() == pytest.approx(10.2)
    assert V[:, 1].max() - V[:, 1].min() == pytest.approx(0.4)
    assert V[:, 2].min() == pytest.approx(0.0) and V[:, 2].max() == pytest.approx(0.2)


def _look(pos, at, hfov, size):
    """A test camera (pos_mm, rot, hfov_deg, image_px) looking from pos at at, built by hand."""
    f = np.asarray(at, float) - pos
    back = -f / np.linalg.norm(f)
    right = np.cross(f, (0, 0, 1.0))
    right /= np.linalg.norm(right)
    up = np.cross(back, right)
    return {"pos_mm": list(pos), "rot": np.c_[right, up, back].tolist(), "hfov_deg": hfov, "image_px": list(size)}


def _pinhole(cam, pts):
    w, h = cam["image_px"]
    f = w / 2 / math.tan(math.radians(cam["hfov_deg"]) / 2)
    R = np.asarray(cam["rot"])
    p = (np.asarray(pts, float) - cam["pos_mm"]) @ R  # camera axes: right, up, back
    return np.c_[w / 2 + f * p[:, 0] / -p[:, 2], h / 2 - f * p[:, 1] / -p[:, 2]]


BED = (260.0, 260.0)
CORNERS = [(0, 0, 0), (BED[0], 0, 0), (BED[0], BED[1], 0), (0, BED[1], 0)]


@pytest.mark.parametrize("pos,at,hfov", [((-10, -20, 70), (150, 170, 10), 80), ((130, -150, 250), (130, 130, 0), 60)])
def test_camera_fit_reprojects_the_bed_corners_within_3_px(pos, at, hfov):
    """(c) A camera fit to four clicked corners (half a pixel off each) puts them back within 3 px."""
    size = (1280, 960)
    true = _look(pos, at, hfov, size)
    px = _pinhole(true, CORNERS) + np.random.default_rng(1).uniform(-0.5, 0.5, (4, 2))
    cam = timelapse.fit_camera(px, size, BED)
    assert max(cam["fit_error_px"]) < 3.0
    assert np.abs(timelapse.project(cam, CORNERS) - px).max() < 3.0
    assert cam["hfov_deg"] == pytest.approx(hfov, abs=3)
    assert np.linalg.norm(np.subtract(cam["pos_mm"], pos)) < 0.05 * np.linalg.norm(np.subtract(at, pos))


def test_bed_corners_parse():
    assert timelapse.parse_corners("1,2 3,4 5,6 7,8") == [(1, 2), (3, 4), (5, 6), (7, 8)]
    with pytest.raises(ValueError):
        timelapse.parse_corners("1,2 3,4")


needs_blender = pytest.mark.skipif(not timelapse.blender() or not shutil.which("ffmpeg"), reason="no Blender or ffmpeg")


@needs_blender
def test_blender_sees_the_bed_where_the_camera_math_puts_it(tmp_path):
    """The rendered bed (a 4 mm slab) fills the outline of its projected corners: Blender's camera
    and timelapse.project agree, so a fitted pose renders as fitted."""
    import cv2
    from PIL import Image

    size = (640, 480)
    cam = _look((-10, -20, 70), (150, 170, 10), 80, size)
    np.savez(tmp_path / "scene.npz", V=np.zeros((0, 3), np.float32), Q=np.zeros((0, 4), np.int32), lv=[0], lq=[0],
             bed=np.array(BED), rgb=np.array([255, 255, 255.0]))
    cfg = {"camera": cam, "size": list(size), "aa": "OFF", "bed_rgb": [255, 255, 255], "background_rgb": [0, 0, 0],
           "frames": [{"full": 0, "part": None, "head": None, "extras": None}]}
    (tmp_path / "frames.json").write_text(json.dumps(cfg))
    script = Path(timelapse.__file__).with_name("timelapse_blender.py")
    run = subprocess.run([timelapse.blender(), "-b", "--factory-startup", "--python", str(script), "--",
                          str(tmp_path / "scene.npz"), str(tmp_path / "frames.json"), str(tmp_path)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-500:]
    seen = np.asarray(Image.open(tmp_path / "f_0000.png").convert("L")) > 8
    slab = [(x, y, z) for z in (0.0, -4.0) for x, y, _ in CORNERS]
    hull = cv2.convexHull(timelapse.project(cam, slab).astype(np.float32)).astype(np.int32)
    want = np.zeros(seen.shape, np.uint8)
    cv2.fillPoly(want, [hull], 1)
    want = want.astype(bool)
    off = (seen ^ want).sum() / cv2.arcLength(hull, True)  # mismatched pixels per pixel of outline
    assert off < 1.5, off


@needs_blender
def test_stone_timelapse_on_a_part_writes_video_sheet_and_frames(jobenv, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    stl = tmp_path / "t.stl"
    _union(_box((6, 6, 4), (12, 0, 0)), _box((30, 6, 1), (0, 0, 4))).export(stl)
    text, code = cli.run(["timelapse", str(stl)])
    assert code == 0, text
    assert "Toolpaths: generated by stone" in text and "supports on" in text
    assert text.strip().splitlines()[-1].startswith("NEXT: ")
    data = json.loads((tmp_path / "timelapse.json").read_text())
    assert data["layers"] == 25 and len(data["frames"]) == 25
    assert [f["z_mm"] for f in data["frames"]] == [round(0.2 * (i + 1), 4) for i in range(25)]
    assert all((tmp_path / f["frame"]).is_file() for f in data["frames"])
    assert (tmp_path / "timelapse.mp4").stat().st_size > 1000 and (tmp_path / "timelapse_sheet.png").stat().st_size > 1000
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt",
                            "-of", "csv=p=0", str(tmp_path / "timelapse.mp4")], capture_output=True, text=True)
    assert probe.stdout.strip() == "h264,yuv420p"


@needs_blender
def test_extras_draw_extra_geometry_into_frames(tmp_path):
    """Injected per-frame geometry (Track P's failure view) shows up only in the frames that carry it."""
    from PIL import Image

    tp = gcode.load(FIX / "creality_washer.gcode.gz")
    frs = timelapse.frames(tp, "per-layer")[:2]
    prof = timelapse.builtin_k2()
    cam = {**prof["camera"], "timelapse_mode": "head-parked"}  # no toolhead in the way
    blob = trimesh.creation.icosphere(radius=25).apply_translation((130, 130, 30))

    def extras(k, fr):  # a red blob and a drooping strand, in the second frame only
        strand = {"polyline": [(100, 100, 5), (98, 100, 3), (97, 100, 0.5)], "width": 0.5, "rgb": (230, 30, 30)}
        return [{"mesh": (blob.vertices, blob.faces), "rgb": (230, 30, 30)}, strand] if k == 1 else []

    files = timelapse.render(tp, frs, prof, cam, tmp_path, extras=extras)
    red = [((a[..., 0] > 120) & (a[..., 1] < 60)).sum() for a in (np.asarray(Image.open(f).convert("RGB"), int) for f in files)]
    assert red[0] < 50 and red[1] > 2000, red
