"""stone fit: what each hole and peg prints at, what it fits, and a coupon that calibrates one printer.
Holes print small by their facets (an n-sided polygon inscribed in the circle) plus the printer's
own error; calibration replaces the typical numbers with this printer's."""
import math
import os
import subprocess

import pytest

from smoothstone import config, fit
from test_cli import REPO, stone
from test_round_case import build_checked


def mesh_of(tmp_path, openscad, body: str):
    src = tmp_path / "m.scad"
    src.write_text("include <lib/stone.scad>\n" + body)
    out = tmp_path / "m.stl"
    env = config.openscad_env() | {"OPENSCADPATH": os.pathsep.join([str(REPO / "recipes"), str(REPO / "vendor")])}
    subprocess.run([openscad, "-o", str(out), str(src)], cwd=tmp_path, env=env, check=True, capture_output=True,
                   timeout=300)
    return fit.load_mesh(out)


# chord loss: a hole's flats sit at d cos(pi/n)

@pytest.mark.parametrize("n,flats", [(16, 4.903926), (32, 4.975924), (64, 4.993977)])
def test_chord_loss_is_exact(n, flats):
    assert fit.inscribed(5.0, n) == pytest.approx(flats, abs=1e-6)
    assert fit.fragments(2.5, fn=n) == n


def test_fragments_follow_openscad_without_fn():
    assert fit.fragments(2.5) == 8  # 2 pi 2.5 / $fs 2 = 7.85, up to 8
    assert fit.fragments(20) == 30  # 360 / $fa 12
    assert fit.fragments(0.5) == 5  # never under 5


@pytest.mark.parametrize("n", [16, 32, 64])
def test_a_built_hole_has_the_flats_the_math_says(tmp_path, openscad, n):
    m = mesh_of(tmp_path, openscad, f"difference() {{ cube([20, 20, 4], center = true); "
                                    f"cylinder(d = 5, h = 10, center = true, $fn = {n}); }}\n")
    holes = [f for f in fit.find_features(m) if f.kind == "hole"]
    assert len(holes) == 1, holes
    h = holes[0]
    assert h.n == n and h.axis == "z"
    assert h.size == pytest.approx(fit.inscribed(5.0, n), abs=1e-3)


def test_circle_fit_recovers_a_5_mm_hole(tmp_path, openscad):
    # upright, on its side, and off center: the modeled 5.00 mm comes back each time
    m = mesh_of(tmp_path, openscad, "difference() { translate([-3, 4, 0]) cube([30, 20, 12]); "
                                    "translate([5, 14, -1]) cylinder(d = 5, h = 20, $fn = 48); "
                                    "translate([-5, 8, 6]) rotate([0, 90, 0]) cylinder(d = 5, h = 40, $fn = 40); }\n")
    holes = sorted((f for f in fit.find_features(m) if f.kind == "hole"), key=lambda f: f.axis)
    assert [(f.axis, f.n) for f in holes] == [("x", 40), ("z", 48)]
    for f in holes:
        assert abs(f.d - 5.0) <= 0.02, f
    assert holes[1].center == pytest.approx((5, 14), abs=0.01)
    assert holes[1].depth == pytest.approx(12, abs=0.01)


def test_a_peg_is_a_peg_and_a_teardrop_is_a_hole(tmp_path, openscad):
    m = mesh_of(tmp_path, openscad, "difference() { cube([30, 20, 10]); "
                                    "translate([-1, 10, 5]) rotate([90, 0, 90]) linear_extrude(32) "
                                    "teardrop2d(4.5, $fn = 64); }\n"
                                    "translate([15, 10, 10]) cylinder(d = 6, h = 8, $fn = 64);\n")
    got = {(f.kind, f.shape, round(f.d, 2)) for f in fit.find_features(m)}
    assert ("peg", "round", 6.0) in got
    assert ("hole", "teardrop", 4.5) in got


# an M3 hole drawn at 3.0 mm is tight; the fix is ISO 273 medium

def test_an_m3_hole_at_3_mm_is_tight_and_the_fix_is_iso_medium():
    pr = fit.printer()
    row = fit.lib()["iso273.m3"]["value"]
    assert row["medium"] == 3.4
    ln = fit.screw_line("hole", 3.0, 96, pr, 0.0006, "M3", row, "hole_d")
    assert ln.verdict == "tight"
    assert ln.param == "hole_d"
    assert fit.printed_hole(ln.value, 96, pr, 0.0006) == pytest.approx(3.4, abs=0.03)
    assert "ISO 273 medium for M3: 3.4 mm" in ln.text


@pytest.mark.parametrize("size", ["M2.5", "M3", "M4"])
def test_following_stone_fit_next_ends_at_a_hole_that_fits_the_screw(jobenv, openscad, monkeypatch, size):
    """A hole drawn at the screw's own size is tight; stone's fix fits, and the next run keeps the
    same screw (it is not guessed again from the size the fix just changed)."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    medium = fit.lib()[f"iso273.{size.lower()}"]["value"]["medium"]
    stone("new", f"A 60 by 40 mm cover plate with two {size} screw holes")
    stone("set", "panel", f"hole_d={size[1:]}", "cutouts=0")
    _, code, _ = stone("build")
    assert code == 0
    text, code, nxt = stone("fit")
    assert code == 0
    assert "tight" in text and f"ISO 273 medium for {size}: {medium:g} mm" in text, text
    assert nxt.startswith("stone set panel hole_d="), nxt
    stone(*nxt.split()[1:])
    stone("build")
    text, _, nxt = stone("fit")
    assert f"{size} screw" in text and "fits" in text and "tight" not in text and "loose" not in text, text
    assert nxt.startswith("none, the part is ready"), nxt


def _panel(**params):
    from types import SimpleNamespace

    from smoothstone import recipes as rc

    r = rc.load("panel", REPO / "recipes")
    full = {p.name: p.default for p in r.params} | params
    return SimpleNamespace(name="panel", summary=r.summary, params=r.params), full


def test_a_guessed_screw_is_kept_when_the_hole_changes():
    pr, known = fit.printer(), {}
    r, params = _panel(hole_d=3.6)
    lines, _ = fit.recipe_lines(r, params, [], pr, 0, "PLA", None, known)
    assert known == {"hole_d": "M3"} and lines[0].verdict == "fits"
    r, params = _panel(hole_d=2.9)  # now nearest M2.5 by size, but the job's screw is M3
    lines, _ = fit.recipe_lines(r, params, [], pr, 0, "PLA", None, known)
    assert "M3 screw" in lines[0].text and lines[0].verdict == "tight" and lines[0].value == 3.6


def test_the_recipes_screw_setting_judges_its_hole():
    r, params = _panel(hole_d=3.4)
    lines, _ = fit.recipe_lines(r, params, [], fit.printer(), 0, "PLA", "M4", {})
    assert "M4 screw" in lines[0].text and lines[0].verdict == "tight", lines[0].text


def test_a_named_screw_comes_from_the_request():
    assert fit.request_screw("two M2.5 screw holes") == "M2.5"
    assert fit.request_screw("an m3 hole and an M4 hole") is None
    assert fit.request_screw("a 60 mm fan") is None
    assert fit.request_screw("a cover plate with two M2.5x8 screw holes") == "M2.5"
    assert fit.request_screw("M3x10 bolts.") == "M3"


# calibration

def test_calibration_round_trips_and_changes_the_prediction(jobenv):
    home = config.user_config_dir() / "stone.toml"
    assert str(home).startswith(os.environ["XDG_CONFIG_HOME"])  # never the real home config
    before = fit.printer()
    assert not before.calibrated
    p0 = fit.printed_hole(3.6, 96, before, 0)
    text, code, nxt = stone("fit", "calibrate", "slide=0.3", "square=20.14", "hole=9.74")
    assert code == 0, text
    assert home.is_file() and "[fit]" in home.read_text()
    after = fit.printer()
    s = fit.shrink("PLA")[0]
    assert after.calibrated and after.slide == 0.3
    assert after.outer_side == pytest.approx((20.14 - 20 * (1 - s)) / 2, abs=1e-4)
    assert after.hole_side == pytest.approx((fit.inscribed(10, 96) * (1 - s) - 9.74) / 2, abs=1e-4)
    assert fit.printed_hole(3.6, 96, after, 0) < p0 - 0.04  # this printer's holes print smaller
    assert fit.band("slide", after, "PLA")[0] == pytest.approx(fit.band("slide", before, "PLA")[0] + 0.1)
    # a second calibration replaces the table, other tables stay
    home.write_text(home.read_text() + '\n[printer]\nmodel = "mk4"\n')
    stone("fit", "calibrate", "slide=0.2")
    got = config._toml(None)
    assert got["printer"]["model"] == "mk4" and got["fit"]["mk4"]["slide"] == 0.2
    assert fit.printer().model == "mk4" and fit.printer().slide == 0.2


def test_the_persons_words_read_as_a_calibration():
    got = fit.parse_calibration(["Label 3 is the first one it slides into. Square is 20.14, big hole 9.74"], 6, 0.1)
    assert got == {"slide": pytest.approx(0.3), "square": 20.14, "hole": 9.74}
    assert fit.parse_calibration(["none", "of", "them"], 6, 0.1)["slide"] == pytest.approx(0.6)
    assert fit.parse_calibration(["slide=0"], 6, 0.1)["slide"] == 0


# the coupon

def test_the_fit_coupon_builds_and_passes_every_print_check():
    built, bad, _, err = build_checked("fit_coupon", {})
    assert built and not bad, (err, bad)


def test_fit_coupon_asks_the_person_and_their_answer_calibrates(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    text, code, nxt = stone("fit", "coupon")
    assert code == 0, text
    assert (jobenv / "stone-job" / "fit_coupon.stl").is_file()
    assert nxt.startswith("ask the person:") and "slides into" in nxt
    _, _, nxt = stone("note", "the peg slides into label 2, square 20.08")
    assert nxt.startswith("stone fit calibrate ")
    import shlex

    text, code, _ = stone(*shlex.split(nxt)[1:])
    assert code == 0, text
    assert fit.printer().slide == pytest.approx(0.2) and fit.printer().calibrated
    assert math.isclose(fit.printer().outer_side, (20.08 - 20 * (1 - fit.shrink("PLA")[0])) / 2, abs_tol=1e-4)


def test_a_deferred_coupon_never_calibrates_from_a_later_answer(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    home = config.user_config_dir() / "stone.toml"
    _, code, nxt = stone("fit", "coupon")
    assert code == 0 and nxt.startswith("ask the person:")
    # the person puts the coupon off: the job carries on, nothing is calibrated
    _, _, nxt = stone("note", "I'll print it later, carry on")
    assert not nxt.startswith("stone fit calibrate") and not nxt.startswith("ask the person")
    # a later question's answer mentions a slide: it is a note, never a calibration
    from smoothstone.job import Job

    Job(jobenv / "stone-job").update(next="ask the person: should the lid slide on or snap on?")
    _, _, nxt = stone("note", "the lid should slide on, about 0.3 mm")
    assert not nxt.startswith("stone fit calibrate")
    assert not home.is_file() and not fit.printer().calibrated


@pytest.mark.parametrize("words", ["I'll print it later, carry on", "Not any time soon, carry on",
                                   "not yet", "haven't printed it, skip that"])
def test_putting_the_coupon_off_never_calibrates(words):
    assert fit.defers(words)
    assert not (fit.parse_calibration([words], 6, 0.1).get("none"))


@pytest.mark.parametrize("words,slide", [("3", 0.3), ("3, square 20.14", 0.3), ("0.2", 0.2),
                                         ("none of them", 0.6), ("label 2 slides, later I'll measure", 0.2)])
def test_the_plainest_answers_read(words, slide):
    assert not fit.defers(words)
    assert fit.parse_calibration([words], 6, 0.1)["slide"] == pytest.approx(slide)


def test_a_bare_label_answer_reaches_calibrate(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("fit", "coupon")
    _, _, nxt = stone("note", "3")
    assert nxt.startswith("stone fit calibrate ")


def test_calibrate_without_a_slide_offers_a_way_on(jobenv):
    text, code, nxt = stone("fit", "calibrate", "not printed yet")
    assert nxt.startswith("stone fit calibrate slide=")
    assert "carry on without it" in text
