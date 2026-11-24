"""stone timelapse --fail (failvideo.py): which failure is shown, what the physics does after it, and
the video's frames up to it being the normal timelapse's."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from smoothstone import cli, failsim, failvideo, gcode, printers, timelapse, toolpaths

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


def test_infill_is_not_read_as_bare_faces():
    """A big infilled plate on the toolpath and on its mesh: one prediction, the same margin. A bore stays a bore."""
    import trimesh

    box = _box((60, 60, 4), (0, 0, 0))
    tp = _toolpath(box)
    inp = failvideo.inputs(tp)
    got, mesh = failsim.predict(inp)[0], failsim.predict(failsim.inputs_from_mesh(box))[0]
    assert got.kind == mesh.kind
    assert got.numbers["margin"] == pytest.approx(mesh.numbers["margin"], rel=0.1)
    ring = trimesh.creation.annulus(4, 12, 4)
    tp = _toolpath(ring)
    inp = failvideo.inputs(tp)
    mid = inp.masks[len(inp.masks) // 2]
    bore = np.array([130.0, 130.0]) - inp.origin
    assert not mid[int(bore[1] / inp.cell), int(bore[0] / inp.cell)]
    assert mid.sum() * inp.cell ** 2 == pytest.approx(np.pi * (144 - 16), rel=0.05)  # the infill's gaps are part of it


def test_the_layer_height_is_not_the_first_layers():
    tp = _toolpath(_box((10, 10, 3), (0, 0, 0)))
    z = np.r_[0.2, 0.2 + 0.12 * np.arange(1, len(tp.layer_z))]
    assert failvideo.inputs(replace(tp, layer_z=z)).layer == pytest.approx(0.12)
    assert failvideo.inputs(replace(tp, layer_z=z), enclosed=False).enclosed is False


def test_the_nozzle_stays_at_the_layer_while_the_strand_falls():
    tp, inp, fail, _ = _story(_t())
    _, frs, _, first, _ = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    heads = [f["head"][2] for f in frs[first:] if f["layer"] == fail.layer]
    assert heads == pytest.approx([float(inp.layer_z[fail.layer])] * len(heads), abs=1e-6)


def test_spaghetti_falls_from_the_layer_and_rests_on_what_is_below():
    tp, inp, fail, _ = _story(_t())
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    z = float(inp.layer_z[fail.layer])
    fell, wide = (np.concatenate([k[j] for k in st.links if k[0] == fail.layer]) for j in (1, 3))
    assert (fell[:, 2] - wide / 2).min() >= -0.03 and fell[:, 2].max() <= z + 2  # resting on the plate by its own radius, drawn thin or not, or a slack loop a little over the layer
    assert (fell[:, 2] < 1.0).mean() > 0.4 and np.median(fell[:, 2]) < z / 2  # most of the arms' plastic lies on or near the bed
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
    """Two posts, a roof over the 8 mm between them, and the roof's arm 14 mm out over nothing, all in one layer."""
    part = _union(_box((6, 20, 4), (0, 0, 0)), _box((6, 20, 4), (14, 0, 0)), _box((34, 20, 1), (0, 0, 4)))
    tp, inp, fail, _ = _story(part)
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    x0 = inp.origin[0] + np.nonzero(np.asarray(inp.masks[0], bool))[1].min() * inp.cell
    x = np.c_[tp.p0[:, 0], tp.p1[:, 0]] - x0
    here = st.ext & (tp.layer == fail.layer)
    roof, arm = here & (x.max(1) < 19) & (x.max(1) > 8) & (x.min(1) < 13), here & (x.min(1) > 22)
    assert fail.kind == "supports" and roof.any() and arm.any()
    assert not st.gone[roof].any() and st.gone[arm].all()
    assert failvideo._first(_story(_arch(8))[1], "bridge") is None  # and a bridge the rules let pass is nothing to show


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
    run = st.runs(5, st.ext)[0]  # walls and infill, full of corners
    mid = np.median(tp.p1[run, 0])
    xs = inp.origin[0] + (np.arange(st.field.shape[1]) + 0.5) * inp.cell
    loose = np.broadcast_to(xs > mid, st.field.shape)
    st.strand(5, run, loose, 60.0)
    a = np.vstack([x[1] for x in st.links])
    r, c = st.px(a)
    far = np.abs(a[:, 0] - mid) > 2
    on = a[far & ~loose[r, c], 2]
    assert np.median(on) == pytest.approx(inp.layer_z[5] - 0.24, abs=0.01)  # where it was laid, half its thickness down
    assert np.median(a[far & loose[r, c], 2]) < 0.7 and st.left == 0
    layer = sum(float((np.pi / 4 * w ** 2 * np.linalg.norm(q - p, axis=1)).sum()) for _, p, q, w in st.links)
    laid = float((st.flows[run] * (tp.t1 - tp.t0)[run]).sum())
    assert layer == pytest.approx(laid, rel=0.02)  # all the plastic the print lays, no more


def test_a_tall_part_tips_about_its_edge():
    tp, inp, fail, _ = _story(_box((20, 20, 8), (0, 0, 0)))
    fail = failsim.Failure("topple", 30, 6.2, 60.0, "bed_adhesion", (130, 130), {"direction": [1.0, 0.0]}, ["x"])
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    V = st.part[0] @ st.mats[-1][:3, :3].T + st.mats[-1][:3, 3]
    assert V[:, 2].min() > -0.5 and np.ptp(V[:, 2]) == pytest.approx(20, abs=1)  # on its side, on the plate
    assert V[:, 0].min() > st.part[0][:, 0].max() - 0.7  # past the edge it turned about


def test_a_ledge_droops_then_curls():
    tp, inp, fail, _ = _story(_union(_box((20, 20, 2), (0, 0, 0)), _box((23, 20, 2), (0, 0, 2))))
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
    assert st.runs(10 ** 6, st.ext) == []  # a layer with nothing to lay


def test_a_dirty_plate_lets_go_slides_and_grows_a_blob():
    tp, inp, fail, what_if = _story(_box((30, 20, 1), (0, 0, 0)), clean=failsim.fact("contamination"))
    assert fail.kind == "detach" and fail.layer == 0 and not what_if
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))
    assert np.linalg.norm(st.mats[-1][:3, 3]) > 10  # it moved
    assert all(i > 0 for i, *_ in st.links)  # every later layer printed into air
    blobs = [np.ptp(it["mesh"][0][:, 0]) for e in extra[first:] for it in e if it.get("name") == "blob"]
    assert len(blobs) >= len(extra) - first - 1 and blobs == sorted(blobs)
    ball = lambda v: 2 * (3 * v / 4 / np.pi) ** (1 / 3)  # noqa: E731
    assert blobs[-1] == pytest.approx(ball(st.blob), rel=0.05)
    assert st.blob > 1.5 * st.hold  # so low, the pile reaches the nozzle and what comes out stays on it


def test_high_up_the_nozzle_carries_only_what_its_tip_holds_and_drags_the_strand():
    tp, inp, fail, _ = _story(_box((20, 20, 12), (0, 0, 0)), "detach")
    st = failvideo.plan(tp, inp, fail, (255, 255, 255), (260, 260))[4]
    i = fail.layer + 1
    assert st.blobs[i] == pytest.approx(failsim.nozzle_hold("PLA")["blob_mm3"], rel=0.02)
    p, d = st.live[i]  # the strand still hangs from the nozzle when the layer ends
    end = tp.p1[np.flatnonzero(tp.layer == i)[-1], :3]
    assert p[-1] == pytest.approx(end, abs=2.0) and p[:, 2].min() < 1.0 < p[-1, 2]
    laid = sum(float((np.pi / 4 * w ** 2 * np.linalg.norm(q - a, axis=1)).sum()) for k, a, q, w in st.links if k == i)
    assert laid + float((np.pi / 4 * d ** 2 * np.linalg.norm(np.diff(p, axis=0), axis=1)).sum()) == pytest.approx(
        float((st.flows * (tp.t1 - tp.t0))[tp.layer == i].sum()) - st.hold + st.flow * len(st.mats) / 30, rel=0.02)


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
    assert code == 1 and "--material wood: the model has no numbers for it; it has PLA, PETG, ABS" in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "--material", "nylon"])
    assert "Material: PA, for NYLON." in text and "A corner lifting is not judged: edge pull about" in text, text
    assert "No other failure predicted" in text and "Nylon is Polymaker's CoPA" in text, text
    assert "no other failure predicted, corners not judged" in text and "NEXT: none, no other failure predicted" in text, text
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
    text, code = cli.run(["timelapse", str(stl), "--fail", "--supports", "off", "--material", "PC"])  # said whatever else fails
    assert "A corner lifting is not judged: edge pull about" in text and "droops" in text, text
    hook = tmp_path / "hook.stl"
    _union(_box((10, 10, 12), (0, 0, 0)), _box((20, 4, 2), (12, 0, 10)), _box((4, 4, 5), (20, 0, 5))).export(hook)
    text, code = cli.run(["timelapse", str(hook), "--fail", "--supports", "off", "--material", "PC"])
    assert "Predicted: supports" in text and "Why: a piece starts in mid air." in text, text
    text, code = cli.run(["timelapse", str(stl), "--fail", "detach", "--material", "PC"])
    assert "What-if (you asked for it, the model cannot judge a corner lifting for this plastic): detach" in text, text
    assert "Why: edge pull about" in text and f"Main assumption: {failsim.note('no_peel')}" in text, text


def test_the_video_says_what_it_does_not_simulate(jobenv, tmp_path, monkeypatch):
    from PIL import Image

    def render(scene, frs, prof, cam, d, *a, **k):
        d.mkdir(parents=True, exist_ok=True)
        files = [d / f"{i}.png" for i in range(len(frs))]
        [Image.new("RGB", (64, 48)).save(f) for f in files]
        return files

    monkeypatch.setattr(timelapse, "missing", lambda: None)
    monkeypatch.setattr(timelapse, "render", render)
    monkeypatch.setattr(timelapse, "video", lambda *a: 1.0)
    monkeypatch.setattr(failvideo, "AFTER", 1)
    stl = tmp_path / "p.stl"
    _box((30, 20, 0.6), (0, 0, 0)).export(stl)
    text, _ = cli.run(["timelapse", str(stl), "--fail", "--plate", "dirty"])
    assert "Limit:" not in text and "Strand: 0.48 mm thick, it leaves the nozzle at" in text and "The nozzle's tip carries 8.0 mm3." in text, text
    monkeypatch.setattr(failvideo, "SIM", 1.0)
    text, _ = cli.run(["timelapse", str(stl), "--fail", "--plate", "dirty"])
    assert f" {failvideo.LIMIT} 1 s of it, the start of each layer." in text, text
    data = json.loads((tmp_path / "p.stl-timelapse" / "fail.json").read_text())
    assert data["strand"]["draw_mn"] > 0 and any("die swell" in a or "as wide as the bore" in a for a in data["assumptions"])


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


def test_the_model_runs_at_the_prints_own_settings(jobenv, tmp_path):
    tp = gcode.parse(file := Path(__file__).parent / "fixtures" / "gcode" / "prusa_screw.gcode.gz")
    gcode.plan(tp)
    inp = failvideo.inputs(tp, "PLA", enclosed=False)
    assert (inp.bed, inp.material.nozzle, inp.infill, inp.fan) == (60, 200, 5, 1)
    assert inp.speed and inp.width and "bed 60 C, nozzle 200 C" in inp.notes[0]
    assert not any("chamber" in n for n in inp.notes)  # an open printer has none
    base = failsim.predict(inp)[0].assumptions
    assert base[0].startswith("this is a model, not a recording; PLA (60 C bed, 200 C nozzle, open printer")
    tp.run[tp.layer < 3, 0] = np.nan
    assert failvideo.inputs(tp, "PLA").fan == 1  # the file says it from layer 4 on
    other = tmp_path / "other.gcode"
    for said, more, line, own in (("PLA", (), "Material: PLA, the G-code says.", True), ("HIPS", (), "no numbers for HIPS, so this is PLA's", False),
                                  ("HIPS", ("--material", "ABS"), "Material: ABS.", True), ("PLA", ("--material", "ABS"), "Material: ABS.", False), ("ASA+", (), "ASA melts, sticks and holds heat as ABS does", True),
                                  (None, (), "PLA is assumed", False)):  # another plastic's heat is not this one's
        other.write_text(gcode.read(file).replace("; filament_type = PLA", f"; filament_type = {said}" if said else ";"))
        text, code = cli.run(["timelapse", "--gcode", str(other), "--fail", "bridge", *more])
        assert line in text and ("bed 60 C" in text) is own and ("not the print's own: bed, nozzle" in text) is not own, text
    unsaid = failsim.note("k2_air")  # PETG-CF's profile names no chamber
    for enclosed, chamber, said in ((True, np.nan, True), (True, 45, False), (False, np.nan, False)):
        tp.run[:, 3] = chamber
        inp = failvideo.inputs(tp, "PETG-CF", enclosed=enclosed)
        assert (unsaid in failsim.predict(inp)[0].assumptions) is (unsaid in inp.notes) is said
        assert not any("not the print's own" in n and "chamber" in n for n in inp.notes)
    tp.run[:, [0, 3]] = 0.4, 45
    inp = failvideo.inputs(tp, "PLA")
    assert (inp.fan, inp.air) == (0.4, 45) and failvideo.inputs(tp, "PLA", enclosed=False).air == failsim.fact("room_air")
    tp.run[:] = np.nan
    inp = failvideo.inputs(tp, "PLA")
    assert inp.bed is None and inp.fan == 1 and inp.material.nozzle == failsim.material("PLA").nozzle
    assert "K2 profile's, not the print's own: bed, nozzle, fan, chamber (fan 100%)" in inp.notes[1]
    mini = failvideo.inputs(tp, "ABS", enclosed=False, prof=printers.get("prusa_mini"))
    assert (mini.material.bed, mini.material.nozzle, mini.air) == (100, 260, failsim.fact("room_air"))
    assert "MINI+ profile's, not the print's own: bed, nozzle, fan (fan" in mini.notes[1] and "reaches 100 C" in mini.notes[2]
    ender = failvideo.inputs(tp, "PLA", enclosed=False, prof=printers.get("creality_ender3_v3"))
    assert not any("open frame" in n or "chamber" in n for n in ender.notes)
    assert mini.process["shells"]["wall_loops"] == 3 and failsim.run(replace(mini, width=None, speed=None)) == (0.4, 50)
    secs = float(np.median(np.diff(failvideo.layer_times(tp), prepend=0.0)))
    assert mini.fan == printers.fan(printers.settings(printers.get("prusa_mini"), "ABS"), secs)


def test_strands_of_one_layer_lie_where_they_fell_while_the_next_one_comes(monkeypatch):
    tp, inp, fail, _ = _story(_t())  # two arms, so more than one strand in the failing layer
    st = failvideo.Story(tp, inp, fail, (255, 255, 255), (260, 260))
    motion = st.run(fail.layer)
    lie = [b for i, _, b, _ in st.links if i == fail.layer]
    settled = lambda p: any(len(b) == len(p) - 1 and np.array_equal(p[1:], b) for b in lie)  # noqa: E731
    assert len(lie) > 1 and all(settled(p) for pieces, _ in motion for p, _ in pieces[:-1])
    assert all(settled(p) for p, _ in motion[-1][0])  # the last one comes to rest in the motion too
    monkeypatch.setattr(failvideo, "SIM", 1e-6)  # nothing is followed: what has plastic under it is drawn as laid
    st = failvideo.Story(tp, inp, fail, (255, 255, 255), (260, 260))
    st.run(fail.layer)
    on = np.asarray(inp.masks[fail.layer - 1], bool)
    air = np.flatnonzero(st.flew)
    flat = np.vstack([b[1] for b in st.bent if b[0] == fail.layer])
    want = np.concatenate([st.line(j, 0.5)[on[st.px(st.line(j, 0.5))]] for j in air])
    assert len(flat) > 20 and np.mean([np.abs(flat - p).sum(1).min() < 1e-9 for p in want]) > 0.8  # all but single points
    assert not st.links and st.gone[air].all()


def test_a_short_run_lays_its_plastic_and_the_plate_past_the_grid_is_bare():
    tp, inp, _, _ = _story(_box((20, 20, 3), (0, 0, 0)))
    st = failvideo.Story(tp, inp, failsim.Failure("supports", 5, 1.2, 1.0, "spaghetti", None, {}, []), (255, 255, 255), (260, 260))
    run = st.runs(5, st.ext)[0][:1]
    tp.t1[run] = tp.t0[run] + 0.002  # under one step
    st.strand(5, run, np.ones(st.field.shape, bool), 60.0)
    assert st.links and st.left == 0
    vol = lambda: sum(float((np.pi / 4 * w ** 2 * np.linalg.norm(q - p, axis=1)).sum()) for _, p, q, w in st.links)  # noqa: E731
    due = float(st.flows[run] @ (tp.t1 - tp.t0)[run])
    assert vol() - st.owed == pytest.approx(due, rel=0.05)
    tp.p1[run] = tp.p0[run] + [0.4, 0, 0, 0]  # it starts on plastic and ends in air, within one step
    xs = inp.origin[0] + (np.arange(st.field.shape[1]) + 0.5) * inp.cell
    edge = tp.p0[run[0], 0] + 0.3
    st.links.clear()
    st.strand(5, run, np.broadcast_to(xs > edge, st.field.shape), 60.0)
    assert np.linalg.norm(st.links[0][1][0] - tp.p0[run[0], :3]) < 0.5 and len(st.links) == 1  # its first end stays where it was pressed on
    st.field[:] = 0
    st.pile(5, np.array([[-30.0, 0, 0.24], [-25.0, 0, 0.24]]), np.array([0.48]))
    assert not st.field.any()


def test_the_fans_share_is_the_winds():
    still, half, full = (failvideo.strand.numbers("PLA", 10.0, 120.0, fan=f)["set_s_fan"] for f in (0.0, 0.4, 1.0))
    assert still > half > full and failvideo.strand.Strand([(0, 0, 0), (0, 0, 1)], 0.48, "PLA", fan=0.4).fan == pytest.approx(0.4 * failsim.fact("fan_air_speed"))


def test_a_skirt_is_not_the_part_and_stays_when_it_goes():
    tp = gcode.parse(Path(__file__).parent / "fixtures" / "gcode" / "prusa_screw.gcode.gz")
    gcode.plan(tp)
    skirt = failvideo.moves_of(tp, "skirt")
    assert skirt.any()
    inp = failvideo.inputs(tp, "PLA", enclosed=False)
    r, c = np.nonzero(inp.masks[0])
    wide = (c.max() - c.min() + 1) * inp.cell
    assert 22 < wide < 26 and not inp.brim.any()  # the screw's head, 23.6 mm wide; the skirt round it is 31.4
    assert not any("brim" in n for n in inp.notes)
    fail, _ = failvideo.choose(failsim.predict(inp), "detach", inp)
    st = failvideo.Story(tp, inp, fail, (1, 1, 1), (250, 250))
    assert not (st.ext & skirt).any() and st.ext.any()
    st.loose(30.0)
    st.moved()
    at = tp.p1[skirt & (tp.layer == 0), :3]
    assert (st.field[st.px(at)] >= at[:, 2] - 1e-6).all()  # still there, for strands to land on
    ring, part = (x["mesh"][0] for x in st.items(st.L, 0.0, None)[::-1])
    assert np.ptp(ring[:, 0]) == pytest.approx(31.8, abs=0.5) and abs(ring[:, 0].mean() - at[:, 0].mean()) < 0.5
    tp.feature[(tp.layer > 0) & (tp.feature == timelapse.gcode.FEATURES.index("outer wall"))] = timelapse.gcode.FEATURES.index("support")
    again = failvideo.inputs(tp, "PLA", enclosed=False)  # supports carry the part, and go with it
    assert (again.masks[3] == inp.masks[3]).all() and again.supports


def test_a_brim_holds_against_sliding_and_goes_with_the_part():
    tp = _toolpath(_box((20, 20, 2), (0, 0, 0)))
    F = timelapse.gcode.FEATURES
    bare = failvideo.inputs(tp, "PLA")
    tp.feature[(tp.layer == 0) & np.isin(tp.feature, [F.index("outer wall"), F.index("inner wall")])] = F.index("skirt")
    inp = failvideo.inputs(tp, "PLA")
    total = int(bare.masks[0].sum())
    assert 0 < inp.brim.sum() and abs(int((inp.brim | inp.masks[0]).sum()) - total) < 0.05 * total
    assert inp.masks[0].sum() < total and any("brim" in n for n in inp.notes)
    hold = [failsim.predict(replace(i, drag=1e6, brim=b))[0].numbers["hold_n"] for i, b in ((inp, None), (inp, inp.brim))]
    grown = (inp.brim & ~inp.masks[0]).sum() * inp.cell ** 2 * failsim.fact("adhesion.shear")
    assert hold[1] - hold[0] == pytest.approx(grown, rel=1e-3)
    fail, _ = failvideo.choose(failsim.predict(inp), "detach", inp)
    st = failvideo.Story(tp, inp, fail, (1, 1, 1), (250, 250))
    assert (st.ext == (tp.extruding() & (tp.layer >= 0))).all()
    tip = failsim.Failure("topple", 5, 1.2, 10.0, "toppled", (100, 100), {"direction": [1.0, 0.0]})
    st = failvideo.Story(tp, inp, tip, (1, 1, 1), (250, 250))
    for T in st.loose(30.0):  # about the brim's edge: none of it goes through the plate
        assert (st.part[0] @ T[:3, :3].T + T[:3, 3])[:, 2].min() > -0.3


def test_strands_fall_on_the_part_where_it_slid_to():
    tp, inp, fail, _ = _story(_box((20, 20, 2), (0, 0, 0)), "detach")
    st = failvideo.Story(tp, inp, fail, (1, 1, 1), (250, 250))
    st.loose(30.0)
    st.moved()
    move = st.mats[-1][:2, 3]
    r, c = np.nonzero(inp.masks[0])
    mid = np.array([inp.origin[0] + (c.mean() + 0.5) * inp.cell, inp.origin[1] + (r.mean() + 0.5) * inp.cell])
    top = float(inp.layer_z[st.L])
    near = lambda at: st.field[st.px(np.c_[at + np.stack(np.meshgrid(*[np.linspace(-3, 3, 31)] * 2), -1).reshape(-1, 2), np.zeros(961)])]  # noqa: E731
    assert np.linalg.norm(move) > 15
    assert near(mid + move).max() == pytest.approx(top, abs=0.01)
    rim = st.field[st.px(np.c_[mid[0] + move[0] + np.linspace(-9.8, 9.8, 99), np.full(99, mid[1] + move[1] - 9.4), np.zeros(99)])]
    assert (rim > 0).all()  # its walls are as wide as their lines, not a row of threads
    assert near(mid).max() == 0  # it left that spot bare


def test_what_is_over_a_brim_is_not_in_the_air():
    tp = _toolpath(_box((20, 20, 2), (0, 0, 0)))
    bare, mid = failvideo.inputs(tp, "PLA"), float(tp.p1[tp.part(), 0].mean())
    tp.feature[tp.extruding() & (tp.layer == 0) & (np.maximum(tp.p0, tp.p1)[:, 0] > mid)] = timelapse.gcode.FEATURES.index("skirt")
    inp = failvideo.inputs(tp, "PLA")
    assert inp.masks[0].sum() < 0.7 * bare.masks[0].sum() and inp.brim.any()
    assert [f.kind for f in failsim.predict(replace(inp, brim=None))][0] == "supports"  # half of it hangs over nothing
    assert [f.kind for f in failsim.predict(inp)] == [f.kind for f in failsim.predict(bare)] == ["none"]
    assert failvideo._first(replace(inp, brim=None), "supports") and not failvideo._first(inp, "supports")
    st = failvideo.Story(tp, inp, failsim.Failure("supports", 1, 0.4, 1.0, "spaghetti", None, {}, []), (1, 1, 1), (250, 250))
    st.run(2)
    assert not st.flew.any() and not st.gone.any()


def test_a_prime_tower_is_there_for_strands_to_end_on():
    tp = _toolpath(_union(_t(), _box((8, 8, 8), (45, 0, 0))))
    bar = failvideo.inputs(_toolpath(_t()), "PLA")
    left = float(tp.p0[tp.part(), 0].min())
    at = tp.extruding() & (tp.p0[:, 0] > left + 40) & (tp.p1[:, 0] > left + 40)
    tp.feature[at] = timelapse.gcode.FEATURES.index("prime tower")
    inp = failvideo.inputs(tp, "PLA")
    fail, _ = failvideo.choose(failsim.predict(inp), "auto", inp)
    st = failvideo.Story(tp, inp, fail, (1, 1, 1), (250, 250))
    assert at.any() and not (st.ext & at).any() and fail.kind == "supports"
    assert [int(m.sum()) for m in inp.masks[:3]] == pytest.approx([int(m.sum()) for m in bar.masks[:3]], rel=0.05)
    strand, air = st.strand, []
    st.strand = lambda i, run, loose, *a, **k: (air.append(loose), strand(i, run, loose, *a, **k))[1]
    st.run(st.L)
    top = tp.p1[at & (tp.layer == st.L), :3]
    assert len(top) and (st.field[st.px(top)] >= inp.layer_z[st.L] - 1e-6).all()
    assert air and not air[0][st.px(top)].any()  # a strand the nozzle takes there is pressed onto it


@pytest.mark.parametrize("said, nozzle, bed, air, note", [
    ({"state": "printing", "nozzle_c": 211.4, "nozzle_target_c": 210, "bed_c": 55.2, "bed_target_c": 55, "chamber_c": 41}, 211.4, 55.2, 41,
     "live heat from k2 (printing), in place of the print's own: nozzle 211 C (set to 210 C), bed 55 C (set to 55 C), chamber 41 C"),
    ({"state": "printing", "nozzle_c": 190, "nozzle_target_c": 220}, 190, None, 35, "its nozzle is 30 C under what it is set to"),
    ({"state": "paused", "nozzle_c": 60, "nozzle_target_c": 0, "bed_c": 50}, 220, 50, 35, "60 C is too cold for PLA to flow; its set heat, 220 C, is used"),
    ({"state": "idle", "nozzle_c": 25, "bed_c": 25}, 220, None, 35, "live heat: k2 is not printing"),
    ({"state": "printing", "nozzle_c": "hot", "bed_c": True, "chamber_c": -40}, 220, None, 35, "in place of the print's own: none given"),
    (None, 220, None, 35, "live heat: k2 did not answer")])
def test_the_printers_own_heat_now(monkeypatch, said, nozzle, bed, air, note):
    calls = []

    def fake(argv, timeout=60):
        calls.append(argv[1])
        if argv[1] == "list":
            return 0, json.dumps({"printers": [{"name": "k2", "model": "creality-k2"}]})
        return (0, json.dumps({**said, "next": "x"})) if said else (1, "no route to host")

    monkeypatch.setattr(printers, "gantrel", lambda: "/fake/gantrel-printer")
    monkeypatch.setattr(printers, "_run", fake)
    base = failsim.Inputs([], 0.2, material=failsim.material("PLA"))
    inp = failvideo.live(base, printers.get("creality_k2"))
    assert (inp.material.nozzle, inp.bed, inp.air) == (nozzle, bed, air) and any(note in n for n in inp.notes), inp.notes
    assert calls == ["list", "status"]  # it only reads
    if nozzle != 220:
        assert inp.material.out < nozzle  # the melt is that hotend's
    monkeypatch.setattr(printers, "gantrel", lambda: None)
    assert "not installed" in failvideo.live(failsim.Inputs([], 0.2), printers.get("creality_k2")).notes[0]
