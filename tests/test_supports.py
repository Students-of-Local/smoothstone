"""stone supports (supports.py): whether a part needs supports, where and why, with no slicer."""

import json
import math

import numpy as np
import pytest
import trimesh

from smoothstone import cli, recipes, scad, supports

from test_slicer import _box, _union


def _frustum(bottom, top, height):
    """A square block that widens from bottom to top mm wide over height: its sides overhang at
    atan((top - bottom) / 2 / height) from vertical."""
    b, t = bottom / 2, top / 2
    pts = [(x, y, 0) for x in (-b, b) for y in (-b, b)] + [(x, y, height) for x in (-t, t) for y in (-t, t)]
    return trimesh.convex.convex_hull(np.array(pts, float))


def _arch(gap, width=10.0, post=5.0, height=10.0, beam=3.0):
    return _union(_box((post, width, height), (0, 0, 0)), _box((post, width, height), (post + gap, 0, 0)),
                  _box((2 * post + gap, width, beam), (0, 0, height)))


def test_a_t_shape_needs_supports_under_both_arms():
    t = _union(_box((6, 6, 10), (12, 0, 0)), _box((30, 6, 3), (0, 0, 10)))
    rep = supports.analyze(t)
    assert rep["needed"]
    assert len(rep["regions"]) == 2
    for r in rep["regions"]:
        assert r["z"][0] == pytest.approx(10.0, abs=0.01) and r["why"] == ["ledge"]
        assert r["area_mm2"] == pytest.approx(12 * 6, rel=0.05)  # each arm's underside
        assert r["worst_deg"] == pytest.approx(90, abs=0.5)
        assert r["support_mm3"] == pytest.approx(12 * 6 * 10, rel=0.05)  # down to the bed
    assert rep["advice"]["best"] == "upside down"  # on its bar, the T needs nothing
    assert not rep["advice"]["keep"]


def test_a_45_degree_chamfer_needs_no_support():
    rep = supports.analyze(_frustum(20, 30, 5))
    assert not rep["needed"] and not rep["regions"]
    assert rep["bands_mm2"]["45-60"] > 100  # the four sides are 45 deg overhangs, under the threshold
    assert rep["advice"]["keep"]


@pytest.mark.parametrize("deg,needed", [(58, False), (63, True)])
@pytest.mark.parametrize("base", [15.0, 17.33])
def test_a_flared_rim_either_side_of_the_threshold(deg, needed, base):
    """One 0.2 mm layer steps 3.2 px at 58 deg and 3.8 px at 63 on a 0.1 mm grid, both 3 or 4 px
    against a 3.46 px reach: the pixels cannot tell them apart, the faces can. Two widths put the
    edges at different pixel phases."""
    h = 4.0
    rep = supports.analyze(_frustum(base, base + 2 * h * math.tan(math.radians(deg)), h))
    assert rep["needed"] is needed, rep["regions"][:3]
    if needed:
        (r,) = rep["regions"]  # one flare, one region, not a piece per run of 4 px layers
        assert r["why"] == ["ledge"] and r["worst_deg"] == pytest.approx(deg, abs=1.0)
        assert r["z"][1] - r["z"][0] > h - 1
    else:
        assert not rep["regions"] and rep["advice"]["keep"]
        assert rep["bands_mm2"]["45-60"] > 100


def test_a_plate_floating_over_a_box_is_an_island():
    gap = 2.0
    part = _union(_box((20, 20, 5), (0, 0, 0)), _box((10, 10, 2), (5, 5, 5 + gap)))
    rep = supports.analyze(part)
    assert rep["needed"]
    (r,) = rep["regions"]
    assert r["why"] == ["island"]
    assert r["z"][0] == pytest.approx(5 + gap, abs=0.01)
    assert r["area_mm2"] == pytest.approx(100, rel=0.05)
    assert r["support_mm3"] == pytest.approx(100 * gap, rel=0.05)  # down to the box, not the bed
    assert "starts in mid air" in supports.why_text(r, rep["max_bridge_mm"])


def test_a_steep_overhang_past_the_threshold_needs_support():
    rep = supports.analyze(_frustum(10, 40, 5))  # 71.6 deg from vertical, past Orca's 60
    assert rep["needed"]
    assert all(r["why"] == ["ledge"] for r in rep["regions"])
    assert max(r["worst_deg"] for r in rep["regions"]) == pytest.approx(71.6, abs=1.0)


@pytest.mark.parametrize("gap", [8.0, 20.0])
def test_an_arch_bridge_is_measured_within_one_pixel(gap):
    rep = supports.analyze(_arch(gap))
    spans = [r["span_mm"] for r in rep["regions"] + rep["bridges"] if r["span_mm"] is not None]
    assert len(spans) == 1
    assert spans[0] == pytest.approx(gap, abs=rep["pixel_mm"] + 1e-9)
    if gap <= rep["max_bridge_mm"]:
        assert not rep["needed"] and rep["bridges"][0]["why"] == ["bridge"]
        assert rep["advice"]["keep"]  # the face estimate counts the ceiling; the layers say it prints as is
    else:
        (r,) = rep["regions"]
        assert rep["needed"] and r["why"] == ["long bridge"]
        assert "bridge 20.0 mm long, over 10 mm" in supports.why_text(r, rep["max_bridge_mm"])


def test_a_tall_pin_flags_tipping():
    pin = trimesh.creation.cylinder(radius=2.5, height=50, sections=48)
    pin.apply_translation((0, 0, 25))
    t = supports.analyze(pin)["tipping"]
    assert t["risk"] and "auto brim" in t["why"]
    assert t["base_mm"] == pytest.approx(5.0, abs=0.3) and t["ratio"] > 9
    cube = supports.analyze(_box((20, 20, 20), (0, 0, 0)))["tipping"]
    assert not cube["risk"] and cube["orca_brim_mm"] < 1


def test_a_leaning_tower_tips_when_its_center_of_mass_leaves_the_first_layer():
    lean = trimesh.convex.convex_hull(np.array(
        [(x, y, 0) for x in (0, 8) for y in (0, 8)] + [(x + 24, y, 40) for x in (0, 8) for y in (0, 8)], float))
    t = supports.analyze(lean)["tipping"]
    assert t["risk"] and "center of mass leaves" in t["why"] and t["com_margin_mm"] < 0


def test_bridge_span_reads_each_direction():
    piece = np.zeros((5, 12), bool)
    piece[1:4, 2:10] = True
    held = np.zeros_like(piece)
    held[1:4, 1] = held[1:4, 10] = True
    assert supports.bridge_span(piece, held, 0.1) == (pytest.approx(0.8), 0)
    held[1:4, 10] = False  # held on one side only: a ledge, not a bridge
    assert supports.bridge_span(piece, held, 0.1) is None


@pytest.mark.parametrize("name,upright,needed", [("fan_guard", False, False), ("hook", False, False), ("hook", True, True)])
def test_recipe_parts(name, upright, needed, openscad, tmp_path):
    """The fan guard and the hook print flat with no support, as their recipes say; the hook stood
    on end needs it, and better rests are named."""
    r = recipes.load(name)
    run = scad.build_stl(openscad, r, r.merged({}), tmp_path / "part.stl")
    assert run.ok, run.error
    mesh = supports.load(tmp_path / "part.stl")
    if upright:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, (1, 0, 0)))
    rep = supports.analyze(mesh)
    assert rep["needed"] is needed, rep["regions"][:2]
    if needed:
        assert rep["advice"]["best"] != "as built"
        assert min(r["z"][0] for r in rep["regions"]) > 0  # heights above the bed, not the file's own z


def test_stone_supports_writes_json_and_png_and_keeps_next(jobenv, tmp_path):
    stl = tmp_path / "t.stl"
    _union(_box((6, 6, 10), (12, 0, 0)), _box((30, 6, 3), (0, 0, 10))).export(stl)
    text, code = cli.run(["supports", str(stl)])
    assert code == 0
    assert "Supports needed: yes (2 regions)" in text
    assert "ledge" not in text and "hangs past the layer below" in text
    assert text.strip().splitlines()[-1].startswith("NEXT: ")
    data = json.loads((tmp_path / "supports.json").read_text())
    assert data["needed"] and len(data["regions"]) == 2 and (tmp_path / "supports.png").stat().st_size > 1000
    assert all(not k.startswith("_") for k in data)


def test_stone_supports_names_an_island(jobenv, tmp_path):
    stl = tmp_path / "float.stl"
    _union(_box((20, 20, 5), (0, 0, 0)), _box((10, 10, 2), (5, 5, 7))).export(stl)
    text, code = cli.run(["supports", str(stl)])
    assert code == 0 and "Supports needed: yes" in text and "starts in mid air" in text


def test_a_part_far_bigger_than_the_bed_is_refused_not_sliced(jobenv, tmp_path):
    stl = tmp_path / "microns.stl"
    big = _box((20, 20, 50), (0, 0, 0))
    big.apply_scale(1000)  # exported in microns: 20 m by 50 m, 250,000 layers
    big.export(stl)
    text, code = cli.run(["supports", str(stl)])
    assert code == 1 and "does not fit" in text and "wrong units" in text
    assert not (tmp_path / "supports.json").exists()
    with pytest.raises(ValueError, match="too big for any bed"):
        supports.cut(big)
    with pytest.raises(ValueError, match="layers"):
        supports.cut(_box((10, 10, 10), (0, 0, 0)), layer=0.0005)
