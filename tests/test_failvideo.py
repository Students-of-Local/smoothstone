"""stone timelapse --fail (failvideo.py): which failure is shown, what the physics does after it, and
the video's frames up to it being the normal timelapse's."""

import json

import numpy as np
import pytest

from smoothstone import cli, failsim, failvideo, printers, timelapse, toolpaths

from test_slicer import _box, _union
from test_supports import _arch
from test_timelapse import needs_blender


def _t():
    return _union(_box((6, 6, 4), (12, 0, 0)), _box((30, 6, 1), (0, 0, 4)))


def _toolpath(mesh):
    prof = printers.get("creality_k2")
    lo, hi = mesh.bounds
    bx, by = prof["build_volume_mm"][:2]
    return toolpaths.generate(mesh, toolpaths.profile(prof), 0.2, None, (bx / 2 - (lo[0] + hi[0]) / 2, by / 2 - (lo[1] + hi[1]) / 2))


def _story(mesh, mode="auto", clean=1.0):
    tp = _toolpath(mesh)
    inp = failvideo.inputs(tp, "PLA", clean)
    fail, what_if = failvideo.choose(failsim.predict(inp), mode, inp)
    return tp, inp, fail, what_if


def test_auto_picks_supports_for_a_t_with_supports_off_and_none_for_a_cube():
    tp, inp, fail, what_if = _story(_t())
    assert fail.kind == "supports" and not what_if
    assert fail.layer == 20 and fail.z == pytest.approx(4.2)  # the bar's first layer, over air
    _, _, none, _ = _story(_box((20, 20, 20), (0, 0, 0)))
    assert none is None


def test_a_forced_mode_is_a_what_if_and_needs_its_feature():
    tp, inp, fail, what_if = _story(_box((20, 20, 20), (0, 0, 0)), "detach")
    assert fail.kind == "detach" and what_if and "what-if" in fail.assumptions[-1]
    assert failvideo.choose(failsim.predict(inp), "bridge", inp) == (None, True)  # a cube has no bridge to sag


def test_spaghetti_falls_from_the_layer_and_rests_on_what_is_below():
    tp, inp, fail, _ = _story(_t())
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    z = float(inp.layer_z[fail.layer])
    fell = [a for i, a, b, w in st.links if i == fail.layer][0]
    assert fell[:, 2].min() >= 0 and fell[:, 2].max() <= z + 0.5  # at most resting on the layer just printed
    assert np.median(fell[:, 2]) < 1.0  # the arms' lines lie on the bed, 4 mm below where they were laid
    assert st.gone.any() and not st.gone[tp.layer < fail.layer].any()  # the scene up to the failure is untouched
    assert [f["layer"] for f in frs[:first]] == list(range(fail.layer))
    lines = [sum(len(it["mesh"][0]) for it in e) for e in extra[first:]]
    falling = [n for n, f in zip(lines, frs[first:]) if f["layer"] == fail.layer]
    assert len(falling) > 3 and falling == sorted(falling) and falling[0] < falling[-1] / 3  # laid bit by bit, not there at once
    ts = [f["t_s"] for f in frs]
    assert ts == sorted(ts) and [f["layer"] for f in frs] == sorted(f["layer"] for f in frs)


def test_a_long_bridge_sags_by_the_catenary():
    tp, inp, fail, _ = _story(_arch(22.5), "bridge")
    assert fail.kind == "bridge"
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    span = fail.numbers["span_mm"]
    low = min(float(b[2].min()) for b in st.bent)
    assert low == pytest.approx(float(failsim.bridge_sag(span, [span / 2])[0]), rel=0.02)
    assert low < -0.2  # past the usable length it sags more than a layer
    by_layer = {i: min(float(b[2].min()) for b in st.bent if b[0] == i) for i in {b[0] for b in st.bent}}
    assert fail.layer + 1 in by_layer and by_layer[fail.layer + 1] == pytest.approx(low)  # the layer above lies on it
    mesh = st.items(fail.layer, 0.0, None)[0]["mesh"][0]
    z = float(inp.layer_z[fail.layer])
    assert mesh[:, 2].max() == pytest.approx(z, abs=0.1)  # its held ends stay where they were printed
    assert mesh[:, 2].min() == pytest.approx(z - float(tp.height[tp.layer == fail.layer].max()) + low, abs=0.1)


def test_what_holds_is_not_drawn_failing():
    """A T whose stem has a 6 mm tunnel through it, its roof a short bridge in the layers where the arms fall."""
    stem = _union(_box((6, 20, 4), (12, 0, 0)), _box((2, 20, 2), (12, 0, 4)), _box((2, 20, 2), (16 + 4, 0, 4)), _box((2, 20, 2), (16, 0, 4)))
    part = _union(stem, _box((8, 20, 4), (12, 0, 0)), _box((10, 20, 1), (12, 0, 6)), _box((30, 4, 1), (0, 0, 6)))
    tp, inp, fail, _ = _story(part)
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    r, c = np.nonzero(np.asarray(inp.masks[0], bool))
    x0, x1 = inp.origin[0] + c.min() * inp.cell, inp.origin[0] + (c.max() + 1) * inp.cell
    y0, y1 = inp.origin[1] + r.min() * inp.cell, inp.origin[1] + (r.max() + 1) * inp.cell
    roof = st.ext & (tp.layer == fail.layer) & (np.minimum(tp.p0[:, 0], tp.p1[:, 0]) > x0) & (np.maximum(tp.p0[:, 0], tp.p1[:, 0]) < x1)
    roof &= np.minimum(tp.p0[:, 1], tp.p1[:, 1]) > y0 + 6
    assert fail.kind == "supports" and roof.any() and not st.gone[roof].any() and st.gone.any()
    tp, inp, fail, _ = _story(_arch(22.5), "bridge")  # and a bridge the rules let pass is nothing to show
    assert failvideo._first(_story(_arch(8))[1], "bridge") is None


def test_a_strand_has_no_gaps_at_any_slope():
    a = np.array([[0, 0, 5.0], [0, 0, 4], [0, 0, 3], [0.5, 0, 2.1], [1.4, 0, 1.6]])
    V, Q = failvideo.tubes(a[:-1], a[1:], np.full(4, 0.3), np.full(4, 0.3))
    boxes = V.reshape(4, 8, 3)
    for k, (p, q) in enumerate(zip(a, a[1:])):
        assert all(np.linalg.norm(boxes[k] - end, axis=1).min() <= 0.27 for end in (p, q))  # it reaches both its ends
        size = np.ptp(boxes[k] @ np.linalg.svd(boxes[k] - boxes[k].mean(0))[2].T, axis=0)
        assert sorted(size) == pytest.approx([0.3, 0.3, np.linalg.norm(q - p) + 0.3], abs=1e-3)  # a whole box
    assert Q.max() == 31


def test_a_strand_with_corners_stays_pinned_where_it_lies_on_plastic():
    tp, inp, fail, _ = _story(_box((20, 20, 3), (0, 0, 0)))
    st = failvideo.Story(tp, inp, fail or failsim.Failure("supports", 5, 1.2, 1.0, "spaghetti", None, {}, []), (255, 255, 255), (260, 260))
    st.layer_now = 5
    st.field[:] = 0.0
    moves = np.flatnonzero(st.ext & (tp.layer == 5))  # walls and infill, full of corners
    xs = inp.origin[0] + (np.arange(st.field.shape[1]) + 0.5) * inp.cell
    loose = np.broadcast_to(xs > np.median(tp.p1[moves, 0]), st.field.shape)
    st.strand(moves, loose)
    _, a, b, w = st.links[-1]
    r, c = st.px(a)
    far = np.abs(a[:, 0] - np.median(tp.p1[moves, 0])) > 2
    assert a[far & ~loose[r, c], 2] == pytest.approx(inp.layer_z[5], abs=1e-6) and a[far & loose[r, c], 2].max() < 1.0


def test_a_tall_part_tips_about_its_edge():
    tp, inp, fail, _ = _story(_box((20, 20, 8), (0, 0, 0)))
    fail = failsim.Failure("topple", 30, 6.2, 60.0, "bed_adhesion", (130, 130), {"direction": [1.0, 0.0]}, ["x"])
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    V = st.part[0] @ st.mats[-1][:3, :3].T + st.mats[-1][:3, 3]
    assert V[:, 2].min() > -0.5 and np.ptp(V[:, 2]) == pytest.approx(20, abs=1)  # on its side, on the plate
    assert V[:, 0].min() > st.part[0][:, 0].max() - 0.7  # past the edge it turned about


def test_a_ledge_droops_then_curls():
    tp, inp, fail, _ = _story(_union(_box((20, 20, 2), (0, 0, 0)), _box((21.5, 20, 2), (0, 0, 2))))
    assert fail.kind == "droop"
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    low = min(float(b[2].min()) for b in st.bent)
    assert low == pytest.approx(-fail.numbers["droop_mm"], rel=0.35)  # the outermost line is half a line in from the edge
    ends = [float(b[2].min()) for b in st.bent if b[0] == fail.layer + 1]
    assert ends and min(ends) == pytest.approx(low, abs=0.05)  # the next layer lies on it
    x = max(float(b[1][:, 0].max()) for b in st.bent)
    tops = [max(v[2] for v in st.items(i, 0.0, None)[0]["mesh"][0] if v[0] > x - 0.3) for i in (fail.layer, fail.layer + 6)]
    assert tops[1] - tops[0] > 6 * inp.layer + 0.004  # and as layers go on, curl lifts the edge


def test_a_late_failure_gets_its_share_and_a_slide_stays_on_the_plate():
    tp, inp, fail, _ = _story(_box((20, 20, 20), (0, 0, 0)), "detach")
    _, frs, _, first, _ = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    assert first == failvideo.LEAD and [f["layer"] for f in frs[:first]][-1] == fail.layer - 1 and len(frs) - first > first / 2
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (142, 142))[4]
    V = st.part[0] + st.mats[-1][:3, 3]
    assert V[:, :2].max() < 142.5 and V[:, :2].min() > -0.5
    assert st.strand(np.zeros(0, int), None) == []  # a layer with nothing to lay


def test_a_dirty_plate_lets_go_slides_and_grows_a_blob():
    tp, inp, fail, what_if = _story(_box((30, 20, 1), (0, 0, 0)), clean=failsim.fact("contamination"))
    assert fail.kind == "detach" and fail.layer == 0 and not what_if
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    assert np.linalg.norm(st.mats[-1][:3, 3]) > 10  # it moved
    assert all(i > 0 for i, *_ in st.links)  # every later layer printed into air
    blobs = [np.ptp(it["mesh"][0][:, 0]) for e in extra[first:] for it in e if it.get("name") == "blob"]
    assert len(blobs) >= len(extra) - first - 1 and blobs[-1] > blobs[0] and blobs == sorted(blobs)
    want = 2 * (3 * float(failsim.blob_volume(st.flow, frs[-1]["t_s"] - fail.time)) / 4 / np.pi) ** (1 / 3)
    assert blobs[-1] == pytest.approx(want, rel=0.05)  # the ball holds what stuck to the nozzle since it let go


def test_no_failure_says_so_and_makes_no_video(jobenv, tmp_path):
    stl = tmp_path / "cube.stl"
    _box((20, 20, 20), (0, 0, 0)).export(stl)
    text, code = cli.run(["timelapse", str(stl), "--fail"])
    assert code == 0 and "No failure predicted; nothing to show. --fail detach shows a loose part anyway." in text
    assert "model, not a recording" in text and not (tmp_path / "cube.stl-timelapse").exists()
    again, code = cli.run(["timelapse", "--fail", str(stl)])  # the file after --fail is the part, not a mode
    assert code == 0 and "No failure predicted" in again, again
    text, code = cli.run(["timelapse", str(stl), "--fail", "bridge"])
    assert "Nothing here fails by bridge" in text and text.strip().endswith("NEXT: none, nothing to show"), text
    assert "Material: PLA is assumed" in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "--material", "wood"])
    assert code == 1 and "--material wood: the model has PLA, PETG, ABS" in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "melt"])
    assert code == 1 and "FIX: --fail melt: one of auto" in text, text
    assert text.strip().splitlines()[-1] == f"NEXT: stone timelapse {stl} --fail auto", text
    text, code = cli.run(["timelapse", str(stl), "--fail", "detach", "--mode", "realtime", "--plate", "dirty"])
    assert code == 1 and "drop --mode" in text and f"NEXT: stone timelapse {stl} --fail detach --plate dirty" in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "--gcode", str(tmp_path / "x.gcode")])  # the normal command's checks
    assert code == 1 and "drop the file" in text, text


def test_without_blender_the_prediction_still_comes_out(jobenv, tmp_path, monkeypatch):
    monkeypatch.setattr(timelapse, "blender", lambda: None)
    stl = tmp_path / "t.stl"
    _t().export(stl)
    text, code = cli.run(["timelapse", str(stl), "--fail", "--supports", "off"])
    assert code == 1 and "Predicted: supports at layer 21" in text and "FIX: no video: Blender not found" in text, text
    assert "NEXT: ask the person: the model says this print fails (supports); print it with supports, or" in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "supports"])  # this print has supports: not predicted
    assert "What-if (drawn without supports, which this print has): supports at layer 21" in text and "Predicted" not in text, text
    assert "the what-if is above" in text.strip().splitlines()[-1], text


@needs_blender
def test_the_frame_before_the_failure_is_the_timelapse_frame(jobenv, tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    stl = tmp_path / "t.stl"
    _t().export(stl)
    d = tmp_path / "t.stl-timelapse"
    text, code = cli.run(["timelapse", str(stl), "--supports", "off", "--fail"])
    assert code == 0, text
    assert "model, not a recording" in text and "Main assumption: " in text and "Predicted: supports at layer 21" in text
    data = json.loads((d / "fail.json").read_text())
    for k in ("layer", "time_s", "what", "numbers", "assumptions", "dominant_assumption", "taxonomy", "z_mm"):
        assert data[k] not in (None, [], {}), k
    assert data["model_not_recording"] and data["kind"] == "supports" and data["layer"] == 20
    assert "droop_mm" in data["numbers"] and data["taxonomy"] == "spaghetti"
    assert (d / "fail.mp4").stat().st_size > 1000 and (d / "fail_sheet.png").stat().st_size > 1000
    text, code = cli.run(["timelapse", str(stl), "--supports", "off"])
    assert code == 0, text
    normal = json.loads((d / "timelapse.json").read_text())
    want = [f["frame"] for f in normal["frames"] if f["layer"] == data["layer"] - 1][0]
    a = np.asarray(Image.open(d / data["pre_failure_frame"]).convert("RGB"), float)
    b = np.asarray(Image.open(d / want).convert("RGB"), float)
    assert np.abs(a - b).mean() < 0.5 and (np.abs(a - b).max(2) > 16).mean() < 0.001
    light = [(np.asarray(Image.open(d / f["frame"]).convert("L"))[:320] > 120).mean() for f in data["frames"] if f["failing"]]
    assert min(light) > 0.005 and light[-1] > 0.03  # the failure fills the close frames: no toolhead box hides it
    c = np.asarray(Image.open(d / data["first_failure_frame"]).convert("RGB"), float)
    assert np.abs(c - b).mean() > 0.5  # and the failure itself is not
