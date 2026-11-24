"""stone fit: what each hole and peg prints at, and what it fits. Holes print small by their
facets (an n-sided polygon inscribed in the circle) plus the printer's own error."""
import os
import subprocess

import pytest

from smoothstone import config, fit
from test_cli import REPO, stone


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

