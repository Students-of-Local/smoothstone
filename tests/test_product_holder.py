"""product_holder: an open top cradle for a catalog product, on a desk or screwed to a wall. "on
the wall" picks the wall mount (the recipe's title must not name it, or the word is read as the
title's). A model's variant words (Pro Max, mini, Plus) keep catalog.find off the plain model.
Stone's own NEXT lines must reach a part the engineering grader passes for e05 and e06.
Reference designs by GPT-6.1 Sol, smoothstone gold set (evals/gold/e05_appletv_wall_holder and
e06_iphone_desk_holder).
"""
import pytest

from smoothstone import catalog, match
from smoothstone import recipes as rc
from test_fitted_case import REPO, SPECS, _follow_next, _top, grade
from test_round_case import build_checked


@pytest.mark.parametrize("text,slug", [
    ("a desk stand for my iPhone 17 Pro", "iphone_17_pro_upright"),
    ("a desk stand for my iPhone 17 Pro Max", None),
    ("a holder for my Mac mini M4", "mac_mini_m4_2024"),
    ("a holder for my Mac mini", None),  # which one: the 2024 M4 is not the 2023 M2's size
])
def test_a_variant_word_keeps_find_off_the_plain_model(text, slug):
    assert catalog.find(text) == slug


def test_on_the_wall_picks_the_wall_mount():
    r = rc.load("product_holder", REPO / "recipes")
    got, _ = match.suggest_full(r, SPECS["e05_appletv_wall_holder"]["request"])
    assert got["mount"] == "wall" and got["product"] == "apple_tv_4k_3rd_gen"
    got, _ = match.suggest_full(r, SPECS["e06_iphone_desk_holder"]["request"])
    assert got.get("mount", "desk") == "desk" and got["product"] == "iphone_17_pro_upright"


@pytest.mark.parametrize("sid", ["e05_appletv_wall_holder", "e06_iphone_desk_holder"])
def test_a_holder_request_ranks_product_holder_first(sid):
    assert _top(SPECS[sid]["request"]) == "product_holder"


@pytest.mark.parametrize("slug", catalog.slugs_for("product_holder"))
@pytest.mark.parametrize("mount", ["desk", "wall"])
def test_product_holder_builds_clean_for_every_product(slug, mount):
    built, bad, eng, err = build_checked("product_holder", {"product": slug, "mount": mount})
    if mount == "wall" and set(catalog.get(slug).get("open_faces", [])) >= {"+y", "-x", "+x"}:
        assert not built and "must stay clear" in err  # no side to screw through: said, not guessed
        return
    assert built and not bad, (err, bad)
    assert ("attach" in eng and "load" in eng) == (mount == "wall")


@pytest.mark.parametrize("sid", ["e05_appletv_wall_holder", "e06_iphone_desk_holder"])
def test_stones_own_path_makes_a_holder_the_engineering_grade_passes(sid, jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS[sid]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show product_holder") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "product_holder.stl")
    assert res["why"] == [], res["why"]
