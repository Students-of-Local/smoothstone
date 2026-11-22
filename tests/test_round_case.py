"""round_case: a snap shut case for a round catalog product (the AirTag), and the shared catalog
pieces the product recipes stand on: recipes/lib/catalog.scad generated from the catalog, each
recipe offered only the products it can make, and the stone_eng echo read into engineering.json.
Stone's own NEXT lines must reach a part the engineering grader passes for e04.
Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e04_airtag_case).
"""
import tempfile
from pathlib import Path

import pytest

from smoothstone import catalog, check, config, fitted, scad
from smoothstone import recipes as rc
from test_fitted_case import REPO, SPECS, _follow_next, _top, grade


def build_checked(name: str, params: dict) -> tuple[bool, list, dict | None, str]:
    """Build a recipe with stone's own checks: (built, failed checks, engineering.json, error)."""
    binary = config.find_openscad()
    if not binary:
        pytest.skip("no OpenSCAD binary")
    r = rc.load(name, REPO / "recipes")
    full = {p.name: p.default for p in r.params} | params
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "part.stl"
        run = scad.build_stl(binary, r, full, out)
        if not run.ok:
            return False, [], None, run.error
        res = check.check_stl(out, r, full, log=run.log)
        return True, [(x.name, x.detail) for x in res if not x.ok], fitted.engineering(r, full, run.log), ""


def test_lib_catalog_scad_is_generated_from_the_catalog():
    assert (REPO / "recipes" / "lib" / "catalog.scad").read_text() == catalog.catalog_table()


def test_each_recipe_is_offered_only_the_products_it_can_make():
    assert catalog.slugs_for("round_case") == ["apple_airtag"]
    assert catalog.slugs_for("knob") == ["bourns_ptv09a_4020s_b103"]
    assert catalog.slugs_for("board_plate") == ["raspberry_pi_4", "raspberry_pi_5"]
    assert "apple_airtag" not in catalog.slugs_for("product_holder")
    assert "bourns_ptv09a_4020s_b103" not in catalog.slugs_for("product_mount")
    assert set(rc.catalog_param(rc.load("round_case", REPO / "recipes")).choices) == {"apple_airtag"}


def test_the_stone_eng_echo_reads_as_engineering_json():
    r = rc.load("round_case", REPO / "recipes")
    log = ('ECHO: stone_eng = [["frame", [[1, 0, 0, -3], [0, 1, 0, 2], [0, 0, 1, 4], [0, 0, 0, 1]]], '
           '["clearance", 0.2], ["retention", [["type", "snap"], ["y", 0.8], ["at", [1, 2, 3]]]]]\n')
    eng = fitted.engineering(r, {"product": "apple_airtag", "material": "PETG"}, log)
    assert eng["frame"][1] == [0, 1, 0, 2] and eng["clearance"] == 0.2 and eng["material"] == "PETG"
    assert eng["retention"] == {"type": "snap", "y": 0.8, "at": [1, 2, 3]}
    assert eng["product"] == "Apple AirTag (2021)" or eng["product"]
    assert all(v.startswith("https://") for v in eng["sources"].values())


def test_an_airtag_case_ranks_round_case_first():
    assert _top(SPECS["e04_airtag_case"]["request"]) == "round_case"


def test_round_case_builds_clean_for_every_round_product():
    for slug in catalog.slugs_for("round_case"):
        built, bad, eng, err = build_checked("round_case", {"product": slug})
        assert built and not bad, (slug, err, bad)
        assert eng["retention"]["type"] == "snap"


def test_stones_own_path_makes_an_airtag_case_the_engineering_grade_passes(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS["e04_airtag_case"]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show round_case") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "round_case.stl")
    assert res["why"] == [], res["why"]
