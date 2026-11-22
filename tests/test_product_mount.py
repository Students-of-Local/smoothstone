"""product_mount: an under desk mount for a catalog product. A product named with punctuation the
phrases do not read ("Mac mini (M4, 2024)") is still found, and its model numbers are used up as
the name, not offered as sizes. Side windows print square on a wall printed on its side.
Stone's own NEXT lines must reach a part the engineering grader passes for e07.
Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e07_mac_mini_mount).
"""
import pytest

from smoothstone import catalog, match
from smoothstone import recipes as rc
from test_fitted_case import REPO, SPECS, _follow_next, _top, grade
from test_round_case import build_checked


def test_a_name_in_parentheses_sets_the_product_and_its_numbers_are_not_sizes():
    r = rc.load("product_mount", REPO / "recipes")
    got, left = match.suggest_full(r, SPECS["e07_mac_mini_mount"]["request"])
    assert got["product"] == "mac_mini_m4_2024"
    assert left == []
    assert "screw" not in got  # "M4" is the chip, not a screw size


def test_a_mount_request_ranks_product_mount_first():
    assert _top(SPECS["e07_mac_mini_mount"]["request"]) == "product_mount"


@pytest.mark.parametrize("slug", catalog.slugs_for("product_mount"))
def test_product_mount_builds_clean_for_every_product(slug):
    built, bad, eng, err = build_checked("product_mount", {"product": slug})
    assert built, err
    if slug == "anker_a1388":
        # 151 mm long and 16 mm low: standing on its front end it tips. Open: a snap off brim, or
        # printing it on its roof with supports, is the owner's choice (LOG.md climb 2).
        assert [n for n, _ in bad] == ["tipping"], bad
        return
    assert not bad, bad
    assert {"load", "attach", "retention"} <= set(eng)


def test_stones_own_path_makes_a_mount_the_engineering_grade_passes(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS["e07_mac_mini_mount"]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show product_mount") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "product_mount.stl")
    assert res["why"] == [], res["why"]
