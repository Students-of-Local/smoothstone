"""Tier L parts from a recipe the model wrote (evals/newpart_grade.py, evals/run.py): size and
openings measured in the mesh, the claude driver's file tools, and a catalog recipe left as it was.
Shapes are made with manifold3d, so no OpenSCAD."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import manifold3d as m3
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
import newpart_grade as npg  # noqa: E402

spec = importlib.util.spec_from_file_location("run_harness_newpart", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def stl(tmp_path: Path, solid: m3.Manifold, name: str = "part.stl") -> Path:
    mesh = solid.to_mesh()
    p = tmp_path / name
    trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)).export(p)
    return p


def hole(d: float, h: float) -> m3.Manifold:
    return m3.Manifold.cylinder(h, d / 2, d / 2, 64)


def bracket() -> m3.Manifold:
    """An L bracket: a 40 x 20 x 4 base with an M4 hole along z, a 4 x 20 x 30 leg with one along x."""
    base = m3.Manifold.cube([40, 20, 4]) - hole(4.5, 10).translate([25, 10, -3])
    leg = m3.Manifold.cube([4, 20, 30]) - hole(4.5, 10).rotate([0, 90, 0]).translate([-3, 10, 20])
    return base + leg


BRACKET = {"new_recipe": True, "dims": [[39.5, 41], [29.5, 31], [19.5, 20.5]],
           "features": [{"name": "m4_holes", "kind": "hole", "d": [4.3, 4.8], "count": 2}]}


def test_a_bracket_with_its_two_holes_passes(tmp_path):
    why, got = npg.check(stl(tmp_path, bracket()), BRACKET)
    assert why == [] and got["dims"] == [40.0, 30.0, 20.0] and got["features"]["m4_holes"] == 2


def test_a_hole_of_the_wrong_size_fails_and_says_what_it_found(tmp_path):
    part = m3.Manifold.cube([40, 20, 4]) - hole(3.4, 10).translate([25, 10, -3])
    why, _ = npg.check(stl(tmp_path, part + m3.Manifold.cube([4, 20, 30])), BRACKET)
    assert any(w.startswith("m4_holes: 0 holes") and "3.4" in w for w in why)


def test_a_part_of_the_wrong_size_fails(tmp_path):
    why, _ = npg.check(stl(tmp_path, bracket().scale([1.5, 1, 1])), {"new_recipe": True, "dims": BRACKET["dims"]})
    assert why == ["largest size 60.0 mm (want 39.5 to 41)"]


def test_a_countersink_or_a_bed_chamfer_does_not_stand_in_for_the_bore(tmp_path):
    sink = m3.Manifold.cylinder(2.2, 4.5, 2.25, 64).translate([10, 10, 4])  # flares to Ø9 at the top
    part = m3.Manifold.cube([20, 20, 6.2]) - hole(4.5, 20).translate([10, 10, -5]) - sink
    why, got = npg.check(stl(tmp_path, part), {"new_recipe": True, "features": [
        {"name": "m4", "kind": "hole", "d": [4.3, 4.8], "count": 1}]})
    assert why == [] and got["features"]["m4"] == 1


def test_a_closed_window_in_a_wall_is_a_cutout_and_a_blind_bore_a_hole(tmp_path):
    wall = m3.Manifold.cube([2, 40, 22]) - m3.Manifold.cube([6, 12.5, 7.5]).translate([-2, 14, 8])
    post = m3.Manifold.cube([8, 8, 22]).translate([2, 0, 0]) - hole(2.5, 20).translate([6, 4, 5])
    why, got = npg.check(stl(tmp_path, wall + post), {"new_recipe": True, "features": [
        {"name": "usb", "kind": "cutout", "w": [12, 13], "h": [7, 8], "count": 1},
        {"name": "pilot", "kind": "hole", "d": [2.3, 2.8], "count": 1}]})
    assert why == [] and got["features"] == {"usb": 1, "pilot": 1}


# --- the claude driver at tier L -----------------------------------------------------------------
def test_tier_l_may_read_the_job_and_write_only_recipes():
    argv = run.drivers.claude_argv("opus", "CARD", "make it", job=Path("/w/run/job"))
    assert argv[argv.index("--tools") + 1] == "Bash,Read,Write,Edit"
    i = argv.index("--allowedTools")
    assert argv[i + 1:argv.index("--permission-mode")] == ["Bash(stone:*)", "Read(//w/run/job/**)",
                                                             "Write(//w/run/job/recipes/**)",
                                                             "Edit(//w/run/job/recipes/**)"]
    plain = run.drivers.claude_argv("opus", "CARD", "make it")
    assert plain[plain.index("--tools") + 1] == "Bash" and not any(a.startswith("Write(") for a in plain)


# --- grading a run with its own recipes ----------------------------------------------------------
def test_a_changed_catalog_recipe_fails_the_run(tmp_path):
    job = tmp_path / "job"
    shutil.copytree(ROOT / "recipes", job / "recipes")
    scad = job / "recipes" / "fan_guard" / "recipe.scad"
    scad.write_text(scad.read_text() + "\n// a model's edit\n")
    g = run.grade_job(job, json.loads((ROOT / "evals" / "tuning" / "t1_fan_guard.json").read_text()), [])
    assert "changed catalog recipes: fan_guard" in g["why"]


def test_a_new_recipe_spec_wants_a_recipe_outside_the_catalog(tmp_path):
    job = tmp_path / "job"
    shutil.copytree(ROOT / "recipes", job / "recipes")
    (job / "build").mkdir()
    (job / "build" / "params.json").write_text(json.dumps({"recipe": "fan_guard", "params": {}}))
    stl(job, bracket(), "fan_guard.stl")
    g = run.grade_job(job, {"id": "x", "request": "r", "expect": BRACKET}, [])
    assert "recipe fan_guard is in the catalog (want a new one)" in g["why"]
    assert "new_recipe" not in g  # a catalog part is not measured as a new one
