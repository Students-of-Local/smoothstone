"""board_plate: a VESA adapter plate for a catalog board, its screw holes from the board's own
mounting holes. "VESA 75" or "100 x 100" picks the pattern; the board's 2.7 mm holes take M2.5.
Stone's own NEXT lines must reach a part the engineering grader passes for e08.
Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e08_rpi4_vesa_adapter).
"""
import pytest

from smoothstone import catalog, match
from smoothstone import recipes as rc
from test_fitted_case import REPO, SPECS, _follow_next, _top, grade
from test_round_case import build_checked


@pytest.mark.parametrize("text,vesa", [
    (None, "75"),
    ("a VESA 100 adapter plate for a Raspberry Pi 5", "100"),
    ("an adapter plate for my Pi 4 to a 100 x 100 monitor mount", "100"),
])
def test_the_request_picks_the_vesa_pattern(text, vesa):
    r = rc.load("board_plate", REPO / "recipes")
    got, left = match.suggest_full(r, text or SPECS["e08_rpi4_vesa_adapter"]["request"])
    assert got["vesa"] == vesa and got["product"] in catalog.slugs_for("board_plate")
    assert left == []


def test_a_board_plate_request_ranks_board_plate_first():
    assert _top(SPECS["e08_rpi4_vesa_adapter"]["request"]) == "board_plate"


@pytest.mark.parametrize("slug", catalog.slugs_for("board_plate"))
@pytest.mark.parametrize("vesa", ["75", "100"])
def test_board_plate_builds_clean_with_m25_holes_and_the_pattern_named(slug, vesa):
    built, bad, eng, err = build_checked("board_plate", {"product": slug, "vesa": vesa})
    assert built and not bad, (err, bad)
    assert eng["retention"]["size"] == "M2.5" and eng["retention"]["hole_d"] == 2.9
    assert len(eng["retention"]["holes"]) == 4
    assert list(eng["part_holes"]) == [f"vesa_{vesa}"]


def test_stones_own_path_makes_a_plate_the_engineering_grade_passes(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS["e08_rpi4_vesa_adapter"]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show board_plate") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "board_plate.stl")
    assert res["why"] == [], res["why"]
