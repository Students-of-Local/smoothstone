"""Toolpaths without a slicer (toolpaths.py): plastic per layer and time against OrcaSlicer's own."""

from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import gcode, printers, toolpaths

from test_slicer import _box, _union

FIX = Path(__file__).parent / "fixtures" / "gcode"


def _k2():
    return toolpaths.profile()


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
            "jerk": 9.0, "max_feed": np.atleast_2d(orca.max_feed)[-1].tolist(), "max_accel": np.atleast_2d(orca.max_accel)[-1].tolist()}
    ours = toolpaths.generate(trimesh.creation.box((side, side, 0.8)), prof, 0.2, None,
                              ((x.min() + x.max()) / 2, (y.min() + y.max()) / 2))
    assert ours.layer_z == orca.layer_z

    def first3(tp):
        dt = tp.t1 - tp.t0
        return float(dt[(tp.layer >= 0) & (tp.layer < 3)].sum())

    assert first3(ours) == pytest.approx(first3(orca), rel=0.10)

    for feat, want in (("outer wall", 0.03), ("solid infill", 0.05)):  # the same lines, not offsetting errors
        ours_mm, orca_mm = (_length(tp, feat) for tp in (ours, orca))
        assert ours_mm == pytest.approx(orca_mm, rel=want), (feat, ours_mm, orca_mm)


def _length(tp, feat):
    sel = tp.extruding() & (tp.layer >= 0) & (tp.layer < 3) & (tp.feature == gcode.FEATURES.index(feat))
    return float(np.linalg.norm(tp.p1[sel, :2] - tp.p0[sel, :2], axis=1).sum())


def test_a_slower_printer_travels_slower_too():
    fast, slow = toolpaths.profile(), toolpaths.profile({"speeds": {"typical_print_mm_s": 50, "max_accel_mm_s2": 500}})
    f = 50 / fast["speeds"]["inner_wall"]
    assert all(slow["speeds"][k] == pytest.approx(v * f) for k, v in fast["speeds"].items())
    assert max(slow["accels"].values()) <= 500 and slow["whose"] == "OrcaSlicer's K2 speeds scaled to this printer"


@pytest.mark.parametrize("pid", printers.load())
def test_a_printer_prints_by_its_own_slicer_process(pid):
    p = printers.get(pid)
    got, own = toolpaths.profile(p), printers.process(p)
    assert all(got[k] == own[k] for k in ("layer", "widths", "speeds", "shells"))
    assert own["accels"].items() <= got["accels"].items() and got["accels"]["sparse_infill"] == own["accels"]["default"]
    assert got["whose"] == f"OrcaSlicer's {printers.short_name(p)} speeds"
    assert got.keys() == toolpaths.profile().keys() and all(got[k].keys() >= toolpaths.profile()[k].keys() for k in ("widths", "speeds", "accels"))


def test_the_k2s_own_process_is_the_one_stone_uses_with_no_printer():
    assert {**toolpaths.profile(), "whose": ""} == {**toolpaths.profile(printers.get("creality_k2")), "whose": ""}


def test_a_minis_walls_take_longer_than_a_k2s():
    mesh = _box((20, 20, 2), (0, 0, 0))
    mini, k2 = (toolpaths.generate(mesh, toolpaths.profile(printers.get(p)), 0.2, None, (90, 90)) for p in ("prusa_mini", "creality_k2"))
    outer = lambda tp: float(np.median(tp.feed[tp.extruding() & (tp.layer > 0) & (tp.feature == gcode.FEATURES.index("outer wall"))]))  # noqa: E731
    assert (outer(mini), outer(k2)) == (40, 200) and mini.t1.max() > 2 * k2.t1.max()


@pytest.mark.parametrize("along_x", [True, False])
def test_a_narrow_ledge_gets_support_lines_either_way_round(along_x):
    from smoothstone import supports

    mesh = _union(_box((30, 10, 10), (0, 0, 0)), _box((30, 11.5, 3), (0, 0, 10)))  # 1.5 mm past the wall, 10 mm up
    if not along_x:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (0, 0, 1)))
    tp = toolpaths.generate(mesh, _k2(), 0.2, supports.analyze(mesh, columns=True))
    sup = tp.feature == gcode.FEATURES.index("support")
    assert sup.any()
    assert np.allclose(tp.width[sup & (tp.layer == 0)], _k2()["widths"]["first_layer"])


def test_supports_at_another_layer_height_are_refused():
    from smoothstone import supports

    mesh = _union(_box((10, 12, 10), (15, 0, 0)), _box((40, 12, 3), (0, 0, 10)))
    with pytest.raises(ValueError, match="0.2 mm layers"):
        toolpaths.generate(mesh, _k2(), 0.28, supports.analyze(mesh, columns=True))


def test_a_hollow_open_top_box_prints():
    prof = _k2()
    prof["shells"] = {**prof["shells"], "sparse_infill_density": 0, "top_shell_layers": 0, "bottom_shell_layers": 0}
    tp = toolpaths.generate(trimesh.creation.box((20, 20, 2)), prof, 0.2)
    assert not (tp.feature == gcode.FEATURES.index("sparse infill")).any()


def test_no_line_asks_for_more_than_the_hotend_melts():
    k2 = toolpaths.profile(printers.get("creality_k2"), "TPU")
    assert k2["max_flow"] == 2 and "no faster than 2 mm3/s of TPU" in k2["whose"]
    box = trimesh.creation.box((20, 20, 2))
    slow, fast = toolpaths.generate(box, k2, 0.2), toolpaths.generate(box, {**k2, "max_flow": None}, 0.2)
    flow = lambda tp: tp.feed * toolpaths.spacing(tp.width, tp.height) * tp.height  # noqa: E731
    on = slow.extruding()
    assert flow(slow)[on].max() == pytest.approx(2) and flow(fast)[on].max() > 20
    assert np.allclose(slow.p1, fast.p1)  # the same lines
    assert slow.t1[-1] > 5 * fast.t1[-1]
