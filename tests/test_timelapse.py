"""stone timelapse (timelapse.py, timelapse_blender.py): frames, ribbons, the camera fit, the Blender
render, injected geometry and the command."""

import gzip
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, gcode, timelapse

from test_gcode import _layer_zs
from test_slicer import _box, _union

FIX = Path(__file__).parent / "fixtures" / "gcode"
GCODES = sorted(FIX.glob("*.gcode.gz"))


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


def test_without_blender_the_print_time_still_comes_out(jobenv, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(timelapse, "blender", lambda: None)
    stl = tmp_path / "box.stl"
    _box((20, 20, 2), (0, 0, 0)).export(stl)
    text, code = cli.run(["timelapse", str(stl)])
    assert code == 1 and "Print time: " in text and "FIX: no video: Blender not found" in text, text
    assert not (tmp_path / "timelapse.mp4").exists()


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
