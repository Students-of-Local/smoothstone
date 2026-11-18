"""The figure recipe without the style and lift models: a stand-in mesh goes through repair,
the plinth recipe and every print check, and the CLI points at stone find when photos are missing."""
import json
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
    text, code, nxt = stone("find", "fan guard")
    assert code == 1 and "figure" in text and nxt == "stone show fan_guard"


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


@pytest.mark.parametrize("request_text", ["A guard for a 120 mm fan", "A mini Abraham Lincoln, 80 mm tall",
                                          "A minifigure of Ada Lovelace", "a tiny Einstein"])
def test_find_never_loops_back_to_find(jobenv, monkeypatch, request_text):
    """A bare find, then a named find: the second NEXT is never another find that refuses."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool
    got = []
    monkeypatch.setattr(findtool, "fetch", lambda q, d, n=4: got.append(q) or [])
    stone("new", request_text)
    stone("find")
    text, code, nxt = stone("find", "fan guard" if "fan" in request_text else "Abraham Lincoln")
    if "fan" in request_text:
        assert not got and code == 1 and not nxt.startswith("stone find")
    else:
        assert got, text  # a subject with no part named is a figure


def _style_picture(path: Path) -> None:
    """A stand-in style picture: a skin-colored head over a black body on white."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (256, 512), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 170, 196, 470], fill=(20, 20, 20))
    d.rectangle([70, 470, 186, 505], fill=(20, 20, 20))
    d.ellipse([70, 20, 186, 180], fill=(225, 180, 150))
    im.save(path)


def test_stone_colors_end_to_end_on_a_figure_with_a_style_picture(jobenv, monkeypatch, openscad, tmp_path):
    """Review medium (cli.py:1299): cmd_colors on a real figure job, listing and then painting."""
    from smoothstone import colors

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and "Part ready" in text, text
    assert nxt.startswith("stone colors"), text

    text, code, nxt = stone("colors")
    assert code == 0, text
    assert "Color regions of figure.stl" in text and "base" in text
    assert "% of surface" in text
    assert nxt.startswith("stone colors ") and "rest=" in nxt, text
    regions = json.loads((jobenv / "stone-job" / "build" / "regions.json").read_text())
    assert regions["anatomy"]["top"] > 0

    text, code, nxt = stone(*nxt.split()[1:])
    assert code == 0, text
    assert "PASS color_edges" in text, text
    out = jobenv / "stone-job" / "figure.3mf"
    assert out.is_file(), text
    n = len(colors.read_3mf(out)[1])
    assert colors.check_3mf(out, n, len(status_json_colors(jobenv)["filaments"])) == []
    assert nxt == cli.DONE_NEXT
    assert (jobenv / "stone-job" / "build" / "views.png").is_file()

    # SPEC3 C: the eval grader reads the parts' colors back from the 3MF
    import sys

    sys.path.insert(0, str(REPO / "evals"))
    import run as evrun

    job = jobenv / "stone-job"
    got = evrun.grade_colors(job, "figure", {"rest": "none"})["parts"]
    assert "base" in got and len(set(got.values())) >= 2, got
    rest = got["base"]
    want: dict = {"rest": rest}
    for part, c in got.items():
        if c != rest:
            want.setdefault(c, []).append(part)
    g = evrun.grade_colors(job, "figure", want)
    assert g["why"] == [] and abs(sum(g["shares"].values()) - 1) < 0.01, g
    odd = next(p for p, c in got.items() if c != rest)
    wrong = {"rest": rest, rest: [odd]}
    assert f"{odd} is {got[odd]} (want {rest})" in evrun.grade_colors(job, "figure", wrong)["why"]


def test_a_failing_color_edge_never_points_back_at_the_same_mapping(jobenv, monkeypatch, openscad, tmp_path):
    """Review first-F1: a ledge fault must give a NEXT that changes the mapping (the region on the
    failing edge takes the rest color, or the part prints in one color), so following NEXT ends in
    a written 3MF instead of a loop."""
    import numpy as np

    from smoothstone import colors

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and nxt.startswith("stone colors"), text

    real = colors.ledges

    def always_a_ledge(V, F, face_fil, lines):  # every two-color paint climbs a ledge
        out = real(V, F, face_fil, lines)
        if len(np.unique(face_fil)) > 1 and out:
            out[0] = {**out[0], "area": 1.0, "angle": 15.0, "fil": int(face_fil.max()), "faces": 9}
        return out

    monkeypatch.setattr(colors, "ledges", always_a_ledge)
    if nxt == "stone colors":
        text, code, nxt = stone("colors")
    tried = []
    for _ in range(6):
        mapping = nxt
        text, code, nxt = stone(*mapping.split()[1:])
        tried.append(mapping)
        if nxt == cli.DONE_NEXT:
            break
        assert "climbs onto a ledge" in text, text
        assert nxt != mapping and nxt != "stone colors", text  # never the mapping that just failed
    assert nxt == cli.DONE_NEXT, tried
    assert len(tried) > 1, tried
    out = jobenv / "stone-job" / "figure.3mf"
    assert out.is_file()
    assert len(status_json_colors(jobenv)["shares"].split(";")) == 1  # the one-color print


def status_json_colors(work: Path) -> dict:
    return json.loads((work / "stone-job" / "status.json").read_text())["colors"]
