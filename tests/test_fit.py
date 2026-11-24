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


def test_stone_fit_flags_an_m3_panel_hole_and_its_fix_fits(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A 60 by 40 mm cover plate with two M3 screw holes")
    stone("set", "panel", "hole_d=3.0", "cutouts=0")
    _, code, _ = stone("build")
    assert code == 0
    text, code, nxt = stone("fit")
    assert code == 0
    assert "tight" in text and "ISO 273 medium for M3: 3.4 mm" in text, text
    assert nxt == "stone set panel hole_d=3.6"
    stone(*nxt.split()[1:])
    stone("build")
    text, _, nxt = stone("fit")
    assert "hole_d=3.6" in text and "fits" in text and "tight" not in text, text
    assert nxt.startswith("none, the part is ready"), nxt

