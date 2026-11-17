"""The figure recipe without the style and lift models: a stand-in mesh goes through repair,
the plinth recipe and every print check, and the CLI points at stone find when photos are missing."""
import shutil
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, figure

REPO = Path(__file__).resolve().parent.parent


def stone(*argv):
    text, code = cli.run(list(argv))
    assert text.splitlines()[-1].startswith("NEXT: "), text
    return text, code, text.splitlines()[-1][6:]


def standin(path: Path) -> Path:
    """A little person, Y up and facing +Z like a lift model writes it: body, head, two feet."""
    body = trimesh.creation.capsule(height=0.9, radius=0.35)  # along Z
    body.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    body.apply_translation([0, 0.8, 0])
    head = trimesh.creation.icosphere(subdivisions=3, radius=0.45)
    head.apply_translation([0, 1.85, 0.05])
    feet = [trimesh.creation.box([0.25, 0.2, 0.4]) for _ in range(2)]
    feet[0].apply_translation([-0.15, 0.1, 0.05])
    feet[1].apply_translation([0.15, 0.1, 0.05])
    m = trimesh.boolean.union([body, head, *feet], engine="manifold")
    m.export(path)
    return path


def test_repair_orients_and_scales(tmp_path):
    info = figure.repair(standin(tmp_path / "lift.glb"), tmp_path / "figure.stl")
    m = trimesh.load(tmp_path / "figure.stl")
    lo, hi = m.bounds
    assert info["watertight"] and m.is_watertight
    assert abs((hi[2] - lo[2]) - 1) < 1e-6 and abs(lo[2]) < 1e-6  # unit height, feet on z = 0
    top = m.vertices[m.vertices[:, 2] > 0.8]
    assert top[:, 1].mean() < 0.02  # the face that pointed +Z now points -Y


def test_prompt_names_the_style():
    assert "chibi" in figure.prompt("chibi") and "this exact person" in figure.prompt("chibi")
    assert "this exact animal" in figure.prompt("statue", "animal")
    with pytest.raises(figure.FigureProblem):
        figure.make([], Path("."), "nope")


def test_build_without_photos_asks_for_find(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of Ada Lovelace, 80 mm tall")
    stone("set", "figure", "height=80")
    text, code, nxt = stone("build")
    assert code == 1 and nxt == 'stone find "Ada Lovelace"'
    assert stone("status")[2] == 'stone find "Ada Lovelace"'


def test_figure_on_plinth_passes_checks(jobenv, monkeypatch, openscad, tmp_path):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    fig = tmp_path / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    stone("new", 'A figure 70 mm tall with "ADA" on the base')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0, text
    assert "Part ready" in text and "70.0 mm" in text


def test_cached_steps_skip_models(tmp_path, monkeypatch):
    """A second build with the same photos and settings reuses every file and runs no model."""
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    calls = []

    def fake_style(photos, out, *a, **k):
        calls.append("style")
        shutil.copyfile(photo, out)
        return out

    def fake_lift(render, out, seed):
        calls.append("lift")
        standin(out)
        return out

    def fake_describe(photo, out, who):
        calls.append("describe")
        out.write_text("short silver hair\n")
        return "short silver hair"

    monkeypatch.setattr(figure, "describe", fake_describe)
    monkeypatch.setattr(figure, "style", fake_style)
    monkeypatch.setattr(figure, "lift", fake_lift)
    a = figure.make([photo], tmp_path / "fig", say=lambda s: None)
    b = figure.make([photo], tmp_path / "fig", say=lambda s: None)
    assert a == b and a.exists() and calls == ["describe", "style", "lift"]


def test_find_leaves_other_plans_alone(jobenv, monkeypatch):
    """stone find on a fan guard job downloads nothing and keeps the job's NEXT."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool

    def no_fetch(*a, **k):
        raise AssertionError("find downloaded photos for a fan guard")

    monkeypatch.setattr(findtool, "fetch", no_fetch)
    stone("new", "A fan guard for a 120 mm fan")
    stone("set", "fan_guard", "size=120")
    before = stone("status")[2]
    text, code, nxt = stone("find", "fan guard")
    assert code == 1 and "figure" in text
    assert stone("status")[2] == before


def test_mini_alone_does_not_pick_figure(monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import recipes as rc
    top = rc.rank(list(rc.load_all().values()), "a mini planter for a succulent")[0][1]
    assert top.name != "figure"


def test_find_before_a_plan_leaves_a_fan_guard_alone(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool

    def no_fetch(*a, **k):
        raise AssertionError("find downloaded photos for a fan guard")

    monkeypatch.setattr(findtool, "fetch", no_fetch)
    stone("new", "A guard for a 120 mm fan")
    before = stone("status")[2]
    text, code, nxt = stone("find", "fan guard")
    assert code == 1 and "figure" in text and stone("status")[2] == before


def test_own_photo_on_a_figure_plan_goes_to_build(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of my dog, 80 mm tall")
    stone("set", "figure", "height=80")
    assert stone("build")[2] == "stone image <path to photo>"
    photo = REPO / "examples" / "dog.png"
    if not photo.exists():
        photo = REPO / "evals" / "heldout" / "dog.png"
    text, code, nxt = stone("image", str(photo))
    assert nxt == "stone build", text
    assert stone("status")[2] == "stone build"
