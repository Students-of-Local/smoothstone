"""finger_gap: a fan guard's largest opening must stop the 12 mm test finger (IEC 61032, IP2X)."""

import shutil

import pytest
import trimesh

from smoothstone import check, recipes, refs, scad
from test_cli import REPO, stone


def plate_with_hole(d, size=60, t=3):
    plate = trimesh.creation.box((size, size, t))
    hole = trimesh.creation.cylinder(radius=d / 2, height=t + 2, sections=256)
    m = trimesh.boolean.difference([plate, hole], engine="manifold")
    m.apply_translation((0, 0, t / 2))
    return m


@pytest.mark.parametrize("d", [8.0, 13.0])
def test_largest_gap_is_the_hole(d):
    gap = check.largest_gap(plate_with_hole(d), 0, 0, 20, 1.5)
    assert gap == pytest.approx(d, abs=0.25)


def test_grille_echo_runs_the_check_and_names_the_setting():
    log = 'ECHO: stone_grille = [0, 0, 20, 1.5, "rings", 3, "up"]\n'
    (res,) = check.grille_results(plate_with_hole(13), log)
    assert not res.ok and res.param == "rings" and res.at == 3 and res.direction == "up"
    (res,) = check.grille_results(plate_with_hole(8), log)
    assert res.ok


def test_limit_is_the_sourced_test_finger():
    finger = refs.get("ip2x.finger")
    assert check.MAX_FINGER_GAP == finger["value"]["diameter"] == 12
    assert "61032" in finger["standard"] and finger["url"]


def test_fan_guard_defaults_stop_a_finger(openscad, tmp_path):
    # the audit: the default rings guard let a 13.1 mm ball through
    r = recipes.load("fan_guard")
    params = r.merged({})
    run = scad.build_stl(openscad, r, params, tmp_path / "part.stl")
    assert run.ok, run.error
    res = {x.name: x for x in check.check_stl(tmp_path / "part.stl", recipe=r, params=params, log=run.log)}
    assert res["finger_gap"].ok, res["finger_gap"].detail
    assert check.passed(res.values()), [x for x in res.values() if not x.ok]


# open guards an audit measured: 3 rings (13.1 mm) and an 11 blade spiral (16.3 mm) on a 120 mm fan
@pytest.mark.parametrize("settings,first_next", [
    (["rings=3"], "stone set rings=4"),
    (["style=spiral", "blades=11"], "stone set blades=15"),
], ids=["rings", "spiral"])
def test_open_guard_fix_leads_to_a_safe_part(settings, first_next, jobenv, recipes_root, openscad):
    shutil.copytree(REPO / "recipes" / "fan_guard", recipes_root / "fan_guard")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    stone("new", "a 120 mm fan guard")
    text, code, nxt = stone("set", "fan_guard", *settings)
    assert code == 0, text
    text, code, nxt = stone("build")
    assert code == 1 and "FIX: finger_gap" in text, text
    assert nxt == first_next, text
    stone(*nxt.split()[1:])
    text, code, nxt = stone("build")
    assert "Part ready" in text, text
