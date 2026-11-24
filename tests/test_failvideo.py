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
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255))
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
    st = failvideo.plan(tp, inp, fail, (255, 255, 255))[4]
    span = fail.numbers["span_mm"]
    low = min(float(dz.min()) for i, p, dz, dd, droops, w in st.bent)
    assert low == pytest.approx(float(failsim.bridge_sag(span, [span / 2])[0]), rel=0.02)
    assert low < -0.2  # past the usable length it sags more than a layer


def test_a_dirty_plate_lets_go_slides_and_grows_a_blob():
    tp, inp, fail, what_if = _story(_box((30, 20, 1), (0, 0, 0)), clean=failsim.fact("contamination"))
    assert fail.kind == "detach" and fail.layer == 0 and not what_if
    scene, frs, extra, first, st = failvideo.plan(tp, inp, fail, (255, 255, 255))
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
    assert f"NEXT: stone timelapse {stl} --supports off --fail detach" in text, text
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
