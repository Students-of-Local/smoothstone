"""knob: a press on knob for a catalog shaft. The part number in the request is the product's
name, not a size; a D shaft gets a flat in the bore at its across flats size.
Stone's own NEXT lines must reach a part the engineering grader passes for e09.
Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e09_pot_knob).
"""
import os
import subprocess

import trimesh

from smoothstone import config, match
from smoothstone import recipes as rc
from test_fitted_case import REPO, SPECS, _follow_next, _top, grade
from test_round_case import build_checked


def test_the_part_number_is_the_product_not_a_size():
    r = rc.load("knob", REPO / "recipes")
    got, left = match.suggest_full(r, SPECS["e09_pot_knob"]["request"])
    assert got == {"product": "bourns_ptv09a_4020s_b103"} and left == []


def test_a_knob_request_ranks_knob_first():
    assert _top(SPECS["e09_pot_knob"]["request"]) == "knob"


def test_knob_builds_clean_with_a_press_fit():
    built, bad, eng, err = build_checked("knob", {})
    assert built and not bad, (err, bad)
    assert eng["retention"] == {"type": "friction", "gap": -0.06}


def test_a_d_shaft_gets_a_flat_in_the_bore(tmp_path, openscad):
    wrap = tmp_path / "dknob.scad"
    wrap.write_text('include <knob/recipe.scad>\n'
                    'function catalog_row(slug) = ["d_shaft", [6, 6, 7], 3, [], [], -1, [], ["d", 4.5]];\n')
    env = config.openscad_env() | {"OPENSCADPATH": os.pathsep.join([str(REPO / "recipes"), str(REPO / "vendor")])}
    out = tmp_path / "d.stl"
    subprocess.run([openscad, "-o", str(out), str(wrap)], cwd=tmp_path, env=env, check=True, capture_output=True,
                   timeout=300)
    m = trimesh.load(out)
    # the flat sits 4.5 - 3 = 1.5 mm from the axis: bore below it, knob above it, round elsewhere
    inside = m.contains([[0, 1.4, 6], [0, 1.6, 6], [0, -2.8, 6], [2.8, 0, 6]])
    assert list(inside) == [False, True, False, False]


def test_stones_own_path_makes_a_knob_the_engineering_grade_passes(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS["e09_pot_knob"]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show knob") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "knob.stl")
    assert res["why"] == [], res["why"]
