"""bed_edge: the first layer squashes out (elephant foot), so every recipe part is inset at the bed."""

import numpy as np
import pytest
import trimesh

from smoothstone import check, recipes, scad


def by_name(results):
    return {r.name: r for r in results}


def plain_recipe():
    return recipes.load("cable_comb")


def plate(x, y, z, chamfer=0.0, steps=0):
    """A plate on the bed. With steps, the bed edge steps in by chamfer over the first chamfer mm,
    the way soft_extrude and bed_chamfer build it."""
    if chamfer <= 0:
        m = trimesh.creation.box((x, y, z))
        m.apply_translation((0, 0, z / 2))
        return m
    parts = []
    for i in range(steps):
        inset = chamfer * (steps - i) / steps
        h = chamfer / steps
        s = trimesh.creation.box((x - 2 * inset, y - 2 * inset, h))
        s.apply_translation((0, 0, h * i + h / 2))
        parts.append(s)
    top = trimesh.creation.box((x, y, z - chamfer))
    top.apply_translation((0, 0, chamfer + (z - chamfer) / 2))
    parts.append(top)
    return trimesh.boolean.union(parts, engine="manifold")


def test_straight_wall_fails_bed_edge():
    res = by_name(check.check_mesh(plate(60, 20, 6), recipe=plain_recipe()))
    assert not res["bed_edge"].ok
    assert res["bed_edge"].value == pytest.approx(0, abs=0.01)


def test_stepped_chamfer_passes_bed_edge_and_is_no_overhang():
    res = by_name(check.check_mesh(plate(60, 20, 6, chamfer=0.4, steps=4), recipe=plain_recipe()))
    assert res["bed_edge"].ok, res["bed_edge"].detail
    assert res["bed_edge"].value == pytest.approx(0.4, abs=0.02)
    # the 45 degree staircase is the slope, not an overhang
    assert res["overhang"].value == 0, res["overhang"].detail


def test_slice_area_counts_holes():
    m = trimesh.creation.annulus(r_min=5, r_max=10, height=4, sections=256)
    m.apply_translation((0, 0, 2))
    area, per = check.slice_area(m, 1.0)
    assert area == pytest.approx(np.pi * (100 - 25), rel=0.01)
    assert per == pytest.approx(2 * np.pi * 15, rel=0.01)


def test_any_stl_and_skipping_recipes_do_not_run_it():
    res = by_name(check.check_mesh(plate(60, 20, 6)))
    assert res["bed_edge"].ok and "skipped" in res["bed_edge"].detail
    r = plain_recipe()
    r.skip = {"bed_edge": "prints on a raft"}
    res = by_name(check.check_mesh(plate(60, 20, 6), recipe=r))
    assert res["bed_edge"].ok and "prints on a raft" in res["bed_edge"].detail


# The audit found these defaults square at the bed (inset 0.00 mm). Built for real, each must now
# step in at least 0.2 mm: soft_extrude (cable_comb, hook) and bed_chamfer (grommet, gear).
@pytest.mark.parametrize("name", ["cable_comb", "hook", "grommet", "spur_gear"])
def test_recipe_defaults_chamfer_the_bed_edge(name, openscad, tmp_path):
    r = recipes.load(name)
    params = r.merged({})
    run = scad.build_stl(openscad, r, params, tmp_path / "part.stl")
    assert run.ok, run.error
    res = by_name(check.check_stl(tmp_path / "part.stl", recipe=r, params=params))
    assert res["bed_edge"].ok, res["bed_edge"].detail
    assert res["bed_edge"].value >= 0.35
    assert check.passed(res.values()), [x for x in res.values() if not x.ok]
